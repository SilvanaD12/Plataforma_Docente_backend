"""
Puerto para la persistencia y recuperación de resultados de generación pedagógica.
"""

from __future__ import annotations

from typing import Any, Protocol


class GenerationRepositoryPort(Protocol):
    """Define las operaciones de persistencia del motor de generación 5E."""

    def get_demo_catalog(self) -> dict[str, Any]:
        """Obtiene el catálogo base o de demostración disponible."""
        ...

    def save(self, result: dict[str, Any], teacher_id: str | None = None) -> None:
        """Persiste el resultado generado para un docente opcional."""
        ...

    def get_by_id(self, generation_id: str) -> dict[str, Any] | None:
        """Obtiene un resultado de generación por su identificador único."""
        ...