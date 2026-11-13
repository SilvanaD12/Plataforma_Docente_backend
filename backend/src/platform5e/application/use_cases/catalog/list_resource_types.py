"""Consulta del catálogo público, independiente de HTTP y de la base de datos."""
from dataclasses import asdict
from typing import Any

from platform5e.domain.generation.resource_catalog import RESOURCE_TYPES
from platform5e.domain.generation.resource_formats import modalities_of


class ListResourceTypesUseCase:
    def execute(self) -> list[dict[str, Any]]:
        # HU-024: cada tipo informa las modalidades que lo incluyen; el cliente filtra con ellas el selector.
        return [{**asdict(entry), "modalities": modalities_of(entry.id)} for entry in RESOURCE_TYPES]
