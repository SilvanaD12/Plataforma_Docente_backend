"""
Puerto de persistencia de los recursos generados: revisión docente e historial de descargas.
"""

from __future__ import annotations

from typing import Any, Protocol


class ResourceReviewRepositoryPort(Protocol):
    """Contrato para la persistencia del ciclo de vida de revisión y descargas."""

    def get_resources_by_unit(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        """Lista los recursos asignados a una unidad académica."""
        ...

    def get_resource_by_id(self, teacher_id: str, resource_id: str) -> dict[str, Any] | None:
        """Obtiene el detalle completo de un recurso por su ID."""
        ...

    def save_resources(
        self, teacher_id: str, unit_id: str, resources: list[dict[str, Any]]
    ) -> None:
        """Guarda o actualiza un lote de recursos para una unidad."""
        ...

    def delete_resource(self, teacher_id: str, resource_id: str) -> None:
        """Elimina un recurso del repositorio."""
        ...

    def get_downloads(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        """Obtiene el historial de descargas realizadas por el docente en la unidad."""
        ...

    def save_download(
        self, teacher_id: str, unit_id: str, download_record: dict[str, Any]
    ) -> None:
        """Registra un evento de descarga en el historial."""
        ...

    def delete_downloads(self, teacher_id: str, unit_id: str) -> None:
        """Limpia el historial de descargas de una unidad."""
        ...

