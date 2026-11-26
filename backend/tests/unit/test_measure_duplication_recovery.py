"""P4 (spec 006): la medición no pierde corridas ni puntajes del juez si algo falla después de generar.

Backend y juez falsos, similitud léxica: sin red y sin proveedores de IA.
"""

from __future__ import annotations

import json

import httpx
import pytest

from tests.unit.test_measure_duplication import EMAIL, PASSWORD
from tests.unit.test_measure_faithfulness import REAL_CLIENT, CitingBackend, FakeJudge, measure  # noqa: F401


def fake_api(measure, monkeypatch, backend):
    monkeypatch.setattr(measure.httpx, "Client", lambda **kwargs: REAL_CLIENT(
        transport=httpx.MockTransport(backend), **kwargs))
    monkeypatch.setenv("EVAL_EMAIL", EMAIL)
    monkeypatch.setenv("EVAL_PASSWORD", PASSWORD)


def args_for(tmp_path, *extra):
    (tmp_path / "tcp.txt").write_text("TCP", encoding="utf-8")
    return ["--corpus", str(tmp_path / "tcp.txt"), "--poll", "0", "--similarity", "lexical", *extra]


def test_a_missing_compare_report_stops_before_generating(measure, tmp_path, monkeypatch):
    backend = CitingBackend()
    fake_api(measure, monkeypatch, backend)
    missing = tmp_path / "v5-gemini-baseline.json"
    with pytest.raises(SystemExit, match="--compare.*v5-gemini-baseline.json"):
        measure.main(args_for(tmp_path, "--mode", "plan", "--runs", "1", "--out", str(tmp_path / "plan.json"),
                              "--compare", str(missing)), judge_factory=FakeJudge())
    assert backend.bodies == []  # ni siquiera inició sesión

    (tmp_path / "sin-resumen.json").write_text(json.dumps({"runs": []}), encoding="utf-8")
    with pytest.raises(SystemExit, match="no tiene resumen"):
        measure.main(args_for(tmp_path, "--mode", "plan", "--out", str(tmp_path / "plan.json"),
                              "--compare", str(tmp_path / "sin-resumen.json")))
    with pytest.raises(SystemExit, match="--from.*no-existe.json"):
        measure.main(args_for(tmp_path, "--recompute", "--from", str(tmp_path / "no-existe.json"),
                              "--out", str(tmp_path / "out.json")))
    assert backend.bodies == []


def test_a_comparison_error_still_writes_the_report_with_its_runs_and_scores(measure, tmp_path, monkeypatch, capsys):
    fake_api(measure, monkeypatch, CitingBackend())
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"summary": {"duplicateRate": 0.1}}), encoding="utf-8")

    def broken(old, new):
        raise KeyError("resourcesPerRequest")

    monkeypatch.setattr(measure, "compare", broken)
    out = tmp_path / "plan.json"
    report = measure.main(args_for(tmp_path, "--mode", "plan", "--runs", "2", "--faithfulness", "--out", str(out),
                                   "--compare", str(baseline)), judge_factory=FakeJudge())
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written == report and len(written["runs"]) == 2 and "comparison" not in written
    assert written["comparisonError"] == "KeyError: 'resourcesPerRequest'"
    assert written["summary"]["faithfulness"]["scored"] == 4
    assert not out.with_name("plan.partial.json").exists()  # el informe final reemplaza al parcial
    assert "--recompute --from" in capsys.readouterr().err


def test_a_partial_report_is_written_after_each_run(measure, tmp_path, monkeypatch):
    fake_api(measure, monkeypatch, CitingBackend())
    real_run = measure.measure_run
    calls = []

    def crashing_run(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("se cayó el backend")
        return real_run(*args, **kwargs)

    monkeypatch.setattr(measure, "measure_run", crashing_run)
    out = tmp_path / "plan.json"
    with pytest.raises(RuntimeError):
        measure.main(args_for(tmp_path, "--mode", "plan", "--runs", "3", "--out", str(out)))
    partial = json.loads(out.with_name("plan.partial.json").read_text(encoding="utf-8"))
    assert [run["requestId"] for run in partial["runs"]] == ["gen-req-1"] and partial["partial"] is True
    assert partial["runs"][0]["resources"][0]["contexts"]  # con los textos citados, para recalcular después


def test_judge_scores_are_saved_as_they_arrive(measure, tmp_path, monkeypatch):
    """Si la medición se corta mientras califica, los puntajes ya recibidos quedan en el informe."""
    fake_api(measure, monkeypatch, CitingBackend())
    judged = []

    def factory(model):
        def evaluate_one(row):
            judged.append(row)
            if len(judged) == 2:
                raise KeyboardInterrupt  # se corta la medición, no es un error de un recurso
            return {"faithfulness": 0.95}
        return evaluate_one

    out = tmp_path / "plan.json"
    with pytest.raises(KeyboardInterrupt):
        measure.main(args_for(tmp_path, "--mode", "plan", "--runs", "1", "--faithfulness", "--judge-concurrency",
                              "1", "--out", str(out)), judge_factory=factory)
    saved = json.loads(out.read_text(encoding="utf-8"))
    scores = [r.get("faithfulness") for r in saved["runs"][0]["resources"]]
    assert {"score": 0.95} in scores and len(saved["runs"]) == 1


class PlannedBackend(CitingBackend):
    """Como la API real, el pedido creado desde un plan vuelve con su `planId` (GenerationRequestStatus)."""

    def __call__(self, request):
        response = super().__call__(request)
        if (request.method, request.url.path) == ("POST", "/api/v1/generation-requests"):
            return httpx.Response(202, json={**response.json(), "planId": "gen-plan-1", "planVersion": 1})
        return response


def without_key(run):
    return {k: v for k, v in run.items() if k != "key"}


@pytest.mark.parametrize("faithfulness", [False, True])
def test_from_requests_rebuilds_the_report_that_measure_run_builds(measure, tmp_path, monkeypatch, faithfulness):
    fake_api(measure, monkeypatch, PlannedBackend())
    extra = ["--faithfulness"] if faithfulness else []
    measured = measure.main(args_for(tmp_path, "--mode", "plan", "--runs", "1", *extra,
                                     "--out", str(tmp_path / "measured.json")), judge_factory=FakeJudge())
    backend = PlannedBackend()
    fake_api(measure, monkeypatch, backend)
    rebuilt = measure.main(args_for(tmp_path, "--mode", "plan", "--from-requests", "gen-req-1", *extra,
                                    "--out", str(tmp_path / "rebuilt.json")), judge_factory=FakeJudge())

    assert [without_key(r) for r in rebuilt["runs"]] == [without_key(r) for r in measured["runs"]]
    assert rebuilt["runs"][0]["key"] is None and rebuilt["fromRequests"] == ["gen-req-1"]
    assert rebuilt["summary"] == measured["summary"]
    # Sin generar: ni planes ni pedidos nuevos (el falso registra todos los POST).
    assert [path for method, path, _ in backend.bodies if method == "POST"] == ["/api/v1/accounts"]


def test_from_requests_checks_the_mode_against_the_request(measure, tmp_path, monkeypatch):
    fake_api(measure, monkeypatch, CitingBackend())
    with pytest.raises(SystemExit, match="gen-req-1.*plan.*--mode baseline"):
        measure.main(args_for(tmp_path, "--mode", "baseline", "--from-requests", "gen-req-1",
                              "--out", str(tmp_path / "b.json")))
    with pytest.raises(SystemExit, match="--mode"):
        measure.main(args_for(tmp_path, "--from-requests", "gen-req-1", "--out", str(tmp_path / "b.json")))
