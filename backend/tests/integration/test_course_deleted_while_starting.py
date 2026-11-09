"""T047 (caso del PR #14): el alta de un pedido y el borrado del curso se coordinan con el bloqueo por docente.

Reproduce lo que encontró la revisión: si el curso se borra después de validar la unidad y antes de guardar el pedido,
el pedido se aceptaba y su paso quedaba guardado. Ahora el repositorio vuelve a comprobar la unidad dentro del bloqueo
por docente, antes de insertar, y `delete_course` toma el mismo bloqueo en PostgreSQL.

Usa los repositorios reales de Cuentas y Generación sobre un SQLite temporal. Con
GENERATION_REPOSITORY_TEST_DATABASE_URL (solo localhost, 127.0.0.1 o ::1) usa PostgreSQL con las migraciones.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import sessionmaker

from platform5e.application.services.accounts.account_service import AccountService
from platform5e.application.use_cases.generation.start_generation_request import (
    StartGenerationCommand,
    StartGenerationRequest,
)
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_request import GenerationMode, GenerationParameters
from platform5e.infrastructure.adapters.account_unit_membership_adapter import AccountUnitMembershipAdapter
from platform5e.infrastructure.persistence.database import normalize_database_url
from platform5e.infrastructure.persistence.migration_runner import apply_database_migrations
from platform5e.infrastructure.persistence.repositories import (
    sqlalchemy_account_repository as accounts,
    sqlalchemy_generation_repository as generations,
)
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_request_repository import (
    SQLAlchemyGenerationRequestRepository,
)
from tests.integration.test_generation_request_repository import POSTGRES_URL
from tests.support.generation_fakes import FakeEvidence, FakeRunner
from tests.support.local_database import NonLocalDatabaseError, ensure_local_database_url

TEACHER = "docente@example.com"


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    if POSTGRES_URL:
        local_url, problem = normalize_database_url(POSTGRES_URL), None
        try:
            ensure_local_database_url(local_url)  # una base remota nunca se vacía
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
        bind = create_engine(f"sqlite:///{tmp_path / 'alta-y-borrado.db'}", connect_args={"check_same_thread": False})
    sessions = sessionmaker(bind=bind)
    monkeypatch.setattr(accounts, "engine", bind)
    monkeypatch.setattr(accounts, "SessionLocal", sessions)
    monkeypatch.setattr(generations, "engine", bind)
    yield bind
    bind.dispose()


class Setup:
    def __init__(self, engine: Engine, repository_class: type[SQLAlchemyGenerationRequestRepository]) -> None:
        self.engine = engine
        account_repository = accounts.SQLAlchemyAccountRepository(generations.SQLAlchemyGenerationRepository())
        self.service = AccountService(account_repository, "", "")
        self.requests = repository_class(engine)
        self.membership = AccountUnitMembershipAdapter(account_repository)
        self.runner = FakeRunner()
        self.course = self.service.save_course(
            TEACHER, {"code": "RED-301", "name": "Redes", "term": "2026-II", "units": [{"title": "Protocolos"}]}
        )
        self.unit_id = self.course["units"][0]["id"]

    def start(self, key: str = "clave-alta-y-borrado"):
        return StartGenerationRequest(self.membership, FakeEvidence(), self.requests, self.runner).execute(
            StartGenerationCommand(
                TEACHER,
                self.unit_id,
                GenerationMode.SEQUENCE,
                key,
                GenerationParameters(resource_types=("pregunta_detonante", "explicacion")),
            )
        )

    def delete_course(self) -> None:
        self.service.delete_course(TEACHER, self.course["id"])

    def stored(self) -> tuple[int, int]:
        """Pedidos de la unidad y pasos en la base, contados sin pasar por el repositorio."""
        with self.engine.connect() as connection:
            requests = connection.execute(
                text("SELECT COUNT(*) FROM gen_generation_requests WHERE unit_id = :unit"), {"unit": self.unit_id}
            ).scalar()
            steps = connection.execute(text("SELECT COUNT(*) FROM gen_generation_steps")).scalar()
        return requests, steps


class DeletesTheCourseBeforeSaving(SQLAlchemyGenerationRequestRepository):
    """Justo antes de guardar (la unidad ya se validó), el docente borra el curso en otra transacción."""

    before_saving: Callable[[], None] = staticmethod(lambda: None)

    def create_within_limit(self, request: Any, max_active: int, *args: Any, **kwargs: Any) -> Any:
        self.before_saving()
        return super().create_within_limit(request, max_active, *args, **kwargs)


def test_a_course_deleted_after_validating_the_unit_rejects_the_request(engine):
    """Orden exacto del caso: validar la unidad → borrar el curso → guardar el pedido. Responde UNIT_NOT_FOUND."""
    setup = Setup(engine, DeletesTheCourseBeforeSaving)
    setup.requests.before_saving = setup.delete_course
    assert setup.membership.get_unit_context(TEACHER, setup.unit_id) is not None

    with pytest.raises(GenerationError) as rejected:
        setup.start()

    assert rejected.value.code == GenerationErrorCode.UNIT_NOT_FOUND
    assert setup.stored() == (0, 0)  # ni pedido ni pasos
    assert setup.requests.find_by_key(TEACHER, "clave-alta-y-borrado") is None
    assert setup.runner.submitted == []


def test_a_request_saved_before_the_course_is_deleted_is_removed_with_it(engine):
    """Orden inverso: el pedido se guarda y luego se borra el curso. T047 elimina el pedido y sus pasos."""
    setup = Setup(engine, SQLAlchemyGenerationRequestRepository)
    started = setup.start()
    assert started.created and setup.stored() == (1, 2)

    setup.delete_course()

    assert setup.stored() == (0, 0)
    assert setup.requests.get(TEACHER, started.request.id) is None


def test_deleting_the_course_waits_for_a_request_being_saved_and_then_removes_it(engine):
    """`delete_course` espera mientras el alta tiene el bloqueo del docente; al seguir, ve el pedido ya guardado y lo
    elimina (T047). En PostgreSQL espera el `pg_advisory_xact_lock`; sin él, el borrado terminaba mientras el alta seguía
    abierta. En SQLite espera la transacción de escritura (`BEGIN IMMEDIATE`) del alta."""
    setup = Setup(engine, SQLAlchemyGenerationRequestRepository)
    inside_lock, release = threading.Event(), threading.Event()
    real_membership = setup.membership

    class PausesInsideTheLock:
        calls = 0

        def get_unit_context(self, teacher_id: str, unit_id: str):
            self.calls += 1
            if self.calls == 2:  # la segunda comprobación es la del repositorio, con el bloqueo tomado
                inside_lock.set()
                assert release.wait(10)
            return real_membership.get_unit_context(teacher_id, unit_id)

    setup.membership = PausesInsideTheLock()  # type: ignore[assignment]
    results: dict[str, Any] = {}
    starting = threading.Thread(target=lambda: results.setdefault("start", setup.start()))
    starting.start()
    assert inside_lock.wait(10)

    deleted = threading.Event()
    deleting = threading.Thread(target=lambda: (setup.delete_course(), deleted.set()))
    deleting.start()
    time.sleep(0.5)
    assert not deleted.is_set(), "delete_course no esperó el bloqueo del docente"

    release.set()
    starting.join(10)
    deleting.join(10)
    assert deleted.is_set() and results["start"].created
    assert setup.stored() == (0, 0)
