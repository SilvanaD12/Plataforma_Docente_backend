"""
Pruebas E2E de seguridad (QA-08):
- Límite de 5 intentos fallidos de inicio de sesión en 15 minutos por correo e IP (6.º responde 429 con Retry-After).
- Sin revelar si el correo existe o no.
- Cabeceras HTTP de seguridad en respuestas públicas y privadas.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from platform5e.main import create_application


def test_security_headers_present_on_responses() -> None:
    app = create_application()
    with TestClient(app) as client:
        res = client.get("/health")
        assert res.status_code == 200
        assert res.headers.get("X-Content-Type-Options") == "nosniff"
        assert res.headers.get("Content-Security-Policy") == "frame-ancestors 'none'"
        assert res.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"


def test_login_rate_limit_blocks_sixth_attempt_without_enumerating_email() -> None:
    app = create_application()
    suffix = uuid4().hex[:10]
    existing_email = f"docente.qa08.{suffix}@example.com"
    unknown_email = f"noexiste.qa08.{suffix}@example.com"

    with TestClient(app) as client:
        # Registrar cuenta real única
        reg = client.post(
            "/api/v1/accounts",
            json={"name": "Docente Prueba", "email": existing_email, "password": "ClaveValida123!"},
        )
        assert reg.status_code == 201

        # 5 intentos fallidos para correo existente -> 401
        existing_messages: set[str] = set()
        for _ in range(5):
            r = client.post(
                "/api/v1/sessions",
                json={"email": existing_email, "password": "wrong-password"},
                headers={"X-Forwarded-For": "203.0.113.10"},
            )
            assert r.status_code == 401
            existing_messages.add(r.json()["error"]["message"])

        # 6.º intento fallido en menos de 15 min -> 429 con Retry-After
        blocked_existing = client.post(
            "/api/v1/sessions",
            json={"email": existing_email, "password": "wrong-password"},
            headers={"X-Forwarded-For": "203.0.113.10"},
        )
        assert blocked_existing.status_code == 429
        retry_after = int(blocked_existing.headers["Retry-After"])
        assert 1 <= retry_after <= 900

        # Misma prueba con un correo inexistente desde otra IP:
        # debe devolver exactamente el mismo mensaje en 401 y en 429 (sin enumeración de usuarios)
        unknown_messages: set[str] = set()
        for _ in range(5):
            r = client.post(
                "/api/v1/sessions",
                json={"email": unknown_email, "password": "wrong-password"},
                headers={"X-Forwarded-For": "203.0.113.11"},
            )
            assert r.status_code == 401
            unknown_messages.add(r.json()["error"]["message"])

        assert existing_messages == unknown_messages

        blocked_unknown = client.post(
            "/api/v1/sessions",
            json={"email": unknown_email, "password": "wrong-password"},
            headers={"X-Forwarded-For": "203.0.113.11"},
        )
        assert blocked_unknown.status_code == 429
        assert "Retry-After" in blocked_unknown.headers
        assert blocked_existing.json() == blocked_unknown.json()

        # Otra IP distinta con el primer correo no debe verse afectada
        other_ip = client.post(
            "/api/v1/sessions",
            json={"email": existing_email, "password": "ClaveValida123!"},
            headers={"X-Forwarded-For": "203.0.113.99"},
        )
        assert other_ip.status_code == 200