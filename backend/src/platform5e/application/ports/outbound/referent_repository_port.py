"""Puerto de salida para persistir y consultar referentes identificados en el material de una unidad (MAT-P2)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from platform5e.domain.generation.generation_plan import Referent


class ReferentRepositoryPort(Protocol):
    def replace_unit_referents(
        self,
        teacher_id: str,
        unit_id: str,
        referents: Sequence[Referent],
        document_id: str | None = None,
    ) -> None:
        """Guarda o reemplaza los referentes de la unidad (o de un documento dentro de la unidad)."""
        ...

    def get_unit_referents(self, teacher_id: str, unit_id: str) -> list[Referent]:
        """Recupera los referentes persistidos de la unidad para el docente indicado."""
        ...