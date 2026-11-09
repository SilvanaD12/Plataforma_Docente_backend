"""GEN-01 (T045, revisión del PR #16): consulta del pedido y claves de idempotencia de evaluation/collect_samples.py.

Sin red: las respuestas del servidor las da un `httpx.MockTransport`.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "evaluation" / "collect_samples.py"
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


@pytest.fixture
def collect(monkeypatch):
    spec = importlib.util.spec_from_file_location("collect_samples", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)  # sin esperas reales entre consultas
    return module


def client_for(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(base_url="http://evaluacion.test", transport=httpx.MockTransport(handler))


def args(**overrides) -> argparse.Namespace:
    return argparse.Namespace(**{"run_id": "corrida-1", "timeout": 5.0, "poll": 0.0, **overrides})


CASE = {"id": "c01", "stage": "engage", "resourceType": "pregunta_detonante", "instructions": "Pregunta sobre TCP."}
UNIT = {"id": "unidad-1"}
ACCEPTED = {"id": "gen-req-1", "status": "queued", "steps": []}
FINISHED = {"id": "gen-req-1", "status": "succeeded", "steps": []}


def error(status: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": message}})


# 1. Rechazo definitivo al consultar el pedido


def test_a_404_while_polling_stops_and_records_the_server_error(collect):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(202, json=ACCEPTED)
        return error(404, "GENERATION_REQUEST_NOT_FOUND", "El pedido no existe.")

    with client_for(handler) as client:
        status, failure, _ = collect.run_case(client, {}, UNIT, CASE, args(timeout=30), 0)

    assert status is None
    assert failure["code"] == "GENERATION_REQUEST_NOT_FOUND" and failure["status"] == 404
    assert failure["message"] == "El pedido no existe." and failure["requestId"] == "gen-req-1"
    assert calls == ["POST", "GET"]  # no siguió consultando hasta el tiempo máximo


@pytest.mark.parametrize(
    "transient",
    [
        lambda: error(429, "TOO_MANY_REQUESTS", "Espera."),
        lambda: error(500, "INTERNAL_ERROR", "Error."),
        lambda: httpx.Response(503),
        lambda: httpx.ConnectError("sin red"),
    ],
    ids=["429", "500", "503", "red"],
)
def test_transient_errors_while_polling_are_retried_until_the_request_ends(collect, transient):
    answers = iter([transient(), httpx.Response(200, json={**ACCEPTED, "status": "running"}), httpx.Response(200, json=FINISHED)])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json=ACCEPTED)
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    with client_for(handler) as client:
        status, failure, _ = collect.run_case(client, {}, UNIT, CASE, args(), 0)
    assert failure is None and status == FINISHED


def test_transient_errors_until_the_deadline_are_a_timeout(collect, monkeypatch):
    clock = iter(range(0, 1000, 1))
    monkeypatch.setattr(collect.time, "monotonic", lambda: float(next(clock)))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json=ACCEPTED)
        return error(429, "TOO_MANY_REQUESTS", "Espera.")

    with client_for(handler) as client:
        status, failure, _ = collect.run_case(client, {}, UNIT, CASE, args(timeout=5), 0)
    assert status is None and failure["code"] == "TIMEOUT"


def test_a_rejected_start_records_the_server_status_code_and_message(collect):
    with client_for(lambda request: error(400, "NO_PROCESSED_MATERIAL", "Sube material.")) as client:
        status, failure, _ = collect.run_case(client, {}, UNIT, CASE, args(), 0)
    assert status is None
    assert (failure["status"], failure["code"], failure["message"]) == (400, "NO_PROCESSED_MATERIAL", "Sube material.")
    json.dumps(failure)  # se puede escribir en failures.jsonl


# 2. Claves de idempotencia


def test_a_long_run_id_keeps_the_case_and_attempt_and_distinct_keys(collect):
    run_id = "corrida-de-evaluacion-" + "x" * 140
    keys = {
        collect.idempotency_key(run_id, case_id, attempt)
        for case_id in ("c01", "c02")
        for attempt in (0, 1)
    }
    assert len(keys) == 4  # dos casos y dos intentos: cuatro claves distintas
    for key in keys:
        assert KEY_PATTERN.fullmatch(key), key
    assert collect.idempotency_key(run_id, "c02", 1).endswith("-c02-1")


def test_the_same_run_id_gives_the_same_keys_and_different_run_ids_do_not_collide(collect):
    long_a = "a" * 200
    long_b = "a" * 199 + "b"  # mismo comienzo: el recorte solo no basta para distinguirlas
    assert collect.idempotency_key(long_a, "c01", 0) == collect.idempotency_key(long_a, "c01", 0)
    assert collect.idempotency_key(long_a, "c01", 0) != collect.idempotency_key(long_b, "c01", 0)
    # Un run-id corto conserva la forma legible de siempre.
    assert collect.idempotency_key("20261109T120000", "c01", 0) == "eval-20261109T120000-c01-0"
    assert KEY_PATTERN.fullmatch(collect.idempotency_key("", "c01", 0))
    assert KEY_PATTERN.fullmatch(collect.idempotency_key("corrida con espacios/y:raros", "c01", 0))


# 3. Las esperas internas respetan el --timeout (reloj simulado)


class SimulatedClock:
    """`time.monotonic` y `time.sleep` del script: dormir solo avanza el reloj."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.start = self.now

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0
        self.now += seconds

    @property
    def elapsed(self) -> float:
        return self.now - self.start


@pytest.fixture
def clock(collect, monkeypatch) -> SimulatedClock:
    simulated = SimulatedClock()
    monkeypatch.setattr(collect.time, "monotonic", simulated.monotonic)
    monkeypatch.setattr(collect.time, "sleep", simulated.sleep)
    return simulated


def _always(answer: Callable[[], httpx.Response | Exception], post: Callable[[], httpx.Response] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        result = post() if (post is not None and request.method == "POST") else answer()
        if isinstance(result, Exception):
            raise result
        return result

    return handler


@pytest.mark.parametrize(
    ("label", "handler"),
    [
        ("503 al crear", _always(lambda: httpx.Response(503))),
        ("red al crear", _always(lambda: httpx.ConnectError("sin red"))),
        ("429 al crear", _always(lambda: httpx.Response(429, headers={"Retry-After": "30"}))),
        ("503 al consultar", _always(lambda: httpx.Response(503), post=lambda: httpx.Response(202, json=ACCEPTED))),
        ("red al consultar", _always(lambda: httpx.ConnectError("sin red"), post=lambda: httpx.Response(202, json=ACCEPTED))),
        (
            "en curso al consultar",
            _always(lambda: httpx.Response(200, json={**ACCEPTED, "status": "running"}),
                    post=lambda: httpx.Response(202, json=ACCEPTED)),
        ),
    ],
)
def test_with_timeout_1_the_case_ends_as_timeout_within_about_one_second(collect, clock, label, handler):
    with client_for(handler) as client:
        status, failure, _ = collect.run_case(client, {}, UNIT, CASE, args(timeout=1, poll=2), 0)
    assert status is None and failure["code"] == "TIMEOUT", (label, failure)
    assert clock.elapsed <= 1.0 + 1e-6, f"{label}: el reloj avanzó {clock.elapsed} s"
