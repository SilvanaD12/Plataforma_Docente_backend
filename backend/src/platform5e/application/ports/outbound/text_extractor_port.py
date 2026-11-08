"""Puerto de extracción de texto de documentos."""

from __future__ import annotations

from typing import Protocol


class TextExtractorPort(Protocol):
    """Puerto para la extracción de texto sin formato a partir de documentos binarios."""

    def extract(self, file_type: str, content: bytes) -> list[tuple[str, str]]:
        """Devuelve [(ubicación, texto)]: una entrada por página, diapositiva o sección."""
        ...
