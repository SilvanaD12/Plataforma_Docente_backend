"""Corrección 1 del PR #14: borrar un curso mientras se genera uno de sus pedidos.

Reproduce lo que encontró la revisión: el pedido se eliminaba, pero el ejecutor volvía a guardar un recurso y dejaba un
paso huérfano en SQLite. Usa los repositorios reales de Cuentas, Revisión y Generación sobre un SQLite temporal (con
la cascada de claves foráneas apagada, como en desarrollo) y un generador falso que se detiene en el primer paso.
"""

from __future__ import annotations

import threading
from typing import Any

from sqlalchemy import URL, create_engine, text
from sqlalchemy.orm import sessionmaker

from platform5e.application.services.accounts.account_service import AccountService
from platform5e.application.use_cases.generation.run_generation_request import RunGenerationRequest
from platform5e.application.use_cases.generation.start_generation_request import (
    StartGenerationCommand,
    StartGenerationRequest,
)
from platform5e.domain.generation.generation_request import GenerationMode, GenerationParameters
from platform5e.infrastructure.adapters.account_unit_membership_adapter import AccountUnitMembershipAdapter
from platform5e.infrastructure.adapters.review_verification_adapter import ReviewVerificationAdapter
from platform5e.infrastructure.persistence.repositories import (
    sqlalchemy_account_repository as accounts,
    sqlalchemy_resource_repository as resources,
)
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_request_repository import (
    SQLAlchemyGenerationRequestRepository,
)
from tests.support.generation_fakes import FakeEvidence, FakeRunner
from tests.unit.test_sequence_orchestrator import StageAwareGenerator

TEACHER = "docente@example.com"


class PausingGenerator(StageAwareGenerator):
    """Redacta como el generador falso de la secuencia, pero en el primer paso espera a que la prueba lo libere."""

    def __init__(self) -> None:
        super().__init__()
        self.drafting = threading.Event()
        self.release = threading.Event()

    def generate(self, context: dict[str, Any]) -> dict[str, Any]:
        if not self.drafting.is_set():
            self.drafting.set()
            assert self.release.wait(10), "la prueba no liberó el generador"
        return super().generate(context)


def test_deleting_the_course_while_a_request_runs_leaves_nothing_of_that_unit(tmp_path, monkeypatch, request):
    engine = create_engine(
        URL.create("sqlite", database=str(tmp_path / "curso-borrado.db")), connect_args={"check_same_thread": False}
    )
    request.addfinalizer(engine.dispose)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(accounts, "engine", engine)
    monkeypatch.setattr(accounts, "SessionLocal", sessions)
    monkeypatch.setattr(resources, "SessionLocal", sessions)

    account_repository = accounts.SQLAlchemyAccountRepository()
    service = AccountService(account_repository, "", "")
    review_repository = resources.SQLAlchemyResourceRepository()
    generation_requests = SQLAlchemyGenerationRequestRepository(engine)
    membership = AccountUnitMembershipAdapter(account_repository)
    evidence = FakeEvidence()
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 0

    course = service.save_course(
        TEACHER, {"code": "RED-301", "name": "Redes", "term": "2026-II", "units": [{"title": "Protocolos"}]}
    )
    unit_id = course["units"][0]["id"]
    started = StartGenerationRequest(membership, evidence, generation_requests, FakeRunner()).execute(
        StartGenerationCommand(
            TEACHER,
            unit_id,
            GenerationMode.SEQUENCE,
            "clave-curso-borrado",
            GenerationParameters(resource_types=("pregunta_detonante", "explicacion"), option_count=3),
        )
    ).request

    generator = PausingGenerator()
    run = RunGenerationRequest(
        generation_requests,
        membership,
        evidence,
        review_repository,
        ReviewVerificationAdapter(),
        generator,
        heartbeat_seconds=0,
    )
    worker = threading.Thread(target=run.execute, args=(started.id,), name="generation-test")
    worker.start()
    assert generator.drafting.wait(10), "el pedido no llegó a redactar el primer paso"

    service.delete_course(TEACHER, course["id"])  # el docente borra el curso mientras se genera
    generator.release.set()
    worker.join(timeout=30)
    assert not worker.is_alive()

    with engine.connect() as connection:
        count = lambda sql: connection.execute(text(sql), {"unit": unit_id, "id": started.id}).scalar()  # noqa: E731
        assert count("SELECT COUNT(*) FROM gen_generation_requests WHERE unit_id = :unit") == 0
        assert count("SELECT COUNT(*) FROM gen_generation_steps WHERE request_id = :id") == 0
        assert count("SELECT COUNT(*) FROM ep002_recursos WHERE unidad = :unit") == 0
    assert review_repository.get_resources_by_unit(TEACHER, unit_id) == []
