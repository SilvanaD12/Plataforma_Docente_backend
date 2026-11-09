"""
Caso de uso: vuelve a generar la imagen o el audio de un recurso con su descripción o guion actual
(por ejemplo, después de que el docente lo editó). Si el servicio no responde, el recurso queda con su respaldo.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from platform5e.application.ports.outbound.media_port import MediaGeneratorPort, MediaRepositoryPort
from platform5e.application.ports.outbound.resource_repository_port import ResourceReviewRepositoryPort
from platform5e.application.services.media.media_attachment import attach_generated_media, has_media
from platform5e.application.services.review.resource_review_service import ResourceReviewService
from platform5e.domain.accounts.teacher_account import AccountConfigurationError


class RegenerateResourceMediaUseCase:
    def __init__(
        self,
        review_service: ResourceReviewService,
        review_repository: ResourceReviewRepositoryPort,
        media_generator: MediaGeneratorPort | None,
        media_repository: MediaRepositoryPort,
    ) -> None:
        self._review_service = review_service
        self._review_repository = review_repository
        self._media_generator = media_generator
        self._media_repository = media_repository

    def execute(self, teacher_id: str, unit_id: str, resource_id: str) -> dict[str, Any]:
        resource = dict(self._review_service.get_resource(teacher_id, unit_id, resource_id))
        if not has_media(resource):
            raise AccountConfigurationError("NO_MEDIA", "Este recurso no tiene imagen ni audio.", 422)
        if resource.get("status") != "pendiente":
            raise AccountConfigurationError(
                "RESOURCE_NOT_PENDING", "Vuelve el recurso a revisión antes de generar su archivo de nuevo.", 409
            )
        if self._media_generator is None:
            raise AccountConfigurationError(
                "MEDIA_GENERATION_DISABLED",
                "La generación de imágenes y voz no está activa en el servidor: se usa la voz del navegador "
                "o la descripción de la imagen.",
                409,
            )
        started_version = resource.get("version", 1)
        was_invalidated = bool((resource.get("media") or {}).get("invalidated"))
        generated = attach_generated_media(teacher_id, resource, self._media_generator, self._media_repository)
        if was_invalidated and not generated:
            # REV-C8: si la generación falla, el archivo sigue sin generar y la aprobación sigue bloqueada.
            resource["media"] = {**resource["media"], "invalidated": True}
        resource["updatedAt"] = datetime.now(timezone.utc).isoformat()
        # REV-R12: el archivo se generó con el guion o la descripción de `started_version`. Si el docente guardó otra
        # versión mientras tanto, el resultado no se guarda para no pisar su edición. La versión no cambia: el archivo
        # no es contenido verificable.
        if not self._review_repository.save_resource_if_version(
            teacher_id, unit_id, resource, started_version, increment=False
        ):
            raise AccountConfigurationError(
                "VERSION_CONFLICT",
                "El recurso cambió mientras se generaba el archivo. Recárgalo y genera el archivo de nuevo si hace falta.",
                409,
            )
        return resource
