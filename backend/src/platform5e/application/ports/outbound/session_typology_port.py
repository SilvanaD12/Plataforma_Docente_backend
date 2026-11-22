"""
GEN-P1: tipologías usadas en las sesiones del curso (CUR-P3, specs/006-plan-de-generacion/research.md R9).

Cursos guarda los tipos de recurso usados en cada sesión, para que el plan siguiente varíe. Mientras CUR-P3 no esté, el
adaptador no tiene sesiones. `record_typology` lo usa GEN-P2 cuando un plan inicia un pedido de generación.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from platform5e.domain.generation.generation_plan import PreviousTypology


class SessionTypologyPort(Protocol):
    def previous_typologies(self, teacher_id: str, unit_id: str, limit: int = 3) -> Sequence[PreviousTypology]:
        """Las últimas tipologías del curso de la unidad, de la más reciente a la más antigua."""
        ...

    def record_typology(
        self, teacher_id: str, unit_id: str, plan_id: str, resource_types: Sequence[str], used_at: str
    ) -> None:
        """Registra la tipología de un plan usado."""
        ...
