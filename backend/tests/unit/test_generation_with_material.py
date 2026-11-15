"""
Generación con el material del docente (RAG) usando puertos falsos: sin red y sin base de datos.
"""

from __future__ import annotations

from typing import Any

import pytest

from platform5e.application.ports.outbound.language_model_port import ResourceGeneratorPort
from platform5e.application.services.generation.prompt_drafting import (
    build_generation_context,
    build_prompt_instructions,
    normalize_generated_resources,
    parse_json_response,
)
from platform5e.application.use_cases.generation.start_generation_request import (
    StartGenerationCommand,
    StartGenerationRequest,
)
from platform5e.domain.generation.errors import GenerationError
from platform5e.domain.generation.generation_request import GenerationMode, GenerationParameters, RequestStatus
from platform5e.domain.materials.text_analysis import retrieve_relevant_chunks
from platform5e.infrastructure.retrieval.bm25_evidence_retriever import Bm25EvidenceRetriever
from tests.support.generation_fakes import (
    FRAGMENTS,
    FakeEvidence,
    FakeMembership,
    FakeRunner,
    run_generation,
    sqlite_repository,
)

MOCK_UNIT = {
    "id": "u1",
    "number": 1,
    "title": "Protocolos de transporte",
    "outcomes": [{"id": "ra-1", "code": "RA1.1", "text": "Distingue TCP y UDP"}],
}
MOCK_COURSE = {
    "id": "c1",
    "name": "Redes",
    "summary": "Curso de redes.",
    "learningGoal": "Explica cómo se comunican los equipos.",
    "units": [MOCK_UNIT],
}
MOCK_FRAGMENTS = [
    {
        "id": "f1",
        "documento_id": "doc1",
        "documentId": "doc1",
        "unidad_id": "u1",
        "unitId": "u1",
        "orden": 0,
        "ubicacion": "p. 1",
        "location": "p. 1",
        "texto": "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable.",
        "text": "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable.",
    },
    {
        "id": "f2",
        "documento_id": "doc1",
        "documentId": "doc1",
        "unidad_id": "u1",
        "unitId": "u1",
        "orden": 1,
        "ubicacion": "p. 2",
        "location": "p. 2",
        "texto": "El protocolo UDP no establece conexión y es más rápido.",
        "text": "El protocolo UDP no establece conexión y es más rápido.",
    },
]
MOCK_DOCUMENT = {"id": "doc1", "unitId": "u1", "fileName": "apuntes.pdf"}


def make_request_dict(**overrides) -> dict[str, Any]:
    base = {
        "unitId": "u1",
        "outcomeId": None,
        "stage": "evaluate",
        "resourceType": "item_opcion_multiple",
        "quantity": 1,
        "difficulty": "intermedia",
        "optionCount": 3,
        "topK": 5,
        "evidenceThreshold": 0.6,
        "instructions": "contexto peruano",
        "audience": "Tercer ciclo",
        "competency": "Pensamiento crítico",
        "modalities": ["Textual"],
    }
    return {**base, **overrides}


MOCK_ITEM = {
    "titulo": "TCP o UDP",
    "contenido": "¿Qué protocolo garantiza una entrega confiable?",
    "citas": [{"afirmacion": "TCP garantiza la entrega", "fragmentos": ["F1"]}],
    "alternativas": [
        {"texto": "TCP", "correcta": True, "retroalimentacion": "Correcto.", "fragmentos": ["F1"]},
        {
            "texto": "UDP",
            "correcta": False,
            "retroalimentacion": "No confirma la entrega.",
            "error_conceptual": "Cree que ser más rápido implica ser confiable.",
            "fragmentos": ["F2"],
        },
        {
            "texto": "IP",
            "correcta": False,
            "retroalimentacion": "IP no es un protocolo de transporte.",
            "error_conceptual": "Confunde la capa de red con la de transporte.",
            "fragmentos": [],
        },
    ],
}


class MockGenerator(ResourceGeneratorPort):
    def __init__(
        self,
        response_data: dict[str, Any] | None = None,
        error: Exception | None = None,
        description: str = "IA falsa",
        uses_ai: bool = True,
    ) -> None:
        self.response_data = response_data
        self.error = error
        self.description = description
        self.uses_ai = uses_ai
        self.captured_contexts: list[dict[str, Any]] = []

    def generate(self, context: dict[str, Any]) -> dict[str, Any]:
        self.captured_contexts.append(context)
        if self.error:
            raise self.error
        return self.response_data or {}


