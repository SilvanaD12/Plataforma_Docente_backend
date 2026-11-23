"""
GEN-P1: el plan de generación (specs/006-plan-de-generacion/data-model.md).

El plan dice qué recursos se van a generar, en qué orden y etapa, para qué sirve cada uno, qué conceptos le
corresponden (`covers`) y en qué fragmentos se apoya. Congela su evidencia al crearse. Se guarda en borrador aunque
sea inválido; solo se aprueba si es válido; pasa a usado cuando inicia un pedido de generación (GEN-P2). Aquí están
las entidades y las transiciones de estado; la validación está en `plan_validation.py`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any

from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.sequence import STAGE_ORDER

MAX_PLAN_TYPES: int = 8
MIN_ITEM_QUANTITY: int = 1
MAX_ITEM_QUANTITY: int = 5
MIN_TOP_K: int = 3
MAX_TOP_K: int = 12
DEFAULT_PLAN_TOP_K: int = 12
MAX_PURPOSE_CHARS: int = 300
MAX_CONCEPT_CHARS: int = 120

VERSION_CONFLICT_MESSAGE: str = "El plan cambió en otra pestaña. Recárgalo y vuelve a intentarlo."
ALREADY_USED_MESSAGE: str = "Este plan ya se usó para generar. Crea un plan nuevo."
INVALID_MESSAGE: str = "El plan tiene problemas. Corrígelos antes de aprobarlo."
NOT_APPROVED_MESSAGE: str = "Aprueba el plan antes de generar."


class PlanStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    USED = "used"


@dataclass(frozen=True)
class RequestedType:
    """Un tipo pedido por el docente; `quantity` None deja que el planificador elija."""

    type: str
    quantity: int | None = None

    def to_payload(self) -> dict[str, Any]:
        return {"type": self.type, "quantity": self.quantity}


@dataclass(frozen=True)
class PlanInputs:
    """Lo que pidió el docente, normalizado. No cambia después de crear el plan."""

    instructions: str
    audience: str
    competency: str
    outcome_id: str | None
    modality: str | None
    resource_types: tuple[RequestedType, ...]
    difficulty: str = "intermedia"
    option_count: int = 4
    evidence_threshold: float = 0.6
    top_k: int = DEFAULT_PLAN_TOP_K

    def to_payload(self) -> dict[str, Any]:
        return {
            "instructions": self.instructions,
            "audience": self.audience,
            "competency": self.competency,
            "outcomeId": self.outcome_id,
            "modality": self.modality,
            "resourceTypes": [requested.to_payload() for requested in self.resource_types],
            "difficulty": self.difficulty,
            "optionCount": self.option_count,
            "evidenceThreshold": self.evidence_threshold,
            "topK": self.top_k,
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> PlanInputs:
        return cls(
            instructions=data.get("instructions", ""),
            audience=data.get("audience", ""),
            competency=data.get("competency", ""),
            outcome_id=data.get("outcomeId"),
            modality=data.get("modality"),
            resource_types=tuple(RequestedType(r["type"], r.get("quantity")) for r in data.get("resourceTypes", [])),
            difficulty=data.get("difficulty", "intermedia"),
            option_count=int(data.get("optionCount", 4)),
            evidence_threshold=float(data.get("evidenceThreshold", 0.6)),
            top_k=int(data.get("topK", DEFAULT_PLAN_TOP_K)),
        )


@dataclass(frozen=True)
class PlanFragment:
    """Un fragmento de la evidencia congelada del plan."""

    id: str
    document_id: str
    document_name: str
    location: str
    text: str
    relevance: float
    source_url: str | None
    license: str | None

    def to_payload(self) -> dict[str, Any]:
        return {"id": self.id, "documentId": self.document_id, "documentName": self.document_name,
                "location": self.location, "text": self.text, "relevance": self.relevance,
                "sourceUrl": self.source_url, "license": self.license}

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> PlanFragment:
        return cls(data["id"], data.get("documentId", ""), data.get("documentName", ""), data.get("location", ""),
                   data.get("text", ""), float(data.get("relevance", 0.0)), data.get("sourceUrl"),
                   data.get("license"))


@dataclass(frozen=True)
class PlanEvidence:
    retrieval_mode: str | None
    retrieved_at: str
    fragments: tuple[PlanFragment, ...]

    @property
    def fragment_ids(self) -> set[str]:
        return {fragment.id for fragment in self.fragments}

    def to_payload(self) -> dict[str, Any]:
        return {"retrievalMode": self.retrieval_mode, "retrievedAt": self.retrieved_at,
                "fragments": [fragment.to_payload() for fragment in self.fragments]}

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> PlanEvidence:
        return cls(data.get("retrievalMode"), data.get("retrievedAt", ""),
                   tuple(PlanFragment.from_payload(f) for f in data.get("fragments", [])))


@dataclass(frozen=True)
class Referent:
    """Un referente del tema (MAT-P2): autor principal, con los fragmentos de la evidencia donde aparece."""

    name: str
    description: str = ""
    fragment_ids: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "fragmentIds": list(self.fragment_ids)}

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> Referent:
        return cls(data.get("name", ""), data.get("description", ""), tuple(data.get("fragmentIds", [])))


@dataclass(frozen=True)
class PreviousTypology:
    """Los tipos usados en una sesión anterior del curso (CUR-P3)."""

    session_label: str
    used_at: str
    resource_types: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {"sessionLabel": self.session_label, "usedAt": self.used_at, "resourceTypes": list(self.resource_types)}


@dataclass(frozen=True)
class SessionContext:
    previous_typologies: tuple[PreviousTypology, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {"previousTypologies": [typology.to_payload() for typology in self.previous_typologies]}

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> SessionContext:
        return cls(tuple(
            PreviousTypology(t.get("sessionLabel", ""), t.get("usedAt", ""), tuple(t.get("resourceTypes", [])))
            for t in data.get("previousTypologies", [])
        ))


@dataclass(frozen=True)
class PlanItem:
    """Un ítem del plan. `doesNotCover` no se guarda: lo calcula `plan_validation.does_not_cover`."""

    position: int
    stage: str
    resource_type: str
    quantity: int
    purpose: str
    covers: tuple[str, ...]
    fragment_ids: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {"position": self.position, "stage": self.stage, "resourceType": self.resource_type,
                "quantity": self.quantity, "purpose": self.purpose, "covers": list(self.covers),
                "fragmentIds": list(self.fragment_ids)}

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> PlanItem:
        return cls(int(data["position"]), data["stage"], data["resourceType"], int(data["quantity"]),
                   data.get("purpose", ""), tuple(data.get("covers", [])), tuple(data.get("fragmentIds", [])))


@dataclass(frozen=True)
class PlanProblem:
    """Un problema de validación, con su código estable y el mensaje para el docente."""

    code: str
    message: str
    item_position: int | None = None

    def to_payload(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "itemPosition": self.item_position}


@dataclass(frozen=True)
class GenerationPlan:
    id: str
    teacher_id: str
    unit_id: str
    idempotency_key: str
    payload_hash: str
    version: int
    status: PlanStatus
    origin: str
    inputs: PlanInputs
    evidence: PlanEvidence
    referents: tuple[Referent, ...]
    session_context: SessionContext
    items: tuple[PlanItem, ...]
    warnings: tuple[str, ...]
    generator: dict[str, Any]
    used_by_request_id: str | None
    created_at: str
    updated_at: str
    approved_at: str | None = None
    used_at: str | None = None
    extra: dict[str, Any] = field(default_factory=dict, compare=False)


class PlanInvalid(GenerationError):
    """Se intentó aprobar un plan con problemas: el router los devuelve en `details`."""

    def __init__(self, problems: Sequence[PlanProblem]) -> None:
        super().__init__(GenerationErrorCode.PLAN_INVALID, INVALID_MESSAGE)
        self.problems: tuple[PlanProblem, ...] = tuple(problems)


def order_items(items: Iterable[PlanItem]) -> tuple[PlanItem, ...]:
    """Ítems en el orden de las etapas y, dentro de cada etapa, en el orden recibido; posiciones de 1 a N."""
    listed = list(items)
    ranked = sorted(
        enumerate(listed),
        key=lambda pair: (STAGE_ORDER.index(pair[1].stage) if pair[1].stage in STAGE_ORDER else len(STAGE_ORDER),
                          pair[0]),
    )
    return tuple(replace(item, position=number) for number, (_, item) in enumerate(ranked, 1))


def _check_writable(plan: GenerationPlan, expected_version: int) -> None:
    if plan.status == PlanStatus.USED:
        raise GenerationError(GenerationErrorCode.PLAN_ALREADY_USED, ALREADY_USED_MESSAGE)
    if expected_version != plan.version:
        raise GenerationError(GenerationErrorCode.PLAN_VERSION_CONFLICT, VERSION_CONFLICT_MESSAGE)


def edit_plan(plan: GenerationPlan, expected_version: int, items: Iterable[PlanItem], now: str) -> GenerationPlan:
    """Edición del docente: sube la versión y vuelve a borrador, aunque el plan quede inválido (data-model)."""
    _check_writable(plan, expected_version)
    return replace(plan, items=order_items(items), version=plan.version + 1, status=PlanStatus.DRAFT,
                   approved_at=None, updated_at=now)


def approve_plan(
    plan: GenerationPlan, expected_version: int, problems: Sequence[PlanProblem], now: str
) -> GenerationPlan:
    """Aprueba un plan válido en su versión actual. Uno ya aprobado en esa versión se devuelve sin cambios."""
    _check_writable(plan, expected_version)
    if plan.status == PlanStatus.APPROVED:
        return plan
    if problems:
        raise PlanInvalid(problems)
    return replace(plan, status=PlanStatus.APPROVED, approved_at=now, updated_at=now)


def mark_plan_used(plan: GenerationPlan, plan_version: int, request_id: str, now: str) -> GenerationPlan:
    """GEN-P2: el plan aprobado, en esa versión, inicia un pedido de generación y pasa a usado."""
    _check_writable(plan, plan_version)
    if plan.status != PlanStatus.APPROVED:
        raise GenerationError(GenerationErrorCode.PLAN_NOT_APPROVED, NOT_APPROVED_MESSAGE)
    return replace(plan, status=PlanStatus.USED, used_by_request_id=request_id, used_at=now, updated_at=now)
