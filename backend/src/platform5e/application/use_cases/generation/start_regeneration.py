"""
Caso de uso GEN-01 (T028): regenera un recurso de Revisión con un pedido `regeneration` de un paso (GEN-R6, GEN-C7).

Usa los `params` guardados en el recurso y la evidencia actual del material, que el pedido recupera al ejecutarse; no
la copia histórica. La clave `regen-{resourceId}-v{resourceVersion}` es única por docente: pedir dos veces la misma
versión devuelve el mismo pedido y no duplica recursos. Los recursos nuevos llevan `regeneratedFrom`.

Generación no descarta ni modifica el recurso anterior: eso lo decide Revisión cuando el pedido termina (research R9).
Lo llamará el adaptador de regeneración de Revisión (T029). Solo depende de otros casos de uso de Generación y del
dominio.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

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
)

WITHOUT_PARAMETERS_MESSAGE: str = (
    "Este recurso se creó antes de que se guardaran los datos de su pedido y no se puede regenerar. "
    "Crea uno nuevo desde Generación."
)
INVALID_TARGET_MESSAGE: str = "No se puede regenerar este recurso: su identificador o su versión no son válidos."
REGENERATED_QUANTITY: int = 1
DEFAULTS = GenerationParameters(resource_types=())


def regeneration_key(resource_id: str, resource_version: int) -> str:
    """Clave del pedido de regeneración de una versión del recurso."""
    return f"regen-{resource_id}-v{resource_version}"


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
        raise GenerationError(GenerationErrorCode.REGENERATION_UNAVAILABLE, WITHOUT_PARAMETERS_MESSAGE)
    resource_type = params.get("resourceType")
    if not isinstance(resource_type, str) or not resource_type:
        raise GenerationError(GenerationErrorCode.REGENERATION_UNAVAILABLE, WITHOUT_PARAMETERS_MESSAGE)
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

    def __init__(self, start_generation: StartGenerationRequest) -> None:
        self._start_generation = start_generation

    def execute(self, command: StartRegenerationCommand) -> StartGenerationResult:
        version = command.resource_version
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise GenerationError(GenerationErrorCode.REGENERATION_UNAVAILABLE, INVALID_TARGET_MESSAGE)
        key = regeneration_key(command.resource_id, version)
        if not command.resource_id or not IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
            raise GenerationError(GenerationErrorCode.REGENERATION_UNAVAILABLE, INVALID_TARGET_MESSAGE)
        parameters = parameters_from_saved(command.params)
        return self._start_generation.execute(
            StartGenerationCommand(
                teacher_id=command.teacher_id,
                unit_id=command.unit_id,
                mode=GenerationMode.REGENERATION,
                idempotency_key=key,
                parameters=parameters,
                regeneration=RegenerationTarget(resource_id=command.resource_id, resource_version=version),
            )
        )
