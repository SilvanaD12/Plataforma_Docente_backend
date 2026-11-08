"""HU-003 por HTTP: un pedido con varios tipos de recurso genera la secuencia con un agente por etapa.

GEN-01 (T023): el pedido se inicia con 202 y se consulta hasta su estado final.
"""

from __future__ import annotations

import json
import time
from uuid import uuid4

import httpx

from tests.e2e.test_accounts_and_review_api import MATERIAL

ACCOUNT = {"name": "Luis Rojas", "email": "luis.rojas@correo.pe", "password": "clave-segura-2"}
FINAL_STATUSES = {"succeeded", "partially_succeeded", "failed", "interrupted"}


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


def _wait_until_final(api: httpx.Client, headers: dict[str, str], request_id: str, timeout: float = 60) -> dict:
    """Consulta el pedido hasta que el servidor confirme un estado final."""
    limit = time.monotonic() + timeout
    while True:
        response = api.get(f"/api/v1/generation-requests/{request_id}", headers=headers)
        assert response.status_code == 200, response.text
        request = response.json()
        if request["status"] in FINAL_STATUSES:
            return request
        assert time.monotonic() < limit, f"El pedido sigue en {request['status']} tras {timeout} s."
        time.sleep(0.2)


def test_a_sequence_request_is_drafted_by_one_agent_per_stage(server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = {"Authorization": "Bearer " + api.post("/api/v1/accounts", json=ACCOUNT).json()["token"]}
        unit = _unit_with_material(api, headers)

        response = api.post(
            "/api/v1/generation-requests",
            headers={**headers, "Idempotency-Key": str(uuid4())},
            json={"mode": "sequence", "unitId": unit["id"], "resourceTypes": ["item_opcion_multiple", "pregunta_detonante"]},
        )
        assert response.status_code == 202, response.text
        result = _wait_until_final(api, headers, response.json()["id"])

        assert [(s["stage"], s["agent"]) for s in result["steps"]] == [
            ("engage", "Agente de Enganchar"),
            ("evaluate", "Agente de Evaluar"),
        ]
        assert all(len(step["resourceIds"]) + len(step["rejections"]) >= 1 for step in result["steps"])
        delivered = {rid: step["agent"] for step in result["steps"] for rid in step["resourceIds"]}
        assert delivered and all(agent.startswith("Agente de") for agent in delivered.values())
        assert result["resourceTypes"] == ["pregunta_detonante", "item_opcion_multiple"]

        saved = api.get(f"/api/v1/units/{unit['id']}/resources", headers=headers).json()
        assert {r["id"]: r["agent"] for r in saved if r.get("requestId") == result["id"]} == delivered
        listed = api.get("/api/v1/generation-requests", headers=headers, params={"unitId": unit["id"]}).json()
        assert listed[0]["id"] == result["id"]


def test_a_request_without_resource_type_is_rejected(server: str):
    with httpx.Client(base_url=server, timeout=30) as api:
        headers = {"Authorization": "Bearer " + api.post("/api/v1/accounts", json=ACCOUNT).json()["token"]}
        unit = _unit_with_material(api, headers)
        headers = {**headers, "Idempotency-Key": str(uuid4())}
        missing = {"mode": "sequence", "unitId": unit["id"]}
        assert api.post("/api/v1/generation-requests", headers=headers, json=missing).status_code == 422
        invalid = api.post(
            "/api/v1/generation-requests",
            headers=headers,
            json={"mode": "sequence", "unitId": unit["id"], "resourceTypes": ["tipo_inventado"]},
        )
        assert invalid.status_code == 422
