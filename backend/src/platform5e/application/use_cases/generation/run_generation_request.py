"""
Caso de uso GEN-01 (T016): ejecuta en segundo plano un pedido de generación ya guardado.

Recupera la evidencia una sola vez y la comparte entre los pasos (GEN-R2). Cada paso, en orden 5E, redacta sus
recursos, aplica el control de repetición contra los pasos anteriores, guarda en cada recurso la copia histórica de los
fragmentos que referencia y su verificación (research R6 y R7), los entrega a Revisión y recién entonces confirma su
estado, para que el progreso que ve el docente siempre lo haya confirmado el servidor (GEN-R3).

Si el curso se borra mientras se genera, el pedido desaparece: antes de guardar los recursos de cada paso se comprueba
que el pedido sigue existiendo y que la unidad sigue siendo del docente, y si confirmar el paso falla porque el pedido
ya no existe, se quitan de Revisión los recursos recién guardados. El ejecutor se detiene sin guardar nada más.
Solo depende de puertos, de los servicios de redacción de Generación y del dominio de Generación.
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
from platform5e.application.ports.outbound.resource_verification_port import ResourceVerificationPort
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
from platform5e.application.services.media.media_attachment import PendingMedia, generate_media
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
from platform5e.domain.generation.grounding import VERIFICATION_RULE_VERSION

logger = logging.getLogger("platform5e.generation.run")

# Identifica este proceso en `worker_boot_id` (diagnóstico del barrido de arranque).
PROCESS_BOOT_ID: str = uuid4().hex
DEFAULT_DEADLINE_SECONDS: int = 900
DEFAULT_HEARTBEAT_SECONDS: float = 15.0
MAX_REASONS_IN_FAILURE: int = 3
# Versión con la que Revisión recibe un recurso nuevo; el PUT de Revisión parte de ella (`expectedVersion = 1`).
INITIAL_RESOURCE_VERSION: int = 1
VERIFICATION_INSUFFICIENT: str = "insufficient"
VERIFICATION_PENDING: str = "pending"

UNIT_NOT_FOUND_MESSAGE: str = "La unidad ya no existe o no pertenece a tus cursos."
DEADLINE_MESSAGE: str = (
    "Se agotó el tiempo máximo del pedido antes de generar este paso. Los pasos anteriores siguen en revisión."
)
STEP_FAILED_MESSAGE: str = "No se pudo generar este paso por un error del servidor o del generador."
NO_GENERATOR_MESSAGE: str = "El generador no respondió y no hay un generador de respaldo disponible."
NO_RESOURCES_MESSAGE: str = "El generador no devolvió recursos válidos para este tipo de recurso."
VERIFICATION_FAILED_MESSAGE: str = (
    "La comprobación del respaldo no pudo completarse al generar el recurso. Reintenta la comprobación en la revisión."
)
VERIFICATION_INSUFFICIENT_MESSAGE: str = "El material no respalda lo suficiente el contenido del recurso."
INSUFFICIENT_EVIDENCE_MESSAGE: str = (
    "No se pudieron redactar recursos que citen el material sin repetirse. "
    "Prueba con otros tipos de recurso o agrega más material a la unidad."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _RequestGone(Exception):
    """El pedido ya no existe (se borró su curso): el ejecutor se detiene sin escribir nada más."""


class _UnitGone(Exception):
    """La unidad ya no pertenece al docente, aunque el pedido siga guardado."""


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
        verification: ResourceVerificationPort,
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
        self._verification = verification
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
            outcome = self._run(request)
        if outcome is None:
            logger.info("El pedido de generación %s se eliminó mientras se ejecutaba.", request_id)
            return
        self._repository.finish(request_id, *outcome)

    # Pedido

    def _run(self, request: GenerationRequest) -> tuple[RequestStatus, Problem | None] | None:
        """Estado final y motivo del pedido, o None si el pedido se eliminó mientras se ejecutaba."""
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
        if not self._repository.save_evidence(request.id, retrieval, retrieved_at):
            return None

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
            if not self._repository.update_step(request.id, running):
                return None
            saved_media: list[str] = []  # multimedia que guardó este paso, para quitarla si el pedido desaparece
            try:
                finished = self._run_step(
                    request, running, unit, retrieval.fragments, retrieved_at, outcome_id, accepted, saved_media
                )
            except _RequestGone:
                return None
            except _UnitGone:
                # Lo que quede sin terminar se cierra como fallido al finalizar el pedido.
                return RequestStatus.FAILED, Problem(GenerationErrorCode.UNIT_NOT_FOUND, UNIT_NOT_FOUND_MESSAGE)
            except Exception:
                logger.exception("Falló el paso %s del pedido de generación %s.", step.position, request.id)
                finished = replace(
                    running,
                    status=StepStatus.FAILED,
                    error=Problem(GenerationErrorCode.GENERATION_FAILED, STEP_FAILED_MESSAGE),
                    finished_at=self._clock(),
                )
            steps[index] = finished
            # La confirmación del paso es su última escritura (research R3).
            if not self._repository.update_step(request.id, finished):
                # El pedido desapareció entre la comprobación y la confirmación: se quitan sus recursos y archivos.
                self._remove_step_outputs(request.teacher_id, finished.resource_ids, saved_media)
                return None

        status = final_status(steps)
        return status, (self._failure_summary(steps) if status == RequestStatus.FAILED else None)

    def _ensure_still_owned(self, request: GenerationRequest) -> None:
        """El pedido sigue guardado y la unidad sigue siendo del docente; si no, se detiene el pedido."""
        if self._repository.get_for_runner(request.id) is None:
            raise _RequestGone()
        if self._membership.get_unit_context(request.teacher_id, request.unit_id) is None:
            raise _UnitGone()

    def _remove_step_outputs(self, teacher_id: str, resource_ids: Sequence[str], media_ids: Sequence[str]) -> None:
        """Quita lo que guardó un paso que no se pudo confirmar: sus recursos y sus archivos de multimedia."""
        for resource_id in resource_ids:
            try:
                self._review_repository.delete_resource(teacher_id, resource_id)
            except Exception:
                logger.exception("No se pudo quitar el recurso %s de un paso sin confirmar.", resource_id)
        for media_id in media_ids:
            try:
                if self._media_repository is not None:
                    self._media_repository.delete_media(teacher_id, media_id)
            except Exception:
                logger.exception("No se pudo quitar el archivo %s de un paso sin confirmar.", media_id)

    def _save_step_outputs(
        self,
        request: GenerationRequest,
        resources: list[dict[str, Any]],
        pending_media: Sequence[PendingMedia],
        saved_media: list[str],
    ) -> None:
        """Guarda la multimedia y después los recursos del paso. Si algo falla a medias, quita lo que ya guardó."""
        try:
            for pending in pending_media:
                assert self._media_repository is not None  # solo hay multimedia pendiente si hay repositorio
                self._media_repository.save_media(request.teacher_id, pending.media, pending.content)
                saved_media.append(pending.media["id"])
            self._review_repository.save_resources(request.teacher_id, request.unit_id, resources)
        except Exception:
            self._remove_step_outputs(request.teacher_id, [resource["id"] for resource in resources], saved_media)
            saved_media.clear()
            raise

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
        saved_media: list[str],
    ) -> GenerationStep:
        """Redacta, verifica y entrega los recursos de un paso. Orden de escritura (research R3): genera la multimedia
        sin guardarla, comprueba que el pedido y la unidad siguen, guarda la multimedia (anota sus ids en
        `saved_media`) y después los recursos. La confirmación del paso la escribe `_run`, al final."""
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

        # Antes de generar multimedia: el curso pudo borrarse mientras se redactaba.
        self._ensure_still_owned(request)
        timestamp = self._clock()
        uses_ai = bool(getattr(generator, "uses_ai", False))
        frozen_parameters = saved_parameters(step_request)
        threshold = request.parameters.evidence_threshold
        evidence = [fragment.to_dict(retrieved_at) for fragment in fragments]
        resources: list[dict[str, Any]] = []
        pending_media: list[PendingMedia] = []
        delivered_drafts: list[dict[str, Any]] = []
        for drafted_resource in drafted.kept:
            resource = {
                **build_resource_dict(
                    drafted_resource, step_request, request.unit_id, outcome_id, generator.description, timestamp
                ),
                "agent": step.agent,
            }
            # Copia histórica de exactamente los fragmentos que Revisión exigirá al verificar (research R6).
            snapshot = build_snapshot(self._verification.referenced_fragment_ids(resource), evidence, retrieved_at)
            resource["evidence"] = [item.to_dict() for item in snapshot.items]
            resource["params"] = frozen_parameters
            resource["generatorKind"] = "ia" if uses_ai else "respaldo"
            resource["version"] = INITIAL_RESOURCE_VERSION
            if request.regeneration is not None:
                resource["regeneratedFrom"] = {
                    "resourceId": request.regeneration.resource_id,
                    "version": request.regeneration.resource_version,
                }
            verification = self._verify(resource, threshold, snapshot.is_complete)
            if verification.get("status") == VERIFICATION_INSUFFICIENT:
                # El borrador no llega a Revisión: se informa como rechazo de anclaje (research R7).
                grounding_rejections.append(
                    {
                        "title": resource["title"],
                        "reason": verification.get("reason") or VERIFICATION_INSUFFICIENT_MESSAGE,
                        "kind": "grounding",
                        "grounding": resource.get("grounding"),
                    }
                )
                continue
            resource["verification"] = verification
            # La multimedia se genera solo para los recursos que se entregan, y todavía no se guarda.
            pending = generate_media(resource, self._media_generator if self._media_repository is not None else None)
            if pending is not None:
                pending_media.append(pending)
            resources.append(resource)
            delivered_drafts.append(drafted_resource)
        accepted.extend({**draft, "etapa": step.stage} for draft in delivered_drafts)

        rejections = [
            {"title": item["title"], "reason": item["reason"], "kind": item.get("kind", "grounding")}
            for item in [*drafted.repeated, *grounding_rejections]
        ]
        if not resources and not rejections:
            rejections.append({"title": step.resource_type, "reason": NO_RESOURCES_MESSAGE, "kind": "structure"})

        finished = replace(
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
        if resources:
            self._ensure_still_owned(request)  # la multimedia pudo tardar: si el curso se borró, no se guarda nada
            self._save_step_outputs(request, resources, pending_media, saved_media)
        return finished

    def _verify(self, resource: dict[str, Any], threshold: float, copy_complete: bool) -> dict[str, Any]:
        """Bloque `verification` del recurso. Si la verificación lanza un error, el recurso queda `pending` con el
        motivo y se puede reintentar en Revisión si su copia histórica está completa (research R7)."""
        try:
            return self._verification.verify(resource, threshold)
        except Exception:
            logger.exception("No se pudo verificar el recurso %s.", resource.get("id"))
        try:
            fingerprint = self._verification.fingerprint(resource)
        except Exception:
            logger.exception("No se pudo calcular la huella del recurso %s.", resource.get("id"))
            fingerprint = ""  # no coincide con ninguna huella: Revisión lo verifica de nuevo al guardarlo
        return {
            "status": VERIFICATION_PENDING,
            "reason": VERIFICATION_FAILED_MESSAGE,
            "fingerprint": fingerprint,
            "verifiedVersion": resource.get("version", INITIAL_RESOURCE_VERSION),
            "evidenceThreshold": threshold,
            "ruleVersion": VERIFICATION_RULE_VERSION,
            "checkedAt": self._clock(),
            "retryAvailable": copy_complete,
            "summary": {},
        }

    def _is_fallback(self, generator: ResourceGeneratorPort) -> bool:
        """True si redactó el generador de respaldo porque el principal falló (research R8)."""
        return (
            self._primary_generator is not None
            and self._fallback_generator is not None
            and generator is self._fallback_generator
            and self._fallback_generator is not self._primary_generator
        )
