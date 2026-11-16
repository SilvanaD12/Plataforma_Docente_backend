"""
Pruebas E2E de seguridad (QA-08):
- Límite de 5 intentos fallidos de inicio de sesión en 15 minutos por correo e IP (6.º responde 429 con Retry-After).
- Sin revelar si el correo existe o no.
- Protección contra spoofing de X-Forwarded-For sin proxies de confianza.
- Reserva atómica bajo solicitudes concurrentes (6 intentos simultáneos devuelven 429 con Retry-After).
- Preservación de reservas de intentos en curso tras un inicio de sesión exitoso.
- Cabeceras HTTP de seguridad en respuestas públicas y privadas.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from platform5e.infrastructure.http.security import LoginRateLimiter
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


def test_successful_login_preserves_in_flight_failed_attempt_reservations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    app = create_application()
    suffix = uuid4().hex[:10]
    email = f"interleaved.qa08.{suffix}@example.com"
    valid_password = "ClaveValida123!"

    with TestClient(app) as client:
        reg = client.post(
            "/api/v1/accounts",
            json={"name": "Docente Intercalado", "email": email, "password": valid_password},
        )
        assert reg.status_code == 201

        # Simula 4 intentos fallidos concurrentes en curso + 1 login válido (5 reservas en total)
        limiter = LoginRateLimiter(max_attempts=5, window_seconds=15 * 60)
        client_ip = "203.0.113.55"
        all_reserved = threading.Barrier(5)
        valid_released = threading.Event()

        def worker_failed() -> int:
            retry_after, _token = limiter.reserve_attempt(email, client_ip)
            assert retry_after == 0
            all_reserved.wait(timeout=5)
            # Espera a que el login válido termine y libere su propia reserva
            assert valid_released.wait(timeout=5)
            # Falla la verificación de contraseña: no se libera su reserva
            return 401

        def worker_valid() -> int:
            retry_after, token = limiter.reserve_attempt(email, client_ip)
            assert retry_after == 0
            all_reserved.wait(timeout=5)
            # El login válido termina primero y libera solo su propia reserva
            limiter.release_attempt(email, client_ip, token)
            valid_released.set()
            return 200

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(worker_failed) for _ in range(4)] + [pool.submit(worker_valid)]
            outcomes = [f.result() for f in futures]

        assert outcomes.count(200) == 1
        assert outcomes.count(401) == 4

        # Como los 4 fallos conservaron sus reservas, queda exactamente 1 cupo para el 5.º fallo
        retry_after_5th, _ = limiter.reserve_attempt(email, client_ip)
        assert retry_after_5th == 0

        # Al alcanzar el límite de 5 fallos, el siguiente intento debe devolver 429 con Retry-After
        retry_after_6th, _ = limiter.reserve_attempt(email, client_ip)
        assert 1 <= retry_after_6th <= 900

    # Prueba E2E HTTP intercalando login válido entre intentos fallidos y comprobando 429 con Retry-After
    app_e2e = create_application()
    email_e2e = f"e2e.interleaved.{suffix}@example.com"
    with TestClient(app_e2e) as client:
        reg = client.post(
            "/api/v1/accounts",
            json={"name": "Docente E2E", "email": email_e2e, "password": valid_password},
        )
        assert reg.status_code == 201

        # 3 intentos fallidos
        for _ in range(3):
            r = client.post("/api/v1/sessions", json={"email": email_e2e, "password": "wrong"})
            assert r.status_code == 401

        # 1 login válido intercalado (no debe borrar los 3 fallos anteriores)
        ok = client.post("/api/v1/sessions", json={"email": email_e2e, "password": valid_password})
        assert ok.status_code == 200

        # 2 intentos fallidos más completan el límite de 5
        for _ in range(2):
            r = client.post("/api/v1/sessions", json={"email": email_e2e, "password": "wrong"})
            assert r.status_code == 401

        # 6.º fallo acumulado -> 429 con Retry-After
        blocked = client.post("/api/v1/sessions", json={"email": email_e2e, "password": "wrong"})
        assert blocked.status_code == 429
        assert 1 <= int(blocked.headers["Retry-After"]) <= 900