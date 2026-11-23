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
    assert (summary["runs"], summary["finishedRuns"], summary["duplicateRate"]) == (3, 2, round(12 / 211, 4))
    assert (summary["meanDuplicateRatePerRun"], summary["meanMaxSimilarity"], summary["resourcesPerRequest"]) == (
        0.05, 0.4, 15.0)
    assert summary["steps"] == 0 and summary["planGenerators"] == {"ai": 0, "rules": 0} and summary["aiOnly"] is None
    assert summary["sentenceNearDuplicateRate"] is None and summary["crossTypeSentenceRate"] is None
    baseline = {"duplicateRate": 0.2, "resourcesPerRequest": 15.0}
    result = measure.compare(baseline, {"duplicateRate": 0.04, "resourcesPerRequest": 15.0})
    assert (result["reduction"], result["meetsTarget"], result["resourcesKept"]) == (0.8, True, True)
    assert result["crossTypeSentenceReduction"] is None and "aiOnly" not in result
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
    comparison = report["comparison"]
    assert comparison["reduction"] == round(1 - round(1 / 3, 4) / 0.5, 4)
    assert (comparison["meetsTarget"], comparison["resourcesKept"]) == (False, True)


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


def test_each_run_counts_ai_and_fallback_steps_and_plan_warnings(measure, tmp_path, monkeypatch):
    """Corrección tras P4: la comparación muestra cuántos pasos redactó la IA, cuántos el respaldo por reglas y cuántos
    avisos de solapamiento del plan hubo (recursos de la IA entregados con `planWarning`)."""

    class MixedBackend(FakeBackend):
        def __call__(self, request):
            if (request.method, request.url.path) == ("GET", "/api/v1/generation-requests/gen-req-1"):
                return httpx.Response(200, json={"status": "succeeded", "steps": [
                    {"resourceType": "explicacion", "planItemPosition": 1, "resourceIds": ["r1", "r2"],
                     "rejections": [], "generator": {"usesAi": True, "fallback": False},
                     "planWarnings": [{"title": "Control de flujo", "reason": "desarrolla «UDP»", "resourceId": "r2"}]},
                    {"resourceType": "glosario", "planItemPosition": 2, "resourceIds": ["r3"],
                     "rejections": [{"kind": "grounding"}], "generator": {"usesAi": False, "fallback": True}},
                    {"resourceType": "sondeo_diagnostico", "planItemPosition": 3, "resourceIds": [],
                     "rejections": [{"kind": "plan"}], "generator": None}]})
            return super().__call__(request)

    real_client = httpx.Client
    monkeypatch.setattr(measure.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(MixedBackend()), **kwargs))
    monkeypatch.setenv("EVAL_EMAIL", EMAIL)
    monkeypatch.setenv("EVAL_PASSWORD", PASSWORD)
    (tmp_path / "tcp.txt").write_text("TCP", encoding="utf-8")
    report = measure.main(["--mode", "plan", "--runs", "2", "--similarity", "lexical", "--corpus",
                           str(tmp_path / "tcp.txt"), "--out", str(tmp_path / "plan.json"), "--poll", "0"])
    run = report["runs"][0]
    assert run["generators"] == {"aiSteps": 1, "fallbackSteps": 1, "rulesSteps": 0, "stepsWithoutGenerator": 1}
    assert run["planWarnings"] == [{"title": "Control de flujo", "reason": "desarrolla «UDP»", "resourceId": "r2"}]
    assert run["steps"][0]["planWarnings"] == 1
    assert report["summary"]["aiSteps"] == 2 and report["summary"]["fallbackSteps"] == 2
    assert report["summary"]["planWarnings"] == 2 and report["summary"]["steps"] == 6



# Métricas de contenido (segunda corrida de P4) y calibración

SENTENCES = [
    "El protocolo UDP envía cada datagrama sin establecer una conexión previa con el receptor.",
    "El control de flujo de TCP evita que el emisor sature al receptor con demasiados segmentos.",
    "La retransmisión de TCP reenvía los segmentos que no recibieron la confirmación del receptor.",
]


def test_resource_sentences_keep_sentences_of_eight_words_or_more(measure):
    text = f"Título corto.\n{SENTENCES[0]} Muy breve aquí. {SENTENCES[1]}"
    assert measure.resource_sentences(text) == [SENTENCES[0], SENTENCES[1]]