def test_instructions_include_course_request_and_chunks():
    context = build_generation_context(
        MOCK_COURSE,
        MOCK_UNIT,
        make_request_dict(outcomeId="ra-1"),
        [{**f, "relevance": 1} for f in MOCK_FRAGMENTS],
        {"doc1": "apuntes.pdf"},
    )
    system_inst, user_prompt = build_prompt_instructions(context)
    assert "Evaluar" in system_inst and "JSON" in system_inst
    assert "Genera solo texto" in system_inst  # Sprint 1: sin multimedia
    for text_sample in (
        "SUMILLA: Curso de redes.",
        "RA1.1: Distingue TCP y UDP",
        "exactamente 3 alternativas",
        "Tercer ciclo",
        "Pensamiento crítico",
        "contexto peruano",
        "[F1] (apuntes.pdf, p. 1)",
    ):
        assert text_sample in user_prompt

    empty_context = build_generation_context(
        {},
        {"title": "U", "number": 2},
        make_request_dict(stage="explain", resourceType="glosario", audience="", competency="", modalities=[], instructions=""),
        [],
        {},
    )
    _, empty_user_prompt = build_prompt_instructions(empty_context)
    assert "no registrada" in empty_user_prompt and "alternativas" in empty_user_prompt


@pytest.mark.parametrize(
    "raw_input,expected_output",
    [
        ('{"recursos": []}', {"recursos": []}),
        ('```json\n{"recursos": [1]}\n```', {"recursos": [1]}),
        ('Aquí tienes: {"recursos": [2]} ¡listo!', {"recursos": [2]}),
    ],
)
def test_extract_json_tolerates_common_formats(raw_input: str, expected_output: dict[str, Any]):
    assert parse_json_response(raw_input) == expected_output


@pytest.mark.parametrize("invalid_raw", ["", None, "sin json", "{roto"])
def test_extract_json_rejects_unreadable_output(invalid_raw: str | None):
    with pytest.raises(ValueError):
        parse_json_response(invalid_raw)


# Afirmación respaldada por el material de prueba (HU-016 rechaza las que no lo están).
SUPPORTED_CLAIM = "El protocolo TCP garantiza una entrega confiable"


def build_test_context(quantity: int = 1, options: int = 3) -> dict[str, Any]:
    return build_generation_context(
        MOCK_COURSE, MOCK_UNIT, make_request_dict(quantity=quantity, optionCount=options), MOCK_FRAGMENTS, {}
    )


def test_normalize_accepts_joined_tags_and_key_as_text():
    options = [
        {"texto": "TCP", "correcta": "true", "fragmentos": "F1, F2"},
        {"texto": "UDP", "correcta": "false", "retroalimentacion": "No confirma.", "errorConceptual": "Rapidez = confianza."},
        {"texto": "IP", "esCorrecta": False, "retroalimentacion": "Es de red.", "error": "Confunde las capas."},
    ]
    item_payload = {**MOCK_ITEM, "citas": [{"afirmacion": SUPPORTED_CLAIM, "fragmentos": "Fragmentos F2 y F1"}], "alternativas": options}
    normalized = normalize_generated_resources({"recursos": [item_payload]}, build_test_context())[0]
    assert normalized["citas"][0]["fragmentIds"] == ["f2", "f1"]
    correct_opt = next(a for a in normalized["alternativas"] if a["correcta"])
    assert correct_opt["texto"] == "TCP" and correct_opt["fragmentos"] == ["f1", "f2"]


def test_normalize_accepts_tags_in_several_formats_and_trims_quantity():
    item_payload = {**MOCK_ITEM, "citas": [{"afirmacion": SUPPORTED_CLAIM, "fragmentos": ["f2", "[F1]", 1, "F7"]}]}
    resources = normalize_generated_resources({"recursos": [item_payload, item_payload]}, build_test_context(quantity=1))
    assert len(resources) == 1 and resources[0]["citas"][0]["fragmentIds"] == ["f2", "f1"]
    assert normalize_generated_resources([item_payload], build_test_context())[0]["titulo"] == "TCP o UDP"
    assert normalize_generated_resources("no es lista", build_test_context()) == []


@pytest.mark.parametrize(
    "options_case",
    [
        [{"texto": "A", "correcta": True}, {"texto": "B", "correcta": True}, {"texto": "C"}],
        [{"texto": "A"}, {"texto": "B"}, {"texto": "C"}],
        [{"texto": "A", "correcta": True}, {"texto": "a"}, {"texto": "B"}],
        "no es lista",
    ],
)
def test_normalize_discards_invalid_items(options_case):
    assert normalize_generated_resources({"recursos": [{**MOCK_ITEM, "alternativas": options_case}]}, build_test_context()) == []


def test_normalize_discards_uncited_or_empty_resources_and_fills_title():
    ctx = build_generation_context(
        MOCK_COURSE, MOCK_UNIT, make_request_dict(stage="explain", resourceType="explicacion", quantity=3), MOCK_FRAGMENTS, {}
    )
    resources = normalize_generated_resources(
        {
            "recursos": [
                {"contenido": "Texto", "citas": [{"afirmacion": SUPPORTED_CLAIM, "fragmentos": "F1"}]},
                {"titulo": "Sin cita", "contenido": "Texto", "citas": []},
                {"titulo": "Vacío", "contenido": "", "citas": [{"afirmacion": "x", "fragmentos": ["F1"]}]},
                "basura",
            ]
        },
        ctx,
    )
    assert len(resources) == 1 and resources[0]["titulo"] == "Explicación citada 1" and resources[0]["alternativas"] is None


