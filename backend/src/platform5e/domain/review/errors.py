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


# Rechazos por el estado de la unidad o de sus recursos (409): se resuelven agregando o procesando material, o
# pidiendo la regeneración otra vez si el recurso nuevo ya no existe (REGENERATED_RESOURCE_NOT_FOUND, PR #17).
# Cualquier otro código de rechazo viene de los parámetros guardados del recurso (422).
MATERIAL_STATE_CODES: frozenset[str] = frozenset(
    {"NO_PROCESSED_MATERIAL", "INSUFFICIENT_EVIDENCE", "REGENERATED_RESOURCE_NOT_FOUND"}
)


class RegenerationFailedError(AccountConfigurationError):
    """REV-C13: la regeneración no terminó bien; el recurso anterior queda como estaba. El mensaje es el motivo.

    Con `code` (Generación rechazó el pedido por los datos del docente) se responde con ese código: 409 por el material
    de la unidad o porque el recurso nuevo ya no existe, y 422 por los parámetros guardados. Sin código es un fallo del proveedor: 502 REGENERATION_FAILED.
    """

    def __init__(self, reason: str, code: str | None = None) -> None:
        if code is None:
            super().__init__("REGENERATION_FAILED", reason, 502)
        else:
            super().__init__(code, reason, 409 if code in MATERIAL_STATE_CODES else 422)