def test_the_near_duplicate_sentence_rate_splits_cross_type_pairs_and_variants(measure):
    by_resource = [[SENTENCES[0], SENTENCES[1]], [SENTENCES[0] + " ", SENTENCES[2]], [SENTENCES[2]]]
    # Los recursos 1 y 2 son de tipos distintos; el 2 y el 3, dos variantes del mismo tipo.
    result = measure.near_duplicate_sentences(by_resource, measure.lexical_matrix, 0.6,
                                              ["explicacion", "glosario", "glosario"])
    assert result["sentences"] == 5
    # La 1.ª oración está en los recursos 1 y 2 (tipos distintos); la 3.ª, en los recursos 2 y 3 (variantes).
    assert (result["all"]["nearDuplicateSentences"], result["all"]["rate"]) == (4, 0.8)
    assert (result["crossType"]["nearDuplicateSentences"], result["crossType"]["rate"]) == (2, 0.4)
    assert (result["variants"]["nearDuplicateSentences"], result["variants"]["rate"]) == (2, 0.4)
    assert result["crossType"]["examples"][0]["types"] == ["explicacion", "glosario"]
    assert result["variants"]["examples"][0]["types"] == ["glosario", "glosario"]
    same_resource = measure.near_duplicate_sentences([[SENTENCES[0], SENTENCES[0]]], measure.lexical_matrix, 0.6)
    assert same_resource["all"]["nearDuplicateSentences"] == 0  # repetir dentro del mismo recurso no cuenta
    assert measure.near_duplicate_sentences([], measure.lexical_matrix, 0.6)["all"]["rate"] is None


def test_titles_and_headings_are_not_sentences(measure):
    long_title = "Cómo el protocolo UDP envía cada datagrama sin establecer una conexión previa"
    api_resource = {"title": long_title, "body": SENTENCES[1], "options": [],
                    "structure": {"steps": [{"title": long_title, "text": SENTENCES[2]}]}}
    assert measure.resource_sentences(measure.resource_body(api_resource)) == [SENTENCES[1], SENTENCES[2]]
    stored_v3 = {"title": long_title, "text": f"{long_title}\n{SENTENCES[1]}"}
    assert measure.resource_sentences(measure.resource_body(stored_v3)) == [SENTENCES[1]]


def test_the_pair_rate_splits_cross_type_pairs_and_variants(measure):
    matrix = [[1.0, 0.9, 0.95], [0.9, 1.0, 0.2], [0.95, 0.2, 1.0]]
    result = measure.duplication(["a", "b", "c"], fixed(matrix), 0.85, ["explicacion", "explicacion", "glosario"],
                                 ["A", "B", "C"])
    assert result["duplicateRate"] == round(2 / 3, 4)
    assert (result["variants"]["pairs"], result["variants"]["duplicatePairs"]) == (1, 1)  # A y B, mismo tipo
    assert (result["crossType"]["pairs"], result["crossType"]["duplicateRate"]) == (2, 0.5)  # A-C sí, B-C no
    assert result["crossType"]["examples"] == [{"titles": ["A", "C"], "types": ["explicacion", "glosario"],
                                                "similarity": 0.95}]


def test_concept_reexplanation_counts_concepts_developed_in_more_than_one_resource(measure):
    texts = [
        "El protocolo UDP es un protocolo sin conexión. El control de flujo regula el envío.",
        "El protocolo UDP no confirma la entrega. Por eso el protocolo UDP es más rápido.",
        "Solo nombramos el control de flujo una vez.",
    ]
    result = measure.reexplained_concepts(texts, ["protocolo UDP", "control de flujo", "saludo de tres vías"],
                                          ["A", "B", "C"])
    assert (result["concepts"], result["reexplained"]) == (3, 1)
    assert result["rate"] == round(1 / 3, 4)
    assert result["items"] == [{"concept": "protocolo UDP", "resources": 2, "titles": ["A", "B"]}]
    # Por concepto: en cuántos recursos se menciona, se desarrolla y se define (para ver si la regla es estricta).
    assert result["table"] == [
        {"concept": "protocolo UDP", "mentioned": 2, "developed": 2, "defined": 1},
        {"concept": "control de flujo", "mentioned": 2, "developed": 0, "defined": 0},
        {"concept": "saludo de tres vías", "mentioned": 0, "developed": 0, "defined": 0},
    ]


