"""GEN-01 (T024): contrato HTTP del pedido de generación de punta a punta, con el servidor real.

Casos GEN-C1, GEN-C4, GEN-C5 y GEN-C6, y V10 (aislamiento entre dos docentes).
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import httpx
import pytest

from tests.e2e.test_sequence_api import _unit_with_material, _wait_until_final

TEACHER_A = {"name": "Rosa Quispe", "email": "rosa.quispe@correo.pe", "password": "clave-segura-3"}
TEACHER_B = {"name": "Mario Salas", "email": "mario.salas@correo.pe", "password": "clave-segura-4"}
ITEM_REQUEST = {"mode": "individual", "resourceTypes": ["item_opcion_multiple"], "quantity": 1, "optionCount": 4}


def _session(api: httpx.Client, account: dict) -> dict[str, str]:
    return {"Authorization": "Bearer " + api.post("/api/v1/accounts", json=account).json()["token"]}


def _start(api: httpx.Client, headers: dict[str, str], body: dict, key: str | None = None) -> httpx.Response:
    return api.post(
        "/api/v1/generation-requests", headers={**headers, "Idempotency-Key": key or str(uuid4())}, json=body
    )


def _unit_resources(api: httpx.Client, headers: dict[str, str], unit_id: str) -> list[dict]:
    return api.get(f"/api/v1/units/{unit_id}/resources", headers=headers).json()


def test_an_individual_request_is_created_and_finishes(server: str):
    """GEN-C1: el recurso pasa a revisión y el pedido termina con el estado que informa el servidor."""
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        response = _start(api, headers, {**ITEM_REQUEST, "unitId": unit["id"]})

        assert response.status_code == 202, response.text
        accepted = response.json()
        assert response.headers["Location"] == f"/api/v1/generation-requests/{accepted['id']}"
        assert accepted["status"] in {"queued", "running", "succeeded"} and accepted["mode"] == "individual"
        assert [s["stage"] for s in accepted["steps"]] == ["evaluate"]

        finished = _wait_until_final(api, headers, accepted["id"])
        [step] = finished["steps"]
        assert finished["status"] == "succeeded" and step["status"] == "succeeded"
        assert step["generator"]["fallback"] is False and step["startedAt"] and step["finishedAt"]
        assert [r["id"] for r in step["resources"]] == step["resourceIds"]
        [resource] = [r for r in _unit_resources(api, headers, unit["id"]) if r["id"] in step["resourceIds"]]
        assert resource["requestId"] == finished["id"] and resource["status"] == "pendiente"


def test_the_same_key_returns_the_same_request_and_other_content_conflicts(server: str):
    """GEN-C4 y GEN-C5: reenviar no duplica recursos; la clave con otro contenido responde 409."""
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        body, key = {**ITEM_REQUEST, "unitId": unit["id"]}, str(uuid4())

        first = _start(api, headers, body, key)
        assert first.status_code == 202, first.text
        _wait_until_final(api, headers, first.json()["id"])
        resources_before = len(_unit_resources(api, headers, unit["id"]))

        again = _start(api, headers, body, key)
        assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
        assert "Location" not in again.headers
        assert len(_unit_resources(api, headers, unit["id"])) == resources_before

        conflict = _start(api, headers, {**body, "quantity": 2}, key)
        assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
        other_mode = _start(api, headers, {**body, "mode": "sequence"}, key)
        assert other_mode.status_code == 409


def test_the_idempotency_key_is_required_and_validated(server: str):
    with httpx.Client(base_url=server, timeout=30) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        body = {**ITEM_REQUEST, "unitId": unit["id"]}

        missing = api.post("/api/v1/generation-requests", headers=headers, json=body)
        assert missing.status_code == 400 and missing.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
        malformed = _start(api, headers, body, key="clave con espacios")
        assert malformed.status_code == 422 and malformed.json()["error"]["code"] == "INVALID_PARAMETERS"
        assert api.post("/api/v1/generation-requests", json=body).status_code == 401


def test_another_teacher_cannot_see_the_request_or_use_the_unit(server: str):
    """GEN-C5 y V10: la consulta ajena y la unidad ajena responden igual que si no existieran."""
    with httpx.Client(base_url=server, timeout=60) as api:
        owner = _session(api, TEACHER_A)
        unit = _unit_with_material(api, owner)
        request_id = _start(api, owner, {**ITEM_REQUEST, "unitId": unit["id"]}).json()["id"]
        _wait_until_final(api, owner, request_id)

        intruder = _session(api, TEACHER_B)
        foreign = api.get(f"/api/v1/generation-requests/{request_id}", headers=intruder)
        missing = api.get("/api/v1/generation-requests/gen-req-no-existe", headers=intruder)
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json() and foreign.json()["error"]["code"] == "GENERATION_REQUEST_NOT_FOUND"

        foreign_unit = _start(api, intruder, {**ITEM_REQUEST, "unitId": unit["id"]})
        missing_unit = _start(api, intruder, {**ITEM_REQUEST, "unitId": "unidad-que-no-existe"})
        assert foreign_unit.status_code == missing_unit.status_code == 404
        assert foreign_unit.json() == missing_unit.json() and foreign_unit.json()["error"]["code"] == "UNIT_NOT_FOUND"
        listed = api.get("/api/v1/generation-requests", headers=intruder, params={"unitId": unit["id"]})
        assert listed.status_code == 404


def test_a_unit_without_processed_material_is_rejected_without_creating_a_request(server: str):
    """GEN-C6."""
    with httpx.Client(base_url=server, timeout=30) as api:
        headers = _session(api, TEACHER_A)
        course = api.post(
            "/api/v1/courses",
            headers=headers,
            json={"code": "BD-101", "name": "Bases de datos", "term": "2026-II", "units": [{"title": "SQL"}]},
        ).json()
        unit_id = course["units"][0]["id"]

        response = _start(api, headers, {**ITEM_REQUEST, "unitId": unit_id})
        assert response.status_code == 400 and response.json()["error"]["code"] == "NO_PROCESSED_MATERIAL"
        assert api.get("/api/v1/generation-requests", headers=headers, params={"unitId": unit_id}).json() == []


@pytest.fixture
def single_worker_server(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> Iterator[str]:
    """Servidor con un solo hilo de generación: los pedidos siguientes esperan en cola y cuentan como activos."""
    monkeypatch.setenv("GENERATION_MAX_WORKERS", "1")
    yield request.getfixturevalue("server")


def test_a_third_active_request_gets_429_with_retry_after(single_worker_server: str):
    """Research R4: dos pedidos activos por docente. Se envían seguidos; con un solo hilo, los primeros siguen activos."""
    with httpx.Client(base_url=single_worker_server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        all_types = [
            "pregunta_detonante", "sondeo_diagnostico", "guia_exploracion", "caso_indagacion",
            "explicacion", "glosario", "ejercicio_aplicacion", "item_opcion_multiple",
        ]
        big = {"mode": "sequence", "unitId": unit["id"], "resourceTypes": all_types, "quantity": 5}

        responses = [_start(api, headers, big) for _ in range(4)]
        codes = [r.status_code for r in responses]
        assert codes[:2] == [202, 202], [r.text for r in responses]
        limited = [r for r in responses if r.status_code == 429]
        assert limited, f"Ningún pedido llegó al límite: {codes}"
        assert limited[0].json()["error"]["code"] == "TOO_MANY_ACTIVE_REQUESTS"
        assert int(limited[0].headers["Retry-After"]) > 0

        for accepted in responses:
            if accepted.status_code == 202:
                _wait_until_final(api, headers, accepted.json()["id"], timeout=120)
