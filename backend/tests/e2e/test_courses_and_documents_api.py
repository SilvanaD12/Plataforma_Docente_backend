"""EP-002: peticiones reales, archivos reales y recuperación con nueva sesión."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any

import httpx
import pytest

GENERATION_REQUEST = {
    "unitId": "u2",
    "outcomeId": None,
    "stage": "explore",
    "resourceType": "guia_exploracion",
    "quantity": 1,
    "difficulty": "intermedia",
    "optionCount": 4,
    "topK": 10,
    "evidenceThreshold": 0.6,
    "instructions": "Contexto de prueba",
    "audience": "Tercer ciclo",
    "competency": "Pensamiento crítico",
    "modalities": ["Textual"],
}

CREDENTIALS = {"email": "docente@5e.demo", "password": "Demo5E!2026"}
COURSE = {"code": "EP002", "name": "Curso de integración", "term": "2026-II", "units": [{"title": "Unidad conectada"}]}


def login(api: httpx.Client) -> dict[str, str]:
    r = api.post("/api/v1/sessions", json=CREDENTIALS)
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def context(unit: str = "u2", ra: list[str] | None = None) -> dict[str, Any]:
    return {
        "unitId": unit,
        "outcomeIds": ["ra-2-1"] if ra is None else ra,
        "documentType": "Guía de práctica",
        "suggestedStage": "explore",
        "usePermission": True,
    }


def upload(
    api: httpx.Client,
    headers: dict[str, str],
    name: str = "evidencia.txt",
    content: bytes = b"Material docente real",
    data: dict[str, Any] | None = None,
) -> httpx.Response:
    return api.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": (name, content)},
        data={"context": json.dumps(data or context())},
    )


def test_login_catalog_file_and_history_persist_with_a_new_session(server: str):
    with httpx.Client(base_url=server) as api:
        h = login(api)
        c = api.post("/api/v1/courses", headers=h, json=COURSE)
        assert c.status_code == 201, c.text
        course = c.json()
        unit = course["units"][0]
        assert unit["outcomes"] == []
        edited = api.put(
            "/api/v1/courses/" + course["id"],
            headers=h,
            json={
                **COURSE,
                "name": "Curso actualizado",
                "units": [{"id": unit["id"], "title": "Unidad actualizada"}, {"title": "Segunda unidad"}],
            },
        )
        assert edited.status_code == 200
        assert edited.json()["units"][0]["id"] == unit["id"]
        doc = upload(api, h, data=context(unit["id"], []))
        assert doc.status_code == 201, doc.text
        document = doc.json()
        assert document["source"] == "backend" and document["fragmentCount"] == 0
        assert document["status"] == "registrado" and document["processedAt"] is None
        file_path = api.get("/api/v1/documents/" + document["id"] + "/file", headers=h)
        assert file_path.content == b"Material docente real"
        generation = api.post("/api/v1/generations", headers=h, json=GENERATION_REQUEST)
        assert generation.status_code == 200, generation.text
        req = generation.json()["request"]
        assert api.get("/api/v1/generations", headers=h).json() == [req]
        assert api.get("/api/v1/generations/" + req["id"]).status_code == 401
        assert api.delete("/api/v1/sessions/current", headers=h).status_code == 204
        assert api.get("/api/v1/courses", headers=h).status_code == 401
        h2 = login(api)
        assert any(c["name"] == "Curso actualizado" for c in api.get("/api/v1/courses", headers=h2).json())
        assert api.get("/api/v1/documents", headers=h2).json() == [document]
        assert api.get("/api/v1/generations", headers=h2).json() == [req]
        assert api.get("/api/v1/generations/" + req["id"], headers=h2).json()["request"] == req
        assert api.delete("/api/v1/documents/" + document["id"], headers=h2).status_code == 204
        assert api.get("/api/v1/documents/" + document["id"] + "/file", headers=h2).status_code == 404


@pytest.mark.parametrize(
    "route",
    ["/api/v1/courses", "/api/v1/documents", "/api/v1/generations", "/api/v1/sessions/current"],
)
def test_private_routes_require_a_session(server: str, route: str):
    assert httpx.get(server + route).status_code == 401
    assert httpx.get(server + route, headers={"Authorization": "Bearer inventado"}).status_code == 401


def test_server_validation_does_not_save_invalid_data(server: str):
    with httpx.Client(base_url=server) as api:
        assert api.post("/api/v1/sessions", json={**CREDENTIALS, "password": "incorrecta"}).status_code == 401
        h = login(api)
        assert api.post("/api/v1/courses", headers=h, json=COURSE).status_code == 201
        assert api.post("/api/v1/courses", headers=h, json={**COURSE, "code": "ep002"}).status_code == 409
        assert api.post("/api/v1/courses", headers=h, json={**COURSE, "units": [{"title": "   "}]}).status_code == 422
        assert upload(api, h, data=context("unidad-ajena")).status_code == 404
        assert upload(api, h, data=context(ra=["ra-3-1"])).status_code == 400
        assert upload(api, h, data={**context(), "usePermission": False}).status_code == 400
        for name, content in [
            ("falso.pdf", b"no pdf"),
            ("falso.pptx", b"PK mentira"),
            ("vacio.txt", b""),
            ("binario.txt", b"\xff"),
            ("../ruta.txt", b"contenido"),
            ("script.exe", b"contenido"),
        ]:
            assert upload(api, h, name, content).status_code == 400
        assert upload(api, h).status_code == 201
        assert upload(api, h).status_code == 409
        assert len(api.get("/api/v1/documents", headers=h).json()) == 1
        assert (
            api.post("/api/v1/generations", headers=h, json={**GENERATION_REQUEST, "unitId": "unidad-ajena"}).status_code
            == 404
        )
        assert api.get("/api/v1/generations", headers=h).json() == []


@pytest.mark.parametrize("modalities", [["Multimedia"], ["Textual", "Gamificado"]])
def test_text_only_rejects_other_modalities(server: str, modalities: list[str]):
    response = httpx.post(f"{server}/api/v1/generations", json={**GENERATION_REQUEST, "modalities": modalities})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_PARAMETERS"


def test_file_over_the_limit_is_not_saved(server: str):
    with httpx.Client(base_url=server, timeout=30) as api:
        h = login(api)
        r = upload(api, h, content=b"x" * (25 * 1024 * 1024 + 1))
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "INVALID_SIZE"
        assert api.get("/api/v1/documents", headers=h).json() == []


def test_catalog_session_file_and_history_survive_a_restart(tmp_path: Path):
    """Dos procesos distintos utilizan el mismo archivo SQLite, sin caché de aplicación."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    src_dir = str(Path(__file__).resolve().parents[2] / "src")
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    pythonpath = f"{src_dir}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else src_dir
    env = {
        **os.environ,
        "PYTHONPATH": pythonpath,
        "DATABASE_URL": f"sqlite:///{tmp_path / 'persistente.db'}",
        "DEMO_CATALOG": "true",
    }
    headers = None
    doc_id = None
    req_id = None
    for attempt in range(2):
        with (tmp_path / f"servidor{attempt}.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "platform5e.main:create_application",
                    "--factory",
                    "--app-dir",
                    src_dir,
                    "--port",
                    str(port),
                ],
                cwd=Path(__file__).resolve().parents[2],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                for _ in range(100):
                    try:
                        if httpx.get(base + "/health", timeout=0.5).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if process.poll() is not None:
                        pytest.fail("No arrancó el servidor persistente.")
                    time.sleep(0.1)
                else:
                    pytest.fail("El servidor persistente no respondió.")
                with httpx.Client(base_url=base) as api:
                    if attempt == 0:
                        headers = login(api)
                        assert api.post("/api/v1/courses", headers=headers, json=COURSE).status_code == 201
                        doc_id = upload(api, headers).json()["id"]
                        req_id = api.post("/api/v1/generations", headers=headers, json=GENERATION_REQUEST).json()["request"]["id"]
                    else:
                        assert api.get("/api/v1/sessions/current", headers=headers).status_code == 200
                        assert any(c["code"] == "EP002" for c in api.get("/api/v1/courses", headers=headers).json())
                        assert (
                            api.get("/api/v1/documents/" + doc_id + "/file", headers=headers).content
                            == b"Material docente real"
                        )
                        assert api.get("/api/v1/generations", headers=headers).json()[0]["id"] == req_id
            finally:
                process.terminate()
                process.wait(timeout=10)


