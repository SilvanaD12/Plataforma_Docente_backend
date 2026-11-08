"""
Puerto de persistencia del pedido de generación en segundo plano (GEN-01) y de sus pasos.
"""

from __future__ import annotations

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


class GenerationRequestRepositoryPort(Protocol):
    """Operaciones de persistencia del pedido. Las consultas del docente siempre filtran por `teacher_id`."""

    def create(self, request: GenerationRequest) -> GenerationRequest:
        """Guarda el pedido con sus pasos (`request.steps`) en una sola transacción.

        Lanza IdempotencyKeyTaken(existing) si (teacher_id, idempotency_key) ya existe.
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

    def save_evidence(self, request_id: str, retrieval: EvidenceRetrieval, retrieved_at: str) -> None: ...

    def update_step(self, request_id: str, step: GenerationStep) -> None: ...

    def heartbeat(self, request_id: str) -> None: ...

    def finish(self, request_id: str, status: RequestStatus, failure: Problem | None) -> None:
        """Cierra el pedido. Un pedido que ya está en un estado final no cambia."""
        ...

    def mark_interrupted(self, stale_before: datetime) -> int:
        """Pasa a interrupted los pedidos queued o running con el latido vencido. Devuelve cuántos cambió."""
        ...
