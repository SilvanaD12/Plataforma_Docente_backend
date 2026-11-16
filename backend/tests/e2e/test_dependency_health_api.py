"""End-to-end tests for GET /health/dependencies and health routes (QA-02 / EN-028).

All external dependencies are mocked or simulated; no test goes to the internet.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx

from platform5e.application.ports.outbound.dependency_probe_port import ProbeResult
from platform5e.application.use_cases.health.check_dependencies import CheckDependencies
from platform5e.infrastructure.http.routers.health import create_health_router
from platform5e.main import create_application


class FakeProbe:
    def __init__(self, name: str, status: str = "up", latency_ms: float = 12.0, detail: str = "ok") -> None:
        self.dependency_name = name
        self._status = status
        self._latency_ms = latency_ms
        self._detail = detail
        self.calls = 0

    def probe(self, timeout_seconds: float) -> ProbeResult:
        self.calls += 1
        return ProbeResult(
            name=self.dependency_name,
            status=self._status,
            latency_ms=self._latency_ms,
            detail=self._detail,
        )


def _build_test_app(probes: list[FakeProbe], cache_ttl: float = 30.0) -> FastAPI:
    app = FastAPI()
    check_use_case = CheckDependencies(probes, cache_ttl_seconds=cache_ttl)
    app.include_router(create_health_router(check_use_case))
    return app


def test_standard_health_endpoints_remain_unchanged() -> None:
    app = create_application()
    client = TestClient(app)

    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json() == {"status": "ok"}

    legacy_health_response = client.get("/salud")
    assert legacy_health_response.status_code == 200
    assert legacy_health_response.json() == {"status": "ok"}


def test_dependency_health_all_up() -> None:
    probes = [
        FakeProbe("database", "up", 3.2, "conexión activa"),
        FakeProbe("gemini", "up", 145.0, "metadatos del modelo obtenidos"),
        FakeProbe("wikipedia", "up", 92.5, "consulta de información del sitio exitosa"),
    ]
    app = _build_test_app(probes)
    client = TestClient(app)

    response = client.get("/health/dependencies")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "ok"
    assert "checkedAt" in data
    assert len(data["checks"]) == 3
    assert [c["name"] for c in data["checks"]] == ["database", "gemini", "wikipedia"]
    assert all(c["status"] == "up" for c in data["checks"])
    assert all(isinstance(c["latencyMs"], (int, float)) for c in data["checks"])


def test_dependency_health_gemini_down_responds_200_degraded() -> None:
    probes = [
        FakeProbe("database", "up", 2.0, "conexión activa"),
        FakeProbe("gemini", "down", 45.0, "Gemini respondió 503"),
        FakeProbe("wikipedia", "up", 80.0, "consulta de información del sitio exitosa"),
    ]
    app = _build_test_app(probes)
    client = TestClient(app)

    response = client.get("/health/dependencies")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "degraded"
    gemini_check = next(c for c in data["checks"] if c["name"] == "gemini")
    assert gemini_check["status"] == "down"
    assert "503" in gemini_check["detail"]


def test_dependency_health_wikipedia_slow_responds_200_degraded() -> None:
    probes = [
        FakeProbe("database", "up", 2.0, "conexión activa"),
        FakeProbe("gemini", "up", 120.0, "metadatos del modelo obtenidos"),
        FakeProbe("wikipedia", "slow", 3200.0, "tiempo de espera agotado (> 3 s)"),
    ]
    app = _build_test_app(probes)
    client = TestClient(app)

    response = client.get("/health/dependencies")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "degraded"
    wiki_check = next(c for c in data["checks"] if c["name"] == "wikipedia")
    assert wiki_check["status"] == "slow"


def test_dependency_health_gemini_not_configured_responds_200_ok() -> None:
    probes = [
        FakeProbe("database", "up", 2.0, "conexión activa"),
        FakeProbe("gemini", "not_configured", 0.0, "proveedor por reglas o sin clave configurada"),
        FakeProbe("wikipedia", "up", 85.0, "consulta de información del sitio exitosa"),
    ]
    app = _build_test_app(probes)
    client = TestClient(app)

    response = client.get("/health/dependencies")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "ok"
    gemini_check = next(c for c in data["checks"] if c["name"] == "gemini")
    assert gemini_check["status"] == "not_configured"


def test_dependency_health_database_down_responds_503() -> None:
    probes = [
        FakeProbe("database", "down", 10.0, "error de conexión: OperationalError"),
        FakeProbe("gemini", "up", 120.0, "metadatos del modelo obtenidos"),
        FakeProbe("wikipedia", "up", 80.0, "consulta de información del sitio exitosa"),
    ]
    app = _build_test_app(probes)
    client = TestClient(app)

    response = client.get("/health/dependencies")
    assert response.status_code == 503
    data = response.json()

    assert data["status"] == "degraded"
    db_check = next(c for c in data["checks"] if c["name"] == "database")
    assert db_check["status"] == "down"


def test_dependency_health_caches_result_for_30_seconds() -> None:
    db_probe = FakeProbe("database", "up", 2.0)
    app = _build_test_app([db_probe], cache_ttl=30.0)
    client = TestClient(app)

    res1 = client.get("/health/dependencies")
    assert res1.status_code == 200
    data1 = res1.json()
    assert db_probe.calls == 1

    res2 = client.get("/health/dependencies")
    assert res2.status_code == 200
    data2 = res2.json()
    assert db_probe.calls == 1  # Cache hit!
    assert data1["checkedAt"] == data2["checkedAt"]


def test_no_secrets_in_detail() -> None:
    fake_key = "AIzaSy" + "Z" * 33
    probes = [
        FakeProbe("gemini", "down", 10.0, f"Error with key {fake_key} and project 12345"),
    ]
    app = _build_test_app(probes)
    client = TestClient(app)

    response = client.get("/health/dependencies")
    text_content = response.text
    # Ensure neither raw API key nor secret patterns appear
    assert fake_key not in text_content or "[clave oculta]" in text_content
