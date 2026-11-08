"""
HU-010 y HU-052: revisión docente persistida en base de datos e historial de descargas.
Permite validar que un recurso cumpla las condiciones pedagógicas de aprobación
(clave correcta definida y mínimo dos distractores aceptados).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from platform5e.application.ports.outbound.resource_repository_port import ResourceReviewRepositoryPort
from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort
from platform5e.domain.accounts.teacher_account import AccountConfigurationError
from platform5e.application.services.media.media_attachment import EDITED_NOTES, fallback_media
from platform5e.domain.generation.resource_formats import needs_structure, normalize_structure, structure_problems

MIN_ACCEPTED_DISTRACTORS: int = 2
ALLOWED_REVIEW_STATUSES: set[str] = {"pendiente", "aprobado", "descartado"}
ALLOWED_OPTION_DECISIONS: set[str] = {"pendiente", "aceptado", "descartado"}
ALLOWED_DISCARD_REASONS: set[str] = {
    "sin_sentido",
    "tambien_correcto",
    "duplicado",
    "fuera_de_unidad",
    "otro",
    "regenerado",
}
ALLOWED_EXPORT_FORMATS: set[str] = {"moodle_xml", "scorm_zip", "documento"}
MAX_DOWNLOADS_HISTORY: int = 50


def validate_approval_blockers(resource_data: dict[str, Any]) -> list[str]:
    """Evalúa las reglas de negocio para determinar si un recurso puede ser aprobado."""
    reasons: list[str] = []
    if not str(resource_data.get("body", "")).strip():
        reasons.append("El contenido no puede estar vacío.")

    options = resource_data.get("options")
    if options:
        distractors = [opt for opt in options if not opt.get("isCorrect")]
        pending_count = sum(opt.get("decision") == "pendiente" for opt in distractors)
        if pending_count:
            reasons.append(
                "Decide el distractor pendiente para poder aprobar." if pending_count == 1
                else f"Decide los {pending_count} distractores pendientes para poder aprobar."
            )
        elif sum(opt.get("decision") == "aceptado" for opt in distractors) < MIN_ACCEPTED_DISTRACTORS:
            reasons.append(
                f"Acepta al menos {MIN_ACCEPTED_DISTRACTORS} distractores para poder aprobar."
            )

        if not any(opt.get("isCorrect") and str(opt.get("text", "")).strip() for opt in options):
            reasons.append("La pregunta necesita una respuesta correcta.")

    if resource_data.get("type"):
        reasons += structure_problems(resource_data["type"], resource_data.get("structure"))
    media = resource_data.get("media") or {}
    if media.get("status") == "ready" and media.get("outdated"):
        reasons.append("El archivo no coincide con el texto editado: genéralo de nuevo para poder aprobar.")
    return reasons


class ResourceReviewService:
    """Servicio de aplicación para la gestión del ciclo de vida de revisión y descargas."""

    def __init__(
        self,
        teacher_repository: TeacherRepositoryPort,
        review_repository: ResourceReviewRepositoryPort,
    ) -> None:
        self._teacher_repository = teacher_repository
        self._review_repository = review_repository

    def _verify_unit_access(self, teacher_id: str, unit_id: str) -> None:
        """Comprueba que la unidad académica pertenezca al docente en sesión."""
        courses = self._teacher_repository.get_courses(teacher_id)
        if not any(u["id"] == unit_id for course in courses for u in course["units"]):
            raise AccountConfigurationError(
                "UNIT_NOT_FOUND", "La unidad no pertenece a tus cursos.", 404
            )

    def get_resource(self, teacher_id: str, unit_id: str, resource_id: str) -> dict[str, Any]:
        """Un recurso de la unidad del docente (404 si no existe o es de otra unidad)."""
        return self._get_resource_or_fail(teacher_id, unit_id, resource_id)

    def _get_resource_or_fail(
        self, teacher_id: str, unit_id: str, resource_id: str
    ) -> dict[str, Any]:
        """Recupera un recurso específico verificando tenencia de unidad."""
        self._verify_unit_access(teacher_id, unit_id)
        resource = self._review_repository.get_resource_by_id(teacher_id, resource_id)
        if resource is None or resource.get("unitId") != unit_id:
            raise AccountConfigurationError(
                "RESOURCE_NOT_FOUND", "El recurso no existe.", 404
            )
        return resource

    def list_resources(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        """Lista los recursos de una unidad ordenados por fecha de creación descendente."""
        self._verify_unit_access(teacher_id, unit_id)
        return sorted(
            self._review_repository.get_resources_by_unit(teacher_id, unit_id),
            key=lambda r: r.get("createdAt", ""),
            reverse=True,
        )

    def update_resource(
        self,
        teacher_id: str,
        unit_id: str,
        resource_id: str,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        """Aplica y persiste las modificaciones y decisiones del docente sobre el recurso."""
        existing = self._get_resource_or_fail(teacher_id, unit_id, resource_id)
        status = changes["status"]
        if status not in ALLOWED_REVIEW_STATUSES:
            raise AccountConfigurationError(
                "INVALID_STATUS", "El estado del recurso no es válido.", 422
            )

        discard_reason = changes.get("discardReason")
        if discard_reason is not None and discard_reason not in ALLOWED_DISCARD_REASONS:
            raise AccountConfigurationError("INVALID_REASON", "Elige un motivo de la lista.", 422)

        updated_resource: dict[str, Any] = {
            **existing,
            "title": changes["title"],
            "body": changes["body"],
            "edited": bool(changes.get("edited")),
        }
        if "bodyHtml" in changes:
            # Ya llega limpio (sin scripts ni atributos peligrosos) desde el adaptador HTTP.
            updated_resource["bodyHtml"] = changes["bodyHtml"] or None
        if changes.get("structure") is not None:
            if not needs_structure(existing.get("type", "")):
                raise AccountConfigurationError(
                    "INVALID_STRUCTURE", "Este tipo de recurso no tiene elementos para editar.", 422
                )
            structure = normalize_structure(existing["type"], changes["structure"])
            if structure is None:
                raise AccountConfigurationError(
                    "INVALID_STRUCTURE", "Completa todos los elementos de la actividad antes de guardar.", 422
                )
            media = existing.get("media") or {}
            if media.get("status") == "ready" and structure != existing.get("structure"):
                # El archivo se generó con el guion o la descripción anterior: deja de usarse para que la revisión,
                # la aprobación y el SCORM no mezclen el texto nuevo con el audio o la imagen viejos.
                updated_resource["media"] = fallback_media(existing["format"], EDITED_NOTES[existing["format"]])
            updated_resource["structure"] = structure

        options = existing.get("options")
        if options is not None:
            incoming_options = changes.get("options")
            if incoming_options is None or sorted(o["id"] for o in incoming_options) != sorted(
                o["id"] for o in options
            ):
                raise AccountConfigurationError(
                    "INVALID_OPTIONS", "Las alternativas no coinciden con el recurso.", 422
                )

            options_by_id = {opt["id"]: opt for opt in incoming_options}
            updated_options = []
            for original_opt in options:
                target = options_by_id[original_opt["id"]]
                if target["decision"] not in ALLOWED_OPTION_DECISIONS or (
                    target.get("discardReason") is not None
                    and target["discardReason"] not in ALLOWED_DISCARD_REASONS
                ):
                    raise AccountConfigurationError(
                        "INVALID_DECISION",
                        "La decisión sobre la alternativa no es válida.",
                        422,
                    )

                decision = "pendiente" if original_opt["isCorrect"] else target["decision"]
                updated_options.append(
                    {
                        **original_opt,
                        "text": target["text"],
                        "feedback": target.get("feedback", ""),
                        "decision": decision,
                        "discardReason": target.get("discardReason")
                        if decision == "descartado"
                        else None,
                        "edited": bool(target.get("edited")),
                    }
                )
            updated_resource["options"] = updated_options

        if status == "aprobado":
            blockers = validate_approval_blockers(updated_resource)
            if blockers:
                raise AccountConfigurationError("APPROVAL_BLOCKED", blockers[0], 409)

        current_time = datetime.now(timezone.utc).isoformat()
        if status != existing.get("status"):
            updated_resource["decidedAt"] = current_time if status != "pendiente" else None

        updated_resource["status"] = status
        updated_resource["discardReason"] = discard_reason if status == "descartado" else None
        updated_resource["updatedAt"] = current_time

        self._review_repository.save_resources(teacher_id, unit_id, [updated_resource])
        return updated_resource

    def delete_resource(self, teacher_id: str, unit_id: str, resource_id: str) -> None:
        """Elimina un recurso del repositorio."""
        self._get_resource_or_fail(teacher_id, unit_id, resource_id)
        self._review_repository.delete_resource(teacher_id, resource_id)

    def get_summary(self, teacher_id: str) -> list[dict[str, Any]]:
        """Genera el consolidado de recursos pendientes y aprobados por unidad."""
        summary_list: list[dict[str, Any]] = []
        for course in self._teacher_repository.get_courses(teacher_id):
            for unit in course["units"]:
                resources = self._review_repository.get_resources_by_unit(teacher_id, unit["id"])
                summary_list.append(
                    {
                        "courseId": course["id"],
                        "unitId": unit["id"],
                        "approved": sum(r.get("status") == "aprobado" for r in resources),
                        "pending": sum(r.get("status") == "pendiente" for r in resources),
                    }
                )
        return summary_list

    def get_downloads_history(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        """Lista las descargas recientes de la unidad."""
        self._verify_unit_access(teacher_id, unit_id)
        return sorted(
            self._review_repository.get_downloads(teacher_id, unit_id),
            key=lambda d: d["createdAt"],
            reverse=True,
        )[:MAX_DOWNLOADS_HISTORY]

    def get_download_record(self, teacher_id: str, unit_id: str, download_id: str) -> dict[str, Any]:
        """Obtiene un registro individual de descarga del historial de la unidad."""
        self._verify_unit_access(teacher_id, unit_id)
        records = self._review_repository.get_downloads(teacher_id, unit_id)
        record = next((d for d in records if d.get("id") == download_id), None)
        if record is None:
            raise AccountConfigurationError("DOWNLOAD_NOT_FOUND", "La descarga solicitada no existe.", 404)
        return record

    def register_download(
        self, teacher_id: str, unit_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Registra un evento de exportación en el historial de descargas."""
        self._verify_unit_access(teacher_id, unit_id)
        if payload["format"] not in ALLOWED_EXPORT_FORMATS:
            raise AccountConfigurationError(
                "INVALID_FORMAT", "El formato de descarga no es válido.", 422
            )

        download_record: dict[str, Any] = {
            "id": f"descarga-{uuid4()}",
            "unitId": unit_id,
            "format": payload["format"],
            "fileName": payload["fileName"],
            "resourceCount": payload["resourceCount"],
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        self._review_repository.save_download(teacher_id, unit_id, download_record)
        return download_record

    def clear_downloads_history(self, teacher_id: str, unit_id: str) -> None:
        """Elimina el registro histórico de descargas de una unidad."""
        self._verify_unit_access(teacher_id, unit_id)
        self._review_repository.delete_downloads(teacher_id, unit_id)

