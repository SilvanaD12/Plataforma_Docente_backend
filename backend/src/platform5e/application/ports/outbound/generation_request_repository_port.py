"""
Puerto de persistencia del pedido de generación en segundo plano (GEN-01) y de sus pasos.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from platform5e.application.ports.outbound.evidence_provider_port import EvidenceRetrieval
from platform5e.domain.generation.generation_request import (
    GenerationRequest,
    GenerationStep,
    Problem,
    RequestStatus,
)
from platform5e.domain.shared.errors import DomainError


class IdempotencyKeyTaken(DomainError):
    """El docente ya tiene un pedido con esa clave. `existing` es ese pedido, para comparar su contenido."""

    def __init__(self, existing: GenerationRequest) -> None:
        super().__init__("El docente ya tiene un pedido con esa clave.")
        self.existing = existing


class ActiveRequestLimitReached(DomainError):
    """El docente ya tiene `max_active` pedidos en `queued` o `running`: el pedido nuevo no se registró."""

    def __init__(self, max_active: int) -> None:
        super().__init__("El docente alcanzó el límite de pedidos activos.")
        self.max_active = max_active


class UnitNoLongerOwned(DomainError):
    """Dentro del bloqueo del docente, la unidad ya no le pertenece (se borró su curso): el pedido no se registró."""

    def __init__(self) -> None:
        super().__init__("La unidad ya no pertenece al docente.")


class GenerationRequestRepositoryPort(Protocol):
    """Operaciones de persistencia del pedido. Las consultas del docente siempre filtran por `teacher_id`."""

    def create(self, request: GenerationRequest) -> GenerationRequest:
        """Guarda el pedido con sus pasos (`request.steps`) en una sola transacción.

        Lanza IdempotencyKeyTaken(existing) si (teacher_id, idempotency_key) ya existe.
        """
        ...

    def create_within_limit(
        self,
        request: GenerationRequest,
        max_active: int,
        unit_still_owned: Callable[[], bool] | None = None,
    ) -> GenerationRequest:
        """Como `create`, pero comprueba el cupo y registra el pedido de forma atómica para el docente: dos envíos
        simultáneos no pueden superar `max_active` pedidos activos (research R4).

        Todo ocurre con el bloqueo por docente tomado, el mismo que toma el borrado de un curso (T047). En orden:
        1. Si (teacher_id, idempotency_key) ya existe lanza IdempotencyKeyTaken(existing), aunque el cupo esté lleno o
           la unidad ya no exista.
        2. Si `unit_still_owned()` devuelve False (el curso se borró después de validar la unidad), lanza
           UnitNoLongerOwned sin insertar nada.
        3. Si el docente ya tiene `max_active` pedidos activos, lanza ActiveRequestLimitReached.
        """
        ...

    def find_by_key(self, teacher_id: str, idempotency_key: str) -> GenerationRequest | None: ...

    def get(self, teacher_id: str, request_id: str) -> GenerationRequest | None:
        """Filtra por docente. Un pedido ajeno devuelve None."""
        ...

    def get_for_runner(self, request_id: str) -> GenerationRequest | None:
        """Lectura sin filtro de docente, solo para el ejecutor en segundo plano."""
        ...

    def list_by_unit(
        self, teacher_id: str, unit_id: str, active_only: bool, limit: int
    ) -> list[GenerationRequest]:
        """Pedidos del docente en la unidad, del más reciente al más antiguo."""
        ...

    def count_active(self, teacher_id: str) -> int:
        """Pedidos del docente en `queued` o `running`."""
        ...

    def mark_running(self, request_id: str, worker_boot_id: str) -> None: ...

    # Las escrituras del ejecutor solo actualizan filas existentes, nunca las insertan: si el pedido se borró (por
    # ejemplo, con su curso) devuelven False y no dejan filas huérfanas.

    def save_evidence(self, request_id: str, retrieval: EvidenceRetrieval, retrieved_at: str) -> bool:
        """Guarda la evidencia recuperada. Devuelve si el pedido existía."""
        ...

    def update_step(self, request_id: str, step: GenerationStep) -> bool:
        """Actualiza un paso existente del pedido. Devuelve False si el pedido o el paso ya no existen."""
        ...

    def heartbeat(self, request_id: str) -> bool:
        """Renueva el latido de un pedido en `queued` o `running`. Devuelve si el pedido existía."""
        ...

    def finish(self, request_id: str, status: RequestStatus, failure: Problem | None) -> bool:
        """Cierra el pedido. Un pedido que ya está en un estado final no cambia. Devuelve si el pedido existía."""
        ...

    def mark_interrupted(self, stale_before: datetime) -> int:
        """Pasa a interrupted los pedidos queued o running cuyo latido (o su creación, si nunca latieron) es anterior a
        `stale_before`. Lo usan el barrido de arranque y el barrido periódico. Devuelve cuántos cambió."""
        ...
