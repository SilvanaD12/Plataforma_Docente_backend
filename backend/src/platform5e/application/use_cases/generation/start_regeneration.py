"""
Caso de uso GEN-01 (T028): regenera un recurso de Revisión con un pedido `regeneration` de un paso (GEN-R6, GEN-C7).

Usa los `params` guardados en el recurso y la evidencia actual del material, que el pedido recupera al ejecutarse; no
la copia histórica. La clave `regen-{resourceId}-v{resourceVersion}` es única por docente: pedir dos veces la misma
versión devuelve el mismo pedido y no duplica recursos, salvo que ese intento haya terminado `failed` o
`interrupted`, o que haya terminado bien pero el docente ya borró todos sus recursos nuevos: entonces se crea otro con
la clave siguiente (`-r2`, `-r3`…). Los recursos nuevos llevan `regeneratedFrom`.

Generación no descarta ni modifica el recurso anterior: eso lo decide Revisión cuando el pedido termina (research R9).
Lo llamará el adaptador de regeneración de Revisión (T029). Solo depende de otros casos de uso de Generación y del
dominio.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from platform5e.application.ports.outbound.resource_repository_port import ResourceReviewRepositoryPort
from platform5e.application.use_cases.generation.start_generation_request import (
    StartGenerationCommand,
    StartGenerationRequest,
    StartGenerationResult,
)
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_request import (
    IDEMPOTENCY_KEY_PATTERN,
    GenerationMode,
    GenerationParameters,
    RegenerationTarget,
    RequestStatus,
)

WITHOUT_PARAMETERS_MESSAGE: str = (
    "Este recurso se creó antes de que se guardaran los datos de su pedido y no se puede regenerar. "
    "Crea uno nuevo desde Generación."
)
INVALID_TARGET_MESSAGE: str = "No se puede regenerar este recurso: su identificador o su versión no son válidos."
REGENERATED_QUANTITY: int = 1
DEFAULTS = GenerationParameters(resource_types=())


# Un intento fallido o interrumpido no bloquea la versión: el siguiente usa la clave `-r2`, `-r3`…
RETRYABLE_STATUSES = frozenset({RequestStatus.FAILED, RequestStatus.INTERRUPTED})
SUCCEEDED_STATUSES = frozenset({RequestStatus.SUCCEEDED, RequestStatus.PARTIALLY_SUCCEEDED})
MAX_REGENERATION_ATTEMPTS: int = 20
TOO_MANY_ATTEMPTS_MESSAGE: str = (
    "Esta versión del recurso ya se intentó regenerar muchas veces sin éxito. Edítalo o crea uno nuevo desde "
    "Generación."
)


def regeneration_key(resource_id: str, resource_version: int, attempt: int = 1) -> str:
    """Clave del pedido de regeneración de una versión del recurso: `regen-{id}-v{versión}` en el primer intento y
    `regen-{id}-v{versión}-r{n}` desde el segundo."""
    key = f"regen-{resource_id}-v{resource_version}"
    return key if attempt == 1 else f"{key}-r{attempt}"


def _text(value: Any, default: str) -> str:
    return value if isinstance(value, str) else default


def _integer(value: Any, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _number(value: Any, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def parameters_from_saved(params: Mapping[str, Any] | None) -> GenerationParameters:
    """El pedido de un paso a partir de los `params` guardados en el recurso (`saved_parameters`).

    Un valor que falta o no tiene el tipo esperado toma el valor por defecto del pedido. Sin `params` o sin
    `resourceType` el recurso no se puede regenerar.
    """
    if not isinstance(params, Mapping):
        raise GenerationError(GenerationErrorCode.REGENERATION_PARAMETERS_MISSING, WITHOUT_PARAMETERS_MESSAGE)
    resource_type = params.get("resourceType")
    if not isinstance(resource_type, str) or not resource_type:
        raise GenerationError(GenerationErrorCode.REGENERATION_PARAMETERS_MISSING, WITHOUT_PARAMETERS_MESSAGE)
    modalities = params.get("modalities")
    outcome_id = params.get("outcomeId")
    return GenerationParameters(
        resource_types=(resource_type,),
        quantity=REGENERATED_QUANTITY,
        outcome_id=outcome_id if isinstance(outcome_id, str) and outcome_id else None,
        difficulty=_text(params.get("difficulty"), DEFAULTS.difficulty) or DEFAULTS.difficulty,
        option_count=_integer(params.get("optionCount"), DEFAULTS.option_count),
        top_k=_integer(params.get("topK"), DEFAULTS.top_k),
        evidence_threshold=_number(params.get("evidenceThreshold"), DEFAULTS.evidence_threshold),
        instructions=_text(params.get("instructions"), DEFAULTS.instructions),
        audience=_text(params.get("audience"), DEFAULTS.audience),
        competency=_text(params.get("competency"), DEFAULTS.competency),
        modalities=(
            tuple(m for m in modalities if isinstance(m, str))
            if isinstance(modalities, list) and any(isinstance(m, str) for m in modalities)
            else DEFAULTS.modalities
        ),
    )


@dataclass(frozen=True)
class StartRegenerationCommand:
    """Recurso que se regenera, la versión que Revisión registró al pedirlo y sus `params` guardados."""

    teacher_id: str
    unit_id: str
    resource_id: str
    resource_version: int
    params: Mapping[str, Any] | None


class StartRegeneration:
    """Inicia la regeneración con las mismas reglas que cualquier pedido: pertenencia, material y límite de activos."""

    def __init__(
        self,
        start_generation: StartGenerationRequest,
        review_repository: ResourceReviewRepositoryPort | None = None,
    ) -> None:
        self._start_generation = start_generation
        # Con el repositorio de Revisión, un intento que terminó bien pero cuyos recursos nuevos el docente ya borró
        # también deja pasar al intento siguiente (PR #17).
        self._review_repository = review_repository

    def execute(self, command: StartRegenerationCommand) -> StartGenerationResult:
        version = command.resource_version
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise GenerationError(GenerationErrorCode.REGENERATION_TARGET_INVALID, INVALID_TARGET_MESSAGE)
        if not command.resource_id or not IDEMPOTENCY_KEY_PATTERN.fullmatch(
            regeneration_key(command.resource_id, version, MAX_REGENERATION_ATTEMPTS)
        ):
            raise GenerationError(GenerationErrorCode.REGENERATION_TARGET_INVALID, INVALID_TARGET_MESSAGE)
        parameters = parameters_from_saved(command.params)
        target = RegenerationTarget(resource_id=command.resource_id, resource_version=version)

        # Cada clave devuelve su pedido si ya existe (en curso, terminado bien o fallido). Si el último intento falló o
        # se interrumpió, se pasa a la clave siguiente; si sigue en curso o terminó bien, se devuelve ese mismo.
        for attempt in range(1, MAX_REGENERATION_ATTEMPTS + 1):
            result = self._start_generation.execute(
                StartGenerationCommand(
                    teacher_id=command.teacher_id,
                    unit_id=command.unit_id,
                    mode=GenerationMode.REGENERATION,
                    idempotency_key=regeneration_key(command.resource_id, version, attempt),
                    parameters=parameters,
                    regeneration=target,
                )
            )
            if result.created:
                return result
            if result.request.status in RETRYABLE_STATUSES:
                continue
            if result.request.status in SUCCEEDED_STATUSES and self._new_resources_deleted(command, result.request):
                continue
            return result
        raise GenerationError(GenerationErrorCode.REGENERATION_ATTEMPTS_EXHAUSTED, TOO_MANY_ATTEMPTS_MESSAGE)

    def _new_resources_deleted(self, command: StartRegenerationCommand, request) -> bool:
        """True si el intento entregó recursos y ninguno sigue en Revisión."""
        if self._review_repository is None:
            return False
        delivered = {resource_id for step in request.steps for resource_id in step.resource_ids}
        if not delivered:
            return False
        stored = self._review_repository.get_resources_by_unit(command.teacher_id, command.unit_id)
        return not any(resource.get("id") in delivered for resource in stored)
