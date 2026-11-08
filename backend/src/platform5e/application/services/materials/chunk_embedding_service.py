"""
Vectorización incremental de los fragmentos del material (EN-013).

Pide los embeddings por lotes y solo de los fragmentos que todavía no tienen vector del modelo actual, así que
volver a ejecutarlo no recalcula lo que ya existe. Si cambia el modelo, los vectores anteriores se vuelven a calcular.
"""

from __future__ import annotations

from dataclasses import dataclass

from platform5e.application.ports.outbound.embedding_port import (
    ChunkEmbeddingRepositoryPort,
    EmbeddingGeneratorPort,
)

DEFAULT_BATCH_SIZE: int = 50


class EmbeddingError(Exception):
    """El modelo de embeddings devolvió una respuesta que no se puede guardar."""


@dataclass(frozen=True)
class EmbeddingRun:
    """Resultado de una vectorización: cuántos vectores se calcularon ahora y cuántos hay en total."""

    embedded: int
    total: int
    model: str
    available: bool = True


class ChunkEmbeddingService:
    """Genera y guarda los embeddings de los fragmentos que todavía no los tienen."""

    def __init__(
        self,
        repository: ChunkEmbeddingRepositoryPort,
        generator: EmbeddingGeneratorPort,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        self._repository = repository
        self._generator = generator
        self._batch_size = max(1, batch_size)

    @property
    def model(self) -> str:
        return self._generator.model

    def embed_pending(self, document_id: str | None = None, limit: int | None = None) -> EmbeddingRun:
        """Vectoriza por lotes los fragmentos pendientes (de un documento o de toda la base)."""
        if not self._repository.vector_store_available():
            return EmbeddingRun(embedded=0, total=0, model=self.model, available=False)

        embedded = 0
        while limit is None or embedded < limit:
            batch_limit = self._batch_size if limit is None else min(self._batch_size, limit - embedded)
            pending = self._repository.get_chunks_missing_embeddings(self.model, batch_limit, document_id)
            if not pending:
                break
            vectors = self._generator.embed_documents([chunk["text"] for chunk in pending])
            self._check_vectors(vectors, len(pending))
            saved = self._repository.save_embeddings(
                {chunk["id"]: vector for chunk, vector in zip(pending, vectors)}, self.model
            )
            if saved == 0:
                break  # nada se guardó: evita repetir el mismo lote para siempre
            embedded += saved
        total = self._repository.count_embedded_chunks(self.model, document_id)
        return EmbeddingRun(embedded=embedded, total=total, model=self.model)

    def _check_vectors(self, vectors: list[list[float]], expected: int) -> None:
        if len(vectors) != expected:
            raise EmbeddingError(f"Se esperaban {expected} vectores y llegaron {len(vectors)}.")
        dimensions = self._generator.dimensions
        if any(len(vector) != dimensions for vector in vectors):
            raise EmbeddingError(f"Los vectores deben tener {dimensions} dimensiones.")