def test_health_answers_on_the_new_path_and_on_the_previous_one(server: str):
    assert httpx.get(server + "/health").json() == {"status": "ok"}
    assert httpx.get(server + "/salud").json() == {"status": "ok"}  # Render, hasta que cambie su Health Check Path
    assert "/salud" not in httpx.get(server + "/openapi.json").json()["paths"]


def test_openapi_declares_bearer_for_swagger(server: str):
    spec = httpx.get(server + "/openapi.json").json()
    assert spec["components"]["securitySchemes"]["TeacherSession"]["type"] == "http"
    assert spec["components"]["securitySchemes"]["TeacherSession"]["scheme"] == "bearer"
    for route, method in [
        ("/api/v1/generations", "get"),
        ("/api/v1/courses", "get"),
        ("/api/v1/documents", "post"),
        ("/api/v1/sessions/current", "delete"),
        ("/api/v1/generations", "post"),
    ]:
        operation = spec["paths"][route][method]
        assert {"TeacherSession": []} in operation["security"]
        assert not any(
            p["in"] == "header" and p["name"].lower() == "authorization" for p in operation.get("parameters", [])
        )
    assert "security" not in spec["paths"]["/api/v1/sessions"]["post"]
    with httpx.Client(base_url=server) as api:
        h = login(api)
        assert api.get("/api/v1/generations", headers=h).status_code == 200
        assert api.get("/api/v1/generations", headers={"Authorization": "Basic incorrecto"}).status_code == 401
        assert (
            api.post(
                "/api/v1/generations",
                headers={"Authorization": "Basic incorrecto"},
                json=GENERATION_REQUEST,
            ).status_code
            == 401
        )