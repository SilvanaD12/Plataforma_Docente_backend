"""
Caso de uso: exporta los recursos aprobados de una unidad en el formato pedido y registra la descarga en el historial.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

from platform5e.application.ports.outbound.media_port import MediaRepositoryPort
from platform5e.application.ports.outbound.resource_repository_port import ResourceReviewRepositoryPort
from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort
from platform5e.application.ports.outbound.unit_exporter_port import ExportedFile, UnitExporterPort
from platform5e.application.services.review.legacy_verification import upgrade_resource_verification
from platform5e.domain.accounts.teacher_account import AccountConfigurationError, find_course_and_unit
from platform5e.domain.review.errors import ExportNotEligibleError
from platform5e.domain.review.export_eligibility import export_ineligibility

UNSUPPORTED_FORMAT = "unsupported_format"
NO_ELIGIBLE_MESSAGE = (
    "Ningún recurso cumple las condiciones para exportar: aprobado, con comprobación vigente y compatible con el formato."
)


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
        match = find_course_and_unit(self._teacher_repository.get_courses(teacher_id), unit_id)
        if match is None:
            raise AccountConfigurationError("UNIT_NOT_FOUND", "La unidad no pertenece a tus cursos.", 404)
        course, unit = match

        exporter = self._exporters.get(export_format)
        if exporter is None:
            raise AccountConfigurationError("INVALID_FORMAT", "El formato de exportación no es válido.", 422)

        # REV-R7: el mismo filtro para los tres formatos. Los recursos sin verificación se verifican antes (D7).
        wanted = set(resource_ids)
        left_out: Counter[str] = Counter()
        eligible = []
        for stored in self._review_repository.get_resources_by_unit(teacher_id, unit_id):
            if wanted and stored["id"] not in wanted:
                continue
            resource = upgrade_resource_verification(self._review_repository, teacher_id, unit_id, stored)
            reason = export_ineligibility(resource) or (None if exporter.supports(resource) else UNSUPPORTED_FORMAT)
            if reason:
                left_out[reason] += 1
            else:
                eligible.append(resource)
        if not eligible:
            raise ExportNotEligibleError(
                NO_ELIGIBLE_MESSAGE, [{"reason": reason, "count": count} for reason, count in sorted(left_out.items())]
            )

        exported = exporter.export([self._with_media_file(teacher_id, r) for r in eligible], course, unit)
        # REV-R9: un solo registro por archivo, con el curso y la unidad, para que el historial sobreviva al borrado.
        self._review_repository.save_download(
            teacher_id,
            unit_id,
            {
                "id": f"descarga-{uuid4()}",
                "unitId": unit_id,
                "courseId": course.get("id"),
                "courseName": course.get("name"),
                "unitName": unit.get("title"),
                "unitNumber": unit.get("number"),
                "format": export_format,
                "fileName": exported.file_name,
                "resourceCount": len(eligible),
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
