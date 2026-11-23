"""
Caso de uso GEN-P1 (T009): aprueba un plan válido en su versión actual (specs/006-plan-de-generacion, PLAN-C7).

Un plan con problemas no se aprueba (PLAN_INVALID, con cada problema). Aprobar otra vez un plan ya aprobado, con su
versión, lo devuelve sin cambios. Aprobar no cambia la versión. Solo depende de puertos y del dominio.
"""

from __future__ import annotations

from collections.abc import Callable

from platform5e.application.ports.outbound.generation_plan_repository_port import GenerationPlanRepositoryPort
from platform5e.application.ports.outbound.resource_catalog_port import ResourceCatalogPort
from platform5e.application.use_cases.generation.get_generation_plan import (
    PlanView,
    plan_view,
    read_plan,
    save_plan,
    utc_now,
)
from platform5e.domain.generation.generation_plan import approve_plan


class ApproveGenerationPlan:
    def __init__(
        self,
        repository: GenerationPlanRepositoryPort,
        catalog: ResourceCatalogPort,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        self._repository = repository
        self._catalog = catalog
        self._clock = clock

    def execute(self, teacher_id: str, plan_id: str, expected_version: int) -> PlanView:
        plan = read_plan(self._repository, teacher_id, plan_id)
        view = plan_view(plan, self._catalog)
        approved = approve_plan(plan, expected_version, view.problems, self._clock())
        if approved is plan:
            return view
        save_plan(self._repository, approved, expected_version)
        return plan_view(approved, self._catalog)