class ContentBackend(FakeBackend):
    """El backend falso con la evidencia del pedido y el plan (generado por Gemini en el segundo intento)."""

    def __call__(self, request):
        path = request.url.path
        if (request.method, path) == ("GET", "/api/v1/generation-requests/gen-req-1/evidence"):
            return httpx.Response(200, json={"fragments": [
                {"text": "El control de flujo de TCP evita saturar al receptor. El modelo OSI tiene siete capas."},
                {"text": "El protocolo UDP no establece conexión; el protocolo UDP es más rápido que TCP."}]})
        if (request.method, path) == ("GET", "/api/v1/generation-plans/gen-plan-1"):
            return httpx.Response(200, json={"id": "gen-plan-1", "items": [
                {"position": 1, "covers": ["control de flujo"]}, {"position": 2, "covers": ["datagrama UDP"]}],
                "generator": {"description": "Gemini", "usesAi": True, "fallback": False, "attempts": 2}})
        if (request.method, path) == ("GET", "/api/v1/units/u1/resources"):
            return httpx.Response(200, json=[
                {"id": "r1", "title": "Control de flujo", "type": "explicacion",
                 "body": f"{SENTENCES[1]} El control de flujo es un mecanismo del receptor y del emisor de TCP."},
                {"id": "r2", "title": "Control otra vez", "type": "glosario",
                 "body": f"{SENTENCES[1]} El control de flujo es la regulación del envío entre los dos extremos."},
                {"id": "r3", "title": "Datagramas", "type": "item_opcion_multiple", "body": SENTENCES[0]},
            ])
        return super().__call__(request)


