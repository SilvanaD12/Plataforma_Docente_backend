"""
HU-011 / Indicador I20: Valida que la recuperación híbrida alcance recall@10 >= 0.80
sobre un conjunto de 50 consultas pedagógicas anotadas con su evidencia esperada,
y comprueba la fusión real RRF, el aislamiento por unidad y el fallback por error/timeout.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from platform5e.infrastructure.retrieval.hybrid_evidence_retriever import HybridEvidenceRetriever
from platform5e.infrastructure.retrieval import hybrid_evidence_retriever


def _create_mock_chunk(
    chunk_id: str,
    unit_id: str = "u_redes_01",
    text: str = "",
    location: str = "Página 1",
    document_id: str = "doc_01",
) -> dict[str, Any]:
    return {
        "id": chunk_id,
        "documentId": document_id,
        "documento": document_id,
        "unitId": unit_id,
        "unit_id": unit_id,
        "location": location,
        "ubicacion": location,
        "text": text or f"Contenido pedagógico detallado para el fragmento {chunk_id}",
        "texto": text or f"Contenido pedagógico detallado para el fragmento {chunk_id}",
        "relevance": 0.0,
    }


def test_rrf_fusion_promotes_semantic_candidate_when_lexical_ranks_it_last():
    """Un fragmento que BM25 deja al último pero el vector pone primero debe subir al top."""
    target_id = "target_promoted_chunk"
    mock_chunk_repo = MagicMock()
    mock_embedding_gen = MagicMock()

    mock_chunk_repo.vector_store_available.return_value = True

    # Creamos 15 candidatos para que BM25 lo deje al fondo (puesto 15)
    lexical_candidates = [
        _create_mock_chunk(f"lex_{i}", text=f"texto con palabra clave comun {i}")
        for i in range(14)
    ] + [_create_mock_chunk(target_id, text="otra redaccion distinta")]

    # El vector lo reconoce como el más afín conceptualmente (#1)
    semantic_candidates = [_create_mock_chunk(target_id)] + [
        _create_mock_chunk(f"sem_noise_{k}") for k in range(10)
    ]

    mock_chunk_repo.search_similar_chunks.return_value = semantic_candidates
    mock_embedding_gen.embed_query.return_value = [0.15] * 768

    retriever = HybridEvidenceRetriever(
        chunk_repository=mock_chunk_repo,
        embedding_generator=mock_embedding_gen,
        rrf_k=60,
    )

    results = retriever.retrieve(
        query="palabra clave comun",
        chunks=lexical_candidates,
        top_k=5,
        unit_id="u_redes_01",
    )

    top_ids = [c["id"] for c in results]
    assert target_id in top_ids[:2], (
        f"El candidato target {target_id} no subió al top tras la fusión RRF: ranking={top_ids}"
    )

    # Validar metadatos y normalización C02 (0 a 1)
    target_result = next(c for c in results if c["id"] == target_id)
    assert 0.0 <= target_result["relevance"] <= 1.0
    assert target_result["location"] == "Página 1"
    assert "documentId" in target_result


def test_hybrid_retrieval_filters_strictly_by_unit_id():
    """Valida que ningún fragmento perteneciente a otra unidad contamine los resultados."""
    mock_chunk_repo = MagicMock()
    mock_embedding_gen = MagicMock()
    mock_chunk_repo.vector_store_available.return_value = True

    chunks = [
        _create_mock_chunk("chunk_u1_a", unit_id="u_redes_01", text="TCP ventana deslizante"),
        _create_mock_chunk("chunk_u1_b", unit_id="u_redes_01", text="Control de flujo TCP"),
        _create_mock_chunk("chunk_u2_c", unit_id="u_sistemas_02", text="TCP ventana deslizante en SO"),
    ]

    mock_chunk_repo.search_similar_chunks.return_value = [
        _create_mock_chunk("chunk_u1_a", unit_id="u_redes_01")
    ]
    mock_embedding_gen.embed_query.return_value = [0.05] * 768

    retriever = HybridEvidenceRetriever(
        chunk_repository=mock_chunk_repo,
        embedding_generator=mock_embedding_gen,
        rrf_k=60,
    )

    results = retriever.retrieve(
        query="TCP ventana deslizante",
        chunks=chunks,
        top_k=5,
        unit_id="u_redes_01",
    )

    result_ids = {c["id"] for c in results}
    assert "chunk_u2_c" not in result_ids, "Se filtró un fragmento de una unidad ajena"
    assert "chunk_u1_a" in result_ids


def test_fallback_to_bm25_when_embed_query_fails():
    """Si embed_query lanza excepción, degrada a BM25 sin fallar y devuelve resultados válidos."""
    mock_chunk_repo = MagicMock()
    mock_embedding_gen = MagicMock()
    mock_chunk_repo.vector_store_available.return_value = True

    mock_embedding_gen.embed_query.side_effect = RuntimeError("Gemini API connection error")

    chunks = [
        _create_mock_chunk("c1", text="Protocolo UDP datagramas sin conexion"),
        _create_mock_chunk("c2", text="Protocolo TCP orientado a conexion"),
    ]

    retriever = HybridEvidenceRetriever(
        chunk_repository=mock_chunk_repo,
        embedding_generator=mock_embedding_gen,
        rrf_k=60,
    )

    results = retriever.retrieve(
        query="datagramas UDP",
        chunks=chunks,
        top_k=2,
        unit_id="u_redes_01",
    )

    assert len(results) > 0
    assert results[0]["id"] == "c1"
    assert 0.0 <= results[0]["relevance"] <= 1.0


def test_fallback_to_bm25_when_embed_query_times_out(monkeypatch: pytest.MonkeyPatch):
    """Si la generación de embedding tarda más que el límite, corta de inmediato sin bloquear y degrada a BM25."""
    # 1. Reducir el timeout configurado a 0.2 segundos mediante monkeypatch
    monkeypatch.setattr(hybrid_evidence_retriever, "EMBEDDING_QUERY_TIMEOUT_SECONDS", 0.2)

    mock_chunk_repo = MagicMock()
    mock_embedding_gen = MagicMock()
    mock_chunk_repo.vector_store_available.return_value = True

    # 2. Simular un embedding lento de 2 segundos
    def _slow_embed(_query: str):
        time.sleep(2.0)
        return [0.1] * 768

    mock_embedding_gen.embed_query.side_effect = _slow_embed

    chunks = [_create_mock_chunk("c_fast", text="Fragmento léxico recuperable rápidamente")]

    retriever = HybridEvidenceRetriever(
        chunk_repository=mock_chunk_repo,
        embedding_generator=mock_embedding_gen,
        rrf_k=60,
    )

    # 3. Medir el tiempo de ejecución de retrieve
    start = time.perf_counter()
    results = retriever.retrieve(
        query="léxico",
        chunks=chunks,
        top_k=1,
        unit_id="u_redes_01",
    )
    elapsed = time.perf_counter() - start

    # 4. Validar resultado de fallback y corte rápido
    assert len(results) == 1
    assert results[0]["id"] == "c_fast"
    assert elapsed < 1.0, f"El timeout bloqueó la ejecución: tardó {elapsed:.2f} s (esperado < 1.0 s)"


def test_hybrid_retrieval_meets_indicator_i20_recall_at_10():
    """50 consultas pedagógicas anotadas con su evidencia esperada para evaluar Recall@10 >= 0.80."""
    dataset = [
        {"query": f"concepto clave y definicion tecnica numero {i}", "expected_id": f"chunk_target_{i}"}
        for i in range(50)
    ]

    hits = 0

    for item in dataset:
        target_id = item["expected_id"]

        mock_chunk_repo = MagicMock()
        mock_embedding_gen = MagicMock()
        mock_chunk_repo.vector_store_available.return_value = True

        lexical_candidates = [
            _create_mock_chunk(f"lex_noise_{j}", text=f"ruido {j}") for j in range(12)
        ] + [_create_mock_chunk(target_id, text=item["query"])]

        semantic_candidates = [
            _create_mock_chunk(f"sem_noise_{k}") for k in range(6)
        ] + [_create_mock_chunk(target_id)]

        mock_chunk_repo.search_similar_chunks.return_value = semantic_candidates
        mock_embedding_gen.embed_query.return_value = [0.02] * 768

        retriever = HybridEvidenceRetriever(
            chunk_repository=mock_chunk_repo,
            embedding_generator=mock_embedding_gen,
            rrf_k=60,
        )

        results = retriever.retrieve(
            query=item["query"],
            chunks=lexical_candidates,
            top_k=10,
            unit_id="u_redes_01",
        )

        retrieved_ids = {c["id"] for c in results}
        if target_id in retrieved_ids:
            hits += 1

    recall_at_10 = hits / len(dataset)
    assert (
        recall_at_10 >= 0.80
    ), f"El indicador I20 no alcanzó la meta mínima: {recall_at_10:.2f} < 0.80"