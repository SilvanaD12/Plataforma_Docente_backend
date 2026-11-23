"""
GEN-P1: catálogo de tipos de recurso que lee Generación (specs/006-plan-de-generacion/research.md R6).

Hoy lo entrega un adaptador sobre el catálogo del código; con CUR-P2, el catálogo configurable de Cursos.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CatalogEntry:
    """Lo que Generación necesita de un tipo de recurso para planificarlo y redactarlo."""

    id: str
    name: str
    stage: str
    format: str
    description: str
    modalities: tuple[str, ...] = ()
    active: bool = True


class ResourceCatalogPort(Protocol):
    def entries(self) -> Sequence[CatalogEntry]:
        """Los tipos activos del catálogo."""
        ...
