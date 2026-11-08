"""
Caso de uso GEN-01 (T015): inicia un pedido de generación individual o de secuencia en segundo plano.

Valida la clave y la unidad; si la clave ya tiene un pedido, lo devuelve (o informa el conflicto) sin aplicar las demás
reglas. Si no, valida el resultado de aprendizaje, el plan de pasos, el material y el límite de pedidos activos, guarda
el pedido y lo encola. Solo depende de puertos y del dominio.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from uuid import uuid4

from platform5e.application.ports.outbound.evidence_provider_port import (
    EvidenceProviderPort,
    NoProcessedMaterial,
)
from platform5e.application.ports.outbound.generation_job_runner_port import GenerationJobRunnerPort
from platform5e.application.ports.outbound.generation_request_repository_port import (
    GenerationRequestRepositoryPort,
    IdempotencyKeyTaken,
)
from platform5e.application.ports.outbound.unit_membership_port import UnitMembershipPort
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_request import (
    GenerationMode,
    GenerationParameters,
    GenerationRequest,
    GenerationStep,
    RegenerationTarget,
    payload_hash,
    validate_idempotency_key,
)
from platform5e.domain.generation.sequence import SequenceError, plan_steps

MAX_ACTIVE_REQUESTS: int = 2
UNIT_NOT_FOUND_MESSAGE: str = "La unidad no existe o no pertenece a tus cursos."
INVALID_OUTCOME_MESSAGE: str = "El resultado de aprendizaje no pertenece a la unidad."
KEY_REUSED_MESSAGE: str = (
    "Ya usaste esta clave para un pedido con otros datos. Recarga la página y vuelve a enviar el pedido."
)
TOO_MANY_ACTIVE_MESSAGE: str = (
    f"Ya tienes {MAX_ACTIVE_REQUESTS} pedidos de generación en curso. Espera a que termine alguno y vuelve a "
    "intentarlo."
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class StartGenerationCommand:
    teacher_id: str
    unit_id: str
    mode: GenerationMode
    idempotency_key: str | None
    parameters: GenerationParameters
    regeneration: RegenerationTarget | None = None


@dataclass(frozen=True)
class StartGenerationResult:
    """`created` es False cuando la clave ya tenía un pedido con el mismo contenido (se devuelve ese pedido)."""

    request: GenerationRequest
    created: bool


class StartGenerationRequest:
    """Inicia un pedido (GEN-R1, GEN-R3, GEN-R5)."""

    def __init__(
        self,
        membership: UnitMembershipPort,
        evidence: EvidenceProviderPort,
        repository: GenerationRequestRepositoryPort,
        runner: GenerationJobRunnerPort,
        clock: Callable[[], str] = _utc_now,
        new_id: Callable[[], str] = lambda: f"gen-req-{uuid4()}",
    ) -> None:
        self._membership = membership
        self._evidence = evidence
        self._repository = repository
        self._runner = runner
        self._clock = clock
        self._new_id = new_id

    def execute(self, command: StartGenerationCommand) -> StartGenerationResult:
        # 1. Clave del pedido.
        key = validate_idempotency_key(command.idempotency_key)

        # 2. Pertenencia: una unidad ajena y una inexistente dan la misma respuesta.
        unit = self._membership.get_unit_context(command.teacher_id, command.unit_id)
        if unit is None:
            raise GenerationError(GenerationErrorCode.UNIT_NOT_FOUND, UNIT_NOT_FOUND_MESSAGE)

        # 3. Misma clave: mismo contenido → el pedido existente; otro contenido → conflicto (GEN-C4, GEN-C5).
        #    Un pedido ya aceptado se devuelve sin aplicar las demás reglas, aunque la unidad haya cambiado después.
        content_hash = payload_hash(command.mode, command.unit_id, command.parameters, command.regeneration)
        existing = self._repository.find_by_key(command.teacher_id, key)
        if existing is not None:
            return self._replay(existing, content_hash)

        # 4. Resultado de aprendizaje de la unidad.
        outcome_id = command.parameters.outcome_id
        if outcome_id and outcome_id not in {outcome.id for outcome in unit.outcomes}:
            raise GenerationError(GenerationErrorCode.INVALID_OUTCOME, INVALID_OUTCOME_MESSAGE)

        # 5. Plan de pasos en orden 5E.
        try:
            planned = plan_steps(command.mode, list(command.parameters.resource_types), command.parameters.quantity)
        except SequenceError as error:
            raise GenerationError(GenerationErrorCode.INVALID_SEQUENCE, str(error)) from error

        # 6. Sin material procesado no se crea el pedido (GEN-C6).
        if not self._evidence.has_processed_material(command.teacher_id, command.unit_id):
            raise NoProcessedMaterial()

        # 7. Límite de pedidos activos por docente (research R4).
        if self._repository.count_active(command.teacher_id) >= MAX_ACTIVE_REQUESTS:
            raise GenerationError(GenerationErrorCode.TOO_MANY_ACTIVE_REQUESTS, TOO_MANY_ACTIVE_MESSAGE)

        # 8. Guardar y encolar. Si otro envío con la misma clave ganó la carrera, se aplica la regla 3.
        request = GenerationRequest(
            id=self._new_id(),
            teacher_id=command.teacher_id,
            unit_id=command.unit_id,
            mode=command.mode,
            idempotency_key=key,
            payload_hash=content_hash,
            # Se guardan los tipos sin repetir y en el orden de la clase; el hash usa el orden recibido.
            parameters=replace(command.parameters, resource_types=tuple(p.resource_type for p in planned)),
            created_at=self._clock(),
            steps=tuple(GenerationStep.from_plan(p) for p in planned),
            regeneration=command.regeneration,
        )
        try:
            created = self._repository.create(request)
        except IdempotencyKeyTaken as taken:
            return self._replay(taken.existing, content_hash)
        self._runner.submit(created.id)
        return StartGenerationResult(request=created, created=True)

    @staticmethod
    def _replay(existing: GenerationRequest, content_hash: str) -> StartGenerationResult:
        if existing.payload_hash != content_hash:
            raise GenerationError(GenerationErrorCode.IDEMPOTENCY_KEY_REUSED, KEY_REUSED_MESSAGE)
        return StartGenerationResult(request=existing, created=False)
