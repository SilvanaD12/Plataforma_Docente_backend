"""
Puerto de evidencia (MAT-01 · Material y Evidencia): Generación recupera una vez los fragmentos del material listo del
docente y la unidad, y los comparte entre los pasos del pedido.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode

# T031: modo que informa la búsqueda de Material: `hybrid` (BM25 + vectores) o `bm25_fallback` (solo BM25, porque no hay
# embeddings o la búsqueda vectorial falló). Conserva None porque no siempre puede determinarse: si la búsqueda no
# devuelve ningún fragmento del docente, no hay de dónde tomar el modo, y los pedidos guardados antes de T031 no lo
# tienen. El contrato HTTP ya lo admite como `retrievalMode: null`.
RetrievalMode = Literal["hybrid", "bm25_fallback"] | None

NO_PROCESSED_MATERIAL_MESSAGE: str = (
    "Esta unidad todavía no tiene material procesado. Sube un documento o busca el tema "
    "en la pestaña Material y vuelve a intentar."
)
EVIDENCE_UNAVAILABLE_MESSAGE: str = (
    "No se pudo consultar el material de la unidad en este momento. Vuelve a intentarlo en unos minutos."
)


class NoProcessedMaterial(GenerationError):
    """La unidad no tiene material procesado del docente (GEN-C6)."""

    def __init__(self, message: str = NO_PROCESSED_MATERIAL_MESSAGE) -> None:
        super().__init__(GenerationErrorCode.NO_PROCESSED_MATERIAL, message)


class EvidenceUnavailable(GenerationError):
    """La búsqueda de evidencia falló por un problema técnico."""

    def __init__(self, message: str = EVIDENCE_UNAVAILABLE_MESSAGE) -> None:
        super().__init__(GenerationErrorCode.EVIDENCE_UNAVAILABLE, message)


@dataclass(frozen=True)
class EvidenceQuery:
    teacher_id: str
    unit_id: str
    query: str
    limit: int  # topK, de 1 a 50


@dataclass(frozen=True)
class EvidenceFragment:
    """Un fragmento recuperado, con su procedencia para la copia histórica."""

    chunk_id: str
    document_id: str
    document_name: str
    location: str
    text: str
    relevance: float  # de 0 a 1
    source_url: str | None
    license: str | None

    def to_dict(self, retrieved_at: str) -> dict[str, Any]:
        """Forma guardada en `GenerationRequest.evidence` (camelCase), con el instante de la recuperación."""
        return {
            "chunkId": self.chunk_id,
            "documentId": self.document_id,
            "documentName": self.document_name,
            "location": self.location,
            "text": self.text,
            "relevance": self.relevance,
            "sourceUrl": self.source_url,
            "license": self.license,
            "retrievedAt": retrieved_at,
        }


@dataclass(frozen=True)
class EvidenceRetrieval:
    fragments: tuple[EvidenceFragment, ...]
    retrieval_mode: RetrievalMode = None


class EvidenceProviderPort(Protocol):
    """Contrato que Material ofrece a Generación para recuperar evidencia."""

    def has_processed_material(self, teacher_id: str, unit_id: str) -> bool:
        """True si la unidad del docente tiene al menos un fragmento de material procesado."""
        ...

    def retrieve(self, query: EvidenceQuery) -> EvidenceRetrieval:
        """Solo busca en material listo del docente y la unidad. Lanza NoProcessedMaterial o EvidenceUnavailable."""
        ...
