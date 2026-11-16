"""
Pruebas E2E de seguridad (QA-08):
- Límite de 5 intentos fallidos de inicio de sesión en 15 minutos por correo e IP (6.º responde 429 con Retry-After).
- Sin revelar si el correo existe o no.
- Protección contra spoofing de X-Forwarded-For sin proxies de confianza.
- Reserva atómica bajo solicitudes concurrentes (6 intentos simultáneos devuelven 429 con Retry-After).
- Cabeceras HTTP de seguridad en respuestas públicas y privadas.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
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


def test_login_rate_limit_blocks_sixth_attempt_without_enumerating_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRUSTED_PROXIES", "testclient")
    app = create_application()
    suffix = uuid4().hex[:10]
    existing_email = f"docente.qa08.{suffix}@example.com"
    unknown_email = f"noexiste.qa08.{suffix}@example.com"

    with TestClient(app) as client:
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

        # Misma prueba con un correo inexistente desde otra IP de cliente detrás de proxy confiable
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


def test_login_ignores_spoofed_x_forwarded_for_from_untrusted_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    app = create_application()
    suffix = uuid4().hex[:10]
    email = f"spoof.qa08.{suffix}@example.com"

    with TestClient(app) as client:
        reg = client.post(
            "/api/v1/accounts",
            json={"name": "Docente Spoof", "email": email, "password": "ClaveValida123!"},
        )
        assert reg.status_code == 201

        # Aunque el cliente cambie X-Forwarded-For en cada petición, no proviene de un proxy confiable
        for idx in range(5):
            res = client.post(
                "/api/v1/sessions",
                json={"email": email, "password": "wrong-password"},
                headers={"X-Forwarded-For": f"198.51.100.{idx + 1}"},
            )
            assert res.status_code == 401

        blocked = client.post(
            "/api/v1/sessions",
            json={"email": email, "password": "wrong-password"},
            headers={"X-Forwarded-For": "198.51.100.99"},
        )
        assert blocked.status_code == 429
        retry_after = int(blocked.headers["Retry-After"])
        assert 1 <= retry_after <= 900


def test_login_concurrent_requests_enforce_atomic_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    app = create_application()
    suffix = uuid4().hex[:10]
    email = f"concurrent.qa08.{suffix}@example.com"

    with TestClient(app) as client:
        reg = client.post(
            "/api/v1/accounts",
            json={"name": "Docente Concurrencia", "email": email, "password": "ClaveValida123!"},
        )
        assert reg.status_code == 201

        def attempt_login() -> tuple[int, str | None]:
            resp = client.post(
                "/api/v1/sessions",
                json={"email": email, "password": "wrong-password"},
            )
            return resp.status_code, resp.headers.get("Retry-After")

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(attempt_login) for _ in range(6)]
            results = [fut.result() for fut in futures]

        status_codes = [code for code, _ in results]
        assert status_codes.count(401) == 5
        assert status_codes.count(429) == 1

        blocked_headers = [retry for code, retry in results if code == 429]
        assert blocked_headers[0] is not None
        assert 1 <= int(blocked_headers[0]) <= 900