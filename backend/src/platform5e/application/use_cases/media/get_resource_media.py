"""
Caso de uso: entrega el archivo visual o de audio de un recurso para mostrarlo en la revisión.

Los gráficos (mapa conceptual, infografía, diagrama) se dibujan al pedirlos desde su estructura; la imagen y el
audio generados se leen del repositorio. Sin imagen generada, se dibuja la tarjeta con la descripción.
"""

from __future__ import annotations

from dataclasses import dataclass

from platform5e.application.ports.outbound.media_port import MediaRepositoryPort, VisualRendererPort
from platform5e.application.services.review.resource_review_service import ResourceReviewService
from platform5e.domain.accounts.teacher_account import AccountConfigurationError
from platform5e.domain.generation.resource_formats import AUDIO, IMAGE, VISUAL


@dataclass(frozen=True)
class ResourceMediaFile:
    content: bytes
    media_type: str
    file_name: str


class GetResourceMediaUseCase:
    def __init__(
        self,
        review_service: ResourceReviewService,
        media_repository: MediaRepositoryPort,
        renderer: VisualRendererPort,
    ) -> None:
        self._review_service = review_service
        self._media_repository = media_repository
        self._renderer = renderer

    def execute(self, teacher_id: str, unit_id: str, resource_id: str) -> ResourceMediaFile:
        resource = self._review_service.get_resource(teacher_id, unit_id, resource_id)
        kind = resource.get("format")
        media = resource.get("media") or {}
        if kind in (IMAGE, AUDIO) and media.get("status") == "ready":
            stored = self._media_repository.get_media(teacher_id, media["id"])
            if stored is not None:
                details, content = stored
                return ResourceMediaFile(content, details["mimeType"], details["fileName"])
        if kind == VISUAL or kind == IMAGE:
            svg = self._renderer.render(resource)
            return ResourceMediaFile(svg.encode("utf-8"), "image/svg+xml", f"{resource_id}.svg")
        raise AccountConfigurationError("NO_MEDIA", "Este recurso no tiene un archivo de imagen o audio.", 404)
