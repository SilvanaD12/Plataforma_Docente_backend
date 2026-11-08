"""
Los adaptadores traducen fallos técnicos de infraestructura antes de llegar a la capa HTTP.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from platform5e.application.services.generation.generation_service import GenerationService
from platform5e.domain.shared.errors import DuplicateRecordError, PersistenceUnavailableError
from platform5e.infrastructure.http.routers.generations import create_generations_router
from platform5e.infrastructure.persistence.repositories import (
    sqlalchemy_generation_repository as generation_repo_module,
)
from platform5e.infrastructure.persistence.repositories.sqlalchemy_account_repository import (
    SQLAlchemyAccountRepository,
)


def test_account_repository_receives_the_catalog_in_its_constructor():
    class MockCatalogProvider:
        def get_demo_catalog(self) -> dict[str, Any]:
            return {"units": [{"id": "unidad-inyectada", "title": "Prueba"}]}

        # Alias en español por compatibilidad de interfaz
        def demo_catalog(self) -> dict[str, Any]:
            return self.get_demo_catalog()

    repo = SQLAlchemyAccountRepository(MockCatalogProvider())
    repo.init_catalog("inyeccion@example.com")
    courses = repo.get_courses("inyeccion@example.com")
    assert courses[0]["units"][0]["id"] == "unidad-inyectada"


@pytest.mark.parametrize(
    "sql_error,expected_domain_error",
    [
        (SQLAlchemyError("detalle interno"), PersistenceUnavailableError),
        (IntegrityError("SQL interno", {}, Exception()), DuplicateRecordError),
    ],
)
def test_sql_error_does_not_cross_the_port(monkeypatch, sql_error, expected_domain_error):
    repo = generation_repo_module.SQLAlchemyGenerationRepository()

    def raise_db_error():
        raise sql_error

    # Intercepta el constructor de sesión del repositorio
    monkeypatch.setattr(generation_repo_module, "SessionLocal", raise_db_error)

    with pytest.raises(expected_domain_error):
        repo.save({"request": {"id": "sol-prueba"}})


def test_generation_with_database_down_keeps_503_response(monkeypatch):
    repo = generation_repo_module.SQLAlchemyGenerationRepository()

    def raise_db_error():
        raise SQLAlchemyError("no debe filtrarse a HTTP")

    monkeypatch.setattr(generation_repo_module, "SessionLocal", raise_db_error)

    app = FastAPI()
    app.include_router(create_generations_router(GenerationService(repo), account_service=None, generator_info={}))

    client = TestClient(app)
    response = client.post(
        "/api/v1/generations",
        json={"unitId": "u2", "stage": "explore", "resourceType": "guia_exploracion", "quantity": 1},
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "PERSISTENCE_UNAVAILABLE"
    assert "no debe filtrarse" not in response.text