"""Unit tests for measure_recovery.py (QA-18 RRe-1-G)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.error

import pytest

from performance.jmeter.measure_recovery import (
    probe_endpoint,
    run_recovery_monitoring,
    write_recovery_report,
)


def test_probe_endpoint_success() -> None:
    mock_resp = MagicMock()
    mock_resp.getcode.return_value = 200
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp):
        code, latency_ms = probe_endpoint("http://127.0.0.1:8000/health")
        assert code == 200
        assert latency_ms >= 0.0


def test_probe_endpoint_http_error() -> None:
    err = urllib.error.HTTPError("http://127.0.0.1:8000/health", 503, "Unavailable", {}, None)
    with patch("urllib.request.urlopen", side_effect=err):
        code, latency_ms = probe_endpoint("http://127.0.0.1:8000/health")
        assert code == 503
        assert latency_ms >= 0.0


def test_probe_endpoint_connection_failure() -> None:
    err = urllib.error.URLError("Connection refused")
    with patch("urllib.request.urlopen", side_effect=err):
        code, latency_ms = probe_endpoint("http://127.0.0.1:8000/health")
        assert code == 0
        assert latency_ms >= 0.0


def test_run_recovery_immediate_nominal() -> None:
    with patch("performance.jmeter.measure_recovery.probe_endpoint", return_value=(200, 35.0)):
        with patch("time.sleep", return_value=None):
            records, recovery_time = run_recovery_monitoring(
                duration_s=3,
                interval_s=0.01,
            )
            assert len(records) == 3
            assert recovery_time == 0.0
            assert all(r["nominal"] for r in records)


def test_run_recovery_delayed_nominal() -> None:
    responses = [(503, 50.0), (503, 60.0), (200, 40.0)]

    def side_effect(*args, **kwargs):
        return responses.pop(0)

    with patch("performance.jmeter.measure_recovery.probe_endpoint", side_effect=side_effect):
        with patch("time.sleep", return_value=None):
            records, recovery_time = run_recovery_monitoring(
                duration_s=3,
                interval_s=0.01,
            )
            assert len(records) == 3
            assert not records[0]["nominal"]
            assert not records[1]["nominal"]
            assert records[2]["nominal"]
            assert recovery_time > 0.0


def test_write_recovery_report(tmp_path: Path) -> None:
    out_file = tmp_path / "recovery.txt"
    records = [
        {
            "probe": 1,
            "timestamp": "2026-11-18 08:00:00",
            "elapsed_s": 0.0,
            "status_code": 200,
            "latency_ms": 32.5,
            "nominal": True,
        }
    ]
    write_recovery_report(records, 0.0, out_file, "http://127.0.0.1:8000/health")
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "RRe-1-G" in content
    assert "200" in content
    assert "32.5 ms" in content
