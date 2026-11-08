"""
HU-019: cada distractor trae su justificación y el error conceptual que representa (C01), y se descartan los que la
evidencia muestra como correctos (C02), lo que alimenta el indicador I5 (error de fiabilidad).
"""

from __future__ import annotations

from platform5e.application.services.generation.prompt_drafting import (
    build_generation_context,
    build_prompt_instructions,
    normalize_generated_resources,
)
from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.domain.generation.distractor_reliability import assess_distractor, reliability_report
from tests.unit.test_generation_with_material import (
    MOCK_COURSE,
    MOCK_UNIT,
    MockGenerator,
    MockMaterialChunkRepository,
    build_service_setup,
    make_request_dict,
)

MATERIAL = {
    "f1": "TCP y SCTP son protocolos orientados a la conexión que garantizan la entrega. UDP no garantiza la entrega.",
    "f2": "UDP es un protocolo sin conexión y más rápido. IP pertenece a la capa de red.",
}
STEM = "¿Qué protocolo orientado a la conexión garantiza la entrega?"


def distractor(text, justification="Revisa el material.", misconception="Confunde los protocolos."):
    option = {"texto": text, "correcta": False, "fragmentos": ["F2"]}
    if justification:
        option["retroalimentacion"] = justification
    if misconception:
        option["error_conceptual"] = misconception
    return option


def item(*distractors):
    return {
        "titulo": "Protocolo con conexión",
        "contenido": STEM,
        "citas": [{"afirmacion": "TCP y SCTP son protocolos orientados a la conexión", "fragmentos": ["F1"]}],
        "alternativas": [
            {"texto": "TCP", "correcta": True, "retroalimentacion": "Correcto.", "fragmentos": ["F1"]},
            *distractors,
        ],
    }


FRAGMENTS = [{"id": fid, "text": text, "location": f"p. {i + 1}"} for i, (fid, text) in enumerate(MATERIAL.items())]


def context(options=4):
    return build_generation_context(
        MOCK_COURSE, MOCK_UNIT, make_request_dict(optionCount=options), FRAGMENTS, {}
    )


# --- C02: la evidencia decide si un distractor también es correcto ---------------------------------------------


def test_a_distractor_the_material_states_as_an_answer_is_flagged_with_the_sentence():
    issue = assess_distractor(STEM, "TCP", "SCTP", MATERIAL)
    assert issue is not None and issue.fragment_id == "f1"
    assert issue.reason.startswith("El material también lo presenta como respuesta: «TCP y SCTP son protocolos")


def test_a_distractor_mentioned_in_another_sense_is_reliable():
    assert assess_distractor(STEM, "TCP", "UDP", MATERIAL) is None  # su oración no habla de conexión ni de entrega
    assert assess_distractor(STEM, "TCP", "IP", MATERIAL) is None


def test_a_negated_sentence_does_not_make_a_distractor_correct():
    material = {"f1": "UDP no está orientado a la conexión ni garantiza la entrega."}
    assert assess_distractor(STEM, "TCP", "UDP", material) is None


def test_a_distractor_that_says_the_same_as_the_key_is_flagged():
    issue = assess_distractor(STEM, "El protocolo TCP", "Protocolo TCP", MATERIAL)
    assert issue is not None and "lo mismo que la respuesta correcta" in issue.reason


def test_words_of_the_instruction_that_are_not_in_the_material_do_not_count():
    stem = "Según el material de la unidad, ¿qué término completa la afirmación? «___ garantiza la entrega»"
    assert assess_distractor(stem, "TCP", "SCTP", MATERIAL) is not None


# --- C01: justificación y error conceptual -----------------------------------------------------------------------


def test_the_prompt_asks_for_the_justification_and_the_misconception_of_each_distractor():
    _, user_prompt = build_prompt_instructions(context())
    assert '"error_conceptual"' in user_prompt and "concepción errónea que representa" in user_prompt


def test_distractors_without_justification_or_misconception_are_not_used():
    raw = item(distractor("UDP"), distractor("IP", misconception=""), distractor("HTTP", justification=""))
    rejected: list[dict] = []
    assert normalize_generated_resources({"recursos": [raw]}, context(options=3), rejected) == []
    ok = normalize_generated_resources({"recursos": [item(distractor("UDP"), distractor("IP"))]}, context(options=3))
    assert [a.get("errorConceptual") for a in ok[0]["alternativas"]] == [None, "Confunde los protocolos.", "Confunde los protocolos."]


def test_the_rule_based_generator_explains_the_misconception_of_each_distractor():
    text = (
        "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable. "
        "El protocolo UDP no confirma la entrega; por eso es más rápido e introduce menos retardo."
    )
    chunks = [{"id": "c1", "text": text, "location": "p. 1"}]
    ctx = build_generation_context(MOCK_COURSE, MOCK_UNIT, make_request_dict(optionCount=4), chunks, {})
    [resource] = normalize_generated_resources(RuleBasedGenerator().generate(ctx), ctx)
    distractors = [a for a in resource["alternativas"] if not a["correcta"]]
    assert len(distractors) == 3 and all(a["errorConceptual"].startswith("Confunde «") for a in distractors)
    assert not any(a.get("tambienCorrecto") for a in distractors)  # ninguno es correcto según el material


# --- En el servicio: descartado con su motivo e I5 ------------------------------------------------------------------


def test_the_service_discards_the_correct_distractor_with_its_reason_and_reports_i5():
    raw = item(distractor("SCTP"), distractor("UDP"), distractor("IP"))
    chunks = MockMaterialChunkRepository([{**f, "documentId": "doc1", "unitId": "u1"} for f in FRAGMENTS])
    service, _ = build_service_setup(MockGenerator({"recursos": [raw]}), chunk_repo=chunks)
    result = service.generate(make_request_dict(optionCount=4), "docente")

    options = {o["text"]: o for o in result["resources"][0]["options"]}
    assert options["SCTP"]["decision"] == "descartado" and options["SCTP"]["discardReason"] == "tambien_correcto"
    assert options["SCTP"]["reliabilityWarning"].startswith("El material también lo presenta como respuesta")
    assert options["UDP"]["decision"] == "pendiente" and options["UDP"]["reliabilityWarning"] is None
    assert options["UDP"]["misconception"] == "Confunde los protocolos." and options["UDP"]["feedback"]
    assert result["distractorReliability"] == {
        "evaluatedDistractors": 3,
        "discardedAsCorrect": 1,
        "reliabilityErrorRate": 0.3333,
    }


def test_an_item_with_less_than_two_reliable_distractors_is_rejected_with_its_reason():
    raw = item(distractor("SCTP"), distractor("UDP"))
    rejected: list[dict] = []
    assert normalize_generated_resources({"recursos": [raw]}, context(options=3), rejected) == []
    assert rejected[0]["reason"] == (
        "«Protocolo con conexión»: solo 1 distractor(es) fiable(s); el material muestra como correctos los demás."
    )


def test_reliability_report_without_items():
    assert reliability_report([{"options": None}]) == {
        "evaluatedDistractors": 0,
        "discardedAsCorrect": 0,
        "reliabilityErrorRate": None,
    }

