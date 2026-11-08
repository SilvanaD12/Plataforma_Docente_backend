"""
Ingesta y procesamiento del material del docente (EN-007, EN-012 y EN-013):
extrae el texto, genera fragmentos con solapamiento, los vectoriza y actualiza el estado del documento.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from platform5e.application.ports.outbound.chunk_repository_port import ChunkRepositoryPort
from platform5e.application.ports.outbound.open_educational_resource_port import OpenEducationalResourcePort
from platform5e.application.ports.outbound.text_extractor_port import TextExtractorPort
from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort
from platform5e.application.services.materials.chunk_embedding_service import ChunkEmbeddingService
from platform5e.domain.materials.chunking import MaterialError, chunk_pages

OPEN_EDUCATIONAL_RESOURCE_TYPE: str = "Artículo de fuente abierta"
NO_TEXT_FOUND_MESSAGE: str = (
    "No se encontró texto en el archivo. Si es un PDF escaneado (solo imágenes), "
    "súbelo como PDF con texto seleccionable o copia el contenido en un TXT."
)

logger = logging.getLogger("platform5e.materials")


def _get_utc_now() -> str:
    """Retorna la fecha y hora actual en formato ISO 8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


def build_article_filename(title: str, source_label: str = "") -> str:
    """Genera un nombre de archivo normalizado para artículos de fuentes abiertas."""
    cleaned_title = re.sub(r"[\\/\x00-\x1f]", " ", title).strip()[:140] or "Artículo"
    return f"{cleaned_title}.txt"


