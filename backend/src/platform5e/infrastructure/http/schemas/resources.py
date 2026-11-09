"""Esquemas de los recursos generados y su revisión docente."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, computed_field, field_validator

from platform5e.application.services.review.resource_review_service import approval_blockers
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
    retrieved_at: str | None = Field(
        default=None, description="When the chunk was retrieved (ISO 8601). `null` means unknown, as in migrated resources."
    )


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


class VerificationResult(ApiResponse):
    """REV-01: result of checking the current content against the stored evidence copy (REV-R4, REV-R5)."""

    status: Literal["current", "insufficient", "pending"] = Field(
        description="Shown as vigente, insuficiente or pendiente. Only `current` with the current fingerprint counts."
    )
    reason: str | None = Field(default=None, description="Why it is not current, in Spanish. Set unless `current`.")
    fingerprint: str = Field(description="Fingerprint of the verified content: `sha256:<hex>`.")
    verified_version: int = Field(description="Resource version whose content was verified.")
    evidence_threshold: float = Field(ge=0, le=1, description="Threshold of the original request, reused on every check.")
    rule_version: int = Field(ge=1, description="VERIFICATION_RULE_VERSION used for this check.")
    checked_at: str = Field(description="When it was checked (ISO 8601).")
    retry_available: bool = Field(
        description="True only for `pending` with a complete evidence copy: «Reintentar comprobación» is offered."
    )
    summary: dict[str, Any] = Field(default_factory=dict, description="What was checked, kept or removed.")


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
    version: int = Field(default=1, ge=1, description="Current version. Send it back as `expectedVersion` when saving.")
    verification: VerificationResult | None = Field(
        default=None, description="Last check against the stored evidence copy (REV-01). None until it is checked."
    )
    review_reset: bool | None = Field(
        default=None,
        description="Only in the save response: true when an approved resource changed its content and went back to review.",
    )

    @computed_field(description="Reasons that block approval, computed by the same rule that validates approval.")
    @property
    def approval_blockers(self) -> list[str]:
        return approval_blockers({
            "body": self.body,
            "type": self.type,
            "structure": self.structure,
            "media": self.media.model_dump(by_alias=True) if self.media else None,
            "options": [option.model_dump(by_alias=True) for option in self.options] if self.options else None,
            "citations": [citation.model_dump(by_alias=True) for citation in self.citations],
            "verification": self.verification.model_dump(by_alias=True) if self.verification else None,
        })


class VerificationRetryInput(ApiRequest):
    """«Reintentar comprobación» de un recurso con verificación pendiente (REV-C3)."""

    expected_version: int = Field(ge=1, description="Version you read. The retry does not change it.", examples=[1])


class ReviewedOptionInput(ApiRequest):
    id: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=600)
    feedback: str = Field(default="", max_length=600)
    decision: OptionDecision
    discard_reason: DiscardReason | None = None
    edited: bool = False


class ReviewedResourceInput(ApiRequest):
    """The teacher's review. Approval is blocked while distractors are pending (409 APPROVAL_BLOCKED). A save that
    starts from an outdated version is rejected (409 VERSION_CONFLICT)."""

    expected_version: int = Field(
        ge=1, description="Version the edit starts from (the `version` you read). Required (REV-R12).", examples=[1]
    )
    title: str = Field(min_length=1, max_length=160)
    body: str = Field(min_length=1, max_length=8000)
    body_html: str | None = Field(
        default=None,
        max_length=20000,
        description=(
            "HTML from the editor; only text formatting and web links are kept. If `body` changes and no new `bodyHtml` "
            "is sent (missing or equal to the stored one), the stored HTML is cleared and `body` is used."
        ),
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
