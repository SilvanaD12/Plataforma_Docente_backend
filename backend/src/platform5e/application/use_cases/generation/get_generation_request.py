"""
Caso de uso GEN-01 (T017): consulta el estado de un pedido del docente y lista sus pedidos de una unidad.

Un pedido ajeno y uno inexistente dan la misma respuesta (GEN-C5). Cada paso incluye una vista corta de sus recursos
para la pantalla de progreso. Solo depende de puertos y del dominio.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from platform5e.application.ports.outbound.generation_request_repository_port import (
    GenerationRequestRepositoryPort,
)
from platform5e.application.ports.outbound.resource_repository_port import ResourceReviewRepositoryPort
from platform5e.application.ports.outbound.unit_membership_port import UnitMembershipPort
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_request import GenerationRequest

REQUEST_NOT_FOUND_MESSAGE: str = "El pedido de generación no existe."
UNIT_NOT_FOUND_MESSAGE: str = "La unidad no existe o no pertenece a tus cursos."
MIN_LIST_LIMIT: int = 1
MAX_LIST_LIMIT: int = 50


VERIFICATION_STATUSES: frozenset[str] = frozenset({"current", "insufficient", "pending"})
VERIFICATION_PENDING: str = "pending"


@dataclass(frozen=True)
class ResourceSummary:
    """Vista corta de un recurso entregado: `current`, `insufficient` o `pending`."""

    id: str
    title: str
    verification_status: str


@dataclass(frozen=True)
class GenerationRequestView:
    """El pedido con la vista corta de los recursos de cada paso, por posición del paso."""

    request: GenerationRequest
    resources_by_step: dict[int, tuple[ResourceSummary, ...]]


def _summary(resource: dict[str, Any]) -> ResourceSummary:
    """El estado real de la verificación en Revisión. Generación entrega `current` o `pending`, pero el docente puede
    editar el recurso hasta dejarlo `insufficient`. Solo un recurso sin verificación se muestra `pending`."""
    verification = resource.get("verification") if isinstance(resource.get("verification"), dict) else {}
    status = verification.get("status")
    return ResourceSummary(
        id=str(resource.get("id", "")),
        title=str(resource.get("title") or ""),
        verification_status=status if status in VERIFICATION_STATUSES else VERIFICATION_PENDING,
    )


class GetGenerationRequest:
    """Consulta de pedidos del docente (GEN-R3, GEN-C4 y GEN-C5)."""

    def __init__(
        self,
        repository: GenerationRequestRepositoryPort,
        membership: UnitMembershipPort,
        review_repository: ResourceReviewRepositoryPort,
    ) -> None:
        self._repository = repository
        self._membership = membership
        self._review_repository = review_repository

    def get(self, teacher_id: str, request_id: str) -> GenerationRequestView:
        request = self._repository.get(teacher_id, request_id)
        if request is None:
            raise GenerationError(GenerationErrorCode.GENERATION_REQUEST_NOT_FOUND, REQUEST_NOT_FOUND_MESSAGE)

        delivered = {resource_id for step in request.steps for resource_id in step.resource_ids}
        resources: dict[str, dict[str, Any]] = {}
        if delivered:
            resources = {
                str(resource.get("id")): resource
                for resource in self._review_repository.get_resources_by_unit(teacher_id, request.unit_id)
                if resource.get("id") in delivered
            }
        # Un recurso que el docente ya eliminó en Revisión no aparece en la vista.
        return GenerationRequestView(
            request=request,
            resources_by_step={
                step.position: tuple(
                    _summary(resources[resource_id]) for resource_id in step.resource_ids if resource_id in resources
                )
                for step in request.steps
            },
        )

    def list(
        self, teacher_id: str, unit_id: str, active_only: bool = False, limit: int = 20
    ) -> list[GenerationRequest]:
        if self._membership.get_unit_context(teacher_id, unit_id) is None:
            raise GenerationError(GenerationErrorCode.UNIT_NOT_FOUND, UNIT_NOT_FOUND_MESSAGE)
        bounded = max(MIN_LIST_LIMIT, min(limit, MAX_LIST_LIMIT))
        return self._repository.list_by_unit(teacher_id, unit_id, active_only, bounded)
