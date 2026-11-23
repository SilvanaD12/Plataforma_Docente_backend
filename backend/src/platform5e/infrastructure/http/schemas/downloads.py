"""Esquemas del historial de descargas y de la exportación en el backend."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from platform5e.infrastructure.http.schemas.common import ApiRequest, ApiResponse

DownloadFormat = Literal["moodle_xml", "scorm_zip", "documento"]


class DownloadResponse(ApiResponse):
    id: str
    unit_id: str
    format: str
    file_name: str
    resource_count: int
    created_at: str
    course_id: str | None = Field(default=None, description="Course at export time (REV-R9).")
    course_name: str | None = Field(
        default=None, description="Course name at export time. Kept after the course is deleted; null in older records."
    )
    unit_name: str | None = Field(default=None, description="Unit title at export time; null in older records.")
    unit_number: int | None = Field(default=None, description="Unit number at export time; null in older records.")


class ExportRequest(ApiRequest):
    format: DownloadFormat = Field(
        description="`scorm_zip`: SCORM 1.2 package for Chamilo. `moodle_xml`: Moodle question bank (multiple choice, true/false and matching). `documento`: printable unit document (HTML)."
    )
    resource_ids: list[str] = Field(
        default_factory=list,
        max_length=500,
        description="Approved resources to export; empty exports every approved resource that fits the format.",
    )


class ExportPreviewRequest(ApiRequest):
    format: str = Field(
        description="Format to preview. Only `scorm_zip` is supported for preview.",
        examples=["scorm_zip"],
    )
    resource_ids: list[str] = Field(
        default_factory=list,
        max_length=500,
        description="Resources to preview; empty includes every eligible resource.",
    )


class ExportPreviewPage(ApiResponse):
    number: int = Field(ge=1, description="1-based page index in sequential order.")
    title: str = Field(description="Page title or quiz name.")
    html: str = Field(description="Full rendered HTML content for this page.")


class ExportExcludedReason(ApiResponse):
    reason: str = Field(description="Exclusion reason code.")
    count: int = Field(ge=0, description="Number of resources excluded for this reason.")


class ExportPreviewResponse(ApiResponse):
    pages: list[ExportPreviewPage] = Field(description="Rendered SCORM pages.")
    excluded: list[ExportExcludedReason] = Field(description="Summary of excluded resources by reason.")

