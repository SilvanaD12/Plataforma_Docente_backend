"""Esquemas de los recursos generados y su revisión docente."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, computed_field, field_validator

from platform5e.application.services.review.resource_review_service import validate_approval_blockers
from platform5e.infrastructure.html_sanitizer import clean_html
from platform5e.infrastructure.http.schemas.common import ApiRequest, ApiResponse

# Valores guardados en la base: pasan al inglés en el Sprint 2 junto con una migración de datos.
ReviewStatus = Literal["pendiente", "aprobado", "descartado"]
OptionDecision = Literal["pendiente", "aceptado", "descartado"]
DiscardReason = Literal["sin_sentido", "tambien_correcto", "duplicado", "fuera_de_unidad", "otro", "regenerado"]


class CitationResponse(ApiResponse):
    claim: str = Field(description="Sentence of the resource that needs support.")
    fragment_ids: list[str] = Field(description="Chunks of the teacher's material that support it.")


class EvidenceResponse(ApiResponse):
    """Copy of a cited chunk, saved with the resource when it was generated."""

    id: str
    text: str
    location: str
    document_id: str
    document_name: str
    source_url: str | None = None
    license: str | None = None


class ResourceOptionResponse(ApiResponse):
    id: str
    text: str
    is_correct: bool
    feedback: str = ""
    source_fragment_ids: list[str] = []
    decision: str = Field(description="Only distractors are decided: `pendiente`, `aceptado` or `descartado`.")
    discard_reason: str | None = None
    edited: bool = False
    misconception: str | None = Field(
        default=None, description="Distractors only: the conceptual error the distractor represents (HU-019)."
    )
    reliability_warning: str | None = Field(
        default=None,
        description=(
            "Why the distractor was discarded automatically: the material shows it as correct (HU-019). "
            "The teacher can accept it again."
        ),
    )


class MediaResponse(ApiResponse):
    """Image or audio generated for the resource. `fallback`: no file, the review shows the description or uses the
    browser's voice."""

    status: Literal["ready", "fallback"]
    id: str | None = None
    mime_type: str | None = None
    file_name: str | None = None
    note: str | None = None
    outdated: bool = Field(default=False, description="The teacher edited the script or description after generating.")


class RemovedClaim(ApiResponse):
    claim: str
    support: float = Field(description="Share of the claim words found in the cited chunks (0 to 1).")
    supported: bool = False
    reason: str | None = Field(default=None, description="Why it was removed, in Spanish.")


class RemovedParagraph(ApiResponse):
    text: str
    support: float = Field(description="Share of the paragraph words found in the retrieved chunks (0 to 1).")
    supported: bool = False
    reason: str | None = Field(default=None, description="Why it was removed, in Spanish.")


class ResourceGrounding(ApiResponse):
    """HU-016: each claim is checked against the retrieved evidence; the unsupported ones are removed."""

    threshold: float = Field(description="Minimum support, from the request `evidenceThreshold`.")
    checked_claims: int
    supported_claims: int
    corrected_claims: int = Field(
        default=0, description="Claims that cited the wrong chunk and were moved to the one that supports them."
    )
    removed_claims: list[RemovedClaim] = []
    paragraph_threshold: float | None = Field(
        default=None, description="Explanation and glossary only: minimum support of each paragraph (HU-049)."
    )
    checked_paragraphs: int | None = Field(default=None, description="Paragraphs or glossary entries checked.")
    supported_paragraphs: int | None = None
    paragraph_sources: list[list[str]] = Field(
        default=[], description="For each kept paragraph, in order, the chunks that support it."
    )
    removed_paragraphs: list[RemovedParagraph] = Field(
        default=[], description="Paragraphs removed from the content because the material does not support them."
    )


class ResourceResponse(ApiResponse):
    id: str
    unit_id: str
    outcome_id: str | None = None
    stage: str = Field(description="5E stage: engage, explore, explain, elaborate or evaluate.")
    type: str = Field(description="Resource type, e.g. `item_opcion_multiple`.")
    title: str
    body: str = Field(description="Content. In questions it is the prompt; paragraphs separated by a blank line.")
    body_html: str | None = Field(default=None, description="Formatted content from the rich text editor (sanitized).")
    format: str = Field(default="text", description="`text`, `visual`, `image`, `audio` or `interactive`.")
    structure: dict[str, Any] | None = Field(
        default=None, description="Items of visual, audio and interactive resources (nodes, steps, pairs, statements…)."
    )
    media: MediaResponse | None = None
    options: list[ResourceOptionResponse] | None = None
    citations: list[CitationResponse] = []
    status: str = Field(description="`pendiente`, `aprobado` or `descartado`.")
    edited: bool = False
    discard_reason: str | None = None
    created_at: str
    updated_at: str | None = None
    decided_at: str | None = None
    evidence: list[EvidenceResponse] = []
    params: dict[str, Any] | None = Field(default=None, description="Request parameters, reused by «Regenerar».")
    agent: str | None = Field(
        default=None, description="Stage agent that drafted the resource in a sequence request (HU-003)."
    )
    grounding: ResourceGrounding | None = Field(
        default=None, description="Grounding check of its claims against the retrieved evidence (HU-016)."
    )

    @computed_field(description="Reasons that block approval, computed by the same rule that validates approval.")
    @property
    def approval_blockers(self) -> list[str]:
        return validate_approval_blockers({
            "body": self.body,
            "type": self.type,
            "structure": self.structure,
            "media": self.media.model_dump(by_alias=True) if self.media else None,
            "options": [option.model_dump(by_alias=True) for option in self.options] if self.options else None,
        })


class ReviewedOptionInput(ApiRequest):
    id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=600)
    feedback: str = Field(default="", max_length=600)
    decision: OptionDecision
    discard_reason: DiscardReason | None = None
    edited: bool = False


class ReviewedResourceInput(ApiRequest):
    """The teacher's review. Approval is blocked while distractors are pending (409 APPROVAL_BLOCKED)."""

    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=8000)
    body_html: str | None = Field(
        default=None, max_length=20000, description="HTML from the editor; only text formatting and web links are kept."
    )
    structure: dict[str, Any] | None = Field(default=None, description="Edited items of the activity or graphic.")
    status: ReviewStatus
    discard_reason: DiscardReason | None = None
    edited: bool = False
    options: list[ReviewedOptionInput] | None = Field(default=None, max_length=10)

    @field_validator("body_html")
    @classmethod
    def sanitize_html(cls, value: str | None) -> str | None:
        return clean_html(value) if value is not None else None


class UnitSummaryResponse(ApiResponse):
    course_id: str
    unit_id: str
    approved: int = Field(description="Approved resources of the unit.")
    pending: int = Field(description="Resources waiting for review.")
