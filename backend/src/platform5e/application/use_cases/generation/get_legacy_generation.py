"""
Caso de uso GEN-01 (T046 parcial): lectura de una generación guardada por la ruta síncrona retirada.

`GET /api/v1/generations/{id}` sigue mostrando el historial guardado en `generaciones_demo`, tal como se respondió.
La comprobación de que la generación es del docente la sigue haciendo Cuentas en la ruta, igual que antes. Solo
depende del puerto reducido y del dominio.
"""

from __future__ import annotations

from typing import Any

from platform5e.application.ports.outbound.generation_repository_port import GenerationRepositoryPort
from platform5e.domain.generation.errors import GenerationError

GENERATION_NOT_FOUND_CODE: str = "GENERATION_NOT_FOUND"
GENERATION_NOT_FOUND_MESSAGE: str = "La solicitud de generación no existe."


class GetLegacyGeneration:
    """Devuelve una generación guardada antes de GEN-01, o GENERATION_NOT_FOUND si no existe."""

    def __init__(self, repository: GenerationRepositoryPort) -> None:
        self._repository = repository

    def get(self, generation_id: str) -> dict[str, Any]:
        result = self._repository.get_by_id(generation_id)
        if result is None:
            raise GenerationError(GENERATION_NOT_FOUND_CODE, GENERATION_NOT_FOUND_MESSAGE)
        return result
