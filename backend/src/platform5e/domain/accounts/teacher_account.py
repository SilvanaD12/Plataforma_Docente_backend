"""
Errores y reglas de negocio del módulo de cuenta y configuración del docente (EP-002).
"""

from __future__ import annotations

from platform5e.domain.shared.errors import DomainError


class AccountConfigurationError(DomainError):
    """Error de validación o configuración de la cuenta del docente."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code: str = code
        self.message: str = message
        self.status_code: int = status_code
        super().__init__(message)
