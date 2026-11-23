"""
GEN-P1: persistencia de los planes de generación (specs/006-plan-de-generacion/data-model.md, «Persistencia»).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from platform5e.domain.generation.generation_plan import GenerationPlan, PlanStatus


class PlanKeyTaken(Exception):
    """Otro alta con la misma clave del docente ganó la carrera; `existing` es ese plan."""

    def __init__(self, existing: GenerationPlan) -> None:
        super().__init__(existing.id)
        self.existing = existing


class GenerationPlanRepositoryPort(Protocol):
    def find_by_key(self, teacher_id: str, idempotency_key: str) -> GenerationPlan | None: ...

    def get(self, teacher_id: str, plan_id: str) -> GenerationPlan | None:
        """El plan del docente, o None si no existe o es de otro docente."""
        ...

    def list_for_unit(
        self, teacher_id: str, unit_id: str, status: PlanStatus | None = None, limit: int = 5
    ) -> Sequence[GenerationPlan]:
        """Los planes de la unidad, del más reciente (por `updatedAt`) al más antiguo."""
        ...

    def list_used_for_units(
        self, teacher_id: str, unit_ids: Sequence[str], limit: int = 3
    ) -> Sequence[GenerationPlan]:
        """Return used plans for the teacher and units, ordered by most recent use."""
        ...

    def create(self, plan: GenerationPlan) -> GenerationPlan:
        """Guarda un plan nuevo. Lanza `PlanKeyTaken` si la clave del docente ya tiene un plan."""
        ...

    def save_if_version(self, plan: GenerationPlan, expected_version: int) -> bool:
        """Guarda `plan` solo si el guardado sigue en `expected_version` y no está usado. False si otro cambio ganó."""
        ...
