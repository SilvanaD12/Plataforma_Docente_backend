"""
HU-011: Adaptador de recuperación híbrida (BM25 léxico + pgvector HNSW semántico) con fusión RRF (k=60).
Filtra por unidad temática y por docente (aislamiento estricto) antes de buscar y degrada limpiamente a BM25 si no hay soporte vectorial.
"""

from __future__ import annotations

import concurrent.futures
import logging
from typing import Any

from platform5e.application.ports.outbound.chunk_repository_port import ChunkRepositoryPort
from platform5e.application.ports.outbound.embedding_port import (
    ChunkEmbeddingRepositoryPort,
    EmbeddingGeneratorPort,
)
from platform5e.domain.materials.text_analysis import retrieve_relevant_chunks

logger = logging.getLogger("platform5e.retrieval")

# Timeout estricto de 10.0 segundos para no bloquear la consulta si el modelo responde lento
EMBEDDING_QUERY_TIMEOUT_SECONDS: float = 10.0


class HybridEvidenceRetriever:
    """Recuperador híbrido que combina coincidencia léxica (BM25) y similitud semántica (HNSW)."""

    description = "búsqueda híbrida (BM25 + pgvector HNSW)"

    def __init__(
        self,
        chunk_repository: ChunkRepositoryPort | ChunkEmbeddingRepositoryPort,
        embedding_generator: EmbeddingGeneratorPort | None = None,
        rrf_k: int = 60,
    ) -> None:
        self._chunk_repository = chunk_repository
        self._embedding_generator = embedding_generator
        self._rrf_k = rrf_k

    def retrieve(
        self,
        query: str,
        chunks: list[dict[str, Any]] | None = None,
        top_k: int = 5,
        unit_id: str | None = None,
        teacher_id: str = "",
    ) -> list[dict[str, Any]]:
        """Recupera fragmentos aplicando RRF sobre los rankings de BM25 y búsqueda vectorial con aislamiento por docente."""
        # 1. Si no se pasaron fragmentos en memoria, teacher_id es estrictamente obligatorio para consultar la base de datos
        if chunks is None:
            if not teacher_id or not teacher_id.strip():
                raise ValueError("teacher_id is required for evidence retrieval")
            
            target_chunks: list[dict[str, Any]] = []
            if unit_id and hasattr(self._chunk_repository, "get_chunks_by_unit"):
                target_chunks = self._chunk_repository.get_chunks_by_unit(teacher_id, unit_id)
            elif hasattr(self._chunk_repository, "get_chunks_by_teacher"):
                target_chunks = self._chunk_repository.get_chunks_by_teacher(teacher_id)
        else:
            target_chunks = list(chunks)

        # 2. Filtrado estricto por docente:
        # Si se especificó un teacher_id, descarta fragmentos ajenos y fragmentos huérfanos/sin dueño
        if teacher_id and teacher_id.strip():
            target_chunks = [
                item for item in target_chunks
                if (item.get("teacher_id") or item.get("teacherId")) == teacher_id
            ]

        # Filtro por unidad temática
        if unit_id:
            target_chunks = [
                item for item in target_chunks
                if (item.get("unit_id") or item.get("unitId")) == unit_id
            ]

        # 3. Ranking Léxico (BM25)
        lexical_results = retrieve_relevant_chunks(query, target_chunks, top_k=max(top_k * 2, 20))

        # 4. Ranking Semántico (pgvector HNSW) con aislamiento de teacher_id
        semantic_results: list[dict[str, Any]] = []
        if (
            teacher_id
            and teacher_id.strip()
            and self._embedding_generator is not None
            and hasattr(self._chunk_repository, "vector_store_available")
            and self._chunk_repository.vector_store_available()
            and hasattr(self._chunk_repository, "search_similar_chunks")
        ):
            try:
                query_vector = self._embed_query_with_timeout(query)
                if query_vector:
                    search_kwargs: dict[str, Any] = {
                        "vector": query_vector,
                        "limit": max(top_k * 2, 20),
                        "unit_id": unit_id,
                        "teacher_id": teacher_id,
                    }
                    try:
                        semantic_results = self._chunk_repository.search_similar_chunks(**search_kwargs)
                    except Exception as error:
                        logger.warning(
                            "Fallo o incompatibilidad en búsqueda vectorial (%s). Degradando a búsqueda léxica.",
                            error,
                        )
                        semantic_results = []
            except Exception as exc:
                logger.warning(
                    "Error o timeout al generar embedding para búsqueda semántica (%s). Degradando a BM25.",
                    exc,
                )
                semantic_results = []

        # Filtrado estricto post-consulta semántica
        if semantic_results and teacher_id and teacher_id.strip():
            semantic_results = [
                item for item in semantic_results
                if (item.get("teacher_id") or item.get("teacherId")) == teacher_id
            ]

        # Si la vectorial falló o no está disponible, degradación directa a BM25
        if not semantic_results:
            results: list[dict[str, Any]] = []
            for item_chunk in lexical_results[:top_k]:
                item = dict(item_chunk)
                raw_relevance = float(item.get("relevance", item.get("relevancia", 1.0)))
                item["relevance"] = round(min(1.0, max(0.0, raw_relevance)), 4)
                item["retrieval_mode"] = "bm25_fallback"
                item["retrievalMode"] = "bm25_fallback"
                results.append(item)
            return results

        # 5. Fusión mediante Reciprocal Rank Fusion (RRF k=60)
        scores: dict[str, float] = {}
        chunk_map: dict[str, dict[str, Any]] = {}

        for rank, chunk in enumerate(lexical_results):
            chunk_id = str(chunk["id"])
            chunk_map[chunk_id] = chunk
            scores[chunk_id] = scores.get(chunk_id, 0.0) + (1.0 / (self._rrf_k + rank + 1))

        for rank, chunk in enumerate(semantic_results):
            chunk_id = str(chunk["id"])
            if chunk_id not in chunk_map:
                chunk_map[chunk_id] = {
                    "id": chunk["id"],
                    "documentId": chunk.get("documentId") or chunk.get("documento") or chunk.get("documento_id"),
                    "location": chunk.get("location") or chunk.get("ubicacion"),
                    "text": chunk.get("text") or chunk.get("texto"),
                    "unitId": chunk.get("unitId") or chunk.get("unit_id") or unit_id,
                }
            scores[chunk_id] = scores.get(chunk_id, 0.0) + (1.0 / (self._rrf_k + rank + 1))

        # 6. Ordenar por score RRF acumulado descendente y normalizar
        max_possible_rrf = 2.0 / (self._rrf_k + 1.0)
        sorted_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)

        results = []
        for chunk_id in sorted_ids[:top_k]:
            item = dict(chunk_map[chunk_id])
            normalized_score = scores[chunk_id] / max_possible_rrf
            item["relevance"] = round(min(1.0, max(0.0, normalized_score)), 4)
            item["retrieval_mode"] = "hybrid"
            item["retrievalMode"] = "hybrid"
            results.append(item)

        return results

    def _embed_query_with_timeout(self, query: str):
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(self._embedding_generator.embed_query, query)
        try:
            return future.result(timeout=EMBEDDING_QUERY_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError as err:
            raise TimeoutError(
                f"Timeout al generar embedding de consulta ({EMBEDDING_QUERY_TIMEOUT_SECONDS} s superados)"
            ) from err
        finally:
            executor.shutdown(wait=False, cancel_futures=True)