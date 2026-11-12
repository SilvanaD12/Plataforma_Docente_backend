"""GEN-01 (T047) y CC-C9: al borrar un curso se eliminan los pedidos de generación de sus unidades y sus pasos.

La descarga registrada se conserva, y los pedidos de otro curso del mismo docente y los de otro docente no se tocan.
Se prueba en SQLite con la cascada de claves foráneas apagada (el valor por defecto) y encendida.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import URL, create_engine, event, func, select, text
from sqlalchemy.orm import sessionmaker

from platform5e.application.services.accounts.account_service import AccountService
from platform5e.domain.generation.generation_request import (
    GenerationMode,
    GenerationParameters,
    GenerationRequest,
    GenerationStep,
    RequestStatus,
    StepStatus,
    payload_hash,
)
from platform5e.domain.generation.sequence import plan_steps
from platform5e.infrastructure.persistence.repositories import (
    sqlalchemy_account_repository as accounts,
    sqlalchemy_resource_repository as resources,
)
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_request_repository import (
    GenerationRequestORM,
    GenerationStepORM,
    SQLAlchemyGenerationRequestRepository,
)

TEACHER = "docente@example.com"
OTHER_TEACHER = "otra.docente@example.com"
TYPES = ("pregunta_detonante", "explicacion")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finished_request(repository: SQLAlchemyGenerationRequestRepository, teacher_id: str, unit_id: str) -> str:
    """Guarda un pedido de dos pasos y lo deja terminado, como lo deja el ejecutor."""
    parameters = GenerationParameters(resource_types=TYPES)
    request = repository.create(
        GenerationRequest(
            id=f"gen-req-{uuid4()}",
            teacher_id=teacher_id,
            unit_id=unit_id,
            mode=GenerationMode.SEQUENCE,
            idempotency_key=f"clave-{uuid4().hex}",
            payload_hash=payload_hash(GenerationMode.SEQUENCE, unit_id, parameters),
            parameters=parameters,
            created_at=_now(),
            steps=tuple(GenerationStep.from_plan(p) for p in plan_steps("sequence", list(TYPES), 1)),
        )
    )
    repository.mark_running(request.id, "proceso-de-prueba")
    for step in request.steps:
        repository.update_step(
            request.id, replace(step, status=StepStatus.SUCCEEDED, started_at=_now(), finished_at=_now())
        )
    repository.finish(request.id, RequestStatus.SUCCEEDED, None)
    return request.id


def _course(service: AccountService, teacher_id: str, code: str) -> dict:
    return service.save_course(
        teacher_id, {"code": code, "name": f"Curso {code}", "term": "2026-II", "units": [{"title": "Unidad 1"}]}
    )


@pytest.mark.parametrize("foreign_keys", [False, True], ids=["sin-cascada", "con-cascada"])
def test_deleting_a_course_removes_its_generation_requests_and_keeps_its_download(
    tmp_path, monkeypatch, request, foreign_keys
):
    engine = create_engine(URL.create("sqlite", database=str(tmp_path / "t047.db")))
    request.addfinalizer(engine.dispose)
    if foreign_keys:
        event.listen(engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys = ON"))
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(accounts, "engine", engine)
    monkeypatch.setattr(accounts, "SessionLocal", sessions)
    monkeypatch.setattr(resources, "SessionLocal", sessions)

    service = AccountService(accounts.SQLAlchemyAccountRepository(), "", "")
    generation_requests = SQLAlchemyGenerationRequestRepository(engine)
    downloads = resources.SQLAlchemyResourceRepository()
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == int(foreign_keys)

    deleted_course = _course(service, TEACHER, "RED-301")
    kept_course = _course(service, TEACHER, "PRO-301")
    other_course = _course(service, OTHER_TEACHER, "RED-301")
    deleted_unit = deleted_course["units"][0]["id"]
    kept_unit = kept_course["units"][0]["id"]
    other_unit = other_course["units"][0]["id"]

    deleted_request = _finished_request(generation_requests, TEACHER, deleted_unit)
    kept_request = _finished_request(generation_requests, TEACHER, kept_unit)
    other_request = _finished_request(generation_requests, OTHER_TEACHER, other_unit)
    # Mismo id de unidad en los datos de otro docente: el borrado también filtra por docente.
    same_unit_request = _finished_request(generation_requests, OTHER_TEACHER, deleted_unit)
    assert generation_requests.get(TEACHER, deleted_request).status == RequestStatus.SUCCEEDED

    download = {
        "id": "descarga-t047",
        "unitId": deleted_unit,
        "format": "moodle_xml",
        "fileName": "redes.xml",
        "resourceCount": 1,
        "createdAt": "2026-11-09T12:00:00Z",
    }
    downloads.save_download(TEACHER, deleted_unit, download)

    service.delete_course(TEACHER, deleted_course["id"])

    with sessions() as session:
        remaining = set(session.scalars(select(GenerationRequestORM.id)))
        steps = dict(
            session.execute(
                select(GenerationStepORM.request_id, func.count()).group_by(GenerationStepORM.request_id)
            ).all()
        )
        stored_download = session.get(accounts.DownloadORM, download["id"])

    # No quedan pedidos ni pasos de las unidades del curso borrado.
    assert deleted_request not in remaining and deleted_request not in steps
    assert generation_requests.get(TEACHER, deleted_request) is None
    assert generation_requests.list_by_unit(TEACHER, deleted_unit, False, 50) == []
    # Los demás pedidos siguen completos, con sus pasos.
    assert remaining == {kept_request, other_request, same_unit_request}
    assert steps == {kept_request: 2, other_request: 2, same_unit_request: 2}
    assert generation_requests.get(TEACHER, kept_request).status == RequestStatus.SUCCEEDED
    assert generation_requests.get(OTHER_TEACHER, same_unit_request).status == RequestStatus.SUCCEEDED
    # La descarga sigue disponible para su docente, y solo se borró el curso indicado.
    assert stored_download is not None and stored_download.teacher_id == TEACHER
    assert downloads.get_downloads(TEACHER, deleted_unit) == [download]
    assert [c["id"] for c in service.list_courses(TEACHER)] == [kept_course["id"]]
    assert [c["id"] for c in service.list_courses(OTHER_TEACHER)] == [other_course["id"]]
