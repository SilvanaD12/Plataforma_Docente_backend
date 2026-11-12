"""REV-C13 por la ruta de Revisión: POST /api/v1/units/{unit_id}/resources/{resource_id}/regenerations responde con el
estado que corresponde al código con que Generación rechaza el pedido (PR #23 de Yan), y el recurso queda como estaba.

Usa el router real con un adaptador de regeneración falso que devuelve `failed` con el código, como
`test_persistence_errors.py` hace con la ruta de pedidos. Pedido de Silvana en la revisión del PR #28.
"""

from __future__ import annotations

import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform5e.domain.accounts.teacher_account import AccountConfigurationError
from platform5e.infrastructure.http.error_handlers import domain_error_handler
from platform5e.infrastructure.http.routers.resources import create_resources_router
from tests.unit.test_resource_regeneration import build

ROUTE = "/api/v1/units/u1/resources/viejo/regenerations"


class SignedInTeacher:
    """Lo único que la ruta usa de Cuentas: la sesión del docente."""

    def authenticate_token(self, authorization: str | None) -> str:
        return "ana"


@pytest.mark.parametrize(
    ("generation_code", "http_status"),
    [
        ("REGENERATION_ATTEMPTS_EXHAUSTED", 409),
        ("REGENERATION_TARGET_INVALID", 422),
        ("REGENERATION_PARAMETERS_MISSING", 422),
    ],
)
def test_the_regeneration_route_answers_generation_rejection_codes(generation_code, http_status):
    service, resources, _ = build(outcome="failed", failure_code=generation_code)
    before = copy.deepcopy(resources.by_id["viejo"])
    app = FastAPI()
    app.add_exception_handler(AccountConfigurationError, domain_error_handler)
    app.include_router(create_resources_router(service, SignedInTeacher(), None, None))  # type: ignore[arg-type]

    response = TestClient(app).post(ROUTE, headers={"Authorization": "Bearer token"}, json={"expectedVersion": 3})

    assert response.status_code == http_status, response.text
    error = response.json()["error"]
    assert error["code"] == generation_code and error["message"]
    old = resources.by_id["viejo"]
    assert {k: old[k] for k in ("status", "body", "version")} == {k: before[k] for k in ("status", "body", "version")}
    assert "viejo" not in resources.claims, "la reserva quedó tomada tras el rechazo"
