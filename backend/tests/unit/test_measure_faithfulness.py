"""T027 (c), spec 006: la fidelidad (faithfulness de Ragas) de los recursos de los informes de P4.

Juez falso (sin Ragas ni Gemini), backend falso y similitud léxica: sin red y sin proveedores de IA.
"""

from __future__ import annotations

import importlib.util
import json
import threading
import time
from pathlib import Path

import httpx
import pytest

from tests.unit.test_measure_duplication import EMAIL, PASSWORD, FallbackBackend

REAL_CLIENT = httpx.Client  # antes de reemplazarlo: un test corre la medición dos veces
SCRIPT = Path(__file__).resolve().parents[2] / "evaluation" / "measure_duplication.py"
CITED = {
    "r1": ["El control de flujo de TCP evita saturar al receptor.", "TCP numera los segmentos."],
    "r2": [],  # sin citas: se omite
    "r3": ["UDP no establece conexión."],
}


@pytest.fixture(scope="module")
def measure():
    spec = importlib.util.spec_from_file_location("measure_duplication_faithfulness", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class CitingBackend(FallbackBackend):
    """r1 (explicación) y r2 (glosario) de la IA, y r3 (ítem) del respaldo. r2 no cita el material."""

    def __call__(self, request):
        response = super().__call__(request)
        if (request.method, request.url.path) == ("GET", "/api/v1/units/u1/resources"):
            resources = response.json()
            for resource in resources:
                resource["evidence"] = [{"id": f"frag-{n}", "text": text, "location": "p. 1", "documentId": "d1",
                                         "documentName": "tcp.txt"} for n, text in enumerate(CITED[resource["id"]])]
            return httpx.Response(200, json=resources)
        return response


class FakeJudge:
    """Juez falso: 0,95 para r1 y 0,80 para r3, que reconoce por su contexto. Puede fallar con un recurso."""

    def __init__(self, fail_on: str | None = None, delay: float = 0.0) -> None:
        self.rows: list[dict] = []
        self.models: list[str] = []
        self.fail_on = fail_on
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def __call__(self, model: str):
        self.models.append(model)

        def evaluate_one(row: dict) -> dict:
            with self.lock:
                self.rows.append(row)
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            try:
                time.sleep(self.delay)
                if self.fail_on and self.fail_on in row["retrieved_contexts"][0]:
                    raise TimeoutError("el juez no respondió a tiempo")
                return {"faithfulness": 0.95 if "TCP" in row["retrieved_contexts"][0] else 0.80}
            finally:
                with self.lock:
                    self.active -= 1

        return evaluate_one


def run_with_judge(measure, tmp_path, monkeypatch, judge, *extra, backend=None):
    monkeypatch.setattr(measure.httpx, "Client", lambda **kwargs: REAL_CLIENT(
        transport=httpx.MockTransport(backend or CitingBackend()), **kwargs))
    monkeypatch.setenv("EVAL_EMAIL", EMAIL)
    monkeypatch.setenv("EVAL_PASSWORD", PASSWORD)
    (tmp_path / "tcp.txt").write_text("TCP", encoding="utf-8")
    return measure.main(["--corpus", str(tmp_path / "tcp.txt"), "--poll", "0", "--similarity", "lexical", *extra],
                        judge_factory=judge)


def test_each_run_scores_the_cited_resources_and_stores_their_contexts(measure, tmp_path, monkeypatch):
    judge = FakeJudge()
    report = run_with_judge(measure, tmp_path, monkeypatch, judge, "--mode", "plan", "--runs", "2",
                            "--faithfulness", "--judge-model", "juez-falso", "--out", str(tmp_path / "plan.json"))
    run = report["runs"][0]
    # Los textos citados quedan en el informe: un recálculo posterior no necesita la API.
    assert [r["contexts"] for r in run["resources"]] == [CITED["r1"], CITED["r2"], CITED["r3"]]
    assert [r["faithfulness"] for r in run["resources"]] == [{"score": 0.95}, {"skipped": "noCitations"},
                                                             {"score": 0.8}]
    faithfulness = run["faithfulness"]
    assert (faithfulness["mean"], faithfulness["atLeastTarget"]) == (0.875, 0.5)
    assert (faithfulness["scored"], faithfulness["skipped"], faithfulness["errors"]) == (2, 1, 0)
    assert faithfulness["byType"]["explicacion"] == {"mean": 0.95, "atLeastTarget": 1.0, "scored": 1, "skipped": 0,
                                                     "errors": 0}
    assert faithfulness["byType"]["glosario"] == {"mean": None, "atLeastTarget": None, "scored": 0, "skipped": 1,
                                                  "errors": 0}
    assert faithfulness["byType"]["item_opcion_multiple"]["mean"] == 0.8
    # Solo los recursos de la IA: r1 (r2 no cita y r3 es del respaldo).
    assert faithfulness["aiOnly"] == {"mean": 0.95, "atLeastTarget": 1.0, "scored": 1, "skipped": 1, "errors": 0}

    # La pregunta es la indicación del pedido; la respuesta, el recurso sin su título; el contexto, lo citado.
    row = next(r for r in judge.rows if r["retrieved_contexts"] == CITED["r1"])
    assert row["user_input"] == measure.INSTRUCTIONS and not row["response"].startswith("Control de flujo")
    assert row["response"] == run["resources"][0]["sentenceText"]
    assert len(judge.rows) == 4 and judge.models == ["juez-falso"]

    summary = report["summary"]["faithfulness"]
    assert (summary["mean"], summary["scored"], summary["skipped"], summary["meanPerRun"]) == (0.875, 4, 2, 0.875)
    assert summary["aiOnly"]["scored"] == 2 and summary["byType"]["item_opcion_multiple"]["scored"] == 2
    assert report["faithfulnessJudge"]["judge"] == "juez-falso" and report["faithfulnessJudge"]["target"] == 0.9


def test_a_judge_error_is_recorded_and_the_run_continues(measure, tmp_path, monkeypatch):
    judge = FakeJudge(fail_on="UDP")
    report = run_with_judge(measure, tmp_path, monkeypatch, judge, "--mode", "plan", "--runs", "1",
                            "--faithfulness", "--out", str(tmp_path / "plan.json"))
    run = report["runs"][0]
    assert run["resources"][2]["faithfulness"] == {"error": "TimeoutError: el juez no respondió a tiempo"}
    assert (run["faithfulness"]["mean"], run["faithfulness"]["scored"], run["faithfulness"]["errors"]) == (0.95, 1, 1)
    assert report["summary"]["faithfulness"]["errors"] == 1 and run["metrics"]["resources"] == 3


def test_a_missing_score_from_the_judge_is_an_error(measure):
    resources = [{"id": "r1", "type": "explicacion", "drafter": "ai", "sentenceText": "Texto.", "contexts": ["F"]}]
    scored = measure.score_faithfulness([{"resources": resources}], lambda row: {"faithfulness": float("nan")},
                                        measure.INSTRUCTIONS, concurrency=1)
    assert scored == 1 and resources[0]["faithfulness"] == {"error": "el juez no devolvió puntaje"}


def test_the_judge_calls_run_with_a_small_concurrency_limit_and_print_progress(measure, capsys):
    resources = [{"id": f"r{n}", "type": "glosario", "drafter": "ai", "sentenceText": "Texto.", "contexts": ["TCP"]}
                 for n in range(6)]
    judge = FakeJudge(delay=0.02)
    measure.score_faithfulness([{"resources": resources}], judge("m"), measure.INSTRUCTIONS, concurrency=2)
    assert judge.max_active == 2 and all(r["faithfulness"] == {"score": 0.95} for r in resources)
    assert "Fidelidad: 6/6" in capsys.readouterr().err


def test_recompute_reads_the_cited_texts_once_and_later_recomputes_need_no_api(measure, tmp_path, monkeypatch):
    first = run_with_judge(measure, tmp_path, monkeypatch, FakeJudge(), "--mode", "plan", "--runs", "1",
                           "--out", str(tmp_path / "plan.json"))
    for resource in first["runs"][0]["resources"]:  # un informe v4: sin los textos citados
        resource.pop("contexts")
    (tmp_path / "v4.json").write_text(json.dumps(first, ensure_ascii=False), encoding="utf-8")

    judge = FakeJudge()
    recomputed = run_with_judge(measure, tmp_path, monkeypatch, judge, "--recompute", "--from",
                                str(tmp_path / "v4.json"), "--faithfulness", "--out", str(tmp_path / "v4r.json"))
    assert recomputed["runs"][0]["resources"][0]["contexts"] == CITED["r1"]
    assert recomputed["runs"][0]["faithfulness"]["scored"] == 2 and len(judge.rows) == 2

    # Sin cuenta ni juez: los puntajes guardados se vuelven a resumir, sin llamar a la API ni al juez.
    monkeypatch.delenv("EVAL_EMAIL")
    again = measure.main(["--recompute", "--from", str(tmp_path / "v4r.json"), "--similarity", "lexical",
                          "--out", str(tmp_path / "v4rr.json")],
                         judge_factory=lambda model: pytest.fail("no debe llamar al juez"))
    assert again["summary"]["faithfulness"] == recomputed["summary"]["faithfulness"]

    # Con --faithfulness otra vez y el mismo juez, solo se califican los que no tienen puntaje.
    judge = FakeJudge()
    measure.main(["--recompute", "--from", str(tmp_path / "v4r.json"), "--similarity", "lexical", "--faithfulness",
                  "--out", str(tmp_path / "v4rr.json")], judge_factory=judge)
    assert judge.rows == []


def test_recompute_with_faithfulness_stops_if_the_cited_texts_are_missing_and_there_is_no_account(
        measure, tmp_path, monkeypatch):
    report = {"mode": "plan", "threshold": 0.885, "runs": [{"requestId": "gen-req-1", "resources": [
        {"id": "r1", "type": "explicacion", "title": "T", "text": "T\nUn texto.", "sentenceText": "Un texto."}]}]}
    (tmp_path / "v4.json").write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.delenv("EVAL_EMAIL", raising=False)
    with pytest.raises(SystemExit, match="EVAL_EMAIL"):
        measure.main(["--recompute", "--from", str(tmp_path / "v4.json"), "--similarity", "lexical",
                      "--faithfulness", "--out", str(tmp_path / "out.json")], judge_factory=FakeJudge())


def test_the_comparison_reports_the_faithfulness_difference_and_the_090_target(measure):
    def summary(mean, ai_mean):
        return {"duplicateRate": 0.1, "resourcesPerRequest": 16, "faithfulness": {
            "mean": mean, "atLeastTarget": 0.6, "scored": 10, "skipped": 0, "errors": 0,
            "aiOnly": {"mean": ai_mean, "atLeastTarget": 0.5, "scored": 8, "skipped": 0, "errors": 0}}}

    result = measure.compare(summary(0.93, 0.92), summary(0.91, 0.88))["faithfulness"]
    assert result == {"baseline": 0.93, "plan": 0.91, "difference": -0.02, "planMeetsTarget": True,
                      "baselineAtLeastTarget": 0.6, "planAtLeastTarget": 0.6,
                      "aiOnly": {"baseline": 0.92, "plan": 0.88, "difference": -0.04, "planMeetsTarget": False,
                                 "baselineAtLeastTarget": 0.5, "planAtLeastTarget": 0.5}}
    assert "faithfulness" not in measure.compare({"duplicateRate": 0.1}, {"duplicateRate": 0.05})


def test_without_ragas_the_measurement_stops_before_generating(measure, tmp_path, monkeypatch):
    real_find_spec = measure.importlib.util.find_spec
    monkeypatch.setattr(measure.importlib.util, "find_spec",
                        lambda name, *a: None if name == "ragas" else real_find_spec(name, *a))
    backend = CitingBackend()
    with pytest.raises(SystemExit, match="Ragas"):
        run_with_judge(measure, tmp_path, monkeypatch, None, "--mode", "plan", "--runs", "1", "--faithfulness",
                       "--out", str(tmp_path / "plan.json"), backend=backend)
    assert backend.bodies == []
