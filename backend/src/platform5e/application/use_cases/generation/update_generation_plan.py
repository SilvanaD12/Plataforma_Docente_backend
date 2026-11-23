"""
Caso de uso GEN-P1 (T009): guarda la edición del docente (specs/006-plan-de-generacion, PLAN-C5).

Reemplaza los ítems, vuelve a borrador y sube la versión. Un plan inválido se guarda igual, con sus problemas, para
que el docente no pierda su trabajo. La etapa de cada ítem sale del catálogo, no del cliente; un tipo que no está en
el catálogo se rechaza con INVALID_PARAMETERS. Solo depende de puertos y del dominio.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from platform5e.application.ports.outbound.generation_plan_repository_port import GenerationPlanRepositoryPort
from platform5e.application.ports.outbound.resource_catalog_port import ResourceCatalogPort
from platform5e.application.use_cases.generation.get_generation_plan import (
    PlanView,
    known_types,
    plan_view,
    read_plan,
    save_plan,
    utc_now,
)
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_plan import PlanItem, edit_plan

UNKNOWN_TYPE_MESSAGE: str = "Estos tipos de recurso no están en el catálogo: {types}."


@dataclass(frozen=True)
class EditedItem:
    """Un ítem tal como lo envía el docente. `stage` y `doesNotCover` no se reciben: los calcula el servidor."""

    resource_type: str
    quantity: int
    purpose: str
    covers: Sequence[str]
    fragment_ids: Sequence[str]


class UpdateGenerationPlan:
    def __init__(
        self,
        repository: GenerationPlanRepositoryPort,
        catalog: ResourceCatalogPort,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        self._repository = repository
        self._catalog = catalog
        self._clock = clock

    def execute(
        self, teacher_id: str, plan_id: str, expected_version: int, items: Sequence[EditedItem]
    ) -> PlanView:
        plan = read_plan(self._repository, teacher_id, plan_id)
        stages = known_types(self._catalog)
        unknown = list(dict.fromkeys(i.resource_type for i in items if i.resource_type not in stages))
        if unknown:
            raise GenerationError(
                GenerationErrorCode.INVALID_PARAMETERS, UNKNOWN_TYPE_MESSAGE.format(types=", ".join(unknown))
            )
        new_items = [
            PlanItem(
                position=number,
                stage=stages[item.resource_type],
                resource_type=item.resource_type,
                quantity=item.quantity,
                purpose=item.purpose.strip(),
                covers=tuple(concept.strip() for concept in item.covers),
                fragment_ids=tuple(item.fragment_ids),
            )
            for number, item in enumerate(items, 1)
        ]
        edited = edit_plan(plan, expected_version, new_items, self._clock())
        save_plan(self._repository, edited, expected_version)
        return plan_view(edited, self._catalog)
