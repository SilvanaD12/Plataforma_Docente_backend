"""
Ingesta y procesamiento del material del docente (EN-007, EN-012, EN-013 y Plan v2-F/G/H):
extrae el texto, evalúa relevancia y duplicidad entre unidades, genera fragmentos y vectoriza.
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from platform5e.application.ports.outbound.chunk_repository_port import ChunkRepositoryPort
from platform5e.application.ports.outbound.evidence_retriever_port import EvidenceRetrieverPort
from platform5e.application.ports.outbound.open_educational_resource_port import OpenEducationalResourcePort
from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort
from platform5e.application.ports.outbound.text_extractor_port import TextExtractorPort
from platform5e.application.ports.outbound.unit_membership_port import UnitMembershipPort
from platform5e.application.ports.outbound.web_content_fetcher_port import WebContentFetcherPort
from platform5e.application.services.materials.chunk_embedding_service import ChunkEmbeddingService
from platform5e.application.services.materials.referent_service import ReferentService
from platform5e.application.services.provider_errors import public_reason, redact_secrets
from platform5e.domain.accounts.teacher_account import find_course_and_unit
from platform5e.domain.generation.generation_plan import PlanFragment
from platform5e.domain.materials.chunking import MaterialError, chunk_pages
from platform5e.domain.review.duplication import similarity

OPEN_EDUCATIONAL_RESOURCE_TYPE: str = "Artículo de fuente abierta"
WEB_URL_RESOURCE_TYPE: str = "Página web"
NO_TEXT_FOUND_MESSAGE: str = (
    "No se encontró texto en el archivo. Si es un PDF escaneado (solo imágenes), "
    "súbelo como PDF con texto seleccionable o copia el contenido en un TXT."
)
RELEVANCE_WARNING_THRESHOLD: float = 0.06
RELEVANCE_WARNING_MESSAGE: str = (
    "Este material parece no tener relación con tu unidad. ¿Deseas conservarlo?"
)

logger = logging.getLogger("platform5e.materials")


def _get_utc_now() -> str:
    """Retorna la fecha y hora actual en formato ISO 8601 UTC."""
    return datetime.now(timezone.utc).isoformat()


def build_article_filename(title: str, source_label: str = "") -> str:
    """Genera un nombre de archivo normalizado para artículos de fuentes abiertas y páginas web."""
    cleaned_title = re.sub(r"[\\/\x00-\x1f]", " ", title).strip()[:140] or "Artículo"
    return f"{cleaned_title}.txt"


def compute_normalized_sha256(text: str) -> str:
    """Calcula la huella SHA-256 sobre el texto normalizado (sin diacríticos, minúsculas y espacios colapsados)."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()
    collapsed = re.sub(r"\s+", " ", without_accents).strip()
    return hashlib.sha256(collapsed.encode("utf-8")).hexdigest()


def evaluate_unit_relevance(
    extracted_text: str,
    course_name: str,
    unit_title: str,
    outcomes: list[dict[str, Any]],
) -> str | None:
    """Evalúa similitud léxica del material contra el curso, unidad y resultados de aprendizaje (sin IA)."""
    outcome_texts = " ".join(
        str(o.get("description") or o.get("text") or "") for o in outcomes if isinstance(o, dict)
    )
    reference_context = f"{course_name} {unit_title} {outcome_texts}".strip()
    if not reference_context or not extracted_text.strip():
        return None

    sample_text = extracted_text[:3500]
    score = similarity(reference_context, sample_text)
    if score < RELEVANCE_WARNING_THRESHOLD:
        return RELEVANCE_WARNING_MESSAGE
    return None


def _is_web_origin_document(metadata: dict[str, Any]) -> bool:
    doc_type = str(metadata.get("documentType") or "")
    origin = metadata.get("origin")
    if doc_type in {OPEN_EDUCATIONAL_RESOURCE_TYPE, WEB_URL_RESOURCE_TYPE}:
        return True
    return isinstance(origin, dict) and bool(origin.get("url"))


def _extract_full_text_from_pages(pages: list[Any]) -> str:
    """Extrae el texto concatenado soportando tuplas `(location, text)` o diccionarios."""
    parts: list[str] = []
    for page in pages:
        if isinstance(page, tuple) and len(page) >= 2:
            parts.append(str(page[1] or ""))
        elif isinstance(page, dict):
            parts.append(str(page.get("text") or page.get("texto") or ""))
        else:
            parts.append(str(page or ""))
    return "\n\n".join(parts)


