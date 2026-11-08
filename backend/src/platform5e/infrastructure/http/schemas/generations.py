"""Esquemas de la generación de recursos con el material de la unidad (RAG)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from platform5e.infrastructure.http.schemas.common import ApiRequest, ApiResponse
from platform5e.infrastructure.http.schemas.resources import ResourceResponse

Stage = Literal["engage", "explore", "explain", "elaborate", "evaluate"]
ResourceType = Literal[
    "pregunta_detonante",
    "sondeo_diagnostico",
    "guia_exploracion",
    "caso_indagacion",
    "explicacion",
    "glosario",
    "ejercicio_aplicacion",
    "item_opcion_multiple",
    "audio_detonante",
    "imagen_ilustrativa",
    "diagrama_proceso",
    "exploracion_guiada",
    "reto_prediccion",
    "mapa_conceptual",
    "infografia",
    "podcast_resumen",
    "caso_aplicado",
    "emparejamiento",
    "ordenar_pasos",
    "verdadero_falso",
    "completar_espacios",
]
Difficulty = Literal["basica", "intermedia", "avanzada"]


class GenerationRequest(ApiRequest):
    unit_id: str = Field(description="Unit whose processed material is used.", examples=["unidad-1"])
    outcome_id: str | None = Field(default=None, description="Learning outcome of the unit, optional.")
    stage: Stage | None = Field(
        default=None, description="5E stage of the requested resource. Required unless `resourceTypes` is sent.",
        examples=["evaluate"],
    )
    resource_type: ResourceType | None = Field(
        default=None, description="Requested resource type. Required unless `resourceTypes` is sent.",
        examples=["item_opcion_multiple"],
    )
    resource_types: list[ResourceType] | None = Field(
        default=None,
        min_length=1,
        max_length=8,
        description=(
            "Several resource types for one class sequence (HU-003). Each type goes to the agent of its 5E stage, "
            "in the order of the class, and a resource that repeats another one of the sequence is rejected. "
            "When present, `stage` and `resourceType` are ignored."
        ),
        examples=[["pregunta_detonante", "explicacion", "item_opcion_multiple"]],
    )
    quantity: int = Field(default=1, ge=1, le=5)
    difficulty: Difficulty = "intermedia"
    option_count: int = Field(default=4, ge=2, le=5, description="Options per multiple-choice item.")
    top_k: int = Field(default=10, ge=1, le=50, description="Chunks retrieved from the material (BM25).")
    evidence_threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum share of a claim's words that its cited chunks must contain (HU-016). "
            "Claims below it are removed, and a resource with less than half of its claims supported is rejected."
        ),
    )
    instructions: str = Field(default="", max_length=500, description="Free text from the teacher.")
    audience: str = Field(default="", max_length=200, examples=["Tercer ciclo"])
    competency: str = Field(default="", max_length=200)
    # Sprint 1: solo texto (HU-053, alcance acordado con el docente). Otra modalidad responde 422.
    modalities: list[Literal["Textual"]] = Field(
        default_factory=lambda: ["Textual"], max_length=1, description="Sprint 1 generates text only."
    )

    @model_validator(mode="after")
    def require_a_resource_type(self) -> "GenerationRequest":
        if not self.resource_types and (self.stage is None or self.resource_type is None):
            raise ValueError("Send `stage` and `resourceType`, or `resourceTypes` for a sequence.")
        return self

    def to_domain(self) -> dict[str, Any]:
        """El diccionario que esperan los servicios de generación."""
        return {
            "unitId": self.unit_id,
            "outcomeId": self.outcome_id,
            "stage": self.stage,
            "resourceType": self.resource_type,
            "resourceTypes": list(self.resource_types) if self.resource_types else None,
            "quantity": self.quantity,
            "difficulty": self.difficulty,
            "optionCount": self.option_count,
            "topK": self.top_k,
            "evidenceThreshold": self.evidence_threshold,
            "instructions": self.instructions,
            "audience": self.audience,
            "competency": self.competency,
            "modalities": self.modalities,
        }


class GeneratorInfo(ApiResponse):
    description: str = Field(examples=["Gemini (gemini-3.8-flash)"])
    uses_ai: bool = Field(description="False when the rule-based generator is active.")
    provider: str = Field(examples=["gemini", "rules"])
    model: str | None = None


class GenerationGenerator(ApiResponse):
    description: str
    uses_ai: bool
    fallback: bool = Field(description="True when the AI failed and the rule-based generator answered.")


class GenerationRequestRecord(ApiResponse):
    """The request as it was saved: GET /generations lists them, newest first."""

    id: str
    unit_id: str
    created_at: str
    stage: str
    resource_type: str
    quantity: int


class GeneratedChunk(ApiResponse):
    id: str
    location: str | None = None
    text: str | None = None
    relevance: float = 0.0


class SequenceStep(ApiResponse):
    """What one stage agent did in a sequence request."""

    stage: str = Field(description="5E stage of the agent.")
    resource_type: str
    agent: str = Field(examples=["Agente de Enganchar"])
    generated: int = Field(description="Resources kept for review.")
    rejected: list[str] = Field(default=[], description="Resources rejected for repeating another one, with the reason.")


class RejectedResource(ApiResponse):
    title: str
    reason: str = Field(description="Why it was rejected, in Spanish.")


class GroundingReport(ApiResponse):
    """HU-016: grounding check of the whole request. `hallucinationRate` is indicator I21."""

    checked_claims: int = Field(description="Claims checked, in kept and rejected resources.")
    supported_claims: int
    unsupported_claims: int
    hallucination_rate: float | None = Field(
        default=None, description="I21: unsupported / checked claims (null when nothing was checked)."
    )
    unsupported_paragraphs: int = Field(
        default=0, description="Explanation paragraphs and glossary entries removed for lack of support (HU-049)."
    )
    rejected_resources: list[RejectedResource] = Field(
        default=[], description="Resources rejected because less than half of their claims had support."
    )


class DistractorReliability(ApiResponse):
    """HU-019: distractors discarded before review because the material shows them as correct (indicator I5)."""

    evaluated_distractors: int
    discarded_as_correct: int
    reliability_error_rate: float | None = Field(
        default=None, description="discardedAsCorrect / evaluatedDistractors, detected before the teacher's review."
    )


class GenerationResult(ApiResponse):
    mode: Literal["api_demo", "rag"] = Field(description="`rag`: the teacher's material; `api_demo`: test catalog.")
    notice: str = Field(description="Message shown to the teacher.")
    generator: GenerationGenerator | None = None
    request: dict[str, Any] = Field(description="The saved request, with its id.")
    resources: list[ResourceResponse] = Field(description="Generated resources, saved as `pendiente` for review.")
    available: int
    fragments: list[dict[str, Any]] = Field(description="Chunks cited by the resources.")
    documents: list[dict[str, Any]] = Field(description="Documents those chunks come from.")
    distractor_reliability: DistractorReliability | None = Field(
        default=None, description="Only with the teacher's material (`rag`): distractor reliability check (HU-019)."
    )
    grounding: GroundingReport | None = Field(
        default=None, description="Only with the teacher's material (`rag`): grounding check of the request (HU-016)."
    )
    sequence: list[SequenceStep] | None = Field(
        default=None, description="Only in sequence requests (`resourceTypes`): one step per stage agent."
    )
    retrieved_chunks: list[GeneratedChunk] = Field(
        default=[], description="Everything retrieved, not only what was cited. Used by the Ragas evaluation."
    )
