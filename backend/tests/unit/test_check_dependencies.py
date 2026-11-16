"""Unit tests for the dependency health check use case and probe adapters (QA-02 / EN-028)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import httpx
import pytest
from sqlalchemy import create_engine

from platform5e.application.ports.outbound.dependency_probe_port import DependencyProbePort, ProbeResult
from platform5e.application.use_cases.health.check_dependencies import (
    CheckDependencies,
    DependencyCheckResult,
)
from platform5e.infrastructure.adapters.database_probe_adapter import DatabaseProbeAdapter
from platform5e.infrastructure.adapters.gemini_probe_adapter import GeminiProbeAdapter
from platform5e.infrastructure.adapters.wikipedia_probe_adapter import WikipediaProbeAdapter


class DummyProbe:
    def __init__(self, name: str, status: str = "up", latency_ms: float = 10.0, detail: str = "ok") -> None:
        self.dependency_name = name
        self._status = status
        self._latency_ms = latency_ms
        self._detail = detail
        self.call_count = 0

    def probe(self, timeout_seconds: float) -> ProbeResult:
        self.call_count += 1
        return ProbeResult(
            name=self.dependency_name,
            status=self._status,
            latency_ms=self._latency_ms,
            detail=self._detail,
        )


def test_all_dependencies_up() -> None:
    probes = [
        DummyProbe("database", "up", 5.0, "connected"),
        DummyProbe("gemini", "up", 120.0, "model metadata retrieved"),
        DummyProbe("wikipedia", "up", 80.0, "siteinfo retrieved"),
    ]
    use_case = CheckDependencies(probes)
    result = use_case.execute()

    assert result.status == "ok"
    assert result.database_down is False
    assert len(result.checks) == 3
    names = [c.name for c in result.checks]
    assert names == ["database", "gemini", "wikipedia"]
    assert all(c.status == "up" for c in result.checks)
    assert result.checked_at


def test_gemini_down_marks_degraded() -> None:
    probes = [
        DummyProbe("database", "up", 5.0, "connected"),
        DummyProbe("gemini", "down", 50.0, "Gemini responded 503"),
        DummyProbe("wikipedia", "up", 80.0, "siteinfo retrieved"),
    ]
    use_case = CheckDependencies(probes)
    result = use_case.execute()

    assert result.status == "degraded"
    assert result.database_down is False
    gemini_check = next(c for c in result.checks if c.name == "gemini")
    assert gemini_check.status == "down"
    assert "503" in gemini_check.detail


def test_wikipedia_slow_marks_degraded() -> None:
    probes = [
        DummyProbe("database", "up", 5.0, "connected"),
        DummyProbe("gemini", "up", 100.0, "model metadata retrieved"),
        DummyProbe("wikipedia", "slow", 3500.0, "tiempo de espera agotado (> 3 s)"),
    ]
    use_case = CheckDependencies(probes)
    result = use_case.execute()

    assert result.status == "degraded"
    assert result.database_down is False
    wiki_check = next(c for c in result.checks if c.name == "wikipedia")
    assert wiki_check.status == "slow"


def test_gemini_not_configured_does_not_count_as_failure() -> None:
    probes = [
        DummyProbe("database", "up", 5.0, "connected"),
        DummyProbe("gemini", "not_configured", 0.0, "proveedor por reglas o sin clave configurada"),
        DummyProbe("wikipedia", "up", 80.0, "siteinfo retrieved"),
    ]
    use_case = CheckDependencies(probes)
    result = use_case.execute()

    assert result.status == "ok"
    assert result.database_down is False
    gemini_check = next(c for c in result.checks if c.name == "gemini")
    assert gemini_check.status == "not_configured"


def test_database_down_marks_database_down_and_degraded() -> None:
    probes = [
        DummyProbe("database", "down", 5.0, "error de conexión: OperationalError"),
        DummyProbe("gemini", "up", 100.0, "model metadata retrieved"),
        DummyProbe("wikipedia", "up", 80.0, "siteinfo retrieved"),
    ]
    use_case = CheckDependencies(probes)
    result = use_case.execute()

    assert result.status == "degraded"
    assert result.database_down is True


def test_cache_prevents_repeated_calls_within_ttl() -> None:
    probe = DummyProbe("database", "up")
    use_case = CheckDependencies([probe], cache_ttl_seconds=0.1)

    res1 = use_case.execute()
    assert probe.call_count == 1

    res2 = use_case.execute()
    assert probe.call_count == 1
    assert res1.checked_at == res2.checked_at

    time.sleep(0.12)

    res3 = use_case.execute()
    assert probe.call_count == 2


def test_probe_exception_captured_as_down() -> None:
    class FailingProbe:
        dependency_name = "flaky"

        def probe(self, timeout_seconds: float) -> ProbeResult:
            raise ConnectionError("Network unreachable")

    use_case = CheckDependencies([FailingProbe()])
    result = use_case.execute()

    assert result.status == "degraded"
    assert len(result.checks) == 1
    assert result.checks[0].status == "down"
    assert "ConnectionError" in result.checks[0].detail


def test_database_probe_adapter_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:")
    adapter = DatabaseProbeAdapter(engine)
    result = adapter.probe(timeout_seconds=3.0)

    assert result.name == "database"
    assert result.status == "up"
    assert result.latency_ms >= 0


def test_database_probe_adapter_error() -> None:
    engine = create_engine("sqlite:////nonexistent/dir/db.sqlite")
    adapter = DatabaseProbeAdapter(engine)
    result = adapter.probe(timeout_seconds=3.0)

    assert result.name == "database"
    assert result.status == "down"


def test_gemini_probe_adapter_not_configured() -> None:
    adapter = GeminiProbeAdapter(api_key=None, model="gemini-3.8-flash")
    result = adapter.probe(timeout_seconds=3.0)

    assert result.name == "gemini"
    assert result.status == "not_configured"
    assert result.latency_ms == 0.0


def test_gemini_probe_adapter_mocked_success() -> None:
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_client.get.return_value = mock_resp

    adapter = GeminiProbeAdapter(api_key="fake-key", model="gemini-3.8-flash", client=mock_client)
    result = adapter.probe(timeout_seconds=3.0)

    assert result.name == "gemini"
    assert result.status == "up"
    mock_client.get.assert_called_once()
    called_url = mock_client.get.call_args[0][0]
    assert "models/gemini-3.8-flash" in called_url
    assert mock_client.get.call_args[1]["headers"]["x-goog-api-key"] == "fake-key"


def test_gemini_probe_adapter_mocked_down() -> None:
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 503
    mock_client.get.return_value = mock_resp

    adapter = GeminiProbeAdapter(api_key="fake-key", model="gemini-3.8-flash", client=mock_client)
    result = adapter.probe(timeout_seconds=3.0)

    assert result.name == "gemini"
    assert result.status == "down"
    assert "503" in result.detail


def test_gemini_probe_adapter_mocked_timeout() -> None:
    mock_client = MagicMock()
    mock_client.get.side_effect = httpx.TimeoutException("timeout")

    adapter = GeminiProbeAdapter(api_key="fake-key", model="gemini-3.8-flash", client=mock_client)
    result = adapter.probe(timeout_seconds=3.0)

    assert result.name == "gemini"
    assert result.status == "slow"


def test_wikipedia_probe_adapter_mocked_success() -> None:
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_client.get.return_value = mock_resp

    adapter = WikipediaProbeAdapter(client=mock_client)
    result = adapter.probe(timeout_seconds=3.0)

    assert result.name == "wikipedia"
    assert result.status == "up"
    mock_client.get.assert_called_once()


def test_wikipedia_probe_adapter_mocked_down() -> None:
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_client.get.return_value = mock_resp

    adapter = WikipediaProbeAdapter(client=mock_client)
    result = adapter.probe(timeout_seconds=3.0)

    assert result.name == "wikipedia"
    assert result.status == "down"
    assert "404" in result.detail


def test_wikipedia_probe_adapter_mocked_timeout() -> None:
    mock_client = MagicMock()
    mock_client.get.side_effect = httpx.TimeoutException("timeout")

    adapter = WikipediaProbeAdapter(client=mock_client)
    result = adapter.probe(timeout_seconds=3.0)

    assert result.name == "wikipedia"
    assert result.status == "slow"
