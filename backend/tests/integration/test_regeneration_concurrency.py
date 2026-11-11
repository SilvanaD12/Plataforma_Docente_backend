"""REV-C12 · Dos solicitudes simultáneas de regenerar el mismo recurso desde la misma versión generan un solo recurso.

Usa el repositorio SQLAlchemy real (SQLite) y dos hilos. Para que la carrera sea determinista, las dos solicitudes
esperan en una barrera justo después de leer el recurso: las dos lo leen sin pedido registrado antes de que alguna
reserve el pedido, como en el caso que reprodujo Silvana en el PR #13.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import sessionmaker

from platform5e.application.ports.outbound.resource_regeneration_port import RegenerationStatus
from platform5e.application.services.accounts.account_service import AccountService
from platform5e.application.services.review.resource_review_service import ResourceReviewService
from platform5e.domain.accounts.teacher_account import AccountConfigurationError
from platform5e.infrastructure.persistence.repositories import (
    sqlalchemy_account_repository as accounts,
    sqlalchemy_generation_repository as generations,
    sqlalchemy_resource_repository as resources,
)

TEACHER = "docente@example.com"
EVIDENCE = "El protocolo TCP confirma la entrega de los datos al receptor."
PARAMS = {"resourceType": "explicacion", "stage": "explain", "outcomeId": None, "difficulty": "intermedia",
          "optionCount": 4, "instructions": "", "audience": "", "competency": "", "modalities": ["Textual"],
          "topK": 8, "evidenceThreshold": 0.6}


def explanation(resource_id: str, unit_id: str) -> dict[str, Any]:
    return {
        "id": resource_id, "unitId": unit_id, "type": "explicacion", "format": "text", "title": "TCP",
        "body": "El protocolo TCP confirma la entrega de los datos.", "options": None, "structure": None,
        "citations": [{"claim": "El protocolo TCP confirma la entrega de los datos.", "fragmentIds": ["f1"]}],
        "evidence": [{"id": "f1", "text": EVIDENCE, "location": "p. 1", "documentId": "d1", "documentName": "redes.pdf"}],
        "status": "pendiente", "edited": False, "discardReason": None, "createdAt": "2026-11-09T10:00:00+00:00",
        "decidedAt": None, "params": dict(PARAMS),
    }


class RacingRepository:
    """El repositorio real; la primera lectura del recurso en cada hilo espera a que el otro hilo también lo lea."""

    def __init__(self, inner: resources.SQLAlchemyResourceRepository, resource_id: str) -> None:
        self._inner, self._resource_id = inner, resource_id
        self._barrier = threading.Barrier(2, timeout=10)
        self._seen = threading.local()

    def get_resource_by_id(self, teacher_id: str, resource_id: str) -> dict[str, Any] | None:
        resource = self._inner.get_resource_by_id(teacher_id, resource_id)
        if resource_id == self._resource_id and not getattr(self._seen, "done", False):
            self._seen.done = True
            self._barrier.wait()
        return resource

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class SlowGeneration:
    """Doble del puerto de regeneración: tarda un poco y guarda un recurso nuevo, como lo hace Generación."""

    def __init__(self, repository: resources.SQLAlchemyResourceRepository) -> None:
        self._repository = repository
        self._lock = threading.Lock()
        self.calls = 0

    def request_regeneration(self, teacher_id, resource_id, resource_version, params) -> RegenerationStatus:
        with self._lock:
            self.calls += 1
        time.sleep(0.2)
        new_id = f"nuevo-{uuid4()}"
        self._repository.save_resources(teacher_id, params["unitId"], [explanation(new_id, params["unitId"])])
        return RegenerationStatus(f"req-{new_id}", "succeeded", (new_id,), None)

    def get_regeneration(self, teacher_id, request_id) -> RegenerationStatus | None:
        return None


def test_two_simultaneous_regenerations_from_the_same_version_create_one_resource(tmp_path, monkeypatch, request):
    engine = create_engine(URL.create("sqlite", database=str(tmp_path / "regeneracion.db")))
    request.addfinalizer(engine.dispose)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(accounts, "engine", engine)
    monkeypatch.setattr(accounts, "SessionLocal", sessions)
    monkeypatch.setattr(generations, "engine", engine)
    monkeypatch.setattr(resources, "engine", engine)
    monkeypatch.setattr(resources, "SessionLocal", sessions)

    account_repository = accounts.SQLAlchemyAccountRepository(generations.SQLAlchemyGenerationRepository())
    course = AccountService(account_repository, "", "").save_course(
        TEACHER, {"code": "RED-301", "name": "Redes", "term": "2026-II", "units": [{"title": "Transporte"}]}
    )
    unit_id = course["units"][0]["id"]
    repository = resources.SQLAlchemyResourceRepository()
    repository.save_resources(TEACHER, unit_id, [explanation("viejo", unit_id)])
    # La primera lectura verifica el recurso antiguo y lo guarda sin cambiar la versión (D7); la carrera va después.
    ResourceReviewService(account_repository, repository).list_resources(TEACHER, unit_id)
    version = repository.get_resource_by_id(TEACHER, "viejo")["version"]

    generation = SlowGeneration(repository)
    service = ResourceReviewService(account_repository, RacingRepository(repository, "viejo"), generation)
    results: list[Any] = []

    def regenerate() -> None:
        try:
            results.append(service.regenerate_resource(TEACHER, unit_id, "viejo", version))
        except AccountConfigurationError as error:
            results.append(error)

    threads = [threading.Thread(target=regenerate) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert len(results) == 2
    assert generation.calls == 1, "las dos solicitudes pidieron a Generación un recurso nuevo"
    new_resources = [r for r in repository.get_resources_by_unit(TEACHER, unit_id) if r["id"] != "viejo"]
    assert len(new_resources) == 1
    statuses = sorted(r["status"] for r in results if isinstance(r, dict))
    assert statuses in (["running", "succeeded"], ["succeeded", "succeeded"])



class BackgroundGeneration:
    """Doble del adaptador en segundo plano: el pedido queda `running`; al consultarlo, las dos consultas esperan en una
    barrera y las dos ven `succeeded`, como en el caso que reprodujo Silvana en el PR #13."""

    def __init__(self, new_id: str) -> None:
        self._new_id = new_id
        self._barrier = threading.Barrier(2, timeout=10)

    def request_regeneration(self, teacher_id, resource_id, resource_version, params) -> RegenerationStatus:
        return RegenerationStatus("gen-req-1", "running")

    def get_regeneration(self, teacher_id, request_id) -> RegenerationStatus | None:
        self._barrier.wait()
        return RegenerationStatus(request_id, "succeeded", (self._new_id,), None)


