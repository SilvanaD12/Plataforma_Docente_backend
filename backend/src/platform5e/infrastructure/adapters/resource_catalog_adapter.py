"""
GEN-P1: catálogo de tipos para Generación, sobre el catálogo actual del código (`domain/generation/resource_catalog.py`).

La descripción de cada tipo es la que ya usa el prompt de redacción (`prompt_drafting.RESOURCE_TYPES`). Cuando CUR-P2
entregue el catálogo configurable de Cursos, otro adaptador de `ResourceCatalogPort` lo reemplaza.
"""

from __future__ import annotations

from collections.abc import Sequence

from platform5e.application.ports.outbound.resource_catalog_port import CatalogEntry, ResourceCatalogPort
from platform5e.application.services.generation.prompt_drafting import RESOURCE_TYPES as TYPE_DESCRIPTIONS
from platform5e.domain.generation.resource_catalog import RESOURCE_TYPES
from platform5e.domain.generation.resource_formats import modalities_of


class StaticResourceCatalogAdapter(ResourceCatalogPort):
    def entries(self) -> Sequence[CatalogEntry]:
        return tuple(
            CatalogEntry(
                id=entry.id,
                name=entry.name,
                stage=entry.stage,
                format=entry.format,
                description=TYPE_DESCRIPTIONS.get(entry.id, (entry.name, entry.name))[1],
                modalities=tuple(modalities_of(entry.id)),
            )
            for entry in RESOURCE_TYPES
        )
