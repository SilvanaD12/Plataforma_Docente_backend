"""
Los adaptadores traducen fallos técnicos de infraestructura antes de llegar a la capa HTTP.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from platform5e.application.use_cases.generation.get_generation_request import GetGenerationRequest
from platform5e.application.use_cases.generation.start_generation_request import StartGenerationRequest
from platform5e.domain.shared.errors import DuplicateRecordError, PersistenceUnavailableError
from platform5e.infrastructure.http.error_handlers import persistence_unavailable_handler
from platform5e.application.use_cases.generation.get_generation_evidence import GetGenerationEvidence
from platform5e.infrastructure.http.routers.generation_requests import create_generation_requests_router
from platform5e.infrastructure.persistence.repositories import (
    sqlalchemy_account_repository as account_repo_module,
)
from platform5e.infrastructure.persistence.repositories.sqlalchemy_account_repository import (
    SQLAlchemyAccountRepository,
)
from tests.support.generation_fakes import (
    FakeEvidence,
    FakeMembership,
    FakeReviewRepository,
    FakeRunner,
    sqlite_repository,
)


def test_account_repository_loads_the_demo_course_once():
    repo = SQLAlchemyAccountRepository()
    teacher_id = "catalogo-demo@example.com"

    repo.init_catalog(teacher_id)
    repo.init_catalog(teacher_id)

    courses = repo.get_courses(teacher_id)
    assert len(courses) == 1
    assert courses[0]["code"] == "ICSI-205"
    assert [unit["id"] for unit in courses[0]["units"]] == ["u2", "u3"]


@pytest.mark.parametrize(
    "sql_error,expected_domain_error",
    [
        (SQLAlchemyError("detalle interno"), PersistenceUnavailableError),
        (IntegrityError("SQL interno", {}, Exception()), DuplicateRecordError),
    ],
)
def test_sql_error_does_not_cross_the_port(monkeypatch, sql_error, expected_domain_error):
    repo = SQLAlchemyAccountRepository()

    def raise_db_error():
        raise sql_error

    # Intercepta el constructor de sesión del repositorio
    monkeypatch.setattr(account_repo_module, "SessionLocal", raise_db_error)

    # T046: el historial de generaciones es de Cuentas; su lectura pasa por la misma traducción.
    with pytest.raises(expected_domain_error):
        repo.get_generation("sol-prueba")


class SignedInTeacher:
    """Lo único que la ruta de pedidos usa de Cuentas: la sesión del docente."""

    def authenticate_token(self, authorization: str | None) -> str:
        return "docente-a"


def test_generation_with_database_down_keeps_503_response(tmp_path):
    """POST /api/v1/generation-requests con la base caída responde 503 sin filtrar el detalle (antes por la ruta
    síncrona retirada en T046)."""
    requests = sqlite_repository(tmp_path)

    def raise_db_error():
        raise SQLAlchemyError("no debe filtrarse a HTTP")

    requests._sessions = raise_db_error
    membership, evidence = FakeMembership(), FakeEvidence()
    app = FastAPI()
    app.add_exception_handler(PersistenceUnavailableError, persistence_unavailable_handler)
    app.include_router(
        create_generation_requests_router(
            StartGenerationRequest(membership, evidence, requests, FakeRunner()),
            GetGenerationRequest(requests, membership, FakeReviewRepository()),
            SignedInTeacher(),  # type: ignore[arg-type]
            {},
            GetGenerationEvidence(requests),
        )
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/generation-requests",
        headers={"Authorization": "Bearer token", "Idempotency-Key": "clave-base-caida"},
        json={"mode": "individual", "unitId": "u1", "resourceTypes": ["guia_exploracion"], "quantity": 1},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "PERSISTENCE_UNAVAILABLE"
    assert "no debe filtrarse" not in response.text
