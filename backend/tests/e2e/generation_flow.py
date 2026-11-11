"""Ayudas de las pruebas de punta a punta para generar recursos con el pedido de GEN-01 y para el historial antiguo.

T046 retiró `POST /api/v1/generations`. Las pruebas que la usaban para crear recursos pasan a
`POST /api/v1/generation-requests` (con `Idempotency-Key`) y consultan el pedido hasta un estado final. El historial
de `GET /api/v1/generations` solo muestra generaciones guardadas antes de GEN-01: para probar esas lecturas se inserta
una en la base, como las que dejó la ruta retirada.
"""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

import httpx

FINAL_STATUSES = {"succeeded", "partially_succeeded", "failed", "interrupted"}


def wait_until_final(
    api: httpx.Client, headers: dict[str, str], request_id: str, timeout: float = 60
) -> dict[str, Any]:
    """Consulta GET /api/v1/generation-requests/{id} hasta que el servidor confirme un estado final."""
    limit = time.monotonic() + timeout
    while True:
        response = api.get(f"/api/v1/generation-requests/{request_id}", headers=headers)
        assert response.status_code == 200, response.text
        if response.json()["status"] in FINAL_STATUSES:
            return response.json()
        assert time.monotonic() < limit, f"El pedido sigue en {response.json()['status']} tras {timeout} s."
        time.sleep(0.2)


def start_generation(
    api: httpx.Client, headers: dict[str, str], unit_id: str, resource_type: str, key: str | None = None, **params: Any
) -> httpx.Response:
    """POST /api/v1/generation-requests de un pedido individual. `params` usa los nombres del contrato (camelCase)."""
    body = {"mode": "individual", "unitId": unit_id, "resourceTypes": [resource_type], **params}
    return api.post(
        "/api/v1/generation-requests",
        headers={**headers, "Idempotency-Key": key or f"e2e-{uuid4().hex}"},
        json=body,
    )


def generate(
    api: httpx.Client, headers: dict[str, str], unit_id: str, resource_type: str, **params: Any
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Crea el pedido, espera su estado final y devuelve (pedido, recursos entregados tal como los lee Revisión)."""
    started = start_generation(api, headers, unit_id, resource_type, **params)
    assert started.status_code in (200, 202), started.text
    final = wait_until_final(api, headers, started.json()["id"])
    delivered = [resource_id for step in final["steps"] for resource_id in step["resourceIds"]]
    stored = {r["id"]: r for r in api.get(f"/api/v1/units/{unit_id}/resources", headers=headers).json()}
    return final, [stored[resource_id] for resource_id in delivered]


def seed_legacy_generation(database_url: str, teacher_id: str, unit_id: str = "u2") -> dict[str, Any]:
    """Inserta una generación como las que guardaba la ruta síncrona retirada y devuelve su `request`."""
    from sqlalchemy import create_engine, text

    request = {
        "id": f"sol-{uuid4().hex[:12]}",
        "unitId": unit_id,
        "stage": "explore",
        "resourceType": "guia_exploracion",
        "quantity": 1,
        "createdAt": "2026-10-20T10:00:00+00:00",
    }
    result = {
        "request": request,
        "mode": "rag",
        "available": 1,
        "resources": [],
        "fragments": [],
        "documents": [],
        "notice": "",
        "generator": {"description": "Generador por reglas (sin IA)", "usesAi": False, "fallback": False},
    }
    engine = create_engine(database_url)
    data = "CAST(:resultado AS JSON)" if engine.dialect.name == "postgresql" else ":resultado"
    try:
        with engine.begin() as connection:
            connection.execute(
                text(f"INSERT INTO generaciones_demo (id, resultado) VALUES (:id, {data})"),
                {"id": request["id"], "resultado": json.dumps(result)},
            )
            connection.execute(
                text("INSERT INTO ep002_generaciones_docente (id, docente) VALUES (:id, :docente)"),
                {"id": request["id"], "docente": teacher_id},
            )
    finally:
        engine.dispose()
    return request
