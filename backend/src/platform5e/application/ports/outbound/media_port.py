"""
Puertos de los medios de un recurso: generar imagen o audio (modelo multimodal), guardarlos y dibujar los gráficos.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class GeneratedMedia:
    """Archivo producido por el modelo: bytes, tipo MIME y extensión sin punto."""

    content: bytes
    mime_type: str
    extension: str


class MediaGeneratorPort(Protocol):
    """Genera la imagen o el audio de un recurso. Lanza una excepción si el servicio no responde."""

    description: str

    def generate_image(self, prompt: str) -> GeneratedMedia: ...

    def synthesize_speech(self, script: str) -> GeneratedMedia: ...


class MediaRepositoryPort(Protocol):
    """Guarda los archivos generados (imagen o audio) de cada recurso."""

    def save_media(self, teacher_id: str, media: Mapping[str, Any], content: bytes) -> None: ...

    def get_media(self, teacher_id: str, media_id: str) -> tuple[dict[str, Any], bytes] | None: ...


class VisualRendererPort(Protocol):
    """Dibuja como SVG los recursos visuales (mapa conceptual, infografía, diagrama) y la tarjeta de respaldo."""

    def render(self, resource: Mapping[str, Any]) -> str: ...
