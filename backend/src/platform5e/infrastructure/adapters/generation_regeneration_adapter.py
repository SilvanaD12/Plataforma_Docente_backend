"""
GEN-01 (T029, caso GEN-C7): adaptador de Generación para `ResourceRegenerationPort`, el puerto de Revisión (REV-01).

Reemplaza al adaptador síncrono provisional. `request_regeneration` crea un pedido `regeneration` con
`StartRegeneration` (clave `regen-{resourceId}-v{resourceVersion}`, o `-r2`, `-r3`… si el intento anterior falló;
unidad tomada de `params["unitId"]`) y espera su resultado hasta `wait_seconds` (10 s por defecto) consultando el
pedido. Si termina, devuelve `succeeded` o `failed`; si no, `pending` o
`running`, y Revisión sigue con `get_regeneration`.

Estados del pedido → estados del puerto:
- `queued` → `pending`, `running` → `running`.
- `succeeded` (o `partially_succeeded` con recursos) → `succeeded` con los recursos nuevos.
- `failed`, `interrupted` o un pedido terminado sin recursos → `failed`, con el motivo y el código.

Un rechazo al iniciar (`REGENERATION_UNAVAILABLE`, `NO_PROCESSED_MATERIAL`, `UNIT_NOT_FOUND`,
`TOO_MANY_ACTIVE_REQUESTS`…) se devuelve como `failed` con su código, igual que el adaptador provisional. Generación no
descarta el recurso anterior: eso lo hace Revisión al ver `succeeded`.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from platform5e.application.ports.outbound.resource_regeneration_port import RegenerationStatus
from platform5e.application.use_cases.generation.get_generation_request import GetGenerationRequest
from platform5e.application.use_cases.generation.start_regeneration import (
    StartRegeneration,
    StartRegenerationCommand,
    regeneration_key,
)
from platform5e.domain.generation.errors import GenerationError
from platform5e.domain.generation.generation_request import (
    GenerationMode,
    GenerationRequest,
    RequestStatus,
    StepStatus,
)
from platform5e.infrastructure.settings import DEFAULT_GENERATION_REGENERATION_WAIT_SECONDS

logger = logging.getLogger("platform5e.regeneration")

DEFAULT_POLL_SECONDS: float = 0.5
UNEXPECTED_ERROR = "La regeneración no pudo completarse. Inténtalo de nuevo más tarde."
NO_RESOURCES_MESSAGE = "La regeneración no produjo recursos nuevos con respaldo suficiente en el material."
NO_RESOURCES_CODE = "INSUFFICIENT_EVIDENCE"
MISSING_UNIT_CODE = "UNIT_NOT_FOUND"
MISSING_UNIT_MESSAGE = "Falta la unidad del recurso para regenerarlo."

FINAL_STATUSES = frozenset(
    {RequestStatus.SUCCEEDED, RequestStatus.PARTIALLY_SUCCEEDED, RequestStatus.FAILED, RequestStatus.INTERRUPTED}
)


def _new_resource_ids(request: GenerationRequest) -> tuple[str, ...]:
    return tuple(resource_id for step in request.steps for resource_id in step.resource_ids)


def _failure_reason(request: GenerationRequest) -> tuple[str, str | None]:
    """Motivo y código del pedido fallido: el del pedido o, si no lo tiene, el del primer paso con problema."""
    if request.failure is not None:
        return request.failure.message, str(request.failure.code)
    for step in request.steps:
        if step.error is not None:
            return step.error.message, str(step.error.code)
        if step.status == StepStatus.REJECTED and step.rejections:
            return f"{NO_RESOURCES_MESSAGE} Motivo: {step.rejections[0]['reason']}", NO_RESOURCES_CODE
    return NO_RESOURCES_MESSAGE, NO_RESOURCES_CODE


def to_regeneration_status(request: GenerationRequest) -> RegenerationStatus:
    """Traduce el estado del pedido de Generación al del puerto de Revisión."""
    if request.status == RequestStatus.QUEUED:
        return RegenerationStatus(request.id, "pending")
    if request.status == RequestStatus.RUNNING:
        return RegenerationStatus(request.id, "running")
    new_ids = _new_resource_ids(request)
    if request.status in (RequestStatus.SUCCEEDED, RequestStatus.PARTIALLY_SUCCEEDED) and new_ids:
        return RegenerationStatus(request.id, "succeeded", new_ids)
    reason, code = _failure_reason(request)
    return RegenerationStatus(request.id, "failed", (), reason, code)


class GenerationRegenerationAdapter:
    """Implementa `ResourceRegenerationPort` con los casos de uso de pedidos de Generación."""

    def __init__(
        self,
        start_regeneration: StartRegeneration,
        get_generation: GetGenerationRequest,
        wait_seconds: float = DEFAULT_GENERATION_REGENERATION_WAIT_SECONDS,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._start = start_regeneration
        self._get = get_generation
        self._wait_seconds = max(0.0, wait_seconds)
        self._poll_seconds = poll_seconds
        self._monotonic = monotonic
        self._sleep = sleep

    def request_regeneration(
        self, teacher_id: str, resource_id: str, resource_version: int, params: dict[str, Any]
    ) -> RegenerationStatus:
        key = regeneration_key(resource_id, resource_version)
        unit_id = params.get("unitId") if isinstance(params, dict) else None
        if not isinstance(unit_id, str) or not unit_id:
            return RegenerationStatus(key, "failed", (), MISSING_UNIT_MESSAGE, MISSING_UNIT_CODE)
        try:
            started = self._start.execute(
                StartRegenerationCommand(teacher_id, unit_id, resource_id, resource_version, params)
            )
        except GenerationError as error:  # rechazo por los datos del docente: Revisión responde con su código
            return RegenerationStatus(key, "failed", (), error.message, str(error.code))
        except Exception as error:  # fallo inesperado: sin código, Revisión responde 502
            logger.warning("No se pudo iniciar la regeneración de %s: %s", resource_id, str(error)[:200])
            return RegenerationStatus(key, "failed", (), UNEXPECTED_ERROR)
        return self._wait(teacher_id, started.request)

    def get_regeneration(self, teacher_id: str, request_id: str) -> RegenerationStatus | None:
        request = self._find(teacher_id, request_id)
        return to_regeneration_status(request) if request is not None else None

    def _find(self, teacher_id: str, request_id: str) -> GenerationRequest | None:
        """El pedido de regeneración del docente, o None si no existe, es ajeno o no es una regeneración."""
        try:
            request = self._get.get(teacher_id, request_id).request
        except GenerationError:
            return None
        return request if request.mode == GenerationMode.REGENERATION else None

    def _wait(self, teacher_id: str, request: GenerationRequest) -> RegenerationStatus:
        """Consulta el pedido hasta que termine o se acabe la espera. Con espera 0 devuelve el estado al crearlo."""
        deadline = self._monotonic() + self._wait_seconds
        while request.status not in FINAL_STATUSES and self._monotonic() < deadline:
            self._sleep(min(self._poll_seconds, max(0.0, deadline - self._monotonic())))
            latest = self._find(teacher_id, request.id)
            if latest is None:  # se borró (por ejemplo, el curso): no hay recursos nuevos
                break
            request = latest
        return to_regeneration_status(request)
