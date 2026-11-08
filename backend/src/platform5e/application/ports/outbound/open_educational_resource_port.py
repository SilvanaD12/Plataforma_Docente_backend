"""Puerto de consulta de fuentes educativas abiertas."""

from __future__ import annotations

from typing import Any, Protocol


class OpenEducationalResourcePort(Protocol):
    """Puerto para la consulta de recursos y fuentes abiertas externas."""

    def search(self, topic: str, limit: int) -> list[dict[str, Any]]:
        """Devuelve [{'titulo', 'url', 'texto', 'licencia', 'fuente'}] sobre el tema solicitado."""
        ...