def run_main(measure, tmp_path, monkeypatch, backend, *extra):
    real_client = httpx.Client
    monkeypatch.setattr(measure.httpx, "Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(backend), **kwargs))
    monkeypatch.setenv("EVAL_EMAIL", EMAIL)
    monkeypatch.setenv("EVAL_PASSWORD", PASSWORD)
    (tmp_path / "tcp.txt").write_text("TCP", encoding="utf-8")
    return measure.main(["--corpus", str(tmp_path / "tcp.txt"), "--poll", "0", "--similarity", "lexical", *extra])


def test_each_run_reports_the_content_metrics_and_the_plan_generator(measure, tmp_path, monkeypatch):
    report = run_main(measure, tmp_path, monkeypatch, ContentBackend(), "--mode", "plan", "--runs", "2",
                      "--out", str(tmp_path / "plan.json"))
    run = report["runs"][0]
    assert run["sentences"]["all"]["nearDuplicateSentences"] == 2 and run["sentences"]["threshold"] == 0.6
    assert run["sentences"]["crossType"]["nearDuplicateSentences"] == 2  # explicacion y glosario: tipos distintos
    assert run["conceptReexplanation"]["source"] == "plan"
    assert run["conceptReexplanation"]["items"][0]["concept"] == "control de flujo"
    assert run["conceptReexplanationEvidence"]["source"] == "evidence"
    assert "control de flujo" in [i["concept"] for i in run["conceptReexplanationEvidence"]["items"]]
    assert run["planGenerator"] == {"usesAi": True, "fallback": False, "attempts": 2, "source": "ai"}
    assert [r["id"] for r in run["resources"]] == ["r1", "r2", "r3"] and run["resources"][0]["text"]
    summary = report["summary"]
    assert summary["sentenceNearDuplicateRate"] == run["sentences"]["all"]["rate"]
    assert summary["crossTypeSentenceRate"] == run["sentences"]["crossType"]["rate"]
    assert summary["meanReexplainedConcepts"] == 1 and summary["meanReexplainedEvidenceConcepts"] >= 1
    assert summary["planGenerators"] == {"ai": 2, "rules": 0}


def test_the_baseline_uses_evidence_concepts_and_the_same_top_k(measure, tmp_path, monkeypatch):
    backend = ContentBackend()
    report = run_main(measure, tmp_path, monkeypatch, backend, "--mode", "baseline", "--runs", "1",
                      "--out", str(tmp_path / "b.json"))
    run = report["runs"][0]
    assert run["conceptReexplanation"]["source"] == "evidence" and run["planGenerator"] is None
    body = next(b for method, path, b in backend.bodies if path == "/api/v1/generation-requests")
    assert body["topK"] == 12  # la misma evidencia que el plan (12 fragmentos)


def test_the_default_is_five_runs(measure):
    assert measure.build_parser().parse_args(["--mode", "plan", "--out", "x.json"]).runs == 5


def test_the_comparison_includes_the_content_metrics(measure):
    baseline = {"duplicateRate": 0.3, "resourcesPerRequest": 15, "sentenceNearDuplicateRate": 0.2,
                "meanReexplainedEvidenceConcepts": 4.0}
    planned = {"duplicateRate": 0.29, "resourcesPerRequest": 15, "sentenceNearDuplicateRate": 0.05,
               "meanReexplainedEvidenceConcepts": 1.0}
    result = measure.compare(baseline, planned)
    assert result["sentenceReduction"] == 0.75 and result["reexplainedConceptsReduction"] == 0.75


FOURTH_SENTENCE = "El puerto 53 recibe las consultas de nombres y responde con la dirección que se buscaba."
OWN_SENTENCES = [
    "El modelo OSI describe siete capas que van desde la física hasta la aplicación del usuario.",
    "Una dirección IP identifica a cada equipo de la red y permite enrutar los paquetes hacia él.",
    "El servicio DNS traduce los nombres de dominio en direcciones numéricas que entienden los equipos.",
    "Wireshark captura el tráfico de la interfaz y muestra los campos de cada paquete en detalle.",
]


def test_calibration_suggests_thresholds_from_unrelated_and_repeated_pairs(measure, tmp_path):
    """Pares que no repiten contenido: tipos distintos de ítems distintos. Pares repetidos: el mismo texto con sus
    oraciones en otro orden y medio recurso copiado. Con embeddings falsos: los textos sobre lo mismo dan 0,9."""
    resources = [
        {"id": f"r{n}", "title": f"R{n}", "type": t, "planItemPosition": n,
         "text": f"{OWN_SENTENCES[n - 1]} {(SENTENCES + [FOURTH_SENTENCE])[n - 1]}"}
        for n, t in enumerate(["explicacion", "glosario", "pregunta_detonante", "item_opcion_multiple"], 1)
    ]
    report_path = tmp_path / "plan.json"
    report_path.write_text(json.dumps({"corpus": "corpus_t067", "runs": [{"resources": resources}]}),
                           encoding="utf-8")
    out = tmp_path / "calibration.json"
    calibration = measure.main(["--calibrate", "--from", str(report_path), "--similarity", "lexical",
                                "--out", str(out)])
    assert json.loads(out.read_text(encoding="utf-8")) == calibration
    pairs = calibration["resourcePairs"]
    assert pairs["unrelated"]["count"] == 6 and pairs["repeated"]["count"] == 8
    assert pairs["repeated"]["p5"] > pairs["unrelated"]["p95"]
    assert pairs["unrelated"]["p95"] < calibration["suggested"]["pairThreshold"] <= pairs["repeated"]["p5"]
    sentences = calibration["sentencePairs"]
    assert sentences["repeated"]["p5"] > sentences["unrelated"]["p95"]
    assert calibration["similarity"].startswith("lexical")
    assert calibration["crossCorpusPairs"] == 0


def test_calibration_reports_overlap_when_the_distributions_mix(measure):
    unrelated, repeated = [0.86, 0.9, 0.93, 0.95], [0.88, 0.97, 0.99, 1.0]
    suggestion = measure.suggest_threshold(unrelated, repeated)
    assert suggestion["overlap"] is True and suggestion["threshold"] == measure.percentile(unrelated, 95)
    clean = measure.suggest_threshold([0.2, 0.3, 0.4], [0.8, 0.9, 1.0])
    assert clean["overlap"] is False and 0.4 < clean["threshold"] < 0.8



# --recompute, motivos del respaldo y recursos no entregados, calibración con la cuenta correcta


def v3_report() -> dict:
    """Un informe como los v3: textos con el título en la primera línea, pasos con `usesAi` y `fallback`, sin
    conceptos guardados y sin quién redactó cada recurso."""
    steps = [{"resourceType": "explicacion", "planItemPosition": 1, "delivered": 1, "usesAi": True, "fallback": False},
             {"resourceType": "glosario", "planItemPosition": 2, "delivered": 1, "usesAi": False, "fallback": True},
             {"resourceType": "item_opcion_multiple", "planItemPosition": 3, "delivered": 1, "usesAi": True,
              "fallback": False}]
    resources = [
        {"id": "r1", "title": "Control de flujo", "type": "explicacion", "planItemPosition": 1,
         "text": f"Control de flujo\n{SENTENCES[1]} {SENTENCES[0]}"},
        {"id": "r2", "title": "Glosario", "type": "glosario", "planItemPosition": 2,
         "text": f"Glosario\n{SENTENCES[1]}"},
        {"id": "r3", "title": "Ítem", "type": "item_opcion_multiple", "planItemPosition": 3,
         "text": f"Ítem\n{SENTENCES[0]}"},
    ]
    return {"measure": "P4", "mode": "plan", "corpus": "corpus_t067", "threshold": 0.885, "sentenceThreshold": 0.865,
            "similarity": "embeddings (coseno), gemini-embedding-001",
            "runs": [{"key": "p4-plan-1", "requestId": "gen-req-1", "planId": "gen-plan-1", "steps": steps,
                      "generators": {"aiSteps": 2, "fallbackSteps": 1, "rulesSteps": 0, "stepsWithoutGenerator": 0},
                      "planGenerator": {"usesAi": False, "fallback": True, "attempts": 2, "source": "rules"},
                      "metrics": {"duplicateRate": 0.9}, "resources": resources}],
            "summary": {"duplicateRate": 0.9}}


def test_recompute_rebuilds_every_metric_from_the_stored_texts_and_keeps_the_run_data(measure, tmp_path,
                                                                                       monkeypatch):
    monkeypatch.delenv("EVAL_EMAIL", raising=False)  # sin cuenta: no lee conceptos de la API
    source = tmp_path / "v3-gemini-plan.json"
    source.write_text(json.dumps(v3_report(), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "v3r-gemini-plan.json"
    report = measure.main(["--recompute", "--from", str(source), "--similarity", "lexical",
                           "--sentence-threshold", "0.6", "--out", str(out)])
    assert json.loads(out.read_text(encoding="utf-8")) == report and report["recomputedFrom"] == source.name
    run = report["runs"][0]
    # Los datos de la corrida se conservan; las métricas se recalculan con los textos.
    assert run["generators"]["fallbackSteps"] == 1 and run["planGenerator"]["source"] == "rules"
    assert run["metrics"]["resources"] == 3 and run["metrics"]["duplicateRate"] != 0.9
    assert [r["drafter"] for r in run["resources"]] == ["ai", "fallback", "ai"]
    # Los títulos no son oraciones: r1 tiene 2 oraciones y r2 y r3, una cada uno.
    assert run["sentences"]["sentences"] == 4 and run["sentences"]["crossType"]["nearDuplicateSentences"] == 4
    # Solo con los recursos de la IA: sin el glosario del respaldo.
    assert run["aiOnly"]["resources"] == 2 and run["aiOnly"]["sentences"]["crossType"]["nearDuplicateSentences"] == 2
    assert run["conceptReexplanationEvidence"] is None  # el informe v3 no guarda los conceptos
    assert report["summary"]["aiOnly"]["resources"] == 2 and report["threshold"] == 0.885
    assert report["sentenceThreshold"] == 0.6 and "comparison" not in report


def test_recompute_reads_missing_concepts_with_the_same_account_and_compares(measure, tmp_path, monkeypatch):
    source = tmp_path / "v3-gemini-plan.json"
    source.write_text(json.dumps(v3_report(), ensure_ascii=False), encoding="utf-8")
    baseline = tmp_path / "v3r-gemini-baseline.json"
    baseline.write_text(json.dumps({"summary": {"duplicateRate": 0.5, "crossTypeSentenceRate": 1.0,
                                                "resourcesPerRequest": 3, "aiOnly": {"crossTypeSentenceRate": 1.0}}}),
                        encoding="utf-8")
    report = run_main(measure, tmp_path, monkeypatch, ContentBackend(), "--recompute", "--from", str(source),
                      "--out", str(tmp_path / "out.json"), "--compare", str(baseline))
    run = report["runs"][0]
    assert run["planConcepts"] == ["control de flujo", "datagrama UDP"] and run["evidenceConcepts"]
    assert run["conceptReexplanation"]["source"] == "plan" and run["conceptReexplanationEvidence"]["table"]
    comparison = report["comparison"]
    assert comparison["crossTypeSentenceReduction"] == round(1 - report["summary"]["crossTypeSentenceRate"], 4)
    assert comparison["aiOnly"]["crossTypeSentenceReduction"] is not None


class FallbackBackend(ContentBackend):
    """Un pedido con un paso del respaldo (con su motivo) y un ítem del plan que entregó 1 de 2 recursos."""

    def __call__(self, request):
        path = request.url.path
        if (request.method, path) == ("GET", "/api/v1/generation-requests/gen-req-1"):
            return httpx.Response(200, json={"id": "gen-req-1", "status": "partially_succeeded", "unitId": "u1",
                                             "planId": "gen-plan-1", "steps": [
                {"resourceType": "explicacion", "planItemPosition": 1, "resourceIds": ["r1", "r2"], "rejections": [],
                 "status": "succeeded", "generator": {"usesAi": True, "fallback": False}},
                {"resourceType": "glosario", "planItemPosition": 2, "resourceIds": ["r3"], "status": "succeeded",
                 "rejections": [{"kind": "grounding", "title": "Glosario 2", "reason": "«Glosario 2»: sin respaldo."}],
                 "generator": {"usesAi": False, "fallback": True,
                               "fallbackReason": "Gemini no respondió (tiempo agotado). Se usó el generador por reglas."}},
            ]})
        if (request.method, path) == ("GET", "/api/v1/generation-plans/gen-plan-1"):
            return httpx.Response(200, json={"id": "gen-plan-1", "items": [
                {"position": 1, "quantity": 2, "covers": ["control de flujo", "saludo de tres vías"]},
                {"position": 2, "quantity": 2, "covers": ["datagrama UDP", "puerto de origen"]}],
                "generator": {"usesAi": True, "fallback": False, "attempts": 1}})
        return super().__call__(request)


def test_each_run_reports_which_steps_fell_back_and_which_planned_resources_were_not_delivered(measure, tmp_path,
                                                                                              monkeypatch):
    report = run_main(measure, tmp_path, monkeypatch, FallbackBackend(), "--mode", "plan", "--runs", "1",
                      "--out", str(tmp_path / "plan.json"))
    run = report["runs"][0]
    assert run["fallbacks"] == [{"resourceType": "glosario", "planItemPosition": 2,
                                 "reason": "Gemini no respondió (tiempo agotado). Se usó el generador por reglas."}]
    assert run["expectedResources"] == 4
    assert run["undelivered"] == [{"resourceType": "glosario", "planItemPosition": 2, "expected": 2, "delivered": 1,
                                   "missing": 1, "status": "succeeded", "error": None,
                                   "rejections": [{"kind": "grounding", "title": "Glosario 2",
                                                   "reason": "«Glosario 2»: sin respaldo."}]}]
    assert [r["drafter"] for r in run["resources"]] == ["ai", "ai", "fallback"]
    assert run["aiOnly"]["resources"] == 2 and report["summary"]["undeliveredResources"] == 1


def test_calibration_stops_with_a_clear_error_when_the_account_cannot_read_the_request(measure, tmp_path, monkeypatch):
    class OtherAccount(FakeBackend):
        def __call__(self, request):
            if request.url.path == "/api/v1/generation-requests/gen-req-1":
                return httpx.Response(404, json={"error": {"code": "GENERATION_REQUEST_NOT_FOUND", "message": "No."}})
            return super().__call__(request)

    old = tmp_path / "v2-gemini-plan.json"
    old.write_text(json.dumps({"runs": [{"requestId": "gen-req-1"}]}), encoding="utf-8")
    with pytest.raises(SystemExit) as stopped:
        run_main(measure, tmp_path, monkeypatch, OtherAccount(), "--calibrate", "--from", str(old),
                 "--out", str(tmp_path / "c.json"))
    assert "respondió 404" in str(stopped.value) and "misma cuenta" in str(stopped.value)
    assert not (tmp_path / "c.json").exists()


def test_embeddings_are_requested_in_batches_and_once_per_text(measure):
    class Counting:
        model = "embeddings-falsos"

        def __init__(self):
            self.batches = []

        def embed_documents(self, texts):
            self.batches.append(len(texts))
            return [[float(len(text)), 1.0] for text in texts]

    embedder = Counting()
    similarity = measure.EmbeddingSimilarity(embedder, batch_size=3, show_progress=False)
    texts = [f"texto {n}" for n in range(7)]
    scores = measure.pair_scores(similarity, [(texts[0], texts[n]) for n in range(1, 7)] + [(texts[0], texts[1])])
    assert len(scores) == 7 and embedder.batches == [3, 3, 1]  # 7 textos distintos en 3 llamadas
    similarity(texts[:3])
    assert embedder.batches == [3, 3, 1]  # ya estaban: ninguna llamada más
