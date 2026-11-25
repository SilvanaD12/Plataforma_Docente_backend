"""Adaptador del catálogo compartido por el selector y la generación de planes."""

from __future__ import annotations

from collections.abc import Sequence

from platform5e.application.ports.outbound.resource_catalog_port import CatalogEntry, ResourceCatalogPort
from platform5e.application.services.generation.prompt_drafting import RESOURCE_TYPES as TYPE_DESCRIPTIONS
from platform5e.domain.generation.resource_catalog import CUR_P2_TEXT_TYPES, RESOURCE_TYPES, ResourceTypeDefinition
from platform5e.domain.generation.text_types import length_hint_from, verification_mode
from platform5e.domain.generation.resource_formats import modalities_of


class StaticResourceCatalogAdapter(ResourceCatalogPort):
    def entries(self) -> Sequence[CatalogEntry]:
        return tuple(self._entry(entry) for entry in RESOURCE_TYPES)

    @staticmethod
    def _entry(entry: ResourceTypeDefinition) -> CatalogEntry:
        metadata = CUR_P2_TEXT_TYPES.get(entry.id, {})
        return CatalogEntry(
            id=entry.id,
            name=entry.name,
            stage=entry.stage,
            format=entry.format,
            description=metadata.get("description", TYPE_DESCRIPTIONS.get(entry.id, (entry.name, entry.name))[1]),
            modalities=tuple(modalities_of(entry.id)),
            length_hint=length_hint_from(metadata.get("lengthHint")),
            verification=verification_mode(metadata.get("verification")),
        )
