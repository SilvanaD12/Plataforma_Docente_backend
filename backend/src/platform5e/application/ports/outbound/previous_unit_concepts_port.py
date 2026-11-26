"""
GEN-P1: conceptos de las unidades anteriores del curso (PLAN-C16, specs/006-plan-de-generacion/research.md R11).

Mismo patrón que CUR-P3 (`SessionTypologyPort`): el plan de una unidad recibe los conceptos propios del último plan
aprobado o usado de cada unidad anterior del mismo curso, para no volver a explicar lo que ya se trató.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from platform5e.domain.generation.generation_plan import PreviousUnitConcepts


class PreviousUnitConceptsPort(Protocol):
    def previous_unit_concepts(
        self, teacher_id: str, unit_id: str, limit: int = 30
    ) -> Sequence[PreviousUnitConcepts]:
        """Los conceptos de las unidades anteriores del curso de la unidad, de la más antigua a la más reciente, con
        hasta `limit` conceptos en total (primero los de la unidad más cercana). Vacío en la primera unidad."""
        ...