def test_two_overlapping_status_queries_keep_the_discarded_result(tmp_path, monkeypatch, request):
    engine = create_engine(URL.create("sqlite", database=str(tmp_path / "estado.db")))
    request.addfinalizer(engine.dispose)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(accounts, "engine", engine)
    monkeypatch.setattr(accounts, "SessionLocal", sessions)
    monkeypatch.setattr(generations, "engine", engine)
    monkeypatch.setattr(resources, "engine", engine)
    monkeypatch.setattr(resources, "SessionLocal", sessions)

    account_repository = accounts.SQLAlchemyAccountRepository(generations.SQLAlchemyGenerationRepository())
    course = AccountService(account_repository, "", "").save_course(
        TEACHER, {"code": "RED-301", "name": "Redes", "term": "2026-II", "units": [{"title": "Transporte"}]}
    )
    unit_id = course["units"][0]["id"]
    repository = resources.SQLAlchemyResourceRepository()
    repository.save_resources(TEACHER, unit_id, [explanation("viejo", unit_id)])
    service = ResourceReviewService(account_repository, repository, BackgroundGeneration("nuevo"))
    service.list_resources(TEACHER, unit_id)
    version = repository.get_resource_by_id(TEACHER, "viejo")["version"]
    assert service.regenerate_resource(TEACHER, unit_id, "viejo", version)["status"] == "running"
    repository.save_resources(TEACHER, unit_id, [explanation("nuevo", unit_id)])  # Generación guardó el nuevo

    results: list[Any] = []

    def query() -> None:
        results.append(service.get_regeneration_status(TEACHER, unit_id, "viejo"))

    threads = [threading.Thread(target=query) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert [r["previousDiscarded"] for r in results] == [True, True]
    old = repository.get_resource_by_id(TEACHER, "viejo")
    assert old["status"] == "descartado" and old["regeneration"]["previousDiscarded"] is True


class LateGeneration:
    """Doble del adaptador en segundo plano: cada pedido queda `running`. La primera consulta del primer pedido espera
    a Generación; mientras tanto ese pedido falla y el docente lo pide otra vez. Después llega la respuesta tardía."""

    def __init__(self, late_status: str) -> None:
        self.late_status = late_status
        self.requests = 0
        self.while_waiting = lambda: None
        self._waiting = True

    def request_regeneration(self, teacher_id, resource_id, resource_version, params) -> RegenerationStatus:
        self.requests += 1
        return RegenerationStatus(f"gen-req-{self.requests}", "running")

    def get_regeneration(self, teacher_id, request_id) -> RegenerationStatus | None:
        if self._waiting:
            self._waiting = False
            self.while_waiting()
            new_ids = ("nuevo-tardio",) if self.late_status == "succeeded" else ()
            return RegenerationStatus(request_id, self.late_status, new_ids, "Respuesta tardía.")  # type: ignore[arg-type]
        return RegenerationStatus(request_id, "failed", (), "Generación no respondió a tiempo.")


@pytest.mark.parametrize("late_status", ["failed", "succeeded"])
def test_a_late_answer_of_an_old_attempt_leaves_the_new_attempt_intact(tmp_path, monkeypatch, request, late_status):
    """Revisión de Silvana en el PR #17 de Yan, con el repositorio real: la respuesta tardía del primer intento no
    cambia el registro, la reserva ni el recurso del intento nuevo, que parte de la misma versión."""
    engine = create_engine(URL.create("sqlite", database=str(tmp_path / "tardia.db")))
    request.addfinalizer(engine.dispose)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(accounts, "engine", engine)
    monkeypatch.setattr(accounts, "SessionLocal", sessions)
    monkeypatch.setattr(generations, "engine", engine)
    monkeypatch.setattr(resources, "engine", engine)
    monkeypatch.setattr(resources, "SessionLocal", sessions)

    account_repository = accounts.SQLAlchemyAccountRepository(generations.SQLAlchemyGenerationRepository())
    course = AccountService(account_repository, "", "").save_course(
        TEACHER, {"code": "RED-301", "name": "Redes", "term": "2026-II", "units": [{"title": "Transporte"}]}
    )
    unit_id = course["units"][0]["id"]
    repository = resources.SQLAlchemyResourceRepository()
    repository.save_resources(TEACHER, unit_id, [explanation("viejo", unit_id)])
    generation = LateGeneration(late_status)
    service = ResourceReviewService(account_repository, repository, generation)
    service.list_resources(TEACHER, unit_id)
    version = repository.get_resource_by_id(TEACHER, "viejo")["version"]
    assert service.regenerate_resource(TEACHER, unit_id, "viejo", version)["status"] == "running"
    if late_status == "succeeded":
        repository.save_resources(TEACHER, unit_id, [explanation("nuevo-tardio", unit_id)])

    def fail_and_retry() -> None:
        assert service.get_regeneration_status(TEACHER, unit_id, "viejo")["status"] == "failed"
        assert service.regenerate_resource(TEACHER, unit_id, "viejo", version)["status"] == "running"

    generation.while_waiting = fail_and_retry
    answer = service.get_regeneration_status(TEACHER, unit_id, "viejo")

    old = repository.get_resource_by_id(TEACHER, "viejo")
    assert old["regeneration"]["requestId"] == "gen-req-2" and old["regeneration"]["status"] == "running"
    assert old["status"] == "pendiente" and old["version"] == version, "la respuesta vieja descartó el recurso"
    assert answer["status"] == "running"
    # La reserva del intento nuevo sigue tomada: pedirlo otra vez desde la misma versión no crea otro pedido.
    assert service.regenerate_resource(TEACHER, unit_id, "viejo", version)["status"] == "running"
    assert generation.requests == 2, "la respuesta vieja liberó la reserva del intento nuevo"


class RunningThenFailedGeneration:
    """Doble del adaptador en segundo plano: el pedido sigue `running` hasta que la prueba lo marca `failed`."""

    def __init__(self) -> None:
        self.requests = 0
        self.failed: set[str] = set()

    def request_regeneration(self, teacher_id, resource_id, resource_version, params) -> RegenerationStatus:
        self.requests += 1
        return RegenerationStatus(f"gen-req-{self.requests}", "running")

    def get_regeneration(self, teacher_id, request_id) -> RegenerationStatus | None:
        if request_id in self.failed:
            return RegenerationStatus(request_id, "failed", (), "Generación no respondió a tiempo.")
        return RegenerationStatus(request_id, "running")


class FailBeforeRunningWrite:
    """El repositorio real; justo antes de la primera escritura de `running`, ejecuta `meanwhile` (otra consulta)."""

    def __init__(self, inner: resources.SQLAlchemyResourceRepository) -> None:
        self._inner = inner
        self.meanwhile = lambda: None
        self._done = False

    def save_resource_if_attempt(self, teacher_id, unit_id, resource, expected_version, attempt_id, increment=False):
        if not self._done and resource["regeneration"]["status"] == "running":
            self._done = True
            self.meanwhile()
        return self._inner.save_resource_if_attempt(teacher_id, unit_id, resource, expected_version, attempt_id, increment)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def test_a_running_write_does_not_overwrite_the_same_attempt_once_it_failed(tmp_path, monkeypatch, request):
    """Revisión de Silvana en el PR #17 de Yan, con el repositorio real: una consulta lee el intento en curso; antes de
    que escriba `running`, otra consulta del mismo intento guarda `failed` y libera la reserva. `failed` se conserva y
    el pedido siguiente crea un intento nuevo."""
    engine = create_engine(URL.create("sqlite", database=str(tmp_path / "terminado.db")))
    request.addfinalizer(engine.dispose)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(accounts, "engine", engine)
    monkeypatch.setattr(accounts, "SessionLocal", sessions)
    monkeypatch.setattr(generations, "engine", engine)
    monkeypatch.setattr(resources, "engine", engine)
    monkeypatch.setattr(resources, "SessionLocal", sessions)

    account_repository = accounts.SQLAlchemyAccountRepository(generations.SQLAlchemyGenerationRepository())
    course = AccountService(account_repository, "", "").save_course(
        TEACHER, {"code": "RED-301", "name": "Redes", "term": "2026-II", "units": [{"title": "Transporte"}]}
    )
    unit_id = course["units"][0]["id"]
    repository = resources.SQLAlchemyResourceRepository()
    repository.save_resources(TEACHER, unit_id, [explanation("viejo", unit_id)])
    generation = RunningThenFailedGeneration()
    service = ResourceReviewService(account_repository, repository, generation)
    service.list_resources(TEACHER, unit_id)
    version = repository.get_resource_by_id(TEACHER, "viejo")["version"]
    assert service.regenerate_resource(TEACHER, unit_id, "viejo", version)["status"] == "running"

    racing = FailBeforeRunningWrite(repository)
    racing_service = ResourceReviewService(account_repository, racing, generation)
    inner: list[dict[str, Any]] = []

    def fail_meanwhile() -> None:
        generation.failed.add("gen-req-1")
        inner.append(service.get_regeneration_status(TEACHER, unit_id, "viejo"))

    racing.meanwhile = fail_meanwhile
    answer = racing_service.get_regeneration_status(TEACHER, unit_id, "viejo")

    assert inner[0]["status"] == "failed"
    stored = repository.get_resource_by_id(TEACHER, "viejo")["regeneration"]
    assert stored["status"] == "failed", "la escritura vieja pisó `failed`"
    assert answer["status"] == "failed"
    assert service.regenerate_resource(TEACHER, unit_id, "viejo", version)["status"] == "running"
    assert generation.requests == 2, "el pedido siguiente respondió «en curso» sin crear uno nuevo"
