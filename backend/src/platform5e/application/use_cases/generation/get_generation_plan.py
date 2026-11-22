"""
Casos de uso GEN-P1 (T009): leer un plan del docente y listar sus planes de una unidad
(specs/006-plan-de-generacion, PLAN-C4 y PLAN-C14).

Un plan ajeno y uno inexistente dan la misma respuesta. La validación se calcula en cada lectura con el catálogo
activo, así un tipo que se quitó del catálogo aparece como problema. Aquí también están las piezas que comparten la
edición y la aprobación. Solo depende de puertos y del dominio.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from platform5e.application.ports.outbound.generation_plan_repository_port import GenerationPlanRepositoryPort
from platform5e.application.ports.outbound.resource_catalog_port import ResourceCatalogPort
from platform5e.application.ports.outbound.unit_membership_port import UnitMembershipPort
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_plan import (
    ALREADY_USED_MESSAGE,
    VERSION_CONFLICT_MESSAGE,
    GenerationPlan,
    PlanProblem,
    PlanStatus,
)
from platform5e.domain.generation.plan_validation import validate_plan

PLAN_NOT_FOUND_MESSAGE: str = "El plan no existe."
UNIT_NOT_FOUND_MESSAGE: str = "La unidad no existe o no pertenece a tus cursos."
MIN_LIST_LIMIT: int = 1
MAX_LIST_LIMIT: int = 20
DEFAULT_LIST_LIMIT: int = 5


def utc_now() -> str:
    """Instante actual en el mismo formato que guarda el repositorio (UTC, con microsegundos)."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass(frozen=True)
class PlanView:
    """El plan con sus problemas de validación, calculados al leerlo."""

    plan: GenerationPlan
    problems: tuple[PlanProblem, ...]


def known_types(catalog: ResourceCatalogPort) -> dict[str, str]:
    """Tipos activos del catálogo con su etapa."""
    return {entry.id: entry.stage for entry in catalog.entries() if entry.active}


def plan_view(plan: GenerationPlan, catalog: ResourceCatalogPort) -> PlanView:
    return PlanView(plan=plan, problems=tuple(validate_plan(plan, known_types(catalog))))


def plan_not_found() -> GenerationError:
    return GenerationError(GenerationErrorCode.PLAN_NOT_FOUND, PLAN_NOT_FOUND_MESSAGE)


def read_plan(repository: GenerationPlanRepositoryPort, teacher_id: str, plan_id: str) -> GenerationPlan:
    plan = repository.get(teacher_id, plan_id)
    if plan is None:
        raise plan_not_found()
    return plan


def save_plan(repository: GenerationPlanRepositoryPort, plan: GenerationPlan, expected_version: int) -> None:
    """Guardado condicional: si otra escritura ganó entre la lectura y el guardado, explica por qué no se guardó."""
    if repository.save_if_version(plan, expected_version):
        return
    current = repository.get(plan.teacher_id, plan.id)
    if current is None:
        raise plan_not_found()
    if current.status == PlanStatus.USED:
        raise GenerationError(GenerationErrorCode.PLAN_ALREADY_USED, ALREADY_USED_MESSAGE)
    raise GenerationError(GenerationErrorCode.PLAN_VERSION_CONFLICT, VERSION_CONFLICT_MESSAGE)


class GetGenerationPlan:
    """Lectura y listado de los planes del docente."""

    def __init__(
        self,
        repository: GenerationPlanRepositoryPort,
        membership: UnitMembershipPort,
        catalog: ResourceCatalogPort,
    ) -> None:
        self._repository = repository
        self._membership = membership
        self._catalog = catalog

    def get(self, teacher_id: str, plan_id: str) -> PlanView:
        return plan_view(read_plan(self._repository, teacher_id, plan_id), self._catalog)

    def list(
        self, teacher_id: str, unit_id: str, status: PlanStatus | None = None, limit: int = DEFAULT_LIST_LIMIT
    ) -> list[PlanView]:
        """Los planes de la unidad, el último modificado primero. Una unidad ajena responde como una inexistente."""
        if self._membership.get_unit_context(teacher_id, unit_id) is None:
            raise GenerationError(GenerationErrorCode.UNIT_NOT_FOUND, UNIT_NOT_FOUND_MESSAGE)
        bounded = max(MIN_LIST_LIMIT, min(int(limit), MAX_LIST_LIMIT))
        return [plan_view(plan, self._catalog)
                for plan in self._repository.list_for_unit(teacher_id, unit_id, status, bounded)]
