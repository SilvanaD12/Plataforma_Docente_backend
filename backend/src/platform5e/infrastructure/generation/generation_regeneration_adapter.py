"""
REV-01 · Adaptador síncrono del puerto de regeneración (decisión provisional D10, sin confirmación de Generación).

Pide a Generación un recurso nuevo con los parámetros guardados del anterior, por el mismo caso de uso que usa la ruta
`POST /api/v1/generations`, y devuelve directamente `succeeded` o `failed`. No modifica ningún archivo de Generación:
si Generación pasa a pedidos en segundo plano, se cambia solo este adaptador (devolviendo `pending` y consultando con
`get_regeneration`), sin tocar Revisión.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol
from uuid import uuid4

from pydantic import ValidationError

from platform5e.application.ports.outbound.resource_regeneration_port import RegenerationStatus
from platform5e.domain.generation.errors import GenerationError
from platform5e.infrastructure.http.schemas.generations import GenerationRequest

logger = logging.getLogger("platform5e.regeneration")

# Lo que se reutiliza del pedido original: los parámetros que Generación guarda en `params` y la unidad.
STORED_PARAMETERS: tuple[str, ...] = (
    "unitId", "resourceType", "stage", "outcomeId", "difficulty", "optionCount", "instructions", "audience",
    "competency", "modalities", "topK", "evidenceThreshold",
)
MISSING_PARAMETERS = "Faltan los parámetros guardados del recurso para regenerarlo: genera uno nuevo desde Generación."
UNEXPECTED_ERROR = "La regeneración no pudo completarse. Inténtalo de nuevo más tarde."


class GenerationUseCase(Protocol):
    def generate(self, request_data: dict[str, Any], teacher_id: str | None = None) -> dict[str, Any]: ...


class GenerationRegenerationAdapter:
    """Implementa `ResourceRegenerationPort` delegando en el caso de uso de generación existente."""

    def __init__(self, generation_service: GenerationUseCase) -> None:
        self._generation = generation_service
        self._requests: dict[str, tuple[str, RegenerationStatus]] = {}

    def request_regeneration(
        self, teacher_id: str, resource_id: str, resource_version: int, params: dict[str, Any]
    ) -> RegenerationStatus:
        request_id = f"regeneracion-{uuid4()}"
        status = self._run(request_id, teacher_id, params)
        self._requests[request_id] = (teacher_id, status)
        return status

    def get_regeneration(self, teacher_id: str, request_id: str) -> RegenerationStatus | None:
        owner, status = self._requests.get(request_id, (None, None))
        return status if owner == teacher_id else None

    def _run(self, request_id: str, teacher_id: str, params: dict[str, Any]) -> RegenerationStatus:
        try:
            request = GenerationRequest.model_validate(
                {**{key: params[key] for key in STORED_PARAMETERS if key in params}, "quantity": 1}
            )
        except ValidationError:
            return RegenerationStatus(request_id, "failed", (), MISSING_PARAMETERS)
        try:
            result = self._generation.generate(request.to_domain(), teacher_id)
        except GenerationError as error:
            return RegenerationStatus(request_id, "failed", (), error.message)
        except Exception as error:  # el recurso anterior se conserva; se informa un motivo general
            logger.warning("Regeneración fallida (%s): %s", request_id, str(error)[:200])
            return RegenerationStatus(request_id, "failed", (), UNEXPECTED_ERROR)
        new_ids = tuple(resource["id"] for resource in result.get("resources") or [] if resource.get("id"))
        if not new_ids:
            notice = result.get("notice") or "Generación no devolvió recursos con respaldo suficiente."
            return RegenerationStatus(request_id, "failed", (), f"La regeneración no produjo recursos nuevos. {notice}")
        return RegenerationStatus(request_id, "succeeded", new_ids, None)