class MaterialService:
    """Servicio de aplicación para coordinar la ingesta y extracción de fragmentos de material."""

    _unit_membership_port: UnitMembershipPort | None
    _evidence_retriever: EvidenceRetrieverPort | None

    def __init__(
        self,
        teacher_repository: TeacherRepositoryPort,
        chunk_repository: ChunkRepositoryPort,
        text_extractor: TextExtractorPort,
        open_resource_port: OpenEducationalResourcePort | None = None,
        embedding_service: ChunkEmbeddingService | None = None,
        unit_membership_port: UnitMembershipPort | None = None,
        evidence_retriever: EvidenceRetrieverPort | None = None,
        web_fetcher_port: WebContentFetcherPort | None = None,
        referent_service: ReferentService | None = None,
    ) -> None:
        self._teacher_repository = teacher_repository
        self._chunk_repository = chunk_repository
        self._text_extractor = text_extractor
        self._open_resource_port = open_resource_port
        self._embedding_service = embedding_service
        self._unit_membership_port = unit_membership_port
        self._evidence_retriever = evidence_retriever
        self._web_fetcher_port = web_fetcher_port
        self._referent_service = referent_service

    def _get_document(self, teacher_id: str, document_id: str) -> tuple[dict[str, Any], bytes]:
        """Recupera los metadatos y bytes del documento validando existencia."""
        found = self._teacher_repository.get_document(teacher_id, document_id)
        if found is None:
            raise MaterialError("DOCUMENT_NOT_FOUND", "El documento no existe.", 404)
        return found

    def _get_unit(self, teacher_id: str, unit_id: str) -> dict[str, Any]:
        """Obtiene la unidad asegurando pertenencia al catálogo de cursos del docente."""
        match = find_course_and_unit(self._teacher_repository.get_courses(teacher_id), unit_id)
        if match is None:
            raise MaterialError("UNIT_NOT_FOUND", "La unidad no pertenece a tus cursos.", 404)
        return match[1]

    def search_evidence(
        self, teacher_id: str, query: str, top_k: int = 5, unit_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Búsqueda híbrida de evidencia across documents con aislamiento por docente y unidad."""
        if unit_id:
            self.validate_unit_membership_secure(teacher_id, unit_id, [])

        if not self._evidence_retriever:
            return []

        return self._evidence_retriever.retrieve(
            query=query,
            top_k=top_k,
            unit_id=unit_id,
            teacher_id=teacher_id,
        )

    def validate_unit_membership_secure(self, teacher_id: str, unit_id: str, outcome_ids: list[str]) -> None:
        """
        Valida que el docente tenga acceso a la unidad y que los outcomes pertenezcan a ella.
        Implementa MAT-C2 / T007: Unidad ajena o inexistente devuelven el mismo 404 Not Found.
        """
        if self._unit_membership_port is not None:
            context = self._unit_membership_port.get_unit_context(teacher_id, unit_id)
            if context is None:
                raise MaterialError("UNIT_NOT_FOUND", "La unidad no existe o no pertenece a tus cursos.", 404)

            if outcome_ids:
                valid_ids = {outcome.id for outcome in context.outcomes if outcome.id}
                invalid_ids = set(outcome_ids) - valid_ids
                if invalid_ids:
                    raise MaterialError(
                        "INVALID_OUTCOMES",
                        "Los resultados de aprendizaje proporcionados no pertenecen a la unidad.",
                        400,
                    )
        else:
            unit = self._get_unit(teacher_id, unit_id)
            if outcome_ids:
                valid_ids = {
                    outcome.get("id")
                    for outcome in unit.get("outcomes", [])
                    if isinstance(outcome, dict) and outcome.get("id")
                }
                invalid_ids = set(outcome_ids) - valid_ids
                if invalid_ids:
                    raise MaterialError(
                        "INVALID_OUTCOMES",
                        "Los resultados de aprendizaje proporcionados no pertenecen a la unidad.",
                        400,
                    )

    def _evaluate_material_warnings(
        self,
        teacher_id: str,
        document_id: str,
        unit_id: str,
        full_text: str,
    ) -> dict[str, Any]:
        """Calcula huella SHA-256, detecta duplicidad en el curso y evalúa relevancia frente a la unidad."""
        content_hash = compute_normalized_sha256(full_text)
        duplicate_warning: str | None = None
        relevance_warning: str | None = None

        courses = self._teacher_repository.get_courses(teacher_id)
        match = find_course_and_unit(courses, unit_id)
        if match is not None:
            course, unit = match
            unit_titles_by_id: dict[str, str] = {
                str(u["id"]): str(u.get("title") or u["id"])
                for u in course.get("units", [])
                if isinstance(u, dict) and u.get("id")
            }

            for existing_doc in self._teacher_repository.get_documents(teacher_id):
                if existing_doc.get("id") == document_id:
                    continue
                existing_unit_id = str(existing_doc.get("unitId") or "")
                if existing_unit_id not in unit_titles_by_id:
                    continue
                if existing_doc.get("contentHash") == content_hash:
                    target_unit_title = unit_titles_by_id[existing_unit_id]
                    duplicate_warning = f"Este material ya está en la unidad «{target_unit_title}»."
                    break

            relevance_warning = evaluate_unit_relevance(
                extracted_text=full_text,
                course_name=str(course.get("name") or ""),
                unit_title=str(unit.get("title") or ""),
                outcomes=unit.get("outcomes") if isinstance(unit.get("outcomes"), list) else [],
            )

        return {
            "contentHash": content_hash,
            "duplicateWarning": duplicate_warning,
            "relevanceWarning": relevance_warning,
        }

    def process_material(self, teacher_id: str, document_id: str) -> dict[str, Any]:
        """Extrae el texto del documento, evalúa advertencias no bloqueantes, fragmenta y persiste."""
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

        full_text = _extract_full_text_from_pages(pages)
        warnings_and_hash = self._evaluate_material_warnings(
            teacher_id=teacher_id,
            document_id=document_id,
            unit_id=metadata["unitId"],
            full_text=full_text,
        )

        persisted_chunks = [{**chunk, "id": f"frag-{uuid4().hex[:16]}"} for chunk in chunks]
        self._chunk_repository.replace_chunks(
            teacher_id, document_id, metadata["unitId"], persisted_chunks
        )

        page_count: int | None = None if _is_web_origin_document(metadata) else len(pages)

        updated_metadata: dict[str, Any] = {
            **metadata,
            **warnings_and_hash,
            "status": "procesado",
            "currentStep": None,
            "processedAt": _get_utc_now(),
            "fragmentCount": len(chunks),
            "pageCount": page_count,
            "errorMessage": None,
            **self._embed_document_chunks(document_id),
        }
        self._chunk_repository.update_document(teacher_id, updated_metadata)

        if self._referent_service is not None:
            origin = metadata.get("origin") if isinstance(metadata.get("origin"), dict) else {}
            doc_name = str(metadata.get("fileName") or metadata.get("file_name") or document_id)
            plan_fragments = tuple(
                PlanFragment(
                    id=str(chunk["id"]),
                    document_id=document_id,
                    document_name=doc_name,
                    location=str(chunk.get("location") or chunk.get("ubicacion") or ""),
                    text=str(chunk.get("text") or chunk.get("texto") or ""),
                    relevance=1.0,
                    source_url=origin.get("url") if isinstance(origin, dict) else None,
                    license=origin.get("license") if isinstance(origin, dict) else None,
                )
                for chunk in persisted_chunks
            )
            self._referent_service.extract_and_store_for_unit(
                teacher_id=teacher_id,
                unit_id=metadata["unitId"],
                topic=doc_name,
                fragments=plan_fragments,
                document_id=document_id,
            )

        return updated_metadata

    def _embed_document_chunks(self, document_id: str) -> dict[str, Any]:
        """EN-013: vectoriza los fragmentos nuevos. Si falla, el documento queda procesado igual (BM25 sigue)."""
        if self._embedding_service is None:
            return {}
        try:
            run = self._embedding_service.embed_pending(document_id=document_id)
        except Exception as exc:
            logger.warning(
                "No se pudieron generar los embeddings de %s: %s", document_id, redact_secrets(str(exc))[:500]
            )
            return {
                "embeddedFragmentCount": 0,
                "embeddingModel": self._embedding_service.model,
                "embeddingError": public_reason(exc)[:200],
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

        self.validate_unit_membership_secure(teacher_id, unit_id, [])

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
            if d.get("unitId") == unit_id
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
                "unitId": unit_id,
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

    def create_from_url(
        self,
        teacher_id: str,
        unit_id: str,
        url: str,
        outcome_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Descarga una URL pública, extrae su texto limpio, la guarda e indexa como material (MAT-P1)."""
        normalized_outcomes = list(dict.fromkeys(outcome_ids or []))

        self.validate_unit_membership_secure(teacher_id, unit_id, normalized_outcomes)

        if self._web_fetcher_port is None:
            raise MaterialError(
                "URL_INGEST_UNAVAILABLE",
                "La ingesta de materiales desde URL no está activada en el servidor.",
                503,
            )

        fetched = self._web_fetcher_port.fetch(url)
        final_url = fetched["url"]
        title = fetched["title"]
        text = fetched["text"]

        # Evita duplicar la misma URL dentro de la misma unidad
        for existing in self._teacher_repository.get_documents(teacher_id):
            origin = existing.get("origin")
            if (
                existing.get("unitId") == unit_id
                and isinstance(origin, dict)
                and origin.get("url") == final_url
            ):
                return existing

        filename = build_article_filename(title, "Web")
        content_bytes = f"{title}\n\n{text}".encode("utf-8")
        doc_data: dict[str, Any] = {
            "unitId": unit_id,
            "outcomeIds": normalized_outcomes,
            "documentType": WEB_URL_RESOURCE_TYPE,
            "suggestedStage": None,
            "usePermission": True,
            "id": f"doc-url-{uuid4()}",
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
                "source": "Web",
                "url": final_url,
                "license": None,
                "topic": None,
            },
        }
        self._teacher_repository.save_document(teacher_id, doc_data, content_bytes)
        return self.process_material(teacher_id, doc_data["id"])