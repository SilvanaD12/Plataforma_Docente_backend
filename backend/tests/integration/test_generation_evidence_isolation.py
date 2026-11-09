"""GEN-01 (T033, Constitución IV): la evidencia de un docente nunca trae fragmentos de otro docente.

Dos docentes guardan material con el mismo `unit_id` y el mismo tema. Se usan el repositorio real de fragmentos sobre un
SQLite temporal, el buscador híbrido real de Material y el adaptador de evidencia de Generación. SQLite no tiene
pgvector, así que la parte vectorial la simula un índice que filtra solo por unidad (el peor caso: devuelve los
fragmentos de los dos docentes); el filtro por docente del buscador y del adaptador debe descartarlos igual.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import sessionmaker

from platform5e.application.ports.outbound.evidence_provider_port import EvidenceQuery, NoProcessedMaterial
from platform5e.infrastructure.adapters.material_evidence_adapter import MaterialEvidenceAdapter
from platform5e.infrastructure.persistence.repositories import (
    sqlalchemy_account_repository as accounts,
    sqlalchemy_chunk_repository as chunks_module,
    sqlalchemy_generation_repository as generations,
)
from platform5e.infrastructure.retrieval.hybrid_evidence_retriever import HybridEvidenceRetriever

TEACHER_A = "rosa.quispe@correo.pe"
TEACHER_B = "mario.salas@correo.pe"
SHARED_UNIT = "unidad-compartida"
QUERY = "diferencias entre TCP y UDP en la capa de transporte"


class UnitOnlyVectorIndex(chunks_module.SQLAlchemyChunkRepository):
    """Repositorio real de fragmentos con un índice vectorial simulado que ignora al docente."""

    def __init__(self) -> None:
        super().__init__()
        self.vector_searches: list[dict[str, Any]] = []
        self.index_ready = False  # al guardar se usa el SQLite real, sin vectores

    def vector_store_available(self) -> bool:
        return self.index_ready

    def search_similar_chunks(
        self, vector: list[float], limit: int, unit_id: str | None = None, teacher_id: str | None = None
    ) -> list[dict[str, Any]]:
        self.vector_searches.append({"unit_id": unit_id, "teacher_id": teacher_id})
        everyone = self.get_chunks_by_unit(TEACHER_A, unit_id or "") + self.get_chunks_by_unit(TEACHER_B, unit_id or "")
        return [{**chunk, "similarity": 0.9} for chunk in everyone][:limit]


class FixedEmbedding:
    def embed_query(self, query: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class NoDocuments:
    def get_documents(self, teacher_id: str) -> list[dict[str, Any]]:
        return []


def _material(teacher: str, prefix: str) -> list[dict[str, Any]]:
    """El mismo tema para los dos docentes, para que BM25 encuentre ambos si no se filtrara por docente."""
    return [
        {"id": f"{prefix}-1", "order": 0, "location": "p. 1", "text": "TCP es orientado a conexión y confiable."},
        {"id": f"{prefix}-2", "order": 1, "location": "p. 2", "text": "UDP no establece conexión en la capa de transporte."},
        {"id": f"{prefix}-3", "order": 2, "location": "p. 3", "text": f"Apuntes de {teacher}: TCP y UDP comparados."},
    ]


@pytest.fixture
def chunk_repository(tmp_path, monkeypatch, request) -> UnitOnlyVectorIndex:
    engine = create_engine(URL.create("sqlite", database=str(tmp_path / "t033.db")))
    request.addfinalizer(engine.dispose)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(accounts, "engine", engine)
    monkeypatch.setattr(accounts, "SessionLocal", sessions)
    monkeypatch.setattr(generations, "engine", engine)
    monkeypatch.setattr(chunks_module, "engine", engine)
    monkeypatch.setattr(chunks_module, "SessionLocal", sessions)
    accounts.SQLAlchemyAccountRepository(generations.SQLAlchemyGenerationRepository())  # crea las tablas

    repository = UnitOnlyVectorIndex()
    repository.replace_chunks(TEACHER_A, "doc-rosa", SHARED_UNIT, _material(TEACHER_A, "frag-rosa"))
    repository.replace_chunks(TEACHER_B, "doc-mario", SHARED_UNIT, _material(TEACHER_B, "frag-mario"))
    repository.index_ready = True
    return repository


@pytest.mark.parametrize("embeddings", [True, False], ids=["hibrida", "solo-bm25"])
@pytest.mark.parametrize(
    ("teacher", "own", "foreign"), [(TEACHER_A, "frag-rosa", "frag-mario"), (TEACHER_B, "frag-mario", "frag-rosa")]
)
def test_one_teacher_never_gets_fragments_of_another_with_the_same_unit_id(
    chunk_repository, embeddings, teacher, own, foreign
):
    retriever = HybridEvidenceRetriever(chunk_repository, FixedEmbedding() if embeddings else None)
    adapter = MaterialEvidenceAdapter(chunk_repository, retriever, NoDocuments())

    # Precondición: la unidad compartida tiene fragmentos de los dos docentes y el índice simulado los mezcla.
    assert len(chunk_repository.get_chunks_by_unit(TEACHER_A, SHARED_UNIT)) == 3
    assert len(chunk_repository.get_chunks_by_unit(TEACHER_B, SHARED_UNIT)) == 3

    retrieval = adapter.retrieve(EvidenceQuery(teacher, SHARED_UNIT, QUERY, limit=10))

    ids = [fragment.chunk_id for fragment in retrieval.fragments]
    assert ids and all(chunk_id.startswith(own) for chunk_id in ids)
    assert not any(chunk_id.startswith(foreign) for chunk_id in ids)
    assert retrieval.retrieval_mode == ("hybrid" if embeddings else "bm25_fallback")
    if embeddings:
        # La búsqueda vectorial recibió el docente; aunque el índice lo ignoró, nada ajeno llegó al pedido.
        assert chunk_repository.vector_searches == [{"unit_id": SHARED_UNIT, "teacher_id": teacher}]
    else:
        assert chunk_repository.vector_searches == []


def test_the_retriever_alone_also_filters_by_teacher(chunk_repository):
    """Sin pasar por el adaptador: el buscador híbrido de Material filtra por docente al leer de la base."""
    retriever = HybridEvidenceRetriever(chunk_repository, FixedEmbedding())
    results = retriever.retrieve(QUERY, top_k=10, unit_id=SHARED_UNIT, teacher_id=TEACHER_A)
    assert results and {item["id"].split("-")[1] for item in results} == {"rosa"}
    assert {item["retrieval_mode"] for item in results} == {"hybrid"}


def test_a_teacher_without_material_in_the_shared_unit_gets_no_evidence(chunk_repository):
    """Que otro docente tenga material con ese `unit_id` no cuenta como material propio."""
    retriever = HybridEvidenceRetriever(chunk_repository, FixedEmbedding())
    adapter = MaterialEvidenceAdapter(chunk_repository, retriever, NoDocuments())
    assert adapter.has_processed_material("otra.docente@correo.pe", SHARED_UNIT) is False
    with pytest.raises(NoProcessedMaterial):
        adapter.retrieve(EvidenceQuery("otra.docente@correo.pe", SHARED_UNIT, QUERY, limit=10))
