"""
Adaptador inicial de `EvidenceProviderPort` sobre los puertos de Material (MAT-01).

Siempre parte de los fragmentos del docente (`get_chunks_by_unit(teacher_id, unit_id)`) y se los entrega al buscador,
para que este nunca cargue fragmentos sin filtrar por docente. Además descarta cualquier resultado que no esté entre
esos fragmentos: la búsqueda vectorial de hoy filtra solo por unidad (riesgo de research R5, Constitución IV).
`retrieval_mode` queda en None hasta que Material informe si degradó a BM25 (T031).
"""

from __future__ import annotations

import logging
from typing import Any

from platform5e.application.ports.outbound.chunk_repository_port import ChunkRepositoryPort
from platform5e.application.ports.outbound.evidence_provider_port import (
    EvidenceFragment,
    EvidenceProviderPort,
    EvidenceQuery,
    EvidenceRetrieval,
    EvidenceUnavailable,
    NoProcessedMaterial,
)
from platform5e.application.ports.outbound.evidence_retriever_port import EvidenceRetrieverPort
from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort

logger = logging.getLogger("platform5e.generation.evidence")


def _relevance(chunk: dict[str, Any]) -> float:
    try:
        value = float(chunk.get("relevance", chunk.get("relevancia", 0.0)))
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, value))


class MaterialEvidenceAdapter(EvidenceProviderPort):
    """Recupera la evidencia del pedido con el buscador de Material y le agrega la procedencia de cada documento."""

    def __init__(
        self,
        chunk_repository: ChunkRepositoryPort,
        retriever: EvidenceRetrieverPort,
        teacher_repository: TeacherRepositoryPort,
    ) -> None:
        self._chunk_repository = chunk_repository
        self._retriever = retriever
        self._teacher_repository = teacher_repository

    def has_processed_material(self, teacher_id: str, unit_id: str) -> bool:
        if not teacher_id or not unit_id:
            return False
        return bool(self._chunk_repository.get_chunks_by_unit(teacher_id, unit_id))

    def retrieve(self, query: EvidenceQuery) -> EvidenceRetrieval:
        if not query.teacher_id or not query.unit_id:
            raise NoProcessedMaterial()
        teacher_chunks = self._chunk_repository.get_chunks_by_unit(query.teacher_id, query.unit_id)
        if not teacher_chunks:
            raise NoProcessedMaterial()
        own_chunks = {str(chunk["id"]): chunk for chunk in teacher_chunks}

        try:
            selected = self._retriever.retrieve(
                query=query.query, chunks=teacher_chunks, top_k=query.limit, unit_id=query.unit_id
            )
            documents = {
                document["id"]: document
                for document in self._teacher_repository.get_documents(query.teacher_id)
                if document.get("unitId") == query.unit_id
            }
        except Exception as error:
            logger.warning("No se pudo recuperar la evidencia de la unidad %s: %s", query.unit_id, error)
            raise EvidenceUnavailable() from error

        fragments: list[EvidenceFragment] = []
        for result in selected:
            chunk_id = str(result.get("id"))
            own_chunk = own_chunks.get(chunk_id)
            if own_chunk is None:
                continue  # resultado fuera de los fragmentos del docente: no se usa
            document_id = str(own_chunk.get("documentId") or own_chunk.get("document_id") or "")
            document = documents.get(document_id) or {}
            origin = document.get("origin") if isinstance(document.get("origin"), dict) else {}
            fragments.append(
                EvidenceFragment(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    document_name=str(document.get("fileName") or ""),
                    location=str(own_chunk.get("location") or ""),
                    text=str(own_chunk.get("text") or ""),
                    relevance=_relevance(result),
                    source_url=origin.get("url") or None,
                    license=origin.get("license") or None,
                )
            )
        return EvidenceRetrieval(fragments=tuple(fragments), retrieval_mode=None)
