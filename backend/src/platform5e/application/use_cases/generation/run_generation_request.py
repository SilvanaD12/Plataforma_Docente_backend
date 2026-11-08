"""
Caso de uso GEN-01 (T016): ejecuta en segundo plano un pedido de generación ya guardado.

Recupera la evidencia una sola vez y la comparte entre los pasos (GEN-R2). Cada paso, en orden 5E, redacta sus
recursos, aplica el control de repetición contra los pasos anteriores, los entrega a Revisión y recién entonces
confirma su estado, para que el progreso que ve el docente siempre lo haya confirmado el servidor (GEN-R3).
Solo depende de puertos, de los servicios de redacción de Generación y del dominio.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from types import TracebackType
from typing import Any
from uuid import uuid4

from platform5e.application.ports.outbound.evidence_provider_port import (
    EvidenceFragment,
    EvidenceProviderPort,
    EvidenceQuery,
)
from platform5e.application.ports.outbound.generation_request_repository_port import (
    GenerationRequestRepositoryPort,
)
from platform5e.application.ports.outbound.language_model_port import ResourceGeneratorPort
from platform5e.application.ports.outbound.media_port import MediaGeneratorPort, MediaRepositoryPort
from platform5e.application.ports.outbound.resource_repository_port import ResourceReviewRepositoryPort
from platform5e.application.ports.outbound.unit_membership_port import UnitContext, UnitMembershipPort
from platform5e.application.services.generation.prompt_drafting import build_step_context
from platform5e.application.services.generation.step_drafting import (
    build_grounding_report,
    build_resource_dict,
    draft_step,
    evidence_query_text,
    previous_sequence,
    retrieval_limit,
    saved_parameters,
)
from platform5e.application.services.media.media_attachment import attach_generated_media
from platform5e.domain.generation.distractor_reliability import reliability_report
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.evidence import build_snapshot
from platform5e.domain.generation.generation_request import (
    GenerationRequest,
    GenerationStep,
    Problem,
    RequestStatus,
    StepStatus,
    final_status,
)

logger = logging.getLogger("platform5e.generation.run")

# Identifica este proceso en `worker_boot_id` (diagnóstico del barrido de arranque).
PROCESS_BOOT_ID: str = uuid4().hex
DEFAULT_DEADLINE_SECONDS: int = 900
DEFAULT_HEARTBEAT_SECONDS: float = 15.0
MAX_REASONS_IN_FAILURE: int = 3

UNIT_NOT_FOUND_MESSAGE: str = "La unidad ya no existe o no pertenece a tus cursos."
DEADLINE_MESSAGE: str = (
    "Se agotó el tiempo máximo del pedido antes de generar este paso. Los pasos anteriores siguen en revisión."
)
STEP_FAILED_MESSAGE: str = "No se pudo generar este paso por un error del servidor o del generador."
NO_GENERATOR_MESSAGE: str = "El generador no respondió y no hay un generador de respaldo disponible."
NO_RESOURCES_MESSAGE: str = "El generador no devolvió recursos válidos para este tipo de recurso."
INSUFFICIENT_EVIDENCE_MESSAGE: str = (
    "No se pudieron redactar recursos que citen el material sin repetirse. "
    "Prueba con otros tipos de recurso o agrega más material a la unidad."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _provisional_referenced_ids(resource: dict[str, Any]) -> list[str]:
    """Fragmentos que referencia el recurso: citas, alternativas y estructura (pasos, predicciones y criterios).

    TODO(T026): reemplazar por `ResourceVerificationPort.referenced_fragment_ids` de Revisión, para que Generación
    copie exactamente los fragmentos que Revisión exigirá al verificar.
    """
    ids = [f_id for citation in resource.get("citations") or [] for f_id in citation.get("fragmentIds") or []]
    ids += [f_id for option in resource.get("options") or [] for f_id in option.get("sourceFragmentIds") or []]
    structure = resource.get("structure") or {}
    for key in ("guidedSteps", "predictions", "criteria"):
        ids += [f_id for item in structure.get(key) or [] for f_id in item.get("fragmentIds") or []]
    return ids


class _Heartbeat:
    """Renueva el latido del pedido cada `interval` segundos en un hilo aparte mientras se ejecuta."""

    def __init__(self, beat: Callable[[], None], interval: float) -> None:
        self._beat = beat
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> _Heartbeat:
        if self._interval > 0:
            self._thread = threading.Thread(target=self._loop, name="generation-heartbeat", daemon=True)
            self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval + 1)

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._beat()
            except Exception:  # un latido perdido no detiene la generación
                logger.warning("No se pudo renovar el latido del pedido de generación.", exc_info=True)


class RunGenerationRequest:
    """Ejecuta un pedido guardado. Lo invoca el ejecutor en segundo plano con el id del pedido."""

    def __init__(
        self,
        repository: GenerationRequestRepositoryPort,
        membership: UnitMembershipPort,
        evidence: EvidenceProviderPort,
        review_repository: ResourceReviewRepositoryPort,
        primary_generator: ResourceGeneratorPort | None,
        fallback_generator: ResourceGeneratorPort | None = None,
        media_generator: MediaGeneratorPort | None = None,
        media_repository: MediaRepositoryPort | None = None,
        deadline_seconds: float = DEFAULT_DEADLINE_SECONDS,
        heartbeat_seconds: float = DEFAULT_HEARTBEAT_SECONDS,
        worker_boot_id: str = PROCESS_BOOT_ID,
        clock: Callable[[], str] = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._repository = repository
        self._membership = membership
        self._evidence = evidence
        self._review_repository = review_repository
        self._primary_generator = primary_generator
        self._fallback_generator = fallback_generator
        self._media_generator = media_generator
        self._media_repository = media_repository
        self._deadline_seconds = deadline_seconds
        self._heartbeat_seconds = heartbeat_seconds
        self._worker_boot_id = worker_boot_id
        self._clock = clock
        self._monotonic = monotonic

    def execute(self, request_id: str) -> None:
        request = self._repository.get_for_runner(request_id)
        if request is None or request.is_final:
            return
        self._repository.mark_running(request_id, self._worker_boot_id)
        request = self._repository.get_for_runner(request_id)
        if request is None or request.status != RequestStatus.RUNNING:
            return  # se interrumpió o terminó mientras esperaba en la cola
        with _Heartbeat(lambda: self._repository.heartbeat(request_id), self._heartbeat_seconds):
            status, failure = self._run(request)
        self._repository.finish(request_id, status, failure)

    # Pedido

    def _run(self, request: GenerationRequest) -> tuple[RequestStatus, Problem | None]:
        deadline = self._monotonic() + self._deadline_seconds
        unit = self._membership.get_unit_context(request.teacher_id, request.unit_id)
        if unit is None:  # el curso se borró mientras el pedido esperaba
            return RequestStatus.FAILED, Problem(GenerationErrorCode.UNIT_NOT_FOUND, UNIT_NOT_FOUND_MESSAGE)

        parameters = request.parameters
        outcome_texts = [o.text for o in unit.outcomes if not parameters.outcome_id or o.id == parameters.outcome_id]
        query = EvidenceQuery(
            teacher_id=request.teacher_id,
            unit_id=request.unit_id,
            query=evidence_query_text(unit.unit_title, outcome_texts, parameters.instructions, parameters.competency),
            limit=retrieval_limit(parameters.top_k),
        )
        try:
            retrieval = self._evidence.retrieve(query)  # una sola vez para todos los pasos (GEN-R2)
        except GenerationError as error:
            return RequestStatus.FAILED, Problem(error.code, error.message)
        retrieved_at = self._clock()
        self._repository.save_evidence(request.id, retrieval, retrieved_at)

        outcome_id = parameters.outcome_id or (unit.outcomes[0].id if unit.outcomes else "")
        accepted: list[dict[str, Any]] = []  # recursos aceptados (formato del generador), con su etapa
        steps = list(request.steps)
        for index, step in enumerate(steps):
            if step.is_final:
                continue
            if self._monotonic() >= deadline:
                self._fail_remaining(request.id, steps, index)
                break
            running = replace(step, status=StepStatus.RUNNING, started_at=self._clock())
            self._repository.update_step(request.id, running)
            try:
                finished = self._run_step(
                    request, running, unit, retrieval.fragments, retrieved_at, outcome_id, accepted
                )
            except Exception:
                logger.exception("Falló el paso %s del pedido de generación %s.", step.position, request.id)
                finished = replace(
                    running,
                    status=StepStatus.FAILED,
                    error=Problem(GenerationErrorCode.GENERATION_FAILED, STEP_FAILED_MESSAGE),
                    finished_at=self._clock(),
                )
            steps[index] = finished
            self._repository.update_step(request.id, finished)

        status = final_status(steps)
        return status, (self._failure_summary(steps) if status == RequestStatus.FAILED else None)

    def _fail_remaining(self, request_id: str, steps: list[GenerationStep], start: int) -> None:
        problem = Problem(GenerationErrorCode.DEADLINE_EXCEEDED, DEADLINE_MESSAGE)
        for index in range(start, len(steps)):
            if not steps[index].is_final:
                steps[index] = replace(
                    steps[index], status=StepStatus.FAILED, error=problem, finished_at=self._clock()
                )
                self._repository.update_step(request_id, steps[index])

    @staticmethod
    def _failure_summary(steps: Sequence[GenerationStep]) -> Problem:
        """Motivo del pedido fallido: el error del primer paso fallido o, si todos se rechazaron, sus motivos."""
        failed = next((step.error for step in steps if step.status == StepStatus.FAILED and step.error), None)
        if failed is not None:
            return failed
        reasons = [item["reason"] for step in steps for item in step.rejections][:MAX_REASONS_IN_FAILURE]
        detail = (" Motivo: " + " ".join(reasons)) if reasons else ""
        return Problem(GenerationErrorCode.INSUFFICIENT_EVIDENCE, INSUFFICIENT_EVIDENCE_MESSAGE + detail)

    # Paso

    def _run_step(
        self,
        request: GenerationRequest,
        step: GenerationStep,
        unit: UnitContext,
        fragments: Sequence[EvidenceFragment],
        retrieved_at: str,
        outcome_id: str,
        accepted: list[dict[str, Any]],
    ) -> GenerationStep:
        step_request = {
            **request.parameters.to_payload(),
            "id": request.id,
            "createdAt": request.created_at,
            "stage": step.stage,
            "resourceType": step.resource_type,
        }
        context = build_step_context(unit, step_request, fragments)
        context["secuenciaPrevia"] = previous_sequence(accepted)

        grounding_rejections: list[dict[str, Any]] = []
        drafted = draft_step(
            context, accepted, self._primary_generator, self._fallback_generator, grounding_rejections
        )
        generator = drafted.generator
        if generator is None:
            return replace(
                step,
                status=StepStatus.FAILED,
                error=Problem(GenerationErrorCode.GENERATION_FAILED, NO_GENERATOR_MESSAGE),
                finished_at=self._clock(),
            )

        timestamp = self._clock()
        uses_ai = bool(getattr(generator, "uses_ai", False))
        frozen_parameters = saved_parameters(step_request)
        evidence = [fragment.to_dict(retrieved_at) for fragment in fragments]
        resources: list[dict[str, Any]] = []
        for drafted_resource in drafted.kept:
            resource = {
                **build_resource_dict(
                    drafted_resource, step_request, request.unit_id, outcome_id, generator.description, timestamp
                ),
                "agent": step.agent,
            }
            attach_generated_media(request.teacher_id, resource, self._media_generator, self._media_repository)
            snapshot = build_snapshot(_provisional_referenced_ids(resource), evidence, retrieved_at)
            resource["evidence"] = [item.to_dict() for item in snapshot.items]
            resource["params"] = frozen_parameters
            resource["generatorKind"] = "ia" if uses_ai else "respaldo"
            # TODO(T026): calcular aquí el bloque `verification` con ResourceVerificationPort.verify (huella, umbral
            # y ruleVersion), rechazar el borrador `insufficient` y guardar `version = 1`. Si la copia histórica
            # está incompleta (snapshot.missing_ids), Revisión lo deja `pending`.
            resources.append(resource)
        accepted.extend({**resource, "etapa": step.stage} for resource in drafted.kept)

        if resources:
            self._review_repository.save_resources(request.teacher_id, request.unit_id, resources)

        rejections = [
            {"title": item["title"], "reason": item["reason"], "kind": item.get("kind", "grounding")}
            for item in [*drafted.repeated, *grounding_rejections]
        ]
        if not resources and not rejections:
            rejections.append({"title": step.resource_type, "reason": NO_RESOURCES_MESSAGE, "kind": "structure"})

        return replace(
            step,
            status=StepStatus.SUCCEEDED if resources else StepStatus.REJECTED,
            resource_ids=tuple(resource["id"] for resource in resources),
            rejections=tuple(rejections),
            generator={
                "description": generator.description,
                "usesAi": uses_ai,
                "fallback": self._is_fallback(generator),
            },
            grounding=build_grounding_report(resources, grounding_rejections),
            distractor_reliability=reliability_report(resources),
            finished_at=self._clock(),
        )

    def _is_fallback(self, generator: ResourceGeneratorPort) -> bool:
        """True si redactó el generador de respaldo porque el principal falló (research R8)."""
        return (
            self._primary_generator is not None
            and self._fallback_generator is not None
            and generator is self._fallback_generator
            and self._fallback_generator is not self._primary_generator
        )
