"""
Puerto de verificación de recursos (REV-01 · Revisión y Exportación): Generación verifica cada recurso antes de
entregarlo a Revisión con las mismas reglas que Revisión aplica al guardarlo, sin importar el dominio de Revisión.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class ResourceVerificationPort(Protocol):
    """Contrato que Revisión ofrece a Generación para la copia histórica, la huella y la verificación."""

    def referenced_fragment_ids(self, resource: Mapping[str, Any]) -> list[str]:
        """Fragmentos que citan las afirmaciones, las alternativas y la estructura del recurso, sin repetir y en orden
        de aparición."""
        ...

    def fingerprint(self, resource: Mapping[str, Any]) -> str:
        """Huella `sha256:<hex>` del contenido verificable del recurso."""
        ...

    def verify(self, resource: Mapping[str, Any], threshold: float) -> dict[str, Any]:
        """Verifica el recurso contra su copia histórica (`evidence`) con la regla vigente. Devuelve el bloque
        `verification` de REV-01: `status` (`current`, `insufficient` o `pending`), `reason`, `fingerprint`,
        `verifiedVersion`, `evidenceThreshold`, `ruleVersion`, `checkedAt`, `retryAvailable` y `summary`."""
        ...
