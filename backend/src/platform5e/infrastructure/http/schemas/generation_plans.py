"""Esquemas del plan de generación (GEN-P1), según specs/006-plan-de-generacion/contracts/generation-plans.openapi.yaml."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from platform5e.domain.generation.generation_plan import (
    DEFAULT_PLAN_TOP_K,
    MAX_CONCEPT_CHARS,
    MAX_ITEM_QUANTITY,
    MAX_PLAN_TYPES,
    MAX_PURPOSE_CHARS,
    MAX_TOP_K,
    MIN_ITEM_QUANTITY,
    MIN_TOP_K,
    PlanInputs as DomainPlanInputs,
    RequestedType as DomainRequestedType,
)
from platform5e.infrastructure.http.schemas.common import ApiRequest, ApiResponse
from platform5e.infrastructure.http.schemas.generation_requests import Modality
from platform5e.infrastructure.http.schemas.generations import Difficulty, Stage

PlanStatus = Literal["draft", "approved", "used"]
PlanOrigin = Literal["teacher", "implicit"]
PlanWarning = Literal["SAME_TYPOLOGY_AS_LAST_SESSION"]
PlanProblemCode = Literal[
    "PLAN_EMPTY", "ITEM_WITHOUT_EVIDENCE", "FRAGMENT_NOT_IN_EVIDENCE", "CONCEPT_OWNED_TWICE", "NOT_ENOUGH_CONCEPTS",
    "TYPE_NOT_IN_CATALOG", "RESOURCE_TYPE_NOT_IN_MODALITY", "QUANTITY_OUT_OF_RANGE", "TOO_MANY_TYPES",
    "PURPOSE_REQUIRED", "CONCEPT_NOT_SHORT",
]
RESOURCE_TYPE_ID_PATTERN = r"^[a-z][a-z0-9_]{2,59}$"
RESOURCE_TYPE_ID_DESCRIPTION = (
    "Id of an active entry of the configurable catalog. Today, the values of `GET /resource-types`."
)
MAX_EDITED_ITEMS = 40
MAX_ITEM_COVERS = 20
MAX_ITEM_FRAGMENTS = 12


# Cuerpos


class RequestedType(ApiRequest):
    type: str = Field(pattern=RESOURCE_TYPE_ID_PATTERN, description=RESOURCE_TYPE_ID_DESCRIPTION,
                      examples=["explicacion"])
    quantity: int | None = Field(
        default=None, ge=MIN_ITEM_QUANTITY, le=MAX_ITEM_QUANTITY,
        description="Optional. `null` lets the planner choose, from 1 to 5, according to the available concepts.",
    )


class CreateGenerationPlan(ApiRequest):
    """Cuerpo de POST /generation-plans. La clave de idempotencia va en la cabecera `Idempotency-Key`."""

    unit_id: str = Field(description="Unit whose processed material is used.", examples=["unidad-1"])
    instructions: str = Field(default="", max_length=500,
                              description="The topic. Checked against the evidence: the material must cover it.")
    audience: str = Field(default="", max_length=200)
    competency: str = Field(default="", max_length=200)
    outcome_id: str | None = Field(default=None, description="Learning outcome of the unit, optional.")
    modality: Modality | None = Field(
        default=None, description="Optional. When sent, every type must belong to it (422 otherwise)."
    )
    resource_types: list[RequestedType] = Field(
        min_length=1, max_length=MAX_PLAN_TYPES,
        description="Distinct catalog types; repeated types answer 422 INVALID_PARAMETERS.",
    )
    difficulty: Difficulty = "intermedia"
    option_count: int = Field(default=4, ge=2, le=5, description="Options per multiple-choice item.")
    evidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    top_k: int = Field(default=DEFAULT_PLAN_TOP_K, ge=MIN_TOP_K, le=MAX_TOP_K,
                       description="Chunks retrieved once and frozen in the plan.")

    def to_inputs(self) -> DomainPlanInputs:
        return DomainPlanInputs(
            instructions=self.instructions,
            audience=self.audience,
            competency=self.competency,
            outcome_id=self.outcome_id,
            modality=self.modality,
            resource_types=tuple(DomainRequestedType(r.type, r.quantity) for r in self.resource_types),
            difficulty=self.difficulty,
            option_count=self.option_count,
            evidence_threshold=self.evidence_threshold,
            top_k=self.top_k,
        )


class EditablePlanItem(ApiRequest):
    resource_type: str = Field(pattern=RESOURCE_TYPE_ID_PATTERN, description=RESOURCE_TYPE_ID_DESCRIPTION)
    quantity: int = Field(ge=MIN_ITEM_QUANTITY, le=MAX_ITEM_QUANTITY)
    purpose: str = Field(min_length=1, max_length=MAX_PURPOSE_CHARS)
    covers: list[str] = Field(min_length=1, max_length=MAX_ITEM_COVERS,
                              description=f"Concepts this item owns, each 1 to {MAX_CONCEPT_CHARS} characters.")
    fragment_ids: list[str] = Field(max_length=MAX_ITEM_FRAGMENTS,
                                    description="Ids of `evidence.fragments`. Empty is saved as ITEM_WITHOUT_EVIDENCE.")


class UpdateGenerationPlan(ApiRequest):
    expected_version: int = Field(ge=1, description="The `version` the teacher edited.")
    items: list[EditablePlanItem] = Field(
        max_length=MAX_EDITED_ITEMS,
        description=(
            "The new list, in the order the teacher wants inside each stage. An empty list is saved and reported as "
            "`PLAN_EMPTY`."
        ),
    )


class ApproveGenerationPlan(ApiRequest):
    expected_version: int = Field(ge=1, description="The `version` the teacher reviewed.")


# Respuestas


class PlanRequestedType(ApiResponse):
    type: str
    quantity: int | None


class PlanInputs(ApiResponse):
    instructions: str
    audience: str
    competency: str
    outcome_id: str | None
    modality: Modality | None
    resource_types: list[PlanRequestedType]
    difficulty: str
    option_count: int
    evidence_threshold: float
    top_k: int


class PlanFragment(ApiResponse):
    id: str
    document_id: str
    document_name: str
    location: str
    text: str
    relevance: float = Field(ge=0.0, le=1.0)
    source_url: str | None = None
    license: str | None = None


class PlanEvidence(ApiResponse):
    retrieval_mode: Literal["hybrid", "bm25_fallback"] | None
    retrieved_at: str = Field(description="ISO 8601 UTC.")
    fragments: list[PlanFragment]


class Referent(ApiResponse):
    """Main authors of the topic found in the unit material. Shown in the UI as «referentes»."""

    name: str
    description: str
    fragment_ids: list[str] = Field(description="Fragments of the plan evidence that mention the referent.")


class PreviousTypology(ApiResponse):
    session_label: str
    used_at: str
    resource_types: list[str]


class SessionContext(ApiResponse):
    previous_typologies: list[PreviousTypology] = Field(max_length=3)


class PlanItem(ApiResponse):
    position: int = Field(ge=1)
    stage: Stage
    resource_type: str
    quantity: int = Field(ge=MIN_ITEM_QUANTITY, le=MAX_ITEM_QUANTITY)
    purpose: str
    covers: list[str] = Field(
        description="Concepts this item develops: short noun phrases of 2 to 4 content words from the material, or "
        "acronyms (`CONCEPT_NOT_SHORT` otherwise). Split in `quantity` consecutive blocks."
    )
    does_not_cover: list[str] = Field(description="Read-only. The `covers` of the other items, in order.")
    fragment_ids: list[str] = Field(description="Ids of `evidence.fragments` that support the item.")


class PlanProblem(ApiResponse):
    code: PlanProblemCode
    message: str = Field(description="In Spanish, shown next to the item.")
    item_position: int | None


class PlanValidation(ApiResponse):
    valid: bool
    problems: list[PlanProblem]


class PlanGenerator(ApiResponse):
    description: str
    uses_ai: bool
    fallback: bool = Field(description="True when the rule-based planner drafted the plan after the AI failed.")
    fallback_reason: str | None = Field(description="Generic public reason; null without fallback.")
    attempts: int = Field(
        default=0, ge=0, le=2,
        description="AI calls made to draft the plan: 0 without AI, 1, or 2 when the first plan was invalid and was "
        "asked again with its problems.",
    )
    repairs: list[dict[str, Any]] = Field(
        default=[],
        description="Safe fixes applied to the AI plan without another call (T027 b): a concept repeated in a later "
        "item removed when that item keeps enough concepts (`CONCEPT_OWNED_TWICE`, `removed`), or a quantity chosen by "
        "the AI lowered to its concepts when the teacher left it free (`NOT_ENOUGH_CONCEPTS`, `quantity_lowered`). "
        "Empty when nothing was fixed.",
    )


class GenerationPlan(ApiResponse):
    id: str = Field(examples=["gen-plan-3f6c2a1e-8b4d-4d7a-9a51-0c2f8e1b7d10"])
    version: int = Field(ge=1)
    status: PlanStatus
    origin: PlanOrigin = Field(description="`implicit`: created by the server for a request without plan.")
    unit_id: str
    inputs: PlanInputs
    evidence: PlanEvidence
    referents: list[Referent]
    session_context: SessionContext
    items: list[PlanItem]
    validation: PlanValidation
    warnings: list[PlanWarning]
    generator: PlanGenerator
    used_by_request_id: str | None
    created_at: str
    updated_at: str
    approved_at: str | None
    used_at: str | None