class MaterialService:
    """Servicio de aplicación para coordinar la ingesta y extracción de fragmentos de material."""

    def __init__(
        self,
        teacher_repository: TeacherRepositoryPort,
        chunk_repository: ChunkRepositoryPort,
        text_extractor: TextExtractorPort,
        open_resource_port: OpenEducationalResourcePort | None = None,
        embedding_service: ChunkEmbeddingService | None = None,
    ) -> None:
        self._teacher_repository = teacher_repository
        self._chunk_repository = chunk_repository
        self._text_extractor = text_extractor
        self._open_resource_port = open_resource_port
        self._embedding_service = embedding_service

    def _get_document(self, teacher_id: str, document_id: str) -> tuple[dict[str, Any], bytes]:
        """Recupera los metadatos y bytes del documento validando existencia."""
        found = self._teacher_repository.get_document(teacher_id, document_id)
        if found is None:
            raise MaterialError("DOCUMENT_NOT_FOUND", "El documento no existe.", 404)
        return found

    def _get_unit(self, teacher_id: str, unit_id: str) -> dict[str, Any]:
        """Obtiene la unidad asegurando pertenencia al catálogo de cursos del docente."""
        unit = next(
            (
                u
                for course in self._teacher_repository.get_courses(teacher_id)
                for u in course["units"]
                if u["id"] == unit_id
            ),
            None,
        )
        if unit is None:
            raise MaterialError("UNIT_NOT_FOUND", "La unidad no pertenece a tus cursos.", 404)
        return unit

    def process_material(self, teacher_id: str, document_id: str) -> dict[str, Any]:
        """Extrae el texto del documento, lo divide en fragmentos y persiste el resultado."""
        metadata, binary_content = self._get_document(teacher_id, document_id)
        try:
            pages = self._text_extractor.extract(metadata["kind"], binary_content)
        except MaterialError as exc:
            return self._mark_processing_error(teacher_id, metadata, exc.message)

        chunks = chunk_pages(pages)
        if not chunks:
            return self._mark_processing_error(
                teacher_id, metadata, NO_TEXT_FOUND_MESSAGE, len(pages) or None
            )

        persisted_chunks = [{**chunk, "id": f"frag-{uuid4().hex[:16]}"} for chunk in chunks]
        self._chunk_repository.replace_chunks(
            teacher_id, document_id, metadata["unitId"], persisted_chunks
        )

        updated_metadata: dict[str, Any] = {
            **metadata,
            "status": "procesado",
            "currentStep": None,
            "processedAt": _get_utc_now(),
            "fragmentCount": len(chunks),
            "pageCount": len(pages),
            "errorMessage": None,
            **self._embed_document_chunks(document_id),
        }
        self._chunk_repository.update_document(teacher_id, updated_metadata)
        return updated_metadata

    def _embed_document_chunks(self, document_id: str) -> dict[str, Any]:
        """EN-013: vectoriza los fragmentos nuevos. Si falla, el documento queda procesado igual (BM25 sigue)."""
        if self._embedding_service is None:
            return {}
        try:
            run = self._embedding_service.embed_pending(document_id=document_id)
        except Exception as exc:  # el material no se pierde por un fallo del modelo de embeddings
            logger.warning("No se pudieron generar los embeddings de %s: %s", document_id, exc)
            return {
                "embeddedFragmentCount": 0,
                "embeddingModel": self._embedding_service.model,
                "embeddingError": str(exc)[:200],
            }
        if not run.available:
            return {}
        return {"embeddedFragmentCount": run.total, "embeddingModel": run.model, "embeddingError": None}

    def _mark_processing_error(
        self,
        teacher_id: str,
        metadata: dict[str, Any],
        error_message: str,
        page_count: int | None = None,
    ) -> dict[str, Any]:
        """Limpia los fragmentos previos y marca el documento en estado de error."""
        self._chunk_repository.replace_chunks(teacher_id, metadata["id"], metadata["unitId"], [])
        error_metadata: dict[str, Any] = {
            **metadata,
            "status": "error",
            "currentStep": None,
            "processedAt": None,
            "fragmentCount": 0,
            "pageCount": page_count,
            "errorMessage": error_message,
        }
        self._chunk_repository.update_document(teacher_id, error_metadata)
        return error_metadata

    def get_document_chunks(self, teacher_id: str, document_id: str) -> list[dict[str, Any]]:
        """Recupera los fragmentos calculados asociados a un documento."""
        self._get_document(teacher_id, document_id)
        raw_chunks = self._chunk_repository.get_chunks_by_document(teacher_id, document_id)
        return [
            {
                "id": chunk["id"],
                "order": chunk.get("order", chunk.get("orden")),
                "location": chunk.get("location", chunk.get("ubicacion")),
                "text": chunk.get("text", chunk.get("texto")),
            }
            for chunk in raw_chunks
        ]

    def create_from_topic(
        self, teacher_id: str, unit_id: str, topic: str, max_articles: int = 3
    ) -> list[dict[str, Any]]:
        """Busca artículos en fuentes abiertas sobre el tema indicado y los procesa como documentos."""
        cleaned_topic = " ".join((topic or "").split())
        if not 3 <= len(cleaned_topic) <= 120:
            raise MaterialError("INVALID_TOPIC", "Escribe un tema de 3 a 120 caracteres.")

        unit = self._get_unit(teacher_id, unit_id)
        if self._open_resource_port is None:
            raise MaterialError(
                "TOPIC_SEARCH_UNAVAILABLE",
                "La búsqueda por tema no está activada en el servidor.",
                503,
            )

        try:
            articles = self._open_resource_port.search(cleaned_topic, max(1, min(max_articles, 5)))
        except MaterialError:
            raise
        except Exception as exc:
            raise MaterialError(
                "SOURCE_UNAVAILABLE",
                "No se pudo consultar la fuente abierta. Revisa la conexión del servidor.",
                503,
            ) from exc

        if not articles:
            raise MaterialError(
                "NO_RESULTS",
                f"No se encontraron artículos sobre «{cleaned_topic}». Prueba con otras palabras.",
                404,
            )

        existing_docs = {
            d["fileName"].casefold(): d
            for d in self._teacher_repository.get_documents(teacher_id)
            if d["unitId"] == unit["id"]
        }
        results: list[dict[str, Any]] = []

        for article in articles:
            filename = build_article_filename(
                article["titulo"], article.get("fuente", "fuente abierta")
            )
            if filename.casefold() in existing_docs:
                results.append(existing_docs[filename.casefold()])
                continue

            content_bytes = f"{article['titulo']}\n\n{article['texto']}".encode("utf-8")
            doc_data: dict[str, Any] = {
                "unitId": unit["id"],
                "outcomeIds": [],
                "documentType": OPEN_EDUCATIONAL_RESOURCE_TYPE,
                "suggestedStage": None,
                "usePermission": True,
                "id": f"doc-api-{uuid4()}",
                "fileName": filename,
                "kind": "txt",
                "sizeBytes": len(content_bytes),
                "status": "registrado",
                "currentStep": None,
                "registeredAt": _get_utc_now(),
                "processedAt": None,
                "fragmentCount": 0,
                "pageCount": None,
                "errorMessage": None,
                "isDemo": False,
                "source": "backend",
                "origin": {
                    "source": article.get("fuente", ""),
                    "url": article["url"],
                    "license": article["licencia"],
                    "topic": cleaned_topic,
                },
            }
            self._teacher_repository.save_document(teacher_id, doc_data, content_bytes)
            results.append(self.process_material(teacher_id, doc_data["id"]))

        return results