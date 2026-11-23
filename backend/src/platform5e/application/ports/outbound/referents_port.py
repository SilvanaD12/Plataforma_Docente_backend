"""
GEN-P1: referentes del tema (MAT-P2, specs/006-plan-de-generacion/research.md R10).

Material entrega los autores principales del tema que aparecen en el material de la unidad. Mientras MAT-P2 no esté,
el adaptador devuelve una lista vacía.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from platform5e.domain.generation.generation_plan import PlanFragment, Referent


class ReferentsPort(Protocol):
    def referents_for(
        self, teacher_id: str, unit_id: str, topic: str, fragments: Sequence[PlanFragment]
    ) -> Sequence[Referent]:
        """Referentes del tema, con los fragmentos de `fragments` donde aparecen. Puede devolver una lista vacía."""
        ...
