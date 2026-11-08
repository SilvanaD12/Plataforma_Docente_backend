"""Esquemas del historial de descargas y de la exportación en el backend."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from platform5e.infrastructure.http.schemas.common import ApiRequest, ApiResponse

DownloadFormat = Literal["moodle_xml", "scorm_zip", "documento"]


class DownloadInput(ApiRequest):
    """Download history entry; exports are built and registered by the backend."""

    format: DownloadFormat
    file_name: str = Field(min_length=1, max_length=200, examples=["red-301-unidad-1-documento.html"])
    resource_count: int = Field(ge=0, le=500)


class DownloadResponse(ApiResponse):
    id: str
    unit_id: str
    format: str
    file_name: str
    resource_count: int
    created_at: str


class ExportRequest(ApiRequest):
    format: DownloadFormat = Field(
        description="`scorm_zip`: SCORM 1.2 package for Chamilo. `moodle_xml`: Moodle question bank (multiple choice). `documento`: printable unit document (HTML)."
    )
    resource_ids: list[str] = Field(
        default_factory=list,
        max_length=500,
        description="Approved resources to export; empty exports every approved resource that fits the format.",
    )
