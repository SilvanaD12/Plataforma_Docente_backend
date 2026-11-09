"""Puerto de persistencia de fragmentos de material."""

from __future__ import annotations

from typing import Any, Protocol


class ChunkRepositoryPort(Protocol):
    """Puerto para la persistencia y consulta de fragmentos de material educativo."""

    def replace_chunks(
        self, teacher_id: str, document_id: str, unit_id: str, chunks: list[dict[str, Any]]
    ) -> None:
        """Reemplaza los fragmentos asociados a un documento y unidad."""
        ...

    def get_chunks_by_document(self, teacher_id: str, document_id: str) -> list[dict[str, Any]]:
        """Obtiene todos los fragmentos asociados a un documento."""
        ...

    def get_chunks_by_unit(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        """Obtiene todos los fragmentos asociados a una unidad pedagógica."""
        ...

    def update_document(self, teacher_id: str, document_data: dict[str, Any]) -> None:
        """Actualiza los metadatos o estado de un documento educativo."""
        ...