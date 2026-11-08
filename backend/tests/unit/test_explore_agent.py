"""
HU-048: el agente de Explorar genera una exploración guiada, una actividad interactiva con pasos y preguntas guía
(C01), en la que cada paso cita su fragmento de origen (C02).
"""

from __future__ import annotations

import io
import json
import re
import zipfile

from platform5e.application.services.generation.prompt_drafting import (
    build_generation_context,
    build_prompt_instructions,
    normalize_generated_resources,
    structure_from_model,
)
from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.domain.generation.grounding import link_step_sources
from platform5e.domain.generation.resource_formats import normalize_structure, resource_format, structure_problems
from platform5e.infrastructure.exporters.scorm_package_exporter import ACTIVITY_JS, ScormPackageExporter
from platform5e.infrastructure.exporters.unit_document_exporter import UnitDocumentExporter
from platform5e.infrastructure.llm.gemini_language_model import GEMINI_RESPONSE_SCHEMA
from tests.unit.test_generation_with_material import MOCK_COURSE, MOCK_FRAGMENTS, MOCK_UNIT, make_request_dict
from tests.unit.test_multimodal_resources import context_for

TCP = "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable."
UDP = "El protocolo UDP no establece conexión y es más rápido."
FRAGMENTS = {"f1": TCP, "f2": UDP}

TCP_STEP = {
    "title": "Entrega confiable",
    "instruction": "Lee cómo el protocolo TCP garantiza una entrega confiable.",
    "question": "¿Por qué TCP necesita la conexión?",
    "fragmentIds": ["f1"],
}
UDP_STEP = {
    "title": "Rapidez de UDP",
    "instruction": "Observa por qué el protocolo UDP es más rápido.",
    "question": "¿Qué pierde UDP al no establecer conexión?",
    "fragmentIds": ["f2"],
}
INVENTED_STEP = {
    "title": "Historia de ARPANET",
    "instruction": "Investiga quién diseñó ARPANET en 1969 y en qué universidades se instaló.",
    "question": "¿Cuántos nodos tenía la primera red militar?",
    "fragmentIds": ["f1"],
}


def context(**overrides):
    request = make_request_dict(**{"stage": "explore", "resourceType": "exploracion_guiada", **overrides})
    return build_generation_context(MOCK_COURSE, MOCK_UNIT, request, MOCK_FRAGMENTS, {})


def model_step(title: str, instruction: str, question: str, tags: list[str]) -> dict:
    return {"titulo": title, "consigna": instruction, "pregunta": question, "fragmentos": tags}


def exploration(*steps: dict, title: str = "Explora TCP y UDP") -> dict:
    return {
        "titulo": title,
        "contenido": "Recorre los pasos y anota lo que encuentres en el material.",
        "citas": [{"afirmacion": "TCP garantiza una entrega confiable", "fragmentos": ["F1"]}],
        "alternativas": [],
        "estructura": {"pasos_guiados": list(steps)},
    }


# --- C01: actividad interactiva con pasos y preguntas guía ----------------------------------------------------------


def test_the_guided_exploration_is_an_interactive_explore_resource():
    assert resource_format("exploracion_guiada") == "interactive"
    structure = normalize_structure("exploracion_guiada", {"guidedSteps": [TCP_STEP, UDP_STEP, TCP_STEP]})
    assert [step["title"] for step in structure["guidedSteps"]] == ["Entrega confiable", "Rapidez de UDP", "Entrega confiable"]
    assert structure_problems("exploracion_guiada", structure) == []


def test_a_step_needs_title_instruction_and_question_and_the_activity_three_steps():
    incomplete = {**TCP_STEP, "question": ""}
    assert normalize_structure("exploracion_guiada", {"guidedSteps": [TCP_STEP, UDP_STEP, incomplete]}) is None
    problems = structure_problems("exploracion_guiada", {"guidedSteps": [TCP_STEP, UDP_STEP]})
    assert problems and "al menos 3" in problems[0]


def test_the_prompt_and_the_gemini_schema_ask_for_guided_steps_with_their_fragments():
    _, prompt = build_prompt_instructions(context())
    assert '"pasos_guiados"' in prompt and '"consigna"' in prompt and '"pregunta"' in prompt
    assert "Exploración guiada" in prompt
    guided = GEMINI_RESPONSE_SCHEMA["properties"]["recursos"]["items"]["properties"]["estructura"]["properties"]
    assert set(guided["pasos_guiados"]["items"]["properties"]) == {"titulo", "consigna", "pregunta", "fragmentos"}


def test_the_model_steps_are_translated_and_their_tags_resolved():
    raw = {"pasos_guiados": [model_step("A", "Lee TCP", "¿Qué?", ["F1"]), model_step("B", "Lee UDP", "¿Y?", "F2"),
                             model_step("C", "Compara", "¿Cuál?", ["F9"])]}
    structure = structure_from_model("exploracion_guiada", raw, "", "", {"F1": "f1", "F2": "f2"})
    assert [step["fragmentIds"] for step in structure["guidedSteps"]] == [["f1"], ["f2"], []]
    assert structure["guidedSteps"][0] == {"title": "A", "instruction": "Lee TCP", "question": "¿Qué?", "fragmentIds": ["f1"]}


# --- C02: cada paso cita su fragmento de origen -----------------------------------------------------------------------


def test_a_step_supported_by_its_fragment_keeps_its_citation():
    result = link_step_sources([TCP_STEP, UDP_STEP], FRAGMENTS)
    assert [step["fragmentIds"] for step in result.steps] == [["f1"], ["f2"]] and result.corrected == 0


def test_a_step_citing_the_wrong_fragment_is_linked_to_the_one_that_supports_it():
    result = link_step_sources([{**UDP_STEP, "fragmentIds": ["f1"]}], FRAGMENTS)
    assert result.steps[0]["fragmentIds"] == ["f2"] and result.corrected == 1


def test_a_step_without_citation_is_linked_to_the_best_fragment():
    result = link_step_sources([{**TCP_STEP, "fragmentIds": []}], FRAGMENTS)
    assert result.steps[0]["fragmentIds"] == ["f1"]


def test_a_step_that_the_material_does_not_support_is_removed_with_its_reason():
    result = link_step_sources([TCP_STEP, INVENTED_STEP], FRAGMENTS)
    assert [step["title"] for step in result.steps] == ["Entrega confiable"]
    [removed] = result.removed
    assert removed["title"] == "Historia de ARPANET" and "mínimo 30 %" in removed["reason"]
    assert result.summary() == {
        "stepThreshold": 0.3, "checkedSteps": 2, "supportedSteps": 1, "correctedSteps": 0, "removedSteps": [removed],
    }


def test_normalization_links_each_step_and_drops_the_invented_one():
    payload = {"recursos": [exploration(
        model_step(TCP_STEP["title"], TCP_STEP["instruction"], TCP_STEP["question"], ["F1"]),
        model_step(UDP_STEP["title"], UDP_STEP["instruction"], UDP_STEP["question"], ["F1"]),  # cita equivocada
        model_step("Conexión", "Compara si el protocolo TCP y el protocolo UDP establecen conexión.",
                   "¿Cuál establece conexión?", ["F1", "F2"]),
        model_step(INVENTED_STEP["title"], INVENTED_STEP["instruction"], INVENTED_STEP["question"], ["F1"]),
    )]}
    rejections: list[dict] = []
    [resource] = normalize_generated_resources(payload, context(), rejections)
    steps = resource["estructura"]["guidedSteps"]
    assert [step["fragmentIds"] for step in steps] == [["f1"], ["f2"], ["f1", "f2"]]
    verification = resource["verificacion"]
    assert (verification["checkedSteps"], verification["supportedSteps"], verification["correctedSteps"]) == (4, 3, 1)
    assert verification["removedSteps"][0]["title"] == "Historia de ARPANET" and rejections == []


def test_an_exploration_with_less_than_three_supported_steps_is_rejected_with_its_reason():
    payload = {"recursos": [exploration(
        model_step(TCP_STEP["title"], TCP_STEP["instruction"], TCP_STEP["question"], ["F1"]),
        model_step(UDP_STEP["title"], UDP_STEP["instruction"], UDP_STEP["question"], ["F2"]),
        model_step(INVENTED_STEP["title"], INVENTED_STEP["instruction"], INVENTED_STEP["question"], ["F1"]),
        title="Inventada",
    )]}
    rejections: list[dict] = []
    assert normalize_generated_resources(payload, context(), rejections) == []
    assert rejections[0]["title"] == "Inventada" and "solo 2 paso(s)" in rejections[0]["reason"]
    assert rejections[0]["grounding"]["removedSteps"][0]["title"] == "Historia de ARPANET"


def test_the_rule_based_fallback_cites_a_fragment_in_every_step():
    ctx = context_for("exploracion_guiada", 1)  # el corpus de protocolos de evaluation/corpus
    [resource] = normalize_generated_resources(RuleBasedGenerator().generate(ctx), ctx)
    steps = resource["estructura"]["guidedSteps"]
    assert len(steps) >= 3 and all(step["fragmentIds"] and step["question"].startswith("¿") for step in steps)
    assert resource["verificacion"]["supportedSteps"] == len(steps)


# --- Exportación -----------------------------------------------------------------------------------------------------


def approved_exploration() -> dict:
    return {
        "id": "r1", "type": "exploracion_guiada", "stage": "explore", "status": "aprobado", "format": "interactive",
        "title": "Explora TCP y UDP", "body": "Recorre los pasos.", "createdAt": "2026-11-02T10:00", "options": None,
        "structure": {"guidedSteps": [TCP_STEP, UDP_STEP, {**TCP_STEP, "fragmentIds": ["f1", "f2"]}]},
        "evidence": [
            {"id": "f1", "text": TCP, "location": "p. 1", "documentName": "apuntes.pdf"},
            {"id": "f2", "text": UDP, "location": "p. 2", "documentName": "apuntes.pdf"},
        ],
    }


def test_the_scorm_page_shows_each_step_with_its_source_and_a_space_to_answer():
    exported = ScormPackageExporter().export([approved_exploration()], {"code": "RED"}, {"number": 1, "title": "T"})
    archive = zipfile.ZipFile(io.BytesIO(exported.content))
    page = next(archive.read(n).decode() for n in archive.namelist() if n.startswith("sco/"))
    assert 'data-kind="activity"' in page
    data = json.loads(re.search(r'id="activity-data">(.*?)</script>', page, re.S).group(1))
    assert data["type"] == "exploracion_guiada"
    assert [step["source"] for step in data["structure"]["guidedSteps"]] == [
        "apuntes.pdf, p. 1", "apuntes.pdf, p. 2", "apuntes.pdf, p. 1; apuntes.pdf, p. 2",
    ]
    assert "exploracion_guiada: function" in ACTIVITY_JS and "textarea" in ACTIVITY_JS


def test_the_unit_document_prints_each_step_with_its_question_and_source():
    html = UnitDocumentExporter().export([approved_exploration()], {"code": "RED"}, {"number": 1, "title": "T"})
    content = html.content.decode()
    assert "Exploración guiada" in content and "¿Por qué TCP necesita la conexión?" in content
    assert "Fuente: p. 1" in content and "Fuente: p. 1, p. 2" in content
