"""Contrato público del catálogo de tipos de recurso."""
from typing import Literal

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
