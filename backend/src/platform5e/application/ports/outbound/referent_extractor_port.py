"""Puerto de salida para identificar autores/referentes principales a partir de fragmentos (MAT-P2)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from platform5e.domain.generation.generation_plan import PlanFragment, Referent


class ReferentExtractorPort(Protocol):
    def extract_referents(self, topic: str, fragments: Sequence[PlanFragment]) -> list[Referent]:
        """Extrae referentes principales mencionados o respaldados por `fragments`. Devuelve [] si no aplica."""
        ...