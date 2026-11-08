"""
Errores y datos de generación independientes del transporte HTTP y de la persistencia.
"""

from __future__ import annotations

from platform5e.domain.shared.errors import DomainError


class GenerationError(DomainError):
    """Error producido durante el flujo de generación del modelo pedagógico 5E."""

    def __init__(self, code: str, message: str) -> None:
        self.code: str = code
        self.message: str = message
        super().__init__(message)
