"""GEN-P2 (T019): medición de la duplicación con y sin plan (P4), con un backend falso y embeddings falsos.

Sin servidor, sin red y sin proveedores de IA: el script se carga desde backend/evaluation.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "evaluation" / "measure_duplication.py"
EMAIL, PASSWORD, TOKEN = "p4.medicion@correo.pe", "clave-secreta-9", "token-secreto-123"


@pytest.fixture(scope="module")
def measure():
    spec = importlib.util.spec_from_file_location("measure_duplication", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def fixed(matrix):
    return lambda texts: matrix


def test_the_duplicate_rate_counts_pairs_over_the_threshold(measure):
    matrix = [[1.0, 0.9, 0.2], [0.9, 1.0, 0.86], [0.2, 0.86, 1.0]]
    metrics = measure.duplication(["a", "b", "c"], fixed(matrix), 0.85)
    assert (metrics["resources"], metrics["pairs"], metrics["duplicatePairs"]) == (3, 3, 2)
    assert metrics["duplicateRate"] == pytest.approx(2 / 3, abs=1e-4)
    assert metrics["meanMaxSimilarity"] == pytest.approx((0.9 + 0.9 + 0.86) / 3, abs=1e-4)
    assert [(d["first"], d["second"]) for d in metrics["duplicates"]] == [(0, 1), (1, 2)]


def test_one_resource_or_none_has_no_pairs(measure):
    assert measure.duplication(["solo"], fixed([[1.0]]), 0.85)["duplicateRate"] == 0.0
    assert measure.duplication([], fixed([]), 0.85)["meanMaxSimilarity"] is None


def test_the_lexical_similarity_is_the_one_of_most_similar(measure):
    same = "El control de flujo de TCP evita saturar al receptor."
    matrix = measure.lexical_matrix([same, same, "Los satélites orbitan sobre el ecuador."])
    assert matrix[0][1] == 1.0 and matrix[0][2] < 0.2


def test_the_embedding_similarity_is_the_cosine_of_each_pair(measure):
    class Embedder:
        model = "embeddings-falsos"

        def embed_documents(self, texts):
            return [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]][: len(texts)]

    matrix = measure.embedding_matrix(Embedder())(["a", "b", "c"])
    assert matrix[0][1] == pytest.approx(1.0) and matrix[0][2] == pytest.approx(0.0)
    similarity, label = measure.choose_similarity("auto", lambda: Embedder())
    assert label.startswith("embeddings") and "embeddings-falsos" in label
    similarity, label = measure.choose_similarity("auto", lambda: None)
    assert similarity is measure.lexical_matrix and "provisional" in label
    with pytest.raises(SystemExit):
        measure.choose_similarity("embeddings", lambda: None)


def test_the_resource_text_includes_title_body_options_and_structure(measure):
    text = measure.resource_text({"title": "T", "body": "Cuerpo", "options": [{"text": "Opción A"}],
                                  "structure": {"steps": [{"title": "Paso", "text": "Hacer"}]}})
    assert text.split("\n") == ["T", "Cuerpo", "Opción A", "Paso", "Hacer"]


def test_the_summary_and_the_comparison_with_the_p4_target(measure):
    runs = [{"metrics": {"duplicateRate": 0.1, "meanMaxSimilarity": 0.5, "resources": 16, "pairs": 120,
                         "duplicatePairs": 12}},
            {"metrics": {"duplicateRate": 0.0, "meanMaxSimilarity": 0.3, "resources": 14, "pairs": 91,
                         "duplicatePairs": 0}},
            {"failure": {"stage": "wait", "code": "TIMEOUT"}}]
    summary = measure.summarize(runs)
    assert summary == {"runs": 3, "finishedRuns": 2, "duplicateRate": round(12 / 211, 4),
                       "meanDuplicateRatePerRun": 0.05, "meanMaxSimilarity": 0.4, "resourcesPerRequest": 15.0}
    baseline = {"duplicateRate": 0.2, "resourcesPerRequest": 15.0}
    assert measure.compare(baseline, {"duplicateRate": 0.04, "resourcesPerRequest": 15.0}) == {
        "reduction": 0.8, "meetsTarget": True, "resourcesKept": True}
    assert measure.compare(baseline, {"duplicateRate": 0.04, "resourcesPerRequest": 12.0})["meetsTarget"] is False
    assert measure.compare(baseline, {"duplicateRate": 0.12, "resourcesPerRequest": 15.0})["meetsTarget"] is False


class FakeBackend:
    """Backend falso: cuenta, curso con el corpus ya procesado, plan, aprobación y un pedido con 3 recursos, dos de
    ellos iguales."""

    def __init__(self) -> None:
        self.bodies: list[tuple[str, str, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else {}
        self.bodies.append((method, path, body))
        unit = {"id": "u1", "title": "Protocolos", "outcomes": [{"id": "ra-1"}]}
        if (method, path) == ("POST", "/api/v1/accounts"):
            return httpx.Response(201, json={"token": TOKEN})
        if (method, path) == ("GET", "/api/v1/courses"):
            return httpx.Response(200, json=[{"code": "EVAL-RAG", "units": [unit]}])
        if (method, path) == ("GET", "/api/v1/documents"):
            return httpx.Response(200, json=[{"unitId": "u1", "fileName": "tcp.txt", "status": "procesado"}])
        if (method, path) == ("POST", "/api/v1/generation-plans"):
            return httpx.Response(201, json={"id": "gen-plan-1", "version": 1, "items": [{}, {}],
                                             "generator": {"usesAi": False}})
        if (method, path) == ("POST", "/api/v1/generation-plans/gen-plan-1/approve"):
            return httpx.Response(200, json={"id": "gen-plan-1", "version": 1, "status": "approved"})
        if (method, path) == ("POST", "/api/v1/generation-requests"):
            return httpx.Response(202, json={"id": "gen-req-1", "status": "queued"})
        if (method, path) == ("GET", "/api/v1/generation-requests/gen-req-1"):
            return httpx.Response(200, json={"status": "succeeded", "steps": [
                {"resourceType": "explicacion", "planItemPosition": 1, "resourceIds": ["r1", "r2"],
                 "rejections": [{"kind": "plan"}], "generator": {"usesAi": False, "fallback": False}},
                {"resourceType": "glosario", "planItemPosition": 2, "resourceIds": ["r3"], "rejections": [],
                 "generator": {"usesAi": False, "fallback": False}}]})
        if (method, path) == ("GET", "/api/v1/units/u1/resources"):
            same = "El control de flujo de TCP evita que el emisor sature al receptor."
            return httpx.Response(200, json=[
                {"id": "r1", "title": "Control de flujo", "body": same},
                {"id": "r2", "title": "Control de flujo", "body": same},
                {"id": "r3", "title": "Datagramas", "body": "El datagrama de UDP lleva puertos y suma de control."},
            ])
        return httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": path}})


@pytest.mark.parametrize("mode", ["plan", "baseline"])
def test_a_run_against_a_fake_backend_writes_the_report_without_secrets(measure, tmp_path, monkeypatch, mode):
    backend = FakeBackend()
    real_client = httpx.Client
    monkeypatch.setattr(measure.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(backend), **kwargs))
    monkeypatch.setenv("EVAL_EMAIL", EMAIL)
    monkeypatch.setenv("EVAL_PASSWORD", PASSWORD)
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "tcp.txt").write_text("TCP", encoding="utf-8")
    out = tmp_path / "p4" / f"{mode}.json"
    report = measure.main(["--mode", mode, "--runs", "2", "--quantity", "2", "--similarity", "lexical",
                           "--corpus", str(tmp_path / "corpus"), "--out", str(out), "--poll", "0"])

    written = out.read_text(encoding="utf-8")
    assert json.loads(written) == report
    assert EMAIL not in written and PASSWORD not in written and TOKEN not in written
    assert report["similarity"].startswith("lexical") and report["threshold"] == 0.85
    assert report["summary"]["finishedRuns"] == 2 and report["summary"]["resourcesPerRequest"] == 3
    run = report["runs"][0]
    assert run["metrics"]["duplicatePairs"] == 1 and run["metrics"]["pairs"] == 3
    assert run["metrics"]["duplicates"][0]["titles"] == ["Control de flujo", "Control de flujo"]
    assert run["rejectionKinds"] == {"plan": 1}
    generated = [body for method, path, body in backend.bodies if path == "/api/v1/generation-requests"]
    if mode == "plan":
        assert generated[0] == {"planId": "gen-plan-1", "planVersion": 1}
        plan = next(body for method, path, body in backend.bodies if path == "/api/v1/generation-plans")
        assert plan["resourceTypes"][0] == {"type": "pregunta_detonante", "quantity": 2} and len(plan["resourceTypes"]) == 8
    else:
        assert generated[0]["mode"] == "sequence" and generated[0]["quantity"] == 2
        assert len(generated[0]["resourceTypes"]) == 8
        assert not any(path == "/api/v1/generation-plans" for _, path, _ in backend.bodies)


def test_the_comparison_is_added_with_a_baseline_report(measure, tmp_path, monkeypatch):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"summary": {"duplicateRate": 0.5, "resourcesPerRequest": 3}}), encoding="utf-8")
    backend = FakeBackend()
    real_client = httpx.Client
    monkeypatch.setattr(measure.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(backend), **kwargs))
    monkeypatch.setenv("EVAL_EMAIL", EMAIL)
    monkeypatch.setenv("EVAL_PASSWORD", PASSWORD)
    (tmp_path / "tcp.txt").write_text("TCP", encoding="utf-8")
    report = measure.main(["--mode", "plan", "--runs", "1", "--similarity", "lexical", "--corpus",
                           str(tmp_path / "tcp.txt"), "--out", str(tmp_path / "plan.json"), "--poll", "0",
                           "--compare", str(baseline)])
    assert report["comparison"] == {"reduction": round(1 - round(1 / 3, 4) / 0.5, 4), "meetsTarget": False,
                                    "resourcesKept": True}


def test_invalid_arguments_and_missing_credentials_stop_before_any_call(measure, tmp_path, monkeypatch):
    monkeypatch.delenv("EVAL_EMAIL", raising=False)
    out = str(tmp_path / "x.json")
    with pytest.raises(SystemExit):
        measure.main(["--mode", "plan", "--out", out])
    monkeypatch.setenv("EVAL_EMAIL", EMAIL)
    monkeypatch.setenv("EVAL_PASSWORD", PASSWORD)
    with pytest.raises(SystemExit):
        measure.main(["--mode", "plan", "--quantity", "6", "--out", out])
    with pytest.raises(SystemExit):
        measure.main(["--mode", "plan", "--threshold", "0", "--out", out])


def test_the_baseline_stops_if_the_server_still_creates_implicit_plans(measure, tmp_path, monkeypatch):
    """La línea base se mide en el mismo servidor con GENERATION_IMPLICIT_PLAN=false: si el pedido trae un plan, el
    servidor no tiene el interruptor apagado y la medición se detiene sin escribir un informe engañoso."""

    class ImplicitBackend(FakeBackend):
        def __call__(self, request):
            if (request.method, request.url.path) == ("POST", "/api/v1/generation-requests"):
                return httpx.Response(202, json={"id": "gen-req-1", "status": "queued", "planId": "gen-plan-9"})
            return super().__call__(request)

    real_client = httpx.Client
    monkeypatch.setattr(measure.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(ImplicitBackend()), **kwargs))
    monkeypatch.setenv("EVAL_EMAIL", EMAIL)
    monkeypatch.setenv("EVAL_PASSWORD", PASSWORD)
    (tmp_path / "tcp.txt").write_text("TCP", encoding="utf-8")
    out = tmp_path / "baseline.json"
    with pytest.raises(SystemExit) as stopped:
        measure.main(["--mode", "baseline", "--runs", "2", "--similarity", "lexical", "--corpus",
                      str(tmp_path / "tcp.txt"), "--out", str(out), "--poll", "0"])
    assert "GENERATION_IMPLICIT_PLAN=false" in str(stopped.value)
    assert not out.exists()


def test_the_report_records_whether_the_requests_had_a_plan(measure, tmp_path, monkeypatch):
    backend = FakeBackend()
    real_client = httpx.Client
    monkeypatch.setattr(measure.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(backend), **kwargs))
    monkeypatch.setenv("EVAL_EMAIL", EMAIL)
    monkeypatch.setenv("EVAL_PASSWORD", PASSWORD)
    (tmp_path / "tcp.txt").write_text("TCP", encoding="utf-8")
    report = measure.main(["--mode", "baseline", "--runs", "1", "--similarity", "lexical", "--corpus",
                           str(tmp_path / "tcp.txt"), "--out", str(tmp_path / "b.json"), "--poll", "0"])
    assert report["runs"][0]["requestPlanId"] is None
    assert "GENERATION_IMPLICIT_PLAN=false" in report["server"]
