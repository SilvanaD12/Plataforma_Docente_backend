"""Corrección 3 del PR #14: un pedido en cola sin dueño no se queda en `queued` para siempre.

Reproduce lo que encontró la revisión: un pedido en cola con 59 s sobrevivía al barrido de arranque y nadie lo volvía a
revisar. Ahora el ejecutor renueva el latido de todo lo que tiene en cola o en ejecución, y un barrido periódico
interrumpe lo que lleva más de 60 s sin latido, sin reiniciar el servidor. SQLite temporal y reloj controlado.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from platform5e.domain.generation.generation_request import RequestStatus
from tests.integration.test_generation_request_repository import make_request
from tests.support.generation_fakes import sqlite_repository

STALE_SECONDS = 60


def _wait_for(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    limit = time.monotonic() + timeout
    while time.monotonic() < limit:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


def test_an_ownerless_queued_request_is_interrupted_without_restarting_and_a_live_one_is_kept(tmp_path):
    from platform5e.infrastructure.jobs.stale_request_sweeper import StaleRequestSweeper
    from platform5e.infrastructure.jobs.thread_pool_generation_runner import ThreadPoolGenerationRunner

    repository = sqlite_repository(tmp_path)
    now = datetime.now(timezone.utc)
    status = lambda request_id: repository.get("docente-a", request_id).status  # noqa: E731

    # Un pedido que dejó en cola el proceso anterior, 59 s antes del arranque: el barrido de arranque no lo alcanza.
    ownerless = repository.create(make_request(key="clave-sin-dueno", created_at=now - timedelta(seconds=59)))
    assert repository.mark_interrupted(now - timedelta(seconds=STALE_SECONDS)) == 0
    assert status(ownerless.id) == RequestStatus.QUEUED

    # Este proceso tiene un hilo ocupado y otro pedido igual de antiguo esperando en su cola.
    release = threading.Event()
    busy = repository.create(make_request(key="clave-ocupando-hilo", created_at=now))
    waiting = repository.create(make_request(key="clave-en-cola-viva", created_at=now - timedelta(seconds=59)))
    runner = ThreadPoolGenerationRunner(lambda request_id: release.wait(10), repository, 1, heartbeat_seconds=0.05)
    offset = [0.0]
    sweeper = StaleRequestSweeper(
        repository,
        interval_seconds=0.05,
        stale_seconds=STALE_SECONDS,
        clock=lambda: datetime.now(timezone.utc) + timedelta(seconds=offset[0]),
    )
    runner.start()
    sweeper.start()
    try:
        runner.submit(busy.id)
        runner.submit(waiting.id)
        time.sleep(0.3)  # varios barridos antes de vencer el plazo
        assert status(ownerless.id) == RequestStatus.QUEUED

        offset[0] = 2.0  # pasan dos segundos: el pedido sin dueño cumple 61 s sin latido
        assert _wait_for(lambda: status(ownerless.id) == RequestStatus.INTERRUPTED)
        interrupted = repository.get("docente-a", ownerless.id)
        assert interrupted.failure.code == "REQUEST_INTERRUPTED"

        time.sleep(0.3)  # más barridos con el plazo vencido
        assert status(waiting.id) == RequestStatus.QUEUED  # su ejecutor sigue vivo y renueva el latido
        assert status(busy.id) == RequestStatus.QUEUED
        assert repository.get("docente-a", waiting.id).heartbeat_at is not None
    finally:
        release.set()
        sweeper.stop()
        runner.shutdown(wait=True)


def test_the_runner_stops_renewing_a_request_once_it_finishes(tmp_path):
    from platform5e.infrastructure.jobs.thread_pool_generation_runner import ThreadPoolGenerationRunner

    repository = sqlite_repository(tmp_path)
    request = repository.create(make_request())
    runner = ThreadPoolGenerationRunner(lambda request_id: None, repository, 1, heartbeat_seconds=0.05)
    runner.start()
    try:
        runner.submit(request.id).result(timeout=5)
        assert _wait_for(lambda: runner.tracked_request_ids() == frozenset())
    finally:
        runner.shutdown(wait=True)


def test_the_sweeper_survives_a_failing_sweep(caplog):
    from platform5e.infrastructure.jobs.stale_request_sweeper import StaleRequestSweeper

    calls: list[datetime] = []

    class FlakyRepository:
        def mark_interrupted(self, stale_before: datetime) -> int:
            calls.append(stale_before)
            if len(calls) == 1:
                raise ConnectionError("base caída")
            return 0

    sweeper = StaleRequestSweeper(FlakyRepository(), interval_seconds=0.02, stale_seconds=STALE_SECONDS)
    with caplog.at_level("WARNING", logger="platform5e.generation.sweep"):
        sweeper.start()
        try:
            assert _wait_for(lambda: len(calls) >= 3)
        finally:
            sweeper.stop()
    assert "barrido" in caplog.text
    count = len(calls)
    time.sleep(0.1)
    assert len(calls) == count  # se detuvo
    assert all(datetime.now(timezone.utc) - moment >= timedelta(seconds=STALE_SECONDS - 1) for moment in calls)
