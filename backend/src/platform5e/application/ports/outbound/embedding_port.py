"""
Puertos de los embeddings (EN-013): convertir textos en vectores y guardarlos junto a cada fragmento del material,
para que la recuperación pueda buscar por significado además de por palabras (HU-011).
"""

from __future__ import annotations

from typing import Any, Protocol


class EmbeddingGeneratorPort(Protocol):
    """Modelo de embeddings: devuelve un vector de `dimensions` números por cada texto."""

    model: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Vectores de los fragmentos del material, en el mismo orden que `texts`."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Vector de una consulta de búsqueda (el modelo lo optimiza distinto que a un documento)."""
        ...


class ChunkEmbeddingRepositoryPort(Protocol):
    """Almacén vectorial de los fragmentos (pgvector en PostgreSQL)."""

    def vector_store_available(self) -> bool:
        """False si la base no tiene pgvector (SQLite o PostgreSQL sin la extensión): no hay dónde guardar."""
        ...

    def get_chunks_missing_embeddings(
        self, model: str, limit: int, document_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Hasta `limit` fragmentos sin vector o con un vector de otro modelo: [{'id', 'text'}]."""
        ...

    def save_embeddings(self, embeddings: dict[str, list[float]], model: str) -> int:
        """Guarda el vector de cada fragmento con el modelo que lo generó. Devuelve cuántos guardó."""
        ...

    def count_embedded_chunks(self, model: str, document_id: str | None = None) -> int:
        """Cuántos fragmentos ya tienen vector de `model` (de un documento o de toda la base)."""
        ...

    def search_similar_chunks(
        self, vector: list[float], limit: int, unit_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Los fragmentos más cercanos por distancia coseno: [{'id', 'documentId', 'location', 'text', 'similarity'}]."""
        ...
