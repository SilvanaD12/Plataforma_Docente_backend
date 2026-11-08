"""
GEN-01: pedido de generación persistido, con sus pasos, estados y transiciones.

El pedido se ejecuta en segundo plano. El docente lo identifica con una clave estable (`Idempotency-Key`), única por
docente: reenviar la misma clave con el mismo contenido devuelve el mismo pedido. Si el servidor se reinicia, el
pedido en curso pasa a `interrupted` y conserva lo que ya entregó.

Este módulo solo tiene reglas puras: no conoce HTTP, la base de datos ni los otros módulos.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.sequence import PlannedStep
from platform5e.domain.shared.errors import DomainError

IDEMPOTENCY_KEY_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
INTERRUPTED_MESSAGE: str = (
    "El servidor se reinició mientras se generaba el pedido. Los recursos ya generados siguen en revisión; "
    "crea un pedido nuevo para completar el resto."
)


class GenerationMode(StrEnum):
    INDIVIDUAL = "individual"
    SEQUENCE = "sequence"
    REGENERATION = "regeneration"


class RequestStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


FINAL_REQUEST_STATUSES: frozenset[RequestStatus] = frozenset(
    {
        RequestStatus.SUCCEEDED,
        RequestStatus.PARTIALLY_SUCCEEDED,
        RequestStatus.FAILED,
        RequestStatus.INTERRUPTED,
    }
)
FINAL_STEP_STATUSES: frozenset[StepStatus] = frozenset(
    {StepStatus.SUCCEEDED, StepStatus.REJECTED, StepStatus.FAILED, StepStatus.INTERRUPTED}
)


class InvalidTransitionError(DomainError):
    """Se intentó cerrar un pedido con pasos sin terminar. Es un error de programación, no del docente."""


@dataclass(frozen=True)
class Problem:
    """Motivo de un fallo o de una interrupción: código estable y mensaje en español para el docente."""

    code: str
    message: str


@dataclass(frozen=True)
class GenerationParameters:
    """El pedido normalizado. Los valores por defecto son los mismos que acepta hoy la API de generación."""

    resource_types: tuple[str, ...]
    quantity: int = 1
    outcome_id: str | None = None
    difficulty: str = "intermedia"
    option_count: int = 4
    top_k: int = 10
    evidence_threshold: float = 0.6
    instructions: str = ""
    audience: str = ""
    competency: str = ""
    modalities: tuple[str, ...] = ("Textual",)

    def to_payload(self) -> dict[str, Any]:
        """Forma JSON (camelCase) del pedido, con `resourceTypes` sin repetidos y en el orden recibido."""
        return {
            "resourceTypes": list(dict.fromkeys(self.resource_types)),
            "quantity": self.quantity,
            "outcomeId": self.outcome_id,
            "difficulty": self.difficulty,
            "optionCount": self.option_count,
            "topK": self.top_k,
            "evidenceThreshold": self.evidence_threshold,
            "instructions": self.instructions,
            "audience": self.audience,
            "competency": self.competency,
            "modalities": list(self.modalities),
        }


@dataclass(frozen=True)
class RegenerationTarget:
    """Recurso de Revisión que se regenera y la versión que Revisión registró al pedirlo (GEN-R6)."""

    resource_id: str
    resource_version: int

    def to_payload(self) -> dict[str, Any]:
        return {"resourceId": self.resource_id, "resourceVersion": self.resource_version}


@dataclass(frozen=True)
class GenerationStep:
    """Un paso del pedido: un tipo de recurso en su etapa 5E y lo que produjo."""

    position: int
    stage: str
    resource_type: str
    agent: str
    status: StepStatus = StepStatus.PENDING
    resource_ids: tuple[str, ...] = ()
    rejections: tuple[dict[str, Any], ...] = ()
    generator: dict[str, Any] | None = None
    grounding: dict[str, Any] | None = None
    distractor_reliability: dict[str, Any] | None = None
    error: Problem | None = None
    started_at: str | None = None
    finished_at: str | None = None

    @classmethod
    def from_plan(cls, planned: PlannedStep) -> GenerationStep:
        """Paso pendiente a partir del plan de `plan_steps`."""
        return cls(
            position=planned.position,
            stage=planned.stage,
            resource_type=planned.resource_type,
            agent=planned.agent,
        )

    @property
    def is_final(self) -> bool:
        return self.status in FINAL_STEP_STATUSES


@dataclass(frozen=True)
class GenerationRequest:
    """Pedido de generación de un docente para una unidad, con sus pasos en orden 5E."""

    id: str
    teacher_id: str
    unit_id: str
    mode: GenerationMode
    idempotency_key: str
    payload_hash: str
    parameters: GenerationParameters
    created_at: str
    steps: tuple[GenerationStep, ...] = ()
    status: RequestStatus = RequestStatus.QUEUED
    retrieval_mode: str | None = None
    evidence: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    regeneration: RegenerationTarget | None = None
    failure: Problem | None = None
    started_at: str | None = None
    finished_at: str | None = None
    heartbeat_at: str | None = None
    worker_boot_id: str | None = None

    @property
    def is_final(self) -> bool:
        return self.status in FINAL_REQUEST_STATUSES


def final_status(steps: tuple[GenerationStep, ...] | list[GenerationStep]) -> RequestStatus:
    """Estado del pedido cuando todos sus pasos terminaron.

    Todos los pasos `succeeded` → `succeeded`; algunos → `partially_succeeded` (GEN-C3); ninguno → `failed` (GEN-C6).
    """
    unfinished = [step.position for step in steps if not step.is_final]
    if unfinished:
        raise InvalidTransitionError(f"El pedido todavía tiene pasos sin terminar: {unfinished}.")
    succeeded = sum(step.status == StepStatus.SUCCEEDED for step in steps)
    if steps and succeeded == len(steps):
        return RequestStatus.SUCCEEDED
    if succeeded:
        return RequestStatus.PARTIALLY_SUCCEEDED
    return RequestStatus.FAILED


def interrupt(request: GenerationRequest, at: str) -> GenerationRequest:
    """GEN-C4: el servidor se reinició. El pedido y sus pasos sin terminar pasan a `interrupted`.

    Los pasos terminados y sus recursos se conservan. Un pedido que ya está en un estado final no cambia.
    """
    if request.is_final:
        return request
    problem = Problem(GenerationErrorCode.REQUEST_INTERRUPTED, INTERRUPTED_MESSAGE)
    steps = tuple(
        step if step.is_final else replace(step, status=StepStatus.INTERRUPTED, error=problem, finished_at=at)
        for step in request.steps
    )
    return replace(request, status=RequestStatus.INTERRUPTED, steps=steps, failure=problem, finished_at=at)


def payload_hash(parameters: GenerationParameters, regeneration: RegenerationTarget | None = None) -> str:
    """SHA-256 del JSON canónico del pedido normalizado: claves ordenadas y sin espacios (GEN-R5).

    Dos envíos que solo difieren en campos omitidos con su valor por defecto, o en tipos repetidos, dan el mismo hash.
    """
    payload: dict[str, Any] = {"parameters": parameters.to_payload()}
    if regeneration is not None:
        payload["regeneration"] = regeneration.to_payload()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_idempotency_key(key: str | None) -> str:
    """Devuelve la clave si cumple el formato. Sin clave → IDEMPOTENCY_KEY_REQUIRED; con otro formato →
    INVALID_PARAMETERS."""
    if key is None or not key.strip():
        raise GenerationError(
            GenerationErrorCode.IDEMPOTENCY_KEY_REQUIRED,
            "Falta la clave del pedido (cabecera Idempotency-Key). Recarga la página y vuelve a intentarlo.",
        )
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(key):
        raise GenerationError(
            GenerationErrorCode.INVALID_PARAMETERS,
            "La clave del pedido debe tener de 8 a 128 letras, números, guiones o guiones bajos.",
        )
    return key
