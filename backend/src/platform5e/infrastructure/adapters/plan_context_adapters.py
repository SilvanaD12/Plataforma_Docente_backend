"""
GEN-P1: adaptadores provisionales de los referentes (MAT-P2) y de las tipologías de sesión (CUR-P3).

No tienen datos todavía: el plan los guarda vacíos. Cuando Material y Cursos entreguen sus puertos, sus adaptadores
reemplazan a estos en `main.py` sin cambiar Generación.
"""

from __future__ import annotations

from collections.abc import Sequence

from platform5e.application.ports.outbound.referents_port import ReferentsPort
from platform5e.application.ports.outbound.session_typology_port import SessionTypologyPort
from platform5e.domain.generation.generation_plan import PlanFragment, PreviousTypology, Referent


class NoReferentsAdapter(ReferentsPort):
    def referents_for(
        self, teacher_id: str, unit_id: str, topic: str, fragments: Sequence[PlanFragment]
    ) -> Sequence[Referent]:
        return ()


class NoSessionTypologyAdapter(SessionTypologyPort):
    def previous_typologies(self, teacher_id: str, unit_id: str, limit: int = 3) -> Sequence[PreviousTypology]:
        return ()

    def record_typology(
        self, teacher_id: str, unit_id: str, plan_id: str, resource_types: Sequence[str], used_at: str
    ) -> None:
        return None
