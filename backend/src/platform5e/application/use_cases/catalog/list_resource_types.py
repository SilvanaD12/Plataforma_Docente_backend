"""Consulta del catálogo público, independiente de HTTP y de la base de datos."""
from dataclasses import asdict
from typing import Any

from platform5e.domain.generation.resource_catalog import RESOURCE_TYPES


class ListResourceTypesUseCase:
    def execute(self) -> list[dict[str, Any]]:
        return [asdict(entry) for entry in RESOURCE_TYPES]
