"""
Caso de uso: exporta los recursos aprobados de una unidad en el formato pedido y registra la descarga en el historial.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

from platform5e.application.ports.outbound.media_port import MediaRepositoryPort
from platform5e.application.ports.outbound.resource_repository_port import ResourceReviewRepositoryPort
from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort
from platform5e.application.ports.outbound.unit_exporter_port import ExportedFile, UnitExporterPort
from platform5e.domain.accounts.teacher_account import AccountConfigurationError

# Quitar "aprobado" cuando los valores guardados estén migrados al inglés.
APPROVED_STATUSES: set[str] = {"approved", "aprobado"}


class ExportUnitResourcesUseCase:
    """Busca la unidad del docente, filtra lo aprobado y delega el archivo al exportador del formato pedido."""

    def __init__(
        self,
        teacher_repository: TeacherRepositoryPort,
        review_repository: ResourceReviewRepositoryPort,
        exporters: Sequence[UnitExporterPort],
        media_repository: MediaRepositoryPort | None = None,
    ) -> None:
        self._media_repository = media_repository
        self._teacher_repository = teacher_repository
        self._review_repository = review_repository
        self._exporters = {exporter.format: exporter for exporter in exporters}

    @property
    def formats(self) -> list[str]:
        return sorted(self._exporters)

    def execute(
        self, teacher_id: str, unit_id: str, export_format: str, resource_ids: Sequence[str] = ()
    ) -> ExportedFile:
        course, unit = next(
            (
                (course, unit)
                for course in self._teacher_repository.get_courses(teacher_id)
                for unit in course["units"]
                if unit["id"] == unit_id
            ),
            (None, None),
        )
        if unit is None:
            raise AccountConfigurationError("UNIT_NOT_FOUND", "La unidad no pertenece a tus cursos.", 404)

        exporter = self._exporters.get(export_format)
        if exporter is None:
            raise AccountConfigurationError("INVALID_FORMAT", "El formato de exportación no es válido.", 422)

        wanted = set(resource_ids)
        approved = [
            resource
            for resource in self._review_repository.get_resources_by_unit(teacher_id, unit_id)
            if resource.get("status") in APPROVED_STATUSES
            and (not wanted or resource["id"] in wanted)
            and exporter.supports(resource)
        ]
        if not approved:
            raise AccountConfigurationError(
                "NO_APPROVED_RESOURCES", "Elige al menos un recurso aprobado que admita este formato.", 422
            )

        exported = exporter.export([self._with_media_file(teacher_id, r) for r in approved], course, unit)
        self._review_repository.save_download(
            teacher_id,
            unit_id,
            {
                "id": f"descarga-{uuid4()}",
                "unitId": unit_id,
                "format": export_format,
                "fileName": exported.file_name,
                "resourceCount": len(approved),
                "createdAt": datetime.now(timezone.utc).isoformat(),
            },
        )
        return exported

    def _with_media_file(self, teacher_id: str, resource: dict) -> dict:
        """Agrega el archivo generado (imagen o audio) para que el exportador lo incluya en el paquete."""
        media = resource.get("media") or {}
        if self._media_repository is None or media.get("status") != "ready" or media.get("outdated"):
            return resource
        stored = self._media_repository.get_media(teacher_id, media["id"])
        if stored is None:
            return resource
        details, content = stored
        return {**resource, "mediaFile": {"fileName": details["fileName"], "mimeType": details["mimeType"], "content": content}}