def test_bm25_adapter_delegates_to_the_domain_search():
    retriever = Bm25EvidenceRetriever()
    assert retriever.description == "búsqueda por palabras (BM25)"
    query = "protocolo confiable con conexión"
    assert retriever.retrieve(query, MOCK_FRAGMENTS, 2) == retrieve_relevant_chunks(query, MOCK_FRAGMENTS, 2)


# --- Redacción de un paso con el material (antes por el servicio síncrono, retirado en T046) ----------------------
# Se ejecutan con StartGenerationRequest y RunGenerationRequest (tests/support/generation_fakes.run_generation).

UDP_FIRST = (FRAGMENTS[1], FRAGMENTS[0])  # la búsqueda devuelve primero UDP: F1 es f2 y F2 es f1


def rules(response: dict[str, Any]) -> MockGenerator:
    return MockGenerator(response, description="Reglas", uses_ai=False)


def test_a_drafted_item_cites_its_chunks_and_the_wrong_citation_is_corrected(tmp_path):
    ai_gen = MockGenerator({"recursos": [MOCK_ITEM]})
    run = run_generation(
        tmp_path, "item_opcion_multiple", primary=ai_gen, fragments=UDP_FIRST, option_count=3, outcome_id="ra-1"
    )

    assert run.request.status == RequestStatus.SUCCEEDED
    assert run.step.generator == {"description": "IA falsa", "usesAi": True, "fallback": False, "fallbackReason": None}
    [resource] = run.resources
    assert resource["source"] == "rag" and resource["status"] == "pendiente" and resource["outcomeId"] == "ra-1"

    real_mapping = {f["etiqueta"]: f["id"] for f in ai_gen.captured_contexts[0]["fragmentos"]}
    # El modelo citó F1, que aquí es el fragmento de UDP: la verificación de anclaje (HU-016) lo corrige al de TCP.
    assert real_mapping["F1"] == "f2"
    assert resource["citations"] == [{"claim": "TCP garantiza la entrega", "fragmentIds": ["f1"]}]
    assert resource["grounding"]["correctedClaims"] == 1 and resource["grounding"]["removedClaims"] == []
    assert sorted(o["text"] for o in resource["options"]) == ["IP", "TCP", "UDP"]
    assert sum(o["isCorrect"] for o in resource["options"]) == 1
    assert all(o["decision"] == "pendiente" for o in resource["options"])

    without_source = next(o for o in resource["options"] if o["text"] == "IP")
    assert without_source["sourceFragmentIds"] == ["f1"] and without_source["feedback"]  # la cita ya corregida

    context = ai_gen.captured_contexts[0]
    assert context["curso"]["sumilla"] == "Curso de redes." and context["fragmentos"][0]["etiqueta"] == "F1"
    assert resource["generatorKind"] == "ia" and resource["params"]["optionCount"] == 3
    # La copia histórica guarda los fragmentos que el recurso cita (research R6), con su documento.
    assert {e["id"] for e in resource["evidence"]} <= {"f1", "f2"} and "f1" in {e["id"] for e in resource["evidence"]}
    assert all(e["documentName"] == "apuntes.pdf" for e in resource["evidence"])


def test_if_the_ai_fails_the_fallback_is_used_and_reported(tmp_path, caplog):
    run = run_generation(
        tmp_path, "item_opcion_multiple",
        primary=MockGenerator(error=RuntimeError("429 límite")),
        fallback=rules({"recursos": [MOCK_ITEM]}),
        option_count=3,
    )
    assert run.step.generator["description"] == "Reglas" and run.step.generator["fallback"] is True
    assert run.resources[0]["generatorKind"] == "respaldo"
    assert "429 límite" in caplog.text


def test_if_the_ai_does_not_cite_properly_the_fallback_is_used(tmp_path):
    bad_output = {"recursos": [{"titulo": "x", "contenido": "y", "citas": [{"afirmacion": "z", "fragmentos": ["F9"]}],
                                "alternativas": []}]}
    run = run_generation(
        tmp_path, "item_opcion_multiple",
        primary=MockGenerator(bad_output), fallback=rules({"recursos": [MOCK_ITEM]}), option_count=3,
    )
    assert run.step.generator["fallback"] is True
    assert [r["title"] for r in run.resources] == ["TCP o UDP"]


def test_without_valid_resources_rejects_without_inventing(tmp_path):
    run = run_generation(tmp_path, "item_opcion_multiple", primary=MockGenerator({"recursos": []}), option_count=3)
    assert run.request.status == RequestStatus.FAILED
    assert run.request.failure.code == "INSUFFICIENT_EVIDENCE" and run.resources == []


def test_a_unit_without_material_asks_to_upload_it(tmp_path):
    start = StartGenerationRequest(
        FakeMembership(), FakeEvidence(material=False), sqlite_repository(tmp_path), FakeRunner()
    )
    with pytest.raises(GenerationError) as err:
        start.execute(StartGenerationCommand(
            "docente-a", "u1", GenerationMode.INDIVIDUAL, "clave-sin-material",
            GenerationParameters(resource_types=("item_opcion_multiple",)),
        ))
    assert err.value.code == "NO_PROCESSED_MATERIAL" and "pestaña Material" in err.value.message
