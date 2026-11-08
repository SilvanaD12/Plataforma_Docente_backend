"""Errores de Revisión y exportación (REV-01)."""

from __future__ import annotations

from typing import Any

from platform5e.domain.accounts.teacher_account import AccountConfigurationError


class ExportNotEligibleError(AccountConfigurationError):
    """REV-C7: ningún recurso cumple el filtro común. `details` dice cuántos quedaron fuera por cada motivo.

    Hereda de `AccountConfigurationError` para conservar el código, el estado y el manejo HTTP que ya tenía el caso.
    """

    def __init__(self, message: str, details: list[dict[str, Any]]) -> None:
        super().__init__("NO_APPROVED_RESOURCES", message, 422)
        self.details: list[dict[str, Any]] = details
