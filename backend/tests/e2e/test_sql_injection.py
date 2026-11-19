"""
Pruebas E2E de prevención de inyección SQL y aislamiento de datos (QA-15):
- Rechazo seguro de entradas con comillas, comentarios y operadores SQL en rutas públicas y privadas.
- Ausencia de errores 500 o trazas internas de SQLAlchemy/PostgreSQL.
- Preservación de integridad de tablas y aislamiento estricto entre docentes.
"""

from __future__ import annotations

import json
import httpx

CREDENTIALS = {"email": "docente@5e.demo", "password": "Demo5E!2026"}

SQL_PAYLOADS = [
    "' OR '1'='1",
    "admin'--",
    "'; DROP TABLE ep002_fragmentos; --",
    "' UNION SELECT NULL, NULL, NULL--",
    "1' OR 1=1#",
]


def _login_demo(api: httpx.Client) -> dict[str, str]:
    res = api.post("/api/v1/sessions", json=CREDENTIALS)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _register_teacher(api: httpx.Client, email: str, name: str) -> dict[str, str]:
    res = api.post(
        "/api/v1/accounts",
        json={"name": name, "email": email, "password": "ClaveSegura-2026!"},
    )
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['token']}"}


def _assert_no_sql_leak(response: httpx.Response) -> None:
    assert response.status_code != 500, response.text
    body_lower = response.text.lower()
    assert "traceback" not in body_lower
    assert "sqlalchemy" not in body_lower
    assert "psycopg" not in body_lower
    assert "syntax error at or near" not in body_lower


def test_sessions_endpoint_rejects_sql_payloads_safely(server: str) -> None:
    with httpx.Client(base_url=server, timeout=15) as api:
        for idx, payload in enumerate(SQL_PAYLOADS):
            res = api.post(
                "/api/v1/sessions",
                json={"email": f"attacker{idx}{payload}@example.com", "password": payload},
                headers={"X-Forwarded-For": f"198.51.100.{idx + 10}"},
            )
            _assert_no_sql_leak(res)
            assert res.status_code in (401, 422, 429)


def test_authenticated_endpoints_resist_sql_payloads_and_preserve_isolation(server: str) -> None:
    with httpx.Client(base_url=server, timeout=30) as api:
        owner_headers = _login_demo(api)
        attacker_headers = _register_teacher(api, "qa15-attacker@example.com", "Docente Externo")

        created = api.post(
            "/api/v1/courses",
            headers=owner_headers,
            json={
                "code": "QA15-SEC",
                "name": "Seguridad de Aplicaciones",
                "term": "2026-II",
                "units": [{"title": "Inyeccion SQL"}],
            },
        )
        assert created.status_code == 201, created.text
        course = created.json()
        unit_id = course["units"][0]["id"]

        upload = api.post(
            "/api/v1/documents",
            headers=owner_headers,
            files={"file": ("apuntes.txt", b"Consultas parametrizadas con SQLAlchemy y pgvector.")},
            data={
                "context": json.dumps(
                    {
                        "unitId": unit_id,
                        "outcomeIds": [],
                        "documentType": "Guía de práctica",
                        "suggestedStage": "explore",
                        "usePermission": True,
                    }
                )
            },
        )
        assert upload.status_code == 201, upload.text
        process = api.post(f"/api/v1/documents/{upload.json()['id']}/process", headers=owner_headers)
        assert process.status_code == 200, process.text

        for idx, payload in enumerate(SQL_PAYLOADS):
            r_post = api.post(
                "/api/v1/courses",
                headers=attacker_headers,
                json={
                    "code": f"ATK-{idx}",
                    "name": f"Curso {payload}",
                    "term": "2026-II",
                    "units": [{"title": f"Unidad {payload}"}],
                },
            )
            _assert_no_sql_leak(r_post)
            assert r_post.status_code in (201, 400, 422)

            r_put = api.put(
                f"/api/v1/courses/{course['id']}",
                headers=attacker_headers,
                json={
                    "code": "QA15-SEC",
                    "name": f"Modificado {payload}",
                    "term": "2026-II",
                    "units": [{"id": unit_id, "title": "Unidad"}],
                },
            )
            _assert_no_sql_leak(r_put)
            assert r_put.status_code == 404

            r_search = api.get(
                "/api/v1/documents/search",
                headers=attacker_headers,
                params={"query": payload, "unitId": unit_id},
            )
            _assert_no_sql_leak(r_search)
            assert r_search.status_code in (200, 400, 404, 422)

            r_interpret = api.post(
                "/api/v1/generation-requests/interpret",
                headers=attacker_headers,
                json={"unitId": unit_id, "message": f"Generar glosario {payload}"},
            )
            _assert_no_sql_leak(r_interpret)
            assert r_interpret.status_code in (404, 422)

        owner_courses = api.get("/api/v1/courses", headers=owner_headers)
        assert owner_courses.status_code == 200
        assert any(c["id"] == course["id"] and c["name"] == "Seguridad de Aplicaciones" for c in owner_courses.json())