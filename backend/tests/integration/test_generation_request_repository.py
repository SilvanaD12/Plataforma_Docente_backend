"""
GEN-01 (T008): repositorio de pedidos de generación sobre una base real.

Por defecto usa un SQLite temporal (el repositorio crea las tablas). Con GENERATION_REPOSITORY_TEST_DATABASE_URL
apunta a un PostgreSQL local (localhost, 127.0.0.1 o ::1), vacía su esquema public, le aplica las migraciones de
database/migrations y repite las mismas pruebas. Con un host remoto, las pruebas fallan sin tocar la base.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from platform5e.application.ports.outbound.evidence_provider_port import EvidenceFragment, EvidenceRetrieval
from platform5e.application.ports.outbound.generation_request_repository_port import IdempotencyKeyTaken
from platform5e.domain.generation.generation_request import (
    GenerationMode,
    GenerationParameters,
    GenerationRequest,
    GenerationStep,
    Problem,
    RegenerationTarget,
    RequestStatus,
    StepStatus,
    payload_hash,
)
from platform5e.domain.generation.sequence import plan_steps
from platform5e.domain.shared.errors import DuplicateRecordError
from platform5e.infrastructure.persistence.database import normalize_database_url
from platform5e.infrastructure.persistence.migration_runner import apply_database_migrations
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_request_repository import (
    SQLAlchemyGenerationRequestRepository,
    utc_text,
)
from tests.support.local_database import NonLocalDatabaseError, ensure_local_database_url

POSTGRES_URL = os.getenv("GENERATION_REPOSITORY_TEST_DATABASE_URL")


@pytest.fixture
def repository(tmp_path: Path) -> Iterator[SQLAlchemyGenerationRequestRepository]:
    if POSTGRES_URL:
        # Se valida antes de crear la conexión: una base remota nunca se vacía.
        local_url, problem = normalize_database_url(POSTGRES_URL), None
        try:
            ensure_local_database_url(local_url)
        except NonLocalDatabaseError as error:
            problem = str(error)
        if problem:
            pytest.fail(f"GENERATION_REPOSITORY_TEST_DATABASE_URL: {problem}", pytrace=False)
        bind = create_engine(local_url, connect_args={"prepare_threshold": None})
        with bind.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        apply_database_migrations(bind)
    else:
        bind = create_engine(f"sqlite:///{tmp_path / 'generation.db'}", connect_args={"check_same_thread": False})
    yield SQLAlchemyGenerationRequestRepository(bind)
    bind.dispose()


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def make_request(
    teacher_id: str = "docente-a",
    key: str = "clave-estable-1",
    unit_id: str = "u1",
    created_at: datetime | None = None,
    quantity: int = 1,
    types: tuple[str, ...] = ("item_opcion_multiple", "pregunta_detonante"),
) -> GenerationRequest:
    parameters = GenerationParameters(resource_types=types, quantity=quantity, outcome_id="ra-1")
    steps = tuple(GenerationStep.from_plan(p) for p in plan_steps("sequence", list(types), quantity))
    return GenerationRequest(
        id=f"gen-req-{uuid4()}",
        teacher_id=teacher_id,
        unit_id=unit_id,
        mode=GenerationMode.SEQUENCE,
        idempotency_key=key,
        payload_hash=payload_hash(GenerationMode.SEQUENCE, unit_id, parameters),
        parameters=parameters,
        created_at=iso(created_at or datetime.now(timezone.utc)),
        steps=steps,
    )


def test_a_request_round_trips_with_its_steps(repository):
    request = replace(
        make_request(),
        mode=GenerationMode.REGENERATION,
        regeneration=RegenerationTarget("rec-1", 3),
    )
    saved = repository.create(request)

    assert saved.id == request.id and saved.status == RequestStatus.QUEUED
    assert saved.parameters == request.parameters and saved.payload_hash == request.payload_hash
    assert saved.regeneration == RegenerationTarget("rec-1", 3)
    assert [(s.position, s.stage, s.status) for s in saved.steps] == [
        (0, "engage", StepStatus.PENDING),
        (1, "evaluate", StepStatus.PENDING),
    ]
    assert repository.get_for_runner(request.id) == saved


def test_the_same_key_is_independent_between_teachers(repository):
    first = repository.create(make_request(teacher_id="docente-a"))
    second = repository.create(make_request(teacher_id="docente-b"))  # GEN-C5: misma clave, otro docente

    assert first.id != second.id
    assert repository.find_by_key("docente-a", "clave-estable-1").id == first.id
    assert repository.find_by_key("docente-b", "clave-estable-1").id == second.id
    # Un pedido ajeno no se ve.
    assert repository.get("docente-b", first.id) is None
    assert repository.get("docente-a", first.id).id == first.id


def test_a_repeated_key_returns_the_existing_request(repository):
    original = repository.create(make_request())
    with pytest.raises(IdempotencyKeyTaken) as taken:
        repository.create(make_request(quantity=2))  # otro contenido, misma clave

    assert taken.value.existing.id == original.id
    assert taken.value.existing.payload_hash == original.payload_hash  # el caso de uso compara el hash
    assert len(repository.list_by_unit("docente-a", "u1", active_only=False, limit=10)) == 1


def test_a_repeated_id_is_not_mistaken_for_a_repeated_key(repository):
    original = repository.create(make_request())
    with pytest.raises(DuplicateRecordError):
        repository.create(replace(make_request(key="otra-clave-1"), id=original.id))


def test_concurrent_inserts_with_the_same_key_create_a_single_request(repository):
    results: list[str] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(6)

    def insert() -> None:
        barrier.wait()
        try:
            results.append(repository.create(make_request()).id)
        except IdempotencyKeyTaken as taken:
            results.append(taken.existing.id)
        except BaseException as error:  # noqa: BLE001 - se informa en la aserción
            errors.append(error)

    threads = [threading.Thread(target=insert) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    assert len(set(results)) == 1 and len(results) == 6
    assert len(repository.list_by_unit("docente-a", "u1", active_only=False, limit=10)) == 1


def test_listing_and_counting_active_requests(repository):
    now = datetime.now(timezone.utc)
    older = repository.create(make_request(key="clave-antigua", created_at=now - timedelta(minutes=5)))
    newer = repository.create(make_request(key="clave-reciente", created_at=now))
    repository.create(make_request(key="clave-otra-unidad", unit_id="u2"))
    repository.finish(older.id, RequestStatus.SUCCEEDED, None)

    listed = repository.list_by_unit("docente-a", "u1", active_only=False, limit=10)
    assert [r.id for r in listed] == [newer.id, older.id]
    assert [r.id for r in repository.list_by_unit("docente-a", "u1", active_only=True, limit=10)] == [newer.id]
    assert repository.list_by_unit("docente-a", "u1", active_only=False, limit=1)[0].id == newer.id
    assert repository.count_active("docente-a") == 2
    assert repository.count_active("docente-b") == 0


def test_the_runner_updates_progress_and_a_final_request_does_not_change(repository):
    request = repository.create(make_request())
    repository.mark_running(request.id, "boot-1")
    fragment = EvidenceFragment("frag-1", "doc-1", "apuntes.pdf", "p. 1", "Texto", 0.8, None, None)
    repository.save_evidence(request.id, EvidenceRetrieval((fragment,), None), "2026-11-10T12:00:00+00:00")
    step = replace(
        request.steps[0],
        status=StepStatus.SUCCEEDED,
        resource_ids=("rec-1",),
        rejections=({"title": "R", "reason": "Repetía otro recurso.", "kind": "repetition"},),
        generator={"description": "reglas", "usesAi": False, "fallback": True},
    )
    repository.update_step(request.id, step)

    running = repository.get("docente-a", request.id)
    assert running.status == RequestStatus.RUNNING and running.worker_boot_id == "boot-1"
    assert running.started_at and running.heartbeat_at
    assert running.evidence[0]["chunkId"] == "frag-1" and running.evidence[0]["retrievedAt"]
    assert running.steps[0].resource_ids == ("rec-1",) and running.steps[0].generator["fallback"] is True

    problem = Problem("DEADLINE_EXCEEDED", "Se agotó el tiempo.")
    repository.finish(request.id, RequestStatus.PARTIALLY_SUCCEEDED, problem)
    finished = repository.get("docente-a", request.id)
    assert finished.status == RequestStatus.PARTIALLY_SUCCEEDED and finished.finished_at
    assert finished.steps[0].status == StepStatus.SUCCEEDED
    assert finished.steps[1].status == StepStatus.FAILED and finished.steps[1].error == problem

    repository.finish(request.id, RequestStatus.FAILED, None)
    repository.mark_running(request.id, "boot-2")
    assert repository.get("docente-a", request.id) == finished


def test_the_startup_sweep_interrupts_only_stale_requests(repository):
    now = datetime.now(timezone.utc)
    stale_queued = repository.create(make_request(key="clave-en-cola", created_at=now - timedelta(minutes=10)))
    stale_running = repository.create(make_request(key="clave-sin-latido", created_at=now - timedelta(minutes=10)))
    repository.mark_running(stale_running.id, "boot-viejo")
    repository.update_step(stale_running.id, replace(stale_running.steps[0], status=StepStatus.SUCCEEDED,
                                                     resource_ids=("rec-guardado",)))
    alive = repository.create(make_request(key="clave-con-latido", created_at=now - timedelta(minutes=10)))
    repository.mark_running(alive.id, "boot-vivo")
    finished = repository.create(make_request(key="clave-terminada", created_at=now - timedelta(minutes=10)))
    repository.finish(finished.id, RequestStatus.SUCCEEDED, None)

    # El latido del pedido que corre en otro proceso es reciente; el del otro pedido quedó en el pasado.
    _set_heartbeat(repository, stale_running.id, now - timedelta(minutes=5))

    changed = repository.mark_interrupted(now - timedelta(seconds=60))

    assert changed == 2
    queued_after = repository.get("docente-a", stale_queued.id)
    running_after = repository.get("docente-a", stale_running.id)
    assert queued_after.status == running_after.status == RequestStatus.INTERRUPTED
    assert running_after.failure.code == "REQUEST_INTERRUPTED"
    # GEN-C4: lo ya generado se conserva y lo pendiente queda interrumpido.
    assert running_after.steps[0].status == StepStatus.SUCCEEDED
    assert running_after.steps[0].resource_ids == ("rec-guardado",)
    assert running_after.steps[1].status == StepStatus.INTERRUPTED
    assert repository.get("docente-a", alive.id).status == RequestStatus.RUNNING
    assert repository.get("docente-a", finished.id).status == RequestStatus.SUCCEEDED
    assert repository.mark_interrupted(now - timedelta(seconds=60)) == 0


def test_the_heartbeat_keeps_a_request_alive(repository):
    request = repository.create(make_request())
    repository.mark_running(request.id, "boot-1")
    _set_heartbeat(repository, request.id, datetime.now(timezone.utc) - timedelta(minutes=5))
    repository.heartbeat(request.id)
    assert repository.mark_interrupted(datetime.now(timezone.utc) - timedelta(seconds=60)) == 0


def _set_heartbeat(repository: SQLAlchemyGenerationRequestRepository, request_id: str, moment: datetime) -> None:
    with repository._engine.begin() as connection:  # noqa: SLF001 - solo para simular el paso del tiempo
        connection.execute(
            text("UPDATE gen_generation_requests SET heartbeat_at = :at WHERE id = :id"),
            {"at": utc_text(moment), "id": request_id},
        )


# Corrección 1 del PR #14: el ejecutor no recrea filas de un pedido que se borró.


def test_runner_writes_only_update_existing_rows_and_say_if_the_request_existed(repository):
    request = repository.create(make_request())
    fragment = EvidenceFragment("frag-1", "doc-1", "apuntes.pdf", "p. 1", "Texto", 0.8, None, None)
    step = replace(request.steps[0], status=StepStatus.SUCCEEDED, resource_ids=("rec-1",))

    assert repository.update_step(request.id, step) is True
    assert repository.save_evidence(request.id, EvidenceRetrieval((fragment,), None), "2026-11-10T12:00:00+00:00")
    assert repository.heartbeat(request.id) is True
    assert repository.finish(request.id, RequestStatus.SUCCEEDED, None) is True

    _delete_request(repository, request.id)  # el curso se borró mientras el pedido corría
    assert repository.update_step(request.id, step) is False
    assert repository.save_evidence(request.id, EvidenceRetrieval((fragment,), None), "2026-11-10T12:00:00+00:00") is False
    assert repository.heartbeat(request.id) is False
    assert repository.finish(request.id, RequestStatus.FAILED, None) is False
    with repository._engine.connect() as connection:  # noqa: SLF001
        assert connection.execute(text("SELECT COUNT(*) FROM gen_generation_steps")).scalar() == 0
        assert connection.execute(text("SELECT COUNT(*) FROM gen_generation_requests")).scalar() == 0


def test_an_unknown_step_position_is_not_inserted(repository):
    request = repository.create(make_request())
    extra = replace(request.steps[0], position=9)
    assert repository.update_step(request.id, extra) is False
    assert [s.position for s in repository.get("docente-a", request.id).steps] == [0, 1]


def _delete_request(repository: SQLAlchemyGenerationRequestRepository, request_id: str) -> None:
    """Como `delete_course`: en SQLite sin cascada se borran los pasos antes del pedido."""
    with repository._engine.begin() as connection:  # noqa: SLF001
        connection.execute(text("DELETE FROM gen_generation_steps WHERE request_id = :id"), {"id": request_id})
        connection.execute(text("DELETE FROM gen_generation_requests WHERE id = :id"), {"id": request_id})


# Corrección 2 del PR #14: el cupo de pedidos activos se comprueba y se registra de forma atómica.


def test_create_within_limit_checks_the_quota_atomically(repository):
    from platform5e.application.ports.outbound.generation_request_repository_port import ActiveRequestLimitReached

    repository.create_within_limit(make_request(key="clave-activa-1"), max_active=2)
    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def submit(key: str) -> None:
        barrier.wait()
        try:
            repository.create_within_limit(make_request(key=key), max_active=2)
            outcomes.append("created")
        except ActiveRequestLimitReached:
            outcomes.append("limit")

    threads = [threading.Thread(target=submit, args=(f"clave-simultanea-{n}",)) for n in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes) == ["created", "limit"]
    assert repository.count_active("docente-a") == 2
    # Otro docente tiene su propio cupo, y un pedido terminado no cuenta.
    repository.create_within_limit(make_request(teacher_id="docente-b", key="clave-otro-docente"), max_active=2)
    first = repository.list_by_unit("docente-a", "u1", active_only=True, limit=10)[0]
    repository.finish(first.id, RequestStatus.SUCCEEDED, None)
    repository.create_within_limit(make_request(key="clave-tras-terminar"), max_active=2)
    assert repository.count_active("docente-a") == 2


def test_create_within_limit_keeps_the_idempotency_answer(repository):
    from platform5e.application.ports.outbound.generation_request_repository_port import ActiveRequestLimitReached

    original = repository.create_within_limit(make_request(key="clave-repetida"), max_active=1)
    # Con el cupo lleno, la misma clave sigue devolviendo el pedido existente y no el error de cupo.
    with pytest.raises(IdempotencyKeyTaken) as taken:
        repository.create_within_limit(make_request(key="clave-repetida"), max_active=1)
    assert taken.value.existing.id == original.id
    with pytest.raises(ActiveRequestLimitReached):
        repository.create_within_limit(make_request(key="clave-nueva"), max_active=1)


def test_two_simultaneous_starts_with_one_active_request_accept_only_one(repository):
    """Reproduce el error: con un pedido activo, dos envíos simultáneos con claves distintas dejaban tres activos."""
    from platform5e.application.use_cases.generation.start_generation_request import (
        StartGenerationCommand,
        StartGenerationRequest,
    )
    from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
    from tests.support.generation_fakes import FakeEvidence, FakeMembership, FakeRunner

    barrier = threading.Barrier(2, timeout=10)

    class BothCheckTogether:
        """El repositorio real; los dos envíos llegan juntos a la comprobación del cupo."""

        def __getattr__(self, name: str):
            return getattr(repository, name)

        def count_active(self, teacher_id: str) -> int:
            barrier.wait()
            return repository.count_active(teacher_id)

        def create_within_limit(self, request, max_active: int):
            barrier.wait()
            return repository.create_within_limit(request, max_active)

    start = StartGenerationRequest(FakeMembership(), FakeEvidence(), BothCheckTogether(), FakeRunner())

    def command(key: str) -> StartGenerationCommand:
        return StartGenerationCommand(
            "docente-a", "u1", GenerationMode.INDIVIDUAL, key, GenerationParameters(("pregunta_detonante",))
        )

    repository.create(make_request(key="clave-ya-activa"))
    outcomes: list[str] = []

    def submit(key: str) -> None:
        try:
            start.execute(command(key))
            outcomes.append("accepted")
        except GenerationError as error:
            outcomes.append(error.code)

    threads = [threading.Thread(target=submit, args=(f"clave-envio-{n}",)) for n in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sorted(outcomes) == sorted(["accepted", GenerationErrorCode.TOO_MANY_ACTIVE_REQUESTS])
    assert repository.count_active("docente-a") == 2
