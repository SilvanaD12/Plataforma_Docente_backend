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
