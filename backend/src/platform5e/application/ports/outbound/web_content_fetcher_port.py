"""Puerto de salida para descargar y extraer texto limpio de una URL pública (MAT-P1)."""

from __future__ import annotations

from typing import Any, Protocol


class WebContentFetcherPort(Protocol):
    def fetch(self, url: str) -> dict[str, Any]:
        """
        Descarga una URL pública y retorna un diccionario con:
        - 'url': str (URL final tras redirecciones seguras)
        - 'title': str (título extraído de la página o dominio)
        - 'text': str (texto plano limpio)
        """
        ...