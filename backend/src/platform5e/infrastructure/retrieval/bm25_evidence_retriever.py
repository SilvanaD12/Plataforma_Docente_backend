"""
Adaptador del puerto EvidenceRetrieverPort con BM25, la búsqueda por palabras del dominio (text_analysis.py).
"""

from __future__ import annotations

from typing import Any

from platform5e.domain.materials.text_analysis import retrieve_relevant_chunks


class Bm25EvidenceRetriever:
    """Busca la evidencia por coincidencia de palabras: no necesita red, modelo ni base vectorial."""

    description = "búsqueda por palabras (BM25)"

    def retrieve(
        self,
        query: str,
        chunks: list[dict[str, Any]] | None = None,
        top_k: int = 5,
        unit_id: str | None = None,
    ) -> list[dict[str, Any]]:
        target_chunks = chunks or []
        if unit_id:
            target_chunks = [c for c in target_chunks if (c.get("unit_id") or c.get("unitId")) == unit_id]
        return retrieve_relevant_chunks(query, target_chunks, top_k)