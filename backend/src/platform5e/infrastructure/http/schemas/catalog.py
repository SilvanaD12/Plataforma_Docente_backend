"""Contrato público del catálogo de tipos de recurso."""
from typing import Literal

from pydantic import Field

from platform5e.infrastructure.http.schemas.common import ApiResponse


class ResourceTypeResponse(ApiResponse):
    id: str
    name: str
    singular: str
    count: tuple[str, str]
    stage: Literal["engage", "explore", "explain", "elaborate", "evaluate"]
    group: str
    format: Literal["text", "visual", "image", "audio", "interactive"]
    has_options: bool
    modalities: list[Literal["Textual", "Gamificado", "Multimedia", "Kinestésico"]] = Field(
        min_length=1,
        description="Modalities that include this type (HU-024). Every catalog type belongs to at least one.",
    )
