"""HU-003 por HTTP: un pedido con varios tipos de recurso genera la secuencia con un agente por etapa."""

from __future__ import annotations

import json

import httpx

from tests.e2e.test_accounts_and_review_api import MATERIAL

ACCOUNT = {"name": "Luis Rojas", "email": "luis.rojas@correo.pe", "password": "clave-segura-2"}


def _unit_with_material(api: httpx.Client, headers: dict[str, str]) -> dict:
    course = api.post(
        "/api/v1/courses",
        headers=headers,
        json={
            "code": "RED-302",
            "name": "Redes",
            "term": "2026-II",
            "units": [{"title": "Protocolos", "outcomes": [{"text": "Distingue TCP y UDP"}]}],
        },
    ).json()
    unit = course["units"][0]
    context = {
        "unitId": unit["id"],
        "outcomeIds": [unit["outcomes"][0]["id"]],
        "documentType": "Separata o apuntes de clase",
        "suggestedStage": None,
        "usePermission": True,
    }
    document = api.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("protocolos.txt", MATERIAL)},
        data={"context": json.dumps(context)},
    ).json()
    assert api.post(f"/api/v1/documents/{document['id']}/process", headers=headers).json()["status"] == "procesado"
    return unit


def test_a_sequence_request_is_drafted_by_one_agent_per_stage(server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = {"Authorization": "Bearer " + api.post("/api/v1/accounts", json=ACCOUNT).json()["token"]}
        unit = _unit_with_material(api, headers)

        response = api.post(
            "/api/v1/generations",
            headers=headers,
            json={"unitId": unit["id"], "resourceTypes": ["item_opcion_multiple", "pregunta_detonante"]},
        )
        assert response.status_code == 200, response.text
        result = response.json()

        assert [(s["stage"], s["agent"]) for s in result["sequence"]] == [
            ("engage", "Agente de Enganchar"),
            ("evaluate", "Agente de Evaluar"),
        ]
        assert all(step["generated"] + len(step["rejected"]) >= 1 for step in result["sequence"])
        assert result["resources"] and all(r["agent"].startswith("Agente de") for r in result["resources"])
        assert result["request"]["resourceTypes"] == ["pregunta_detonante", "item_opcion_multiple"]

        saved = api.get(f"/api/v1/units/{unit['id']}/resources", headers=headers).json()
        assert {r["id"]: r["agent"] for r in saved} == {r["id"]: r["agent"] for r in result["resources"]}
        assert api.get("/api/v1/generations", headers=headers).json()[0]["id"] == result["request"]["id"]


def test_a_request_without_resource_type_is_rejected(server: str):
    with httpx.Client(base_url=server, timeout=30) as api:
        headers = {"Authorization": "Bearer " + api.post("/api/v1/accounts", json=ACCOUNT).json()["token"]}
        unit = _unit_with_material(api, headers)
        assert api.post("/api/v1/generations", headers=headers, json={"unitId": unit["id"]}).status_code == 422
        invalid = api.post(
            "/api/v1/generations", headers=headers, json={"unitId": unit["id"], "resourceTypes": ["tipo_inventado"]}
        )
        assert invalid.status_code == 422
