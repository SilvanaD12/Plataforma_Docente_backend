"""GEN-01 (T029): adaptador de Generación para el puerto de regeneración de Revisión, con casos de uso falsos."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from platform5e.application.use_cases.generation.get_generation_request import GenerationRequestView
from platform5e.application.use_cases.generation.start_generation_request import StartGenerationResult
from platform5e.application.use_cases.generation.start_regeneration import StartRegeneration
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_request import (
    GenerationMode,
    Problem,
    RegenerationTarget,
    RequestStatus,
    StepStatus,
)
from platform5e.infrastructure.adapters.generation_regeneration_adapter import (
    GenerationRegenerationAdapter,
    to_regeneration_status,
)
from tests.integration.test_generation_request_repository import make_request

PARAMS = {"unitId": "u1", "resourceType": "explicacion", "difficulty": "intermedia"}


def regeneration(status: RequestStatus, resource_ids: tuple[str, ...] = (), **changes: Any):
    base = make_request(teacher_id="ana", key="regen-rec-viejo-v3", types=("explicacion",))
    step = replace(
        base.steps[0],
        status=StepStatus.SUCCEEDED if resource_ids else StepStatus.PENDING,
        resource_ids=resource_ids,
    )
    return replace(
        base,
        mode=GenerationMode.REGENERATION,
        status=status,
        steps=(step,),
        regeneration=RegenerationTarget("rec-viejo", 3),
        **changes,
    )


class FakeStartGeneration:
    """El `StartGenerationRequest` que recibe `StartRegeneration`: guarda el comando y responde lo indicado."""

    def __init__(self, request=None, error: Exception | None = None) -> None:
        self.request = request
        self.error = error
        self.commands: list[Any] = []

    def execute(self, command):
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return StartGenerationResult(request=self.request, created=True)


class FakeGetGeneration:
    """Devuelve, en orden, los estados del pedido en cada consulta (el último se repite)."""

    def __init__(self, *states) -> None:
        self.states = list(states)
        self.calls: list[tuple[str, str]] = []

    def get(self, teacher_id: str, request_id: str) -> GenerationRequestView:
        self.calls.append((teacher_id, request_id))
        request = self.states.pop(0) if len(self.states) > 1 else (self.states[0] if self.states else None)
        if request is None or request.teacher_id != teacher_id or request.id != request_id:
            raise GenerationError(GenerationErrorCode.GENERATION_REQUEST_NOT_FOUND, "No existe.")
        return GenerationRequestView(request=request, resources_by_step={})


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def adapter(start: FakeStartGeneration, get: FakeGetGeneration, wait: float = 60.0) -> GenerationRegenerationAdapter:
    clock = Clock()
    return GenerationRegenerationAdapter(
        StartRegeneration(start), get, wait_seconds=wait, poll_seconds=0.5, monotonic=clock.monotonic, sleep=clock.sleep
    )


def test_request_regeneration_creates_a_regeneration_request_and_waits_for_its_result():
    queued = regeneration(RequestStatus.QUEUED)
    finished = replace(regeneration(RequestStatus.SUCCEEDED, ("rec-nuevo",)), id=queued.id)
    start = FakeStartGeneration(queued)
    get = FakeGetGeneration(replace(queued, status=RequestStatus.RUNNING), finished)

    status = adapter(start, get).request_regeneration("ana", "rec-viejo", 3, PARAMS)

    assert (status.request_id, status.status, status.new_resource_ids) == (queued.id, "succeeded", ("rec-nuevo",))
    [command] = start.commands
    assert command.idempotency_key == "regen-rec-viejo-v3" and command.mode == GenerationMode.REGENERATION
    assert command.unit_id == "u1" and command.teacher_id == "ana"
    assert command.regeneration == RegenerationTarget("rec-viejo", 3)
    assert get.calls == [("ana", queued.id), ("ana", queued.id)]


def test_with_a_short_wait_it_answers_pending_or_running_without_blocking():
    queued = regeneration(RequestStatus.QUEUED)
    instant = adapter(FakeStartGeneration(queued), get := FakeGetGeneration(queued), wait=0)
    assert instant.request_regeneration("ana", "rec-viejo", 3, PARAMS).status == "pending"
    assert get.calls == []  # con espera 0 no consulta: devuelve el estado al crearlo

    running = replace(queued, status=RequestStatus.RUNNING)
    slow = adapter(FakeStartGeneration(queued), FakeGetGeneration(running), wait=2)
    assert slow.request_regeneration("ana", "rec-viejo", 3, PARAMS).status == "running"


@pytest.mark.parametrize(
    "code",
    [
        GenerationErrorCode.REGENERATION_UNAVAILABLE,
        GenerationErrorCode.NO_PROCESSED_MATERIAL,
        GenerationErrorCode.UNIT_NOT_FOUND,
        GenerationErrorCode.TOO_MANY_ACTIVE_REQUESTS,
    ],
)
def test_a_rejection_when_starting_is_failed_with_its_code(code):
    start = FakeStartGeneration(error=GenerationError(code, "Motivo para el docente."))
    status = adapter(start, FakeGetGeneration()).request_regeneration("ana", "rec-viejo", 3, PARAMS)
    assert (status.status, status.code, status.reason) == ("failed", str(code), "Motivo para el docente.")
    assert status.new_resource_ids == ()


def test_saved_parameters_without_resource_type_or_unit_are_rejected_without_creating_a_request():
    start = FakeStartGeneration(regeneration(RequestStatus.QUEUED))
    without_type = adapter(start, FakeGetGeneration()).request_regeneration("ana", "rec-viejo", 3, {"unitId": "u1"})
    assert (without_type.status, without_type.code) == ("failed", "REGENERATION_UNAVAILABLE")
    without_unit = adapter(start, FakeGetGeneration()).request_regeneration("ana", "rec-viejo", 3, {"resourceType": "explicacion"})
    assert (without_unit.status, without_unit.code) == ("failed", "UNIT_NOT_FOUND")
    assert start.commands == []


def test_an_unexpected_error_is_failed_without_code():
    start = FakeStartGeneration(error=ConnectionError("base caída"))
    status = adapter(start, FakeGetGeneration()).request_regeneration("ana", "rec-viejo", 3, PARAMS)
    assert status.status == "failed" and status.code is None and "base caída" not in (status.reason or "")


def test_get_regeneration_translates_the_request_states():
    for request_status, expected in [
        (RequestStatus.QUEUED, "pending"),
        (RequestStatus.RUNNING, "running"),
    ]:
        assert to_regeneration_status(regeneration(request_status)).status == expected

    succeeded = to_regeneration_status(regeneration(RequestStatus.SUCCEEDED, ("rec-nuevo",)))
    assert (succeeded.status, succeeded.new_resource_ids, succeeded.reason) == ("succeeded", ("rec-nuevo",), None)

    failed = to_regeneration_status(
        regeneration(RequestStatus.FAILED, failure=Problem(GenerationErrorCode.EVIDENCE_UNAVAILABLE, "Sin búsqueda."))
    )
    assert (failed.status, failed.reason, failed.code) == ("failed", "Sin búsqueda.", "EVIDENCE_UNAVAILABLE")

    interrupted = to_regeneration_status(
        regeneration(RequestStatus.INTERRUPTED, failure=Problem("REQUEST_INTERRUPTED", "El servidor se reinició."))
    )
    assert (interrupted.status, interrupted.code) == ("failed", "REQUEST_INTERRUPTED")

    request = regeneration(RequestStatus.FAILED)
    rejected_step = replace(
        request.steps[0], status=StepStatus.REJECTED, rejections=({"title": "x", "reason": "No cita.", "kind": "grounding"},)
    )
    rejected = to_regeneration_status(replace(request, steps=(rejected_step,)))
    assert rejected.status == "failed" and rejected.code == "INSUFFICIENT_EVIDENCE" and "No cita." in rejected.reason


def test_get_regeneration_returns_none_for_a_missing_foreign_or_non_regeneration_request():
    request = regeneration(RequestStatus.SUCCEEDED, ("rec-nuevo",))
    own = adapter(FakeStartGeneration(), FakeGetGeneration(request))
    assert own.get_regeneration("ana", request.id).new_resource_ids == ("rec-nuevo",)
    assert own.get_regeneration("otra", request.id) is None
    assert own.get_regeneration("ana", "gen-req-inexistente") is None

    sequence = replace(request, mode=GenerationMode.SEQUENCE)
    assert adapter(FakeStartGeneration(), FakeGetGeneration(sequence)).get_regeneration("ana", sequence.id) is None


def test_the_regeneration_wait_setting_accepts_zero_and_ignores_invalid_values():
    from platform5e.infrastructure.settings import generation_regeneration_wait_seconds

    assert generation_regeneration_wait_seconds({}) == 10.0
    assert generation_regeneration_wait_seconds({"GENERATION_REGENERATION_WAIT_SECONDS": "0"}) == 0.0
    assert generation_regeneration_wait_seconds({"GENERATION_REGENERATION_WAIT_SECONDS": "2.5"}) == 2.5
    for invalid in ("-1", "abc", "nan", ""):
        assert generation_regeneration_wait_seconds({"GENERATION_REGENERATION_WAIT_SECONDS": invalid}) == 10.0
