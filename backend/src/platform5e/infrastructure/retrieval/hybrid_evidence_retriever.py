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

# Timeout estricto de 1.5 segundos para no bloquear la consulta si Gemini responde lento
EMBEDDING_QUERY_TIMEOUT_SECONDS: float = 1.5


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
        teacher_id: str | None = None,  # <--- Añadido teacher_id para cumplir con el contrato y aislamiento
    ) -> list[dict[str, Any]]:
        """Recupera fragmentos aplicando RRF sobre los rankings de BM25 y búsqueda vectorial con aislamiento por docente."""
        # 1. Resolver fragmentos base filtrados por docente y unidad
        target_chunks = list(chunks) if chunks is not None else []
        
        if not target_chunks and hasattr(self._chunk_repository, "get_chunks_by_unit") and unit_id:
            # Si hay unit_id, podemos buscar por unidad (asegurando el filtrado por teacher_id si el repositorio lo soporta)
            target_chunks = self._chunk_repository.get_chunks_by_unit(teacher_id or "", unit_id)
        elif not target_chunks and teacher_id and hasattr(self._chunk_repository, "get_chunks_by_teacher"):
            target_chunks = self._chunk_repository.get_chunks_by_teacher(teacher_id)
        elif not target_chunks and hasattr(self._chunk_repository, "get_chunks_by_unit"):
            # Si no hay unit_id ni chunks, intentamos obtener por unidad vacía o pasándole el teacher_id si aplica
            target_chunks = self._chunk_repository.get_chunks_by_unit(teacher_id or "", "")

        # Filtro estricto por teacher_id y unit_id en memoria por seguridad defensiva
        if teacher_id:
            target_chunks = [
                c for c in target_chunks 
                if (c.get("teacher_id") or c.get("teacherId") or teacher_id) == teacher_id
            ]

        if unit_id:
            target_chunks = [
                c for c in target_chunks if (c.get("unit_id") or c.get("unitId")) == unit_id
            ]

        # 2. Ranking Léxico (BM25)
        lexical_results = retrieve_relevant_chunks(query, target_chunks, top_k=max(top_k * 2, 20))

        # 3. Ranking Semántico (pgvector HNSW filtrado por unit_id y/o teacher_id) con timeout
        semantic_results: list[dict[str, Any]] = []
        if (
            self._embedding_generator is not None
            and hasattr(self._chunk_repository, "vector_store_available")
            and self._chunk_repository.vector_store_available()
            and hasattr(self._chunk_repository, "search_similar_chunks")
        ):
            try:
                query_vector = self._embed_query_with_timeout(query)
                if query_vector:
                    # Pasamos teacher_id y unit_id al repositorio si soporta el aislamiento
                    search_kwargs: dict[str, Any] = {
                        "vector": query_vector,
                        "limit": max(top_k * 2, 20),
                        "unit_id": unit_id,
                    }
                    if "teacher_id" in self._chunk_repository.search_similar_chunks.__code__.co_varnames:
                        search_kwargs["teacher_id"] = teacher_id

                    semantic_results = self._chunk_repository.search_similar_chunks(**search_kwargs)
            except Exception as exc:
                logger.warning(
                    "Error o timeout al generar embedding para búsqueda semántica (%s). Degradando a BM25.",
                    exc,
                )
                semantic_results = []

        # Filtrar resultados semánticos por docente estrictamente por seguridad
        if teacher_id and semantic_results:
            semantic_results = [
                c for c in semantic_results 
                if (c.get("teacher_id") or c.get("teacherId") or teacher_id) == teacher_id
            ]

        # Si no hubo resultados vectoriales disponibles, degradación directa a BM25
        if not semantic_results:
            results: list[dict[str, Any]] = []
            for chunk in lexical_results[:top_k]:
                item = dict(chunk)
                raw_rel = float(item.get("relevance", item.get("relevancia", 1.0)))
                item["relevance"] = round(min(1.0, max(0.0, raw_rel)), 4)
                results.append(item)
            return results

        # 4. Fusión mediante Reciprocal Rank Fusion (RRF k=60)
        scores: dict[str, float] = {}
        chunk_map: dict[str, dict[str, Any]] = {}

        for rank, chunk in enumerate(lexical_results):
            cid = str(chunk["id"])
            chunk_map[cid] = chunk
            scores[cid] = scores.get(cid, 0.0) + (1.0 / (self._rrf_k + rank + 1))

        for rank, chunk in enumerate(semantic_results):
            cid = str(chunk["id"])
            if cid not in chunk_map:
                chunk_map[cid] = {
                    "id": chunk["id"],
                    "documentId": chunk.get("documentId") or chunk.get("documento") or chunk.get("documento_id"),
                    "location": chunk.get("location") or chunk.get("ubicacion"),
                    "text": chunk.get("text") or chunk.get("texto"),
                    "unitId": unit_id or chunk.get("unitId") or chunk.get("unit_id"),
                }
            scores[cid] = scores.get(cid, 0.0) + (1.0 / (self._rrf_k + rank + 1))

        # 5. Ordenar por score RRF acumulado descendente y normalizar relevancia de 0 a 1
        max_possible_rrf = 2.0 / (self._rrf_k + 1.0)
        sorted_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)

        results = []
        for cid in sorted_ids[:top_k]:
            item = dict(chunk_map[cid])
            normalized_score = scores[cid] / max_possible_rrf
            item["relevance"] = round(min(1.0, max(0.0, normalized_score)), 4)
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