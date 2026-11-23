"""
Pruebas E2E de protección contra denegación de servicio (QA-16 — ISO/IEC 25023 RAv-1-G, RFt-1-G):
- Límite de tasa por IP (429 con Retry-After y cabeceras CORS) en rutas costosas respetando TRUSTED_PROXIES.
- Límite de tamaño de cuerpo (413 Payload Too Large con cabeceras CORS) antes de leer el payload:
  * > 25 MB en POST /api/v1/documents
  * > 1 MB en rutas JSON
- Disponibilidad intacta de /health bajo ráfaga en rutas costosas.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn

from platform5e.main import create_application


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture()
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'qa16.db'}")
    monkeypatch.setenv("LLM_PROVIDER", "rules")
    monkeypatch.setenv("EMBEDDINGS_ENABLED", "false")
    monkeypatch.setenv("MEDIA_GENERATION_ENABLED", "false")
    monkeypatch.setenv("TOPIC_SEARCH_ENABLED", "false")
    monkeypatch.setenv("DEMO_CATALOG", "true")
    monkeypatch.setenv("EXPENSIVE_RATE_LIMIT_MAX_REQUESTS", "3")
    monkeypatch.setenv("EXPENSIVE_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://plataformadocente.dev")

    port = _free_port()
    app = create_application()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            if httpx.get(f"{base_url}/health", timeout=0.5).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        pytest.fail("El servidor local para pruebas de QA-16 no arrancó a tiempo.")

    try:
        yield base_url
    finally:
        srv.should_exit = True
        thread.join(timeout=5)


def _login_demo(api: httpx.Client) -> tuple[dict[str, str], str]:
    res = api.post(
        "/api/v1/sessions",
        json={"email": "docente@5e.demo", "password": "Demo5E!2026"},
    )
    assert res.status_code == 200, res.text
    headers = {"Authorization": f"Bearer {res.json()['token']}"}

    courses_res = api.get("/api/v1/courses", headers=headers)
    assert courses_res.status_code == 200, courses_res.text
    courses = courses_res.json()
    unit_id = courses[0]["units"][0]["id"]
    return headers, unit_id


def test_rate_limit_on_expensive_routes_returns_429_with_retry_after(server: str) -> None:
    with httpx.Client(base_url=server, timeout=15) as api:
        headers, unit_id = _login_demo(api)
        ip_a = {**headers, "X-Forwarded-For": "198.51.100.10", "Origin": "https://plataformadocente.dev"}
        ip_b = {**headers, "X-Forwarded-For": "198.51.100.20", "Origin": "https://plataformadocente.dev"}
        payload = {"unitId": unit_id, "message": "Generar una guía de redes de computadoras"}

        # Cupo configurado en el fixture: 3 peticiones por ventana para ip_a
        for _ in range(3):
            res = api.post(
                "/api/v1/generation-requests/interpret",
                headers=ip_a,
                json=payload,
            )
            assert res.status_code == 200, res.text

        # La 4.ª petición desde ip_a dispara 429 con Retry-After, cabecera CORS y cabeceras de seguridad
        blocked = api.post(
            "/api/v1/generation-requests/interpret",
            headers=ip_a,
            json=payload,
        )
        assert blocked.status_code == 429, blocked.text
        assert "Retry-After" in blocked.headers
        assert int(blocked.headers["Retry-After"]) >= 1
        assert blocked.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert blocked.headers.get("access-control-allow-origin") == "https://plataformadocente.dev"
        assert blocked.headers.get("X-Content-Type-Options") == "nosniff"

        # Otra IP distinta (ip_b) mantiene su propio cupo independiente
        allowed_other_ip = api.post(
            "/api/v1/generation-requests/interpret",
            headers=ip_b,
            json=payload,
        )
        assert allowed_other_ip.status_code == 200, allowed_other_ip.text

        # /health permanece 200 disponible sin verse afectado por el bloqueo
        health = api.get("/health")
        assert health.status_code == 200


def test_creating_a_generation_plan_is_a_costly_route(server: str) -> None:
    """GEN-P1: crear el plan llama a la IA y recupera evidencia; cuenta para el mismo cupo por IP."""
    with httpx.Client(base_url=server, timeout=15) as api:
        headers, unit_id = _login_demo(api)
        ip_c = {**headers, "X-Forwarded-For": "198.51.100.30"}
        body = {"unitId": unit_id, "resourceTypes": [{"type": "explicacion"}]}
        answers = [
            api.post("/api/v1/generation-plans", headers={**ip_c, "Idempotency-Key": f"plan-cupo-{n:04d}"}, json=body)
            for n in range(4)
        ]
        listed = api.get("/api/v1/generation-plans", headers=ip_c, params={"unitId": unit_id})
    assert [a.status_code == 429 for a in answers] == [False, False, False, True]
    assert answers[3].json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert listed.status_code == 200  # leer no es costoso


def test_payload_size_limit_rejects_oversized_json_and_upload_with_413(server: str) -> None:
    host_port = server.removeprefix("http://")
    host, port_text = host_port.split(":")
    port = int(port_text)

    # 1. Ruta JSON con Content-Length > 1 MB (1_048_576 bytes): rechazada antes de leer el cuerpo, con CORS
    with socket.create_connection((host, port), timeout=5) as sock:
        raw_request = (
            f"POST /api/v1/sessions HTTP/1.1\r\n"
            f"Host: {host_port}\r\n"
            f"Origin: https://plataformadocente.dev\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {1_048_577}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("ascii")
        sock.sendall(raw_request)
        response_bytes = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response_bytes += chunk

    response_text = response_bytes.decode("utf-8", errors="replace")
    assert "HTTP/1.1 413 " in response_text
    assert "PAYLOAD_TOO_LARGE" in response_text
    assert "access-control-allow-origin: https://plataformadocente.dev" in response_text.lower()

    # 2. Subida en POST /api/v1/documents con Content-Length > 25 MB (26_214_400 bytes), con CORS
    with socket.create_connection((host, port), timeout=5) as sock:
        raw_upload = (
            f"POST /api/v1/documents HTTP/1.1\r\n"
            f"Host: {host_port}\r\n"
            f"Origin: https://plataformadocente.dev\r\n"
            f"Content-Type: multipart/form-data; boundary=----QA16Boundary\r\n"
            f"Content-Length: {25 * 1024 * 1024 + 1}\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("ascii")
        sock.sendall(raw_upload)
        upload_bytes = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            upload_bytes += chunk

    upload_text = upload_bytes.decode("utf-8", errors="replace")
    assert "HTTP/1.1 413 " in upload_text
    assert "PAYLOAD_TOO_LARGE" in upload_text
    assert "access-control-allow-origin: https://plataformadocente.dev" in upload_text.lower()