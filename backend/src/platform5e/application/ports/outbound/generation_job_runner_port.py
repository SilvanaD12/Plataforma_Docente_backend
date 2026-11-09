"""
Puerto del ejecutor en segundo plano de los pedidos de generación (GEN-01, research R3).
"""

from __future__ import annotations

from typing import Protocol


class GenerationJobRunnerPort(Protocol):
    """Encola la ejecución de un pedido ya guardado. El adaptador inicial usa un grupo de hilos del proceso."""

    def submit(self, request_id: str) -> None:
        """Encola la ejecución. No bloquea."""
        ...

    def shutdown(self, wait: bool) -> None:
        """Deja de aceptar pedidos. Con `wait`, espera a que terminen los que están en curso."""
        ...
