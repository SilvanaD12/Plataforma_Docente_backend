"""TA-010 (T065): campos nuevos de cases.json y muestras con todo lo recuperado en evaluation/collect_samples.py.

Sin red: las respuestas del servidor las da un `httpx.MockTransport`. Research R12.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest

from tests.unit.test_collect_samples import client_for, collect  # noqa: F401 (fixture)

OLD_CASE = {"id": "c05", "stage": "explain", "resourceType": "explicacion", "quantity": 1, "difficulty": "intermedia",
            "optionCount": 4, "topK": 8, "instructions": "Explicación de TCP y UDP."}
UNIT = {"id": "unidad-1", "title": "Protocolos de transporte",
        "outcomes": [{"id": "ra-1", "text": "Distingue TCP, UDP e IP según su función"}]}
COURSE_CODE_PATTERN = re.compile(r"^EVAL-RAG-[0-9a-f]{12}$")


# Cuerpo del pedido


def test_an_old_case_sends_the_same_body_as_before_without_modalities(collect):
    assert collect.request_body(OLD_CASE, UNIT) == {
        "mode": "individual", "unitId": "unidad-1", "resourceTypes": ["explicacion"], "quantity": 1,
        "outcomeId": None, "difficulty": "intermedia", "optionCount": 4, "topK": 8, "evidenceThreshold": 0.6,
        "instructions": "Explicación de TCP y UDP.", "audience": "", "competency": "",
    }


def test_the_competency_of_the_case_is_sent(collect):
    body = collect.request_body({**OLD_CASE, "competency": "Pensamiento crítico"}, UNIT)
    assert body["competency"] == "Pensamiento crítico"


def test_a_sequence_case_sends_its_types(collect):
    case = {"id": "s01", "mode": "sequence", "resourceTypes": ["pregunta_detonante", "explicacion"],
            "instructions": "Secuencia sobre TCP."}
    body = collect.request_body(case, UNIT)
    assert body["mode"] == "sequence" and body["resourceTypes"] == ["pregunta_detonante", "explicacion"]
    assert collect.case_label(case) == "s01 · secuencia · pregunta_detonante, explicacion"
    assert collect.case_label(OLD_CASE) == "c05 · explain · explicacion"


@pytest.mark.parametrize(
    "case",
    [
        {"id": "x1", "mode": "sequence", "instructions": "Sin tipos."},
        {"id": "x2", "mode": "sequence", "resourceTypes": [], "instructions": "Lista vacía."},
        {"id": "x3", "instructions": "Sin resourceType."},
        {"id": "x4", "mode": "lote", "resourceType": "glosario", "instructions": "Otro modo."},
    ],
)
def test_a_case_without_valid_types_or_mode_is_reported(collect, case):
    with pytest.raises(ValueError) as invalid:
        collect.request_body(case, UNIT)
    assert case["id"] in str(invalid.value)


# Unidad del caso


def _courses_server(existing: list[dict]):
    calls: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, body))
        if request.method == "GET":
            return httpx.Response(200, json=existing)
        units = [{**unit, "id": f"unidad-{len(existing) + 1}",
                  "outcomes": [{"id": "ra-x", **outcome} for outcome in unit["outcomes"]]} for unit in body["units"]]
        course = {**body, "id": f"curso-{len(existing) + 1}", "units": units}
        existing.append(course)
        return httpx.Response(201, json=course)

    return handler, calls


def test_an_old_case_uses_the_evaluation_unit_as_today(collect):
    handler, calls = _courses_server([])
    with client_for(handler) as client:
        unit = collect.ensure_case_unit(client, {}, OLD_CASE, {})
    [(_, _, created)] = [call for call in calls if call[0] == "POST"]
    assert created["code"] == "EVAL-RAG" and unit["title"] == "Protocolos de transporte"
    assert created["units"][0]["outcomes"] == [{"text": "Distingue TCP, UDP e IP según su función"}]


def test_a_case_with_its_own_unit_gets_its_own_course_and_reuses_it(collect):
    case = {**OLD_CASE, "unitTitle": "Capa de red", "outcomeText": "Explica el enrutamiento IP"}
    handler, calls = _courses_server([])
    cache: dict = {}
    with client_for(handler) as client:
        unit = collect.ensure_case_unit(client, {}, case, cache)
        again = collect.ensure_case_unit(client, {}, {**case, "id": "c06"}, cache)
    [(_, _, created)] = [call for call in calls if call[0] == "POST"]
    assert COURSE_CODE_PATTERN.fullmatch(created["code"]) and len(created["code"]) <= 30
    assert created["units"] == [{"title": "Capa de red", "outcomes": [{"text": "Explica el enrutamiento IP"}]}]
    assert unit["title"] == "Capa de red" and again == unit
    assert len([call for call in calls if call[0] == "GET"]) == 1  # la segunda vez usa la caché


def test_an_existing_course_of_the_unit_is_reused_without_creating_another(collect):
    case = {**OLD_CASE, "unitTitle": "Capa de red", "outcomeText": "Explica el enrutamiento IP"}
    code = collect.course_code("Capa de red", "Explica el enrutamiento IP")
    existing = [{"id": "curso-9", "code": code, "units": [{"id": "unidad-9", "title": "Capa de red", "outcomes": []}]}]
    handler, calls = _courses_server(existing)
    with client_for(handler) as client:
        unit = collect.ensure_case_unit(client, {}, case, {})
    assert unit["id"] == "unidad-9" and not [call for call in calls if call[0] == "POST"]


def test_the_course_code_depends_on_the_title_and_the_outcome(collect):
    first = collect.course_code("Capa de red", "Explica el enrutamiento IP")
    assert first == collect.course_code("Capa de red", "Explica el enrutamiento IP")
    assert first != collect.course_code("Capa de red", "Otro resultado")
    assert first != collect.course_code("Capa de enlace", "Explica el enrutamiento IP")
    # Solo el título u solo el resultado completan el otro con el de la unidad de evaluación.
    assert collect.unit_spec({**OLD_CASE, "unitTitle": "Capa de red"}) == (
        "Capa de red", "Distingue TCP, UDP e IP según su función",
    )
    assert collect.unit_spec(OLD_CASE) is None


# Consulta de recuperación


def test_the_retrieval_query_is_the_one_the_request_uses(collect):
    query = collect.retrieval_query(UNIT, {**OLD_CASE, "competency": "Pensamiento crítico"})
    assert query == {
        "unitTitle": "Protocolos de transporte",
        "outcomes": ["Distingue TCP, UDP e IP según su función"],
        "instructions": "Explicación de TCP y UDP.",
        "competency": "Pensamiento crítico",
        "text": "Protocolos de transporte Distingue TCP, UDP e IP según su función Explicación de TCP y UDP. "
        "Pensamiento crítico",
    }
    assert collect.retrieval_query(UNIT, OLD_CASE)["text"].endswith("Explicación de TCP y UDP.")


# Evidencia del pedido


EVIDENCE = {
    "requestId": "gen-req-1", "retrievalMode": "hybrid", "limit": 8, "retrievedAt": "2026-11-13T10:00:00+00:00",
    "fragments": [
        {"chunkId": "f3", "text": "UDP no confirma la entrega."},
        {"chunkId": "f1", "text": "TCP garantiza una entrega confiable."},
        {"chunkId": "f2", "text": "IP enruta los paquetes."},
    ],
}


def test_the_evidence_is_read_from_the_request_route(collect):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json=EVIDENCE)

    with client_for(handler) as client:
        evidence, problem = collect.fetch_evidence(client, {}, "gen-req-1", deadline=None)
    assert seen == ["/api/v1/generation-requests/gen-req-1/evidence"]
    assert evidence == EVIDENCE and problem is None


def test_a_rejected_evidence_query_is_reported(collect):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"code": "GENERATION_REQUEST_NOT_FOUND", "message": "No existe."}})

    with client_for(handler) as client:
        evidence, problem = collect.fetch_evidence(client, {}, "gen-req-1", deadline=None)
    assert evidence is None
    assert problem == {"kind": "evidence", "status": 404, "code": "GENERATION_REQUEST_NOT_FOUND",
                       "message": "No existe.", "requestId": "gen-req-1"}


def test_a_network_failure_on_the_evidence_query_is_reported(collect):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red")

    with client_for(handler) as client:
        evidence, problem = collect.fetch_evidence(client, {}, "gen-req-1", deadline=None)
    assert evidence is None and problem["kind"] == "evidence" and problem["code"] == "NETWORK_ERROR"


# Muestras


def _resource(resource_id: str, cited: list[str]) -> dict:
    return {"id": resource_id, "title": "Recurso", "body": "Texto del recurso.", "options": [],
            "citations": [{"claim": "TCP", "fragmentIds": cited}],
            "evidence": [{"id": f, "text": next(x["text"] for x in EVIDENCE["fragments"] if x["chunkId"] == f)}
                         for f in cited]}


STATUS = {"id": "gen-req-1", "status": "succeeded", "retrievalMode": "hybrid", "steps": [
    {"position": 0, "stage": "explain", "resourceType": "explicacion", "resourceIds": ["r1"],
     "generator": {"description": "Generador por reglas (sin IA)", "usesAi": False, "fallback": False}},
]}


def test_a_sample_has_every_retrieved_fragment_and_keeps_the_cited_ones_apart(collect):
    [sample] = collect.build_samples(OLD_CASE, STATUS, {"r1": _resource("r1", ["f1"])}, EVIDENCE, UNIT, 1.5, [])
    assert sample["retrieved_contexts"] == [f["text"] for f in EVIDENCE["fragments"]]  # en el orden recuperado
    assert sample["cited_contexts"] == ["TCP garantiza una entrega confiable."]
    assert (sample["retrieved_count"], sample["limit"], sample["retrieval_mode"]) == (3, 8, "hybrid")
    assert sample["user_input"] == "Explicación citada: Explicación de TCP y UDP."  # como hoy
    assert sample["retrieval_query"]["text"].startswith("Protocolos de transporte")
    assert "reference" not in sample and "expected_fragments" not in sample
    assert sample["case_id"] == "c05" and sample["stage"] == "explain" and sample["resource_type"] == "explicacion"


def test_the_reference_and_expected_fragments_of_the_case_go_into_the_sample(collect):
    case = {**OLD_CASE, "reference": "TCP es confiable; UDP es rápido.", "expectedFragments": ["TCP garantiza"]}
    [sample] = collect.build_samples(case, STATUS, {"r1": _resource("r1", ["f1"])}, EVIDENCE, UNIT, 1.5, [])
    assert sample["reference"] == "TCP es confiable; UDP es rápido."
    assert sample["expected_fragments"] == ["TCP garantiza"]


def test_each_resource_of_a_sequence_is_a_sample_with_its_own_stage_and_type(collect):
    case = {"id": "s01", "mode": "sequence", "resourceTypes": ["pregunta_detonante", "explicacion"],
            "instructions": "Secuencia sobre TCP."}
    status = {**STATUS, "steps": [
        {**STATUS["steps"][0], "position": 0, "stage": "engage", "resourceType": "pregunta_detonante",
         "resourceIds": ["r1"]},
        {**STATUS["steps"][0], "position": 1, "resourceIds": ["r2"]},
    ]}
    stored = {"r1": _resource("r1", ["f3"]), "r2": _resource("r2", ["f1", "f2"])}
    samples = collect.build_samples(case, status, stored, EVIDENCE, UNIT, 2.0, [])
    assert [(s["stage"], s["resource_type"]) for s in samples] == [
        ("engage", "pregunta_detonante"), ("explain", "explicacion"),
    ]
    assert samples[0]["user_input"] == "Pregunta detonante: Secuencia sobre TCP."
    assert all(len(s["retrieved_contexts"]) == 3 for s in samples)


def test_a_resource_missing_from_review_is_a_problem_not_a_sample(collect):
    problems: list[dict] = []
    assert collect.build_samples(OLD_CASE, STATUS, {}, EVIDENCE, UNIT, 1.0, problems) == []
    assert problems == [{"kind": "missing", "message": "el recurso r1 ya no está en revisión"}]
