"""T020 (spec 006, quickstart V9): tiempo de creación del plan, con un backend falso.

Sin servidor, sin red y sin proveedores de IA: el script se carga desde backend/scripts.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from tests.unit.test_measure_duplication import EMAIL, PASSWORD, TOKEN, FakeBackend

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "measure_plan_latency.py"
REAL_CLIENT = httpx.Client


@pytest.fixture(scope="module")
def latency():
    spec = importlib.util.spec_from_file_location("measure_plan_latency", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class PlanBackend(FakeBackend):
    """Crea planes de reglas (o de la IA, con `ai`); el plan número `fail_on` responde 422."""

    def __init__(self, ai: bool = False, fail_on: int | None = None) -> None:
        super().__init__()
        self.ai = ai
        self.fail_on = fail_on
        self.plans = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if (method, path) == ("GET", "/api/v1/generator"):
            return httpx.Response(200, json={"provider": "gemini" if self.ai else "rules",
                                             "description": "Gemini" if self.ai else "Reglas"})
        if (method, path) == ("POST", "/api/v1/generation-plans"):
            self.bodies.append((method, path, json.loads(request.content)))
            self.plans += 1
            if self.plans == self.fail_on:
                return httpx.Response(422, json={"error": {"code": "INSUFFICIENT_EVIDENCE", "message": "…"}})
            generator = ({"usesAi": True, "fallback": self.plans == 2, "attempts": 2 if self.plans == 3 else 1}
                         if self.ai else {"usesAi": False, "fallback": False, "attempts": None})
            return httpx.Response(201, json={"id": f"gen-plan-{self.plans}", "version": 1, "status": "draft",
                                             "items": [{}, {}, {}], "validation": {"valid": True, "problems": []},
                                             "generator": generator})
        return super().__call__(request)


def run(latency, tmp_path, monkeypatch, backend, *extra):
    monkeypatch.setattr(latency.httpx, "Client", lambda **kwargs: REAL_CLIENT(
        transport=httpx.MockTransport(backend), **kwargs))
    monkeypatch.setenv("EVAL_EMAIL", EMAIL)
    monkeypatch.setenv("EVAL_PASSWORD", PASSWORD)
    (tmp_path / "tcp.txt").write_text("TCP", encoding="utf-8")
    return latency.main(["--corpus", str(tmp_path / "tcp.txt"), "--out", str(tmp_path / "out.json"), *extra])


def test_twenty_plans_in_a_row_with_the_v1_sequence_report_p50_p95_max_and_the_planner(latency, tmp_path,
                                                                                       monkeypatch):
    backend = PlanBackend()
    report = run(latency, tmp_path, monkeypatch, backend)
    sent = [body for method, path, body in backend.bodies if path == "/api/v1/generation-plans"]
    assert len(sent) == 20 and latency.DEFAULT_PLANS == 20
    assert sent[0]["resourceTypes"] == [{"type": "pregunta_detonante", "quantity": 1},
                                        {"type": "explicacion", "quantity": None},
                                        {"type": "item_opcion_multiple", "quantity": 2}]
    keys = [r["key"] for r in report["plans"]]
    assert len(set(keys)) == 20  # una clave por plan: la misma clave devolvería el mismo plan
    summary = report["summary"]
    assert (summary["created"], summary["failed"], summary["planners"]) == (20, 0, {"ai": 0, "rules": 20})
    assert summary["p50Ms"] <= summary["p95Ms"] <= summary["maxMs"] and summary["meetsRulesTarget"] is True
    written = (tmp_path / "out.json").read_text(encoding="utf-8")
    assert json.loads(written) == report
    assert EMAIL not in written and PASSWORD not in written and TOKEN not in written
    # No aprueba ni genera.
    assert not any("approve" in path or "generation-requests" in path for _, path, _ in backend.bodies)


def test_ai_planners_failures_and_attempts_are_counted(latency, tmp_path, monkeypatch):
    report = run(latency, tmp_path, monkeypatch, PlanBackend(ai=True, fail_on=4), "--plans", "5")
    summary = report["summary"]
    assert (summary["plans"], summary["created"], summary["failed"]) == (5, 4, 1)
    assert summary["planners"] == {"ai": 4, "rules": 0}
    assert summary["aiFallbacks"] == 1 and summary["aiAttempts"] == {"1": 3, "2": 1}
    assert summary["meetsRulesTarget"] is None  # la meta de 1 s es solo con reglas
    [failed] = [r for r in report["plans"] if r["status"] != 201]
    assert failed["errorCode"] == "INSUFFICIENT_EVIDENCE" and failed["ms"] is not None


def test_percentiles_and_the_rules_target(latency):
    records = [{"status": 201, "ms": float(ms), "planner": "rules", "usesAi": False, "fallback": False,
                "attempts": None, "valid": True} for ms in range(10, 210, 10)]
    summary = latency.summarize(records)
    assert (summary["p50Ms"], summary["p95Ms"], summary["maxMs"]) == (105.0, 190.5, 200.0)
    slow = [{**r, "ms": r["ms"] * 10} for r in records]
    assert latency.summarize(slow)["meetsRulesTarget"] is False
    assert "NO cumple" in latency.format_summary(latency.summarize(slow))


@pytest.mark.parametrize("api", ["https://api.plataformadocente.dev", "http://10.0.0.5:8000",
                                 "https://platform5e.onrender.com"])
def test_it_refuses_non_local_urls_before_any_request(latency, tmp_path, monkeypatch, api):
    backend = PlanBackend()
    with pytest.raises(SystemExit, match="Solo contra un backend local"):
        run(latency, tmp_path, monkeypatch, backend, "--api", api)
    assert backend.bodies == []


@pytest.mark.parametrize("api", ["http://127.0.0.1:8000/", "http://localhost:8000", "http://[::1]:8000"])
def test_local_urls_are_accepted(latency, api):
    assert latency.require_local(api) == api.rstrip("/")
