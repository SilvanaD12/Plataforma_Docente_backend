"""
GEN-P1: catálogo de tipos de recurso que lee Generación (specs/006-plan-de-generacion/research.md R6).

Hoy lo entrega un adaptador sobre el catálogo del código; con CUR-P2, el catálogo configurable de Cursos.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from platform5e.domain.generation.text_types import LengthHint


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
    # CUR-P2 (research R6): extensión esperada, guía del prompt y nunca regla de rechazo; None si no trae una válida.
    length_hint: LengthHint | None = None
    # CUR-P2: `strict` o `framed` en los tipos de texto nuevos; None en los tipos con redactor propio.
    verification: str | None = None


class ResourceCatalogPort(Protocol):
    def entries(self) -> Sequence[CatalogEntry]:
        """Los tipos activos del catálogo."""
        ...
