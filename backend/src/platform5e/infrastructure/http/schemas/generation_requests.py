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
RejectionKind = Literal["grounding", "repetition", "structure", "distractor"]
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


class StepRejection(ApiResponse):
    title: str
    reason: str = Field(description="In Spanish, shown to the teacher.")
    kind: RejectionKind


class StepGenerator(ApiResponse):
    description: str
    uses_ai: bool
    fallback: bool = Field(description="True when the rule-based generator drafted after the AI failed.")


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


class RegenerationTargetView(ApiResponse):
    resource_id: str
    resource_version: int


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
    steps: list[GenerationStep] = Field(description="One step per resource type, in 5E order.")


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
