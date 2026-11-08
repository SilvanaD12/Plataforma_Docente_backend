"""
EN-013: los fragmentos se vectorizan por lote (C01), de forma incremental sin recalcular lo existente (C02) y al
procesar el material (C03). Si el modelo falla, el documento queda procesado y la búsqueda por palabras sigue.
"""

from __future__ import annotations

from typing import Any

import pytest

from platform5e.application.ports.outbound.embedding_port import (
    ChunkEmbeddingRepositoryPort,
    EmbeddingGeneratorPort,
)
from platform5e.application.services.materials.chunk_embedding_service import (
    ChunkEmbeddingService,
    EmbeddingError,
)
from tests.unit.test_material_service import PAGE_TEXT, build_test_environment


class FakeEmbedder(EmbeddingGeneratorPort):
    """Devuelve un vector de 4 dimensiones por texto y registra el tamaño de cada lote."""

    dimensions = 4

    def __init__(self, model: str = "modelo-falso", fail: bool = False, wrong_size: bool = False) -> None:
        self.model = model
        self.fail = fail
        self.wrong_size = wrong_size
        self.batches: list[int] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise ConnectionError("Gemini no respondió")
        self.batches.append(len(texts))
        size = 3 if self.wrong_size else self.dimensions
        return [[float(len(text))] + [0.0] * (size - 1) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class InMemoryVectorStore(ChunkEmbeddingRepositoryPort):
    """Almacén vectorial en memoria: {id: {'text', 'document', 'vector', 'model'}}."""

    def __init__(self, chunks: dict[str, dict[str, Any]] | None = None, available: bool = True) -> None:
        self.chunks = chunks or {}
        self.available = available

    def vector_store_available(self) -> bool:
        return self.available

    def get_chunks_missing_embeddings(self, model: str, limit: int, document_id: str | None = None) -> list[dict]:
        pending = [
            {"id": chunk_id, "text": chunk["text"]}
            for chunk_id, chunk in self.chunks.items()
            if (chunk.get("vector") is None or chunk.get("model") != model)
            and (document_id is None or chunk["document"] == document_id)
        ]
        return pending[:limit]

    def save_embeddings(self, embeddings: dict[str, list[float]], model: str) -> int:
        for chunk_id, vector in embeddings.items():
            self.chunks[chunk_id].update(vector=vector, model=model)
        return len(embeddings)

    def count_embedded_chunks(self, model: str, document_id: str | None = None) -> int:
        return sum(
            1
            for chunk in self.chunks.values()
            if chunk.get("vector") is not None and chunk.get("model") == model
            and (document_id is None or chunk["document"] == document_id)
        )

    def search_similar_chunks(self, vector: list[float], limit: int, unit_id: str | None = None) -> list[dict]:
        return []


def store_with(count: int, document: str = "doc1") -> InMemoryVectorStore:
    return InMemoryVectorStore(
        {f"frag-{i}": {"text": f"Fragmento {i} sobre TCP y UDP", "document": document} for i in range(count)}
    )


# --- C01: por lotes ----------------------------------------------------------------------------------------------


def test_chunks_are_embedded_in_batches():
    store, embedder = store_with(7), FakeEmbedder()
    run = ChunkEmbeddingService(store, embedder, batch_size=3).embed_pending()
    assert embedder.batches == [3, 3, 1]
    assert (run.embedded, run.total, run.model) == (7, 7, "modelo-falso")
    assert all(len(chunk["vector"]) == 4 and chunk["model"] == "modelo-falso" for chunk in store.chunks.values())


def test_the_limit_stops_after_that_many_chunks():
    store, embedder = store_with(10), FakeEmbedder()
    run = ChunkEmbeddingService(store, embedder, batch_size=4).embed_pending(limit=6)
    assert embedder.batches == [4, 2] and run.embedded == 6 and run.total == 6


def test_only_the_chunks_of_the_document_are_embedded():
    store = store_with(2, "doc1")
    store.chunks["otro"] = {"text": "Otro documento", "document": "doc2"}
    run = ChunkEmbeddingService(store, FakeEmbedder()).embed_pending(document_id="doc1")
    assert run.embedded == 2 and store.chunks["otro"].get("vector") is None


# --- C02: incremental ----------------------------------------------------------------------------------------------


def test_a_second_run_does_not_recompute_existing_embeddings():
    store, embedder = store_with(5), FakeEmbedder()
    service = ChunkEmbeddingService(store, embedder)
    service.embed_pending()
    run = service.embed_pending()
    assert embedder.batches == [5] and run.embedded == 0 and run.total == 5


def test_only_new_chunks_are_embedded_when_some_already_have_a_vector():
    store, embedder = store_with(3), FakeEmbedder()
    ChunkEmbeddingService(store, embedder).embed_pending()
    store.chunks["nuevo"] = {"text": "Fragmento nuevo", "document": "doc1"}
    run = ChunkEmbeddingService(store, embedder).embed_pending()
    assert embedder.batches == [3, 1] and (run.embedded, run.total) == (1, 4)


def test_changing_the_model_recomputes_the_vectors():
    store = store_with(3)
    ChunkEmbeddingService(store, FakeEmbedder("modelo-a")).embed_pending()
    run = ChunkEmbeddingService(store, FakeEmbedder("modelo-b")).embed_pending()
    assert run.embedded == 3 and {chunk["model"] for chunk in store.chunks.values()} == {"modelo-b"}


# --- Respuestas que no se pueden guardar y bases sin pgvector -----------------------------------------------------


def test_vectors_with_another_dimension_are_not_saved():
    store = store_with(2)
    with pytest.raises(EmbeddingError, match="4 dimensiones"):
        ChunkEmbeddingService(store, FakeEmbedder(wrong_size=True)).embed_pending()
    assert all(chunk.get("vector") is None for chunk in store.chunks.values())


def test_without_pgvector_nothing_is_requested_from_the_model():
    store, embedder = InMemoryVectorStore(available=False), FakeEmbedder()
    run = ChunkEmbeddingService(store, embedder).embed_pending()
    assert not run.available and run.embedded == 0 and embedder.batches == []


# --- C03: al procesar el material ------------------------------------------------------------------------------


class VectorChunkRepository(InMemoryVectorStore):
    """Une el repositorio de fragmentos de las pruebas de ingesta con el almacén vectorial en memoria."""

    def __init__(self, chunk_repository: Any) -> None:
        super().__init__()
        self.chunk_repository = chunk_repository

    def get_chunks_missing_embeddings(self, model: str, limit: int, document_id: str | None = None) -> list[dict]:
        for document, chunks in self.chunk_repository.chunks_db.items():
            for chunk in chunks:
                text = chunk.get("text", chunk.get("texto"))
                self.chunks.setdefault(chunk["id"], {"text": text, "document": document})
        return super().get_chunks_missing_embeddings(model, limit, document_id)


def processing_with(embedder: FakeEmbedder):
    service, config_repo, chunk_repo = build_test_environment()
    store = VectorChunkRepository(chunk_repo)
    service._embedding_service = ChunkEmbeddingService(store, embedder)
    return service, config_repo, store


def test_processing_the_material_embeds_its_chunks():
    service, config_repo, store = processing_with(FakeEmbedder())
    data = service.process_material("d", "doc1")
    assert data["status"] == "procesado"
    assert (data["embeddedFragmentCount"], data["embeddingModel"], data["embeddingError"]) == (1, "modelo-falso", None)
    assert config_repo.docs["doc1"][0]["embeddedFragmentCount"] == 1
    [chunk] = store.chunks.values()
    assert chunk["text"].startswith(PAGE_TEXT[:20]) and chunk["vector"] is not None


def test_if_the_model_fails_the_material_stays_processed_with_the_reason():
    service, _, store = processing_with(FakeEmbedder(fail=True))
    data = service.process_material("d", "doc1")
    assert data["status"] == "procesado" and data["fragmentCount"] == 1
    assert data["embeddedFragmentCount"] == 0 and "Gemini no respondió" in data["embeddingError"]


def test_without_embeddings_the_processing_result_does_not_change():
    service, _, _ = build_test_environment()
    data = service.process_material("d", "doc1")
    assert "embeddedFragmentCount" not in data
