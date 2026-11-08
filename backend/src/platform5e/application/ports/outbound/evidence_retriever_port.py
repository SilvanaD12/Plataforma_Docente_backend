"""
Puerto de recuperación de evidencia (la «R» de RAG): elige los fragmentos del material que sustentan un pedido.

Implementado por búsqueda por palabras BM25 y búsqueda híbrida (BM25 + pgvector HNSW, HU-011).
"""

from __future__ import annotations

from typing import Any, Protocol


class EvidenceRetrieverPort(Protocol):
    """Contrato del buscador de evidencia dentro del material procesado de una unidad."""

    description: str

    def retrieve(
        self,
        query: str,
        chunks: list[dict[str, Any]] | None = None,
        top_k: int = 5,
        unit_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Devuelve hasta `top_k` fragmentos más relevantes para `query`.

        Recibe opcionalmente los fragmentos cargados en memoria (`chunks`) o el identificador
        de la unidad temática (`unit_id`) para filtrado indexado en base de datos.
        Cada fragmento conserva sus llaves y agrega 'relevance', un valor entre 0 y 1.
        """
        ...