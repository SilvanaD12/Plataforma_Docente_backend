"""Esquemas del pedido de generación en segundo plano (GEN-01), según contracts/generation-requests.openapi.yaml."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from platform5e.domain.generation.generation_request import GenerationParameters
from platform5e.domain.generation.sequence import MAX_QUANTITY_PER_TYPE, MAX_SEQUENCE_TYPES, MIN_QUANTITY_PER_TYPE
from platform5e.infrastructure.http.schemas.common import ApiRequest, ApiResponse
from platform5e.infrastructure.http.schemas.generations import (
    Difficulty,
    DistractorReliability,
    GroundingReport,
    ResourceType,
    Stage,
)

RequestMode = Literal["individual", "sequence"]
StoredMode = Literal["individual", "sequence", "regeneration"]
RequestStatus = Literal["queued", "running", "succeeded", "partially_succeeded", "failed", "interrupted"]
StepStatus = Literal["pending", "running", "succeeded", "rejected", "failed", "interrupted"]
# GEN-P2: `plan` es un recurso que no desarrolló sus conceptos del plan o desarrolló los de otro recurso.
RejectionKind = Literal["grounding", "repetition", "structure", "distractor", "plan"]
VerificationStatus = Literal["current", "insufficient", "pending"]
Modality = Literal["Textual", "Gamificado", "Multimedia", "Kinestésico"]


class StartGenerationRequest(ApiRequest):
    """Cuerpo de POST /generation-requests. La clave de idempotencia va en la cabecera `Idempotency-Key`."""

    mode: RequestMode = Field(description="`individual`: exactly one type. `sequence`: one step per type, in 5E order.")
    unit_id: str = Field(description="Unit whose processed material is used.", examples=["unidad-1"])
    resource_types: list[ResourceType] = Field(
        min_length=1,
        max_length=MAX_SEQUENCE_TYPES,
        description=(
            "`individual` requires exactly one type. In `sequence`, repeated types are ignored and the steps follow "
            "the 5E order."
        ),
        examples=[["pregunta_detonante", "item_opcion_multiple"]],
    )
    quantity: int = Field(
        default=1, ge=MIN_QUANTITY_PER_TYPE, le=MAX_QUANTITY_PER_TYPE, description="Common quantity for every type."
    )
    outcome_id: str | None = Field(default=None, description="Learning outcome of the unit, optional.")
    difficulty: Difficulty = "intermedia"
    option_count: int = Field(default=4, ge=2, le=5, description="Options per multiple-choice item.")
    top_k: int = Field(default=10, ge=1, le=50, description="Chunks retrieved from the material.")
    evidence_threshold: float = Field(
        default=0.6, ge=0.0, le=1.0, description="Minimum share of a claim's words that its cited chunks must contain."
    )
    instructions: str = Field(default="", max_length=500, description="Free text from the teacher.")
    audience: str = Field(default="", max_length=200, examples=["Tercer ciclo"])
    competency: str = Field(default="", max_length=200)
    modalities: list[Modality] = Field(
        default_factory=list,
        max_length=1,
        description=(
            "Optional. One modality per request (HU-024). When sent, every type in `resourceTypes` must belong to it "
            "(422 RESOURCE_TYPE_NOT_IN_MODALITY, nothing is created). When omitted, types are not filtered and the "
            "request is saved without a modality. There is no server default."
        ),
    )

    def to_parameters(self) -> GenerationParameters:
        """Los parámetros del dominio. El modo y la unidad viajan aparte en el comando."""
        return GenerationParameters(
            resource_types=tuple(self.resource_types),
            quantity=self.quantity,
            outcome_id=self.outcome_id,
            difficulty=self.difficulty,
            option_count=self.option_count,
            top_k=self.top_k,
            evidence_threshold=self.evidence_threshold,
            instructions=self.instructions,
            audience=self.audience,
            competency=self.competency,
            modality=self.modalities[0] if self.modalities else None,
        )

class StartPlannedGenerationRequest(ApiRequest):
    """GEN-P2: cuerpo de POST /generation-requests con un plan aprobado (specs/006-plan-de-generacion)."""

    plan_id: str = Field(min_length=1, description="An approved plan of the teacher.", examples=["gen-plan-1"])
    plan_version: int = Field(ge=1, description="The plan version the teacher approved; another version answers 409.")


class InterpretGenerationRequest(ApiRequest):
    """Cuerpo de POST /generation-requests/interpret."""

    unit_id: str = Field(
        min_length=1,
        description="The unit open in the Generation tab.",
    )
    message: str = Field(
        min_length=1,
        max_length=2000,
        pattern=r"\S",
        description="Teacher message, trimmed before validation.",
    )

class GenerationInterpretationOption(ApiResponse):
    value: str | int
    label: str


class GenerationInterpretationIssue(ApiResponse):
    field: Literal[
        "unitId", "resourceTypes", "quantity", "modalities",
        "outcomeId", "audience", "competency", "instructions",
    ]
    kind: Literal["missing", "ambiguous", "not_allowed"]
    message: str
    options: list[GenerationInterpretationOption]


class GenerationInterpretationStage(ApiResponse):
    resource_type: ResourceType
    stage: Stage


class GenerationInterpretationSuggestedUnit(ApiResponse):
    unit_id: str
    label: str


class GenerationInterpretationDraft(ApiResponse):
    unit_id: str
    resource_types: list[ResourceType] = Field(max_length=MAX_SEQUENCE_TYPES)
    mode: RequestMode | None = None
    quantity: int | None = Field(
        default=None,
        ge=MIN_QUANTITY_PER_TYPE,
        le=MAX_QUANTITY_PER_TYPE,
    )
    modalities: list[Modality] | None = Field(
        default=None, min_length=1, max_length=1
    )
    outcome_id: str | None = None
    audience: str | None = Field(default=None, max_length=200)
    competency: str | None = Field(default=None, max_length=200)
    instructions: str | None = Field(default=None, max_length=500)


class GenerationInterpretation(ApiResponse):
    draft: GenerationInterpretationDraft
    stages: list[GenerationInterpretationStage]
    issues: list[GenerationInterpretationIssue]
    suggested_unit: GenerationInterpretationSuggestedUnit | None = None

class Problem(ApiResponse):
    code: str = Field(examples=["DEADLINE_EXCEEDED"])
    message: str = Field(description="In Spanish, shown to the teacher.")


class GenerationParametersView(ApiResponse):
    """Los parámetros guardados del pedido. El modo y la unidad están en el nivel superior."""

    resource_types: list[ResourceType] = Field(description="Without duplicates and in 5E order.")
    quantity: int
    outcome_id: str | None = None
    difficulty: Difficulty
    option_count: int
    top_k: int
    evidence_threshold: float
    instructions: str
    audience: str
    competency: str
    modalities: list[Modality] = Field(
        max_length=1,
        description=(
            "The modality chosen by the teacher, as a list of 0 or 1 items (HU-024), with the same shape as the "
            "request body. Empty when the request did not send one. Requests saved before HU-024 return an empty list."
        ),
    )


class GenerationRequestSummary(ApiResponse):
    id: str = Field(examples=["gen-req-6a1f2c3d-0000-4000-8000-000000000000"])
    mode: StoredMode
    unit_id: str
    status: RequestStatus
    resource_types: list[ResourceType] = Field(description="In 5E order.")
    created_at: str = Field(description="ISO 8601 date-time in UTC.")
    finished_at: str | None = None


class StepResource(ApiResponse):
    """Vista corta de un recurso entregado a Revisión."""

    id: str
    title: str
    verification_status: VerificationStatus = Field(
        description=(
            "Current `verification.status` of the resource in Review (REV-01). Generation delivers `current` or "
            "`pending`; `insufficient` appears after an edit in Review. `pending` if the resource has no verification."
        ),
    )


class StepPlanWarning(ApiResponse):
    """GEN-P2: un recurso de la IA entregado con aviso de solapamiento con su plan (research R5)."""

    title: str
    reason: str = Field(description="In Spanish, shown to the teacher.")
    resource_id: str


class StepRejection(ApiResponse):
    title: str
    reason: str = Field(description="In Spanish, shown to the teacher.")
    kind: RejectionKind


class StepGenerator(ApiResponse):
    description: str
    uses_ai: bool
    fallback: bool = Field(description="True when the rule-based generator drafted after the AI failed.")
    fallback_reason: str | None = Field(
        default=None,
        description="In Spanish: why the AI draft was not used (the same warning as the server log). `null` when "
        "`fallback` is false.",
    )


class GenerationStep(ApiResponse):
    position: int = Field(ge=0)
    stage: Stage
    resource_type: ResourceType
    agent: str = Field(examples=["Agente de Enganchar"])
    status: StepStatus
    resource_ids: list[str] = Field(
        description="Resources delivered to Review in this step. Read them with `GET /units/{unitId}/resources/{id}`."
    )
    resources: list[StepResource] = Field(default=[], description="Short view of the delivered resources.")
    rejections: list[StepRejection]
    generator: StepGenerator | None = None
    grounding: GroundingReport | None = None
    distractor_reliability: DistractorReliability | None = None
    error: Problem | None = None
    started_at: str | None = None
    finished_at: str | None = None
    plan_item_position: int | None = Field(
        default=None, ge=1, description="GEN-P2: the plan item this step drafts. `null` in requests without a plan."
    )
    plan_warnings: list[StepPlanWarning] = Field(
        default=[],
        description="GEN-P2: AI resources of this step delivered although they did not fully follow the plan (another "
        "item's concept developed, or none of their own). The rule-based path rejects them with `kind: plan` instead.",
    )


class RegenerationTargetView(ApiResponse):
    resource_id: str
    resource_version: int
    plan_block: int | None = Field(
        default=None, ge=0,
        description="GEN-P2: the block of concepts of the plan item drafted again. Absent for resources without a plan.",
    )


class GenerationRequestStatus(GenerationRequestSummary):
    """Estado del pedido y de cada paso, en orden 5E, tal como lo confirmó el servidor."""

    parameters: GenerationParametersView
    retrieval_mode: Literal["hybrid", "bm25_fallback"] | None = Field(
        default=None,
        description="Search fallback reported by Material. It is independent of `steps[].generator.fallback`.",
    )
    regeneration: RegenerationTargetView | None = Field(
        default=None, description="Only in `regeneration` mode, started by Review through its regeneration port."
    )
    failure: Problem | None = None
    started_at: str | None = None
    plan_id: str | None = Field(
        default=None,
        description="GEN-P2: the approved plan the request started from (an implicit one for the previous body). "
        "`null` in requests created before generation plans.",
    )
    plan_version: int | None = Field(default=None, ge=1, description="GEN-P2: the plan version that was used.")
    steps: list[GenerationStep] = Field(
        description="One step per resource type, in 5E order. With a plan, one step per plan item, in plan order."
    )


class RetrievedFragment(ApiResponse):
    """Un fragmento recuperado por el pedido, con su procedencia (TA-010)."""

    chunk_id: str
    document_id: str
    document_name: str
    location: str
    text: str
    relevance: float = Field(ge=0.0, le=1.0, description="Relevance reported by Material, from 0 to 1.")
    source_url: str | None = None
    license: str | None = None


class GenerationEvidence(ApiResponse):
    """Todo lo que el pedido recuperó del material y entregó al modelo, no solo lo citado (TA-010, research R12)."""

    request_id: str
    retrieval_mode: Literal["hybrid", "bm25_fallback"] | None = Field(
        description="Search fallback reported by Material. `null` while the request is queued."
    )
    limit: int = Field(
        ge=1, description="Maximum number of chunks the request retrieved: its `topK`, bounded from 3 to 12."
    )
    retrieved_at: str | None = Field(
        description="When the request retrieved the chunks (ISO 8601). `null` while the request is queued."
    )
    fragments: list[RetrievedFragment] = Field(
        description=(
            "Every retrieved chunk, in retrieval order. The resources cite a subset of them. Empty while the request "
            "is queued or if the retrieval failed."
        )
    )
