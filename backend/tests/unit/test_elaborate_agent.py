"""
HU-050: el agente de Elaborar genera un caso aplicado con consigna y criterios de logro (C01) y no repite contenido de
las etapas anteriores de la clase (C02). En el caso, cada criterio cita el fragmento con el concepto que aplica.
"""

from __future__ import annotations

import io
import json
import re
import zipfile

from platform5e.application.services.generation.generation_service import NO_REPEAT_INSTRUCTION
from platform5e.application.services.generation.prompt_drafting import (
    build_generation_context,
    build_prompt_instructions,
    normalize_generated_resources,
    structure_from_model,
)
from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.domain.generation.grounding import link_criterion_sources
from platform5e.domain.generation.resource_catalog import RESOURCE_TYPES
from platform5e.domain.generation.resource_formats import normalize_structure, resource_format, structure_problems
from platform5e.domain.generation.sequence import SIMILARITY_THRESHOLD, content_similarity, resource_text
from platform5e.infrastructure.exporters.scorm_package_exporter import ACTIVITY_JS, ScormPackageExporter
from platform5e.infrastructure.exporters.unit_document_exporter import UnitDocumentExporter
from platform5e.infrastructure.llm.gemini_language_model import GEMINI_RESPONSE_SCHEMA
from tests.unit.test_generation_with_material import MOCK_COURSE, MOCK_FRAGMENTS, MOCK_UNIT, make_request_dict
from tests.unit.test_multimodal_resources import context_for
from tests.unit.test_sequence_orchestrator import (
    DISTINCT_RESOURCES,
    StageAwareGenerator,
    build_service,
    sequence_request,
)

TCP = "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable."
UDP = "El protocolo UDP no establece conexión y es más rápido."
FRAGMENTS = {"f1": TCP, "f2": UDP}

SCENARIO = (
    "Un colegio de Trujillo transmitirá en vivo su ceremonia de graduación y, por la misma red, enviará a cada familia "
    "la libreta de notas del año."
)
TASK = "Propón qué protocolo usar para cada servicio y justifica tu decisión ante la dirección del colegio."
TCP_CRITERION = {
    "criterion": "Justifica el uso de TCP porque es orientado a la conexión y garantiza una entrega confiable.",
    "fragmentIds": ["f1"],
}
UDP_CRITERION = {"criterion": "Explica por qué UDP es más rápido: no establece conexión.", "fragmentIds": ["f2"]}
BOTH_CRITERION = {
    "criterion": "Compara cuándo conviene la entrega confiable de TCP y cuándo la rapidez de UDP.",
    "fragmentIds": ["f1", "f2"],
}
INVENTED_CRITERION = {
    "criterion": "Calcula la latencia del enlace con la fórmula de Shannon y el ancho de banda.",
    "fragmentIds": ["f1"],
}


def context(**overrides):
    request = make_request_dict(**{"stage": "elaborate", "resourceType": "caso_aplicado", **overrides})
    return build_generation_context(MOCK_COURSE, MOCK_UNIT, request, MOCK_FRAGMENTS, {})


def model_criterion(criterion: dict, tags: list[str] | str) -> dict:
    return {"criterio": criterion["criterion"], "fragmentos": tags}


def applied_case(
    *criteria: dict, title: str = "La red del colegio", scenario: str = SCENARIO, task: str = TASK
) -> dict:
    return {
        "titulo": title,
        "contenido": "Lee la situación, resuelve la consigna y revisa tu solución con los criterios de logro.",
        "citas": [{"afirmacion": "TCP garantiza una entrega confiable", "fragmentos": ["F1"]}],
        "alternativas": [],
        "estructura": {"situacion": scenario, "consigna": task, "criterios": list(criteria)},
    }


GOOD_CASE = applied_case(
    model_criterion(TCP_CRITERION, ["F1"]),
    model_criterion(UDP_CRITERION, ["F2"]),
    model_criterion(BOTH_CRITERION, ["F1", "F2"]),
)


# --- C01: un caso aplicado con consigna y criterios de logro ---------------------------------------------------------


def test_elaborate_offers_an_applied_case_besides_the_application_exercise():
    elaborate = {entry.id: entry.format for entry in RESOURCE_TYPES if entry.stage == "elaborate"}
    assert elaborate["caso_aplicado"] == "interactive"
    assert elaborate["ejercicio_aplicacion"] == "text"  # el ejercicio de texto se conserva
    assert resource_format("caso_aplicado") == "interactive"


def test_an_applied_case_needs_a_scenario_a_task_and_three_criteria():
    criteria = [TCP_CRITERION, UDP_CRITERION, BOTH_CRITERION]
    structure = normalize_structure("caso_aplicado", {"scenario": SCENARIO, "task": TASK, "criteria": criteria})
    assert structure == {"scenario": SCENARIO, "task": TASK, "criteria": criteria}
    assert structure_problems("caso_aplicado", structure) == []
    for missing in ("scenario", "task"):
        assert normalize_structure("caso_aplicado", {**structure, missing: ""}) is None
    # Dos criterios iguales cuentan como uno: con eso quedan 2 y no alcanza.
    shouted = {**UDP_CRITERION, "criterion": UDP_CRITERION["criterion"].upper()}
    repeated = {**structure, "criteria": [TCP_CRITERION, UDP_CRITERION, shouted]}
    assert normalize_structure("caso_aplicado", repeated) is None
    problems = structure_problems("caso_aplicado", {**structure, "criteria": [TCP_CRITERION, UDP_CRITERION]})
    assert problems and "al menos 3" in problems[0]


def test_the_prompt_and_the_gemini_schema_ask_for_the_case_with_its_criteria():
    system_prompt, prompt = build_prompt_instructions(context())
    assert "Caso aplicado" in prompt and '"situacion"' in prompt and '"consigna"' in prompt and '"criterios"' in prompt
    assert "situación nueva" in prompt and "cada criterio salen solo de los fragmentos" in prompt
    # La solución la valora el docente: no se le dice al modelo que la plataforma la califica sola.
    assert "la califica el docente" in system_prompt and "califica automáticamente" not in system_prompt
    schema = GEMINI_RESPONSE_SCHEMA["properties"]["recursos"]["items"]["properties"]["estructura"]["properties"]
    assert schema["situacion"] == schema["consigna"] == {"type": "STRING"}
    assert set(schema["criterios"]["items"]["properties"]) == {"criterio", "fragmentos"}


def test_the_model_case_is_translated_and_its_tags_resolved():
    criteria = [model_criterion(TCP_CRITERION, ["F1"]), model_criterion(UDP_CRITERION, "F2"),
                model_criterion(BOTH_CRITERION, ["F9"])]
    raw = GOOD_CASE["estructura"] | {"criterios": criteria}
    structure = structure_from_model("caso_aplicado", raw, "", "", {"F1": "f1", "F2": "f2"})
    assert (structure["scenario"], structure["task"]) == (SCENARIO, TASK)
    assert [c["fragmentIds"] for c in structure["criteria"]] == [["f1"], ["f2"], []]


def test_a_criterion_whose_concept_is_in_its_fragment_keeps_its_citation():
    result = link_criterion_sources([TCP_CRITERION, UDP_CRITERION, BOTH_CRITERION], FRAGMENTS)
    assert [c["fragmentIds"] for c in result.criteria] == [["f1"], ["f2"], ["f1", "f2"]] and result.corrected == 0


def test_a_criterion_citing_the_wrong_fragment_is_linked_to_the_one_with_its_concept():
    result = link_criterion_sources([{**UDP_CRITERION, "fragmentIds": ["f1"]}], FRAGMENTS)
    assert result.criteria[0]["fragmentIds"] == ["f2"] and result.corrected == 1


def test_a_criterion_that_is_not_in_the_material_is_removed_with_its_reason():
    result = link_criterion_sources([TCP_CRITERION, INVENTED_CRITERION], FRAGMENTS)
    assert [c["criterion"] for c in result.criteria] == [TCP_CRITERION["criterion"]]
    [removed] = result.removed
    assert removed["criterion"] == INVENTED_CRITERION["criterion"] and "mínimo 30 %" in removed["reason"]
    assert result.summary() == {
        "criterionThreshold": 0.3, "checkedCriteria": 2, "supportedCriteria": 1,
        "correctedCriteria": 0, "removedCriteria": [removed],
    }


def test_normalization_keeps_the_new_scenario_links_each_criterion_and_drops_the_invented_one():
    payload = {"recursos": [applied_case(
        model_criterion(TCP_CRITERION, ["F1"]),
        model_criterion(UDP_CRITERION, ["F1"]),  # cita equivocada
        model_criterion(BOTH_CRITERION, ["F1", "F2"]),
        model_criterion(INVENTED_CRITERION, ["F1"]),
    )]}
    rejections: list[dict] = []
    [resource] = normalize_generated_resources(payload, context(), rejections)
    structure = resource["estructura"]
    # La situación del colegio no está en el material y no se contrasta: a propósito es un contexto nuevo.
    assert (structure["scenario"], structure["task"]) == (SCENARIO, TASK)
    assert [c["fragmentIds"] for c in structure["criteria"]] == [["f1"], ["f2"], ["f1", "f2"]]
    verification = resource["verificacion"]
    counts = (verification["checkedCriteria"], verification["supportedCriteria"], verification["correctedCriteria"])
    assert counts == (4, 3, 1)
    assert verification["removedCriteria"][0]["criterion"] == INVENTED_CRITERION["criterion"] and rejections == []


def test_a_case_with_less_than_three_supported_criteria_is_rejected_with_its_reason():
    payload = {"recursos": [applied_case(
        model_criterion(TCP_CRITERION, ["F1"]),
        model_criterion(UDP_CRITERION, ["F2"]),
        model_criterion(INVENTED_CRITERION, ["F1"]),
        title="Inventado",
    )]}
    rejections: list[dict] = []
    assert normalize_generated_resources(payload, context(), rejections) == []
    assert rejections[0]["title"] == "Inventado" and "solo 2 criterio(s) de logro" in rejections[0]["reason"]
    assert rejections[0]["grounding"]["removedCriteria"][0]["criterion"] == INVENTED_CRITERION["criterion"]


def test_the_rule_based_fallback_writes_a_case_whose_criteria_cite_the_material():
    ctx = context_for("caso_aplicado", 2)  # el corpus de protocolos de evaluation/corpus
    resources = normalize_generated_resources(RuleBasedGenerator().generate(ctx), ctx)
    assert len(resources) == 2 and resources[0]["estructura"]["scenario"] != resources[1]["estructura"]["scenario"]
    for resource in resources:
        structure = resource["estructura"]
        assert structure["scenario"] and structure["task"].startswith("Propón una solución")
        assert 3 <= len(structure["criteria"]) <= 4 and all(c["fragmentIds"] for c in structure["criteria"])
        assert resource["verificacion"]["supportedCriteria"] == len(structure["criteria"])


# --- C02: no repite contenido de las etapas anteriores ---------------------------------------------------------------

CASE_RESPONSE = GOOD_CASE
# Un caso que copia la explicación de la etapa anterior en vez de plantear una situación nueva.
COPIED_CASE = applied_case(
    model_criterion({"criterion": "TCP garantiza la entrega: antes de enviar datos establece una conexión."}, ["F1"]),
    model_criterion({"criterion": "TCP garantiza la entrega confiable y establece una conexión."}, ["F1"]),
    model_criterion({"criterion": "Antes de enviar datos, TCP establece una conexión."}, ["F1"]),
    title="Entrega confiable con TCP",
    scenario="TCP garantiza la entrega: antes de enviar datos establece una conexión.",
    task="Explica que TCP garantiza la entrega y que establece una conexión antes de enviar datos.",
)


def test_an_applied_case_that_repeats_an_earlier_stage_is_asked_again_and_rejected():
    generator = StageAwareGenerator({**DISTINCT_RESOURCES, "caso_aplicado": COPIED_CASE})
    service, _ = build_service(generator)
    result = service.generate_sequence(sequence_request("explicacion", "caso_aplicado"), "docente")

    assert [r["type"] for r in result["resources"]] == ["explicacion"]
    elaborate_step = result["sequence"][1]
    assert elaborate_step["agent"] == "Agente de Elaborar" and elaborate_step["generated"] == 0
    assert "repetía «Entrega confiable con TCP»" in elaborate_step["rejected"][0]
    # Se le pidió de nuevo una vez, con la instrucción de no repetir, antes de rechazarlo.
    retries = [c for c in generator.contexts if NO_REPEAT_INSTRUCTION in c["solicitud"]["indicaciones"]]
    assert [c["solicitud"]["tipo"] for c in retries] == ["caso_aplicado"]


def test_the_retry_keeps_the_applied_case_when_it_no_longer_repeats():
    generator = StageAwareGenerator(
        {**DISTINCT_RESOURCES, "caso_aplicado": COPIED_CASE}, retry_responses={"caso_aplicado": CASE_RESPONSE}
    )
    service, _ = build_service(generator)
    result = service.generate_sequence(sequence_request("explicacion", "caso_aplicado"), "docente")
    assert [r["title"] for r in result["resources"]] == ["Entrega confiable con TCP", "La red del colegio"]
    assert result["sequence"][1]["generated"] == 1 and result["sequence"][1]["rejected"] == []


def test_a_distinct_applied_case_follows_the_earlier_stages_and_knows_what_they_wrote():
    generator = StageAwareGenerator({**DISTINCT_RESOURCES, "caso_aplicado": CASE_RESPONSE})
    service, _ = build_service(generator)
    result = service.generate_sequence(
        sequence_request("caso_aplicado", "pregunta_detonante", "explicacion", "item_opcion_multiple"), "docente"
    )

    assert [r["stage"] for r in result["resources"]] == ["engage", "explain", "elaborate", "evaluate"]
    case = result["resources"][2]
    assert case["type"] == "caso_aplicado" and case["agent"] == "Agente de Elaborar"
    assert case["structure"]["scenario"] == SCENARIO and len(case["structure"]["criteria"]) == 3
    assert all(step["rejected"] == [] for step in result["sequence"])
    # El agente de Elaborar recibe lo que redactaron Enganchar y Explicar para no repetirlo.
    elaborate_context = next(c for c in generator.contexts if c["solicitud"]["tipo"] == "caso_aplicado")
    assert [p["titulo"] for p in elaborate_context["secuenciaPrevia"]] == [
        "Video en vivo sin esperas", "Entrega confiable con TCP",
    ]
    _, prompt = build_prompt_instructions(elaborate_context)
    assert "OTROS AGENTES YA REDACTARON" in prompt and "- Entrega confiable con TCP:" in prompt


def test_the_copied_case_is_over_the_repetition_threshold_and_the_new_one_is_not():
    explanation = resource_text(DISTINCT_RESOURCES["explicacion"])
    copied = normalize_generated_resources({"recursos": [COPIED_CASE]}, context())[0]
    new = normalize_generated_resources({"recursos": [CASE_RESPONSE]}, context())[0]
    # Del caso se compara lo que debe ser nuevo (título, situación y consigna), no sus criterios, que citan el material
    # a propósito, ni las instrucciones para el estudiante, que son las mismas en todos los casos.
    assert resource_text(new) == f"La red del colegio {SCENARIO} {TASK}"
    assert content_similarity(resource_text(copied), explanation) >= SIMILARITY_THRESHOLD
    assert content_similarity(resource_text(new), explanation) < SIMILARITY_THRESHOLD


# --- Exportación -----------------------------------------------------------------------------------------------------


def approved_case() -> dict:
    return {
        "id": "r1", "type": "caso_aplicado", "stage": "elaborate", "status": "aprobado", "format": "interactive",
        "title": "La red del colegio", "body": "Resuelve el caso.", "createdAt": "2026-11-04T10:00", "options": None,
        "structure": {"scenario": SCENARIO, "task": TASK, "criteria": [TCP_CRITERION, UDP_CRITERION, BOTH_CRITERION]},
        "evidence": [
            {"id": "f1", "text": TCP, "location": "p. 1", "documentName": "apuntes.pdf"},
            {"id": "f2", "text": UDP, "location": "p. 2", "documentName": "apuntes.pdf"},
        ],
    }


def test_the_scorm_page_asks_for_a_solution_and_shows_each_criterion_with_its_source():
    exported = ScormPackageExporter().export([approved_case()], {"code": "RED"}, {"number": 1, "title": "T"})
    archive = zipfile.ZipFile(io.BytesIO(exported.content))
    page = next(archive.read(n).decode() for n in archive.namelist() if n.startswith("sco/"))
    assert 'data-kind="activity"' in page and "Para aplicar" in page
    data = json.loads(re.search(r'id="activity-data">(.*?)</script>', page, re.S).group(1))
    assert data["type"] == "caso_aplicado" and data["structure"]["scenario"] == SCENARIO
    assert [c["source"] for c in data["structure"]["criteria"]] == [
        "apuntes.pdf, p. 1", "apuntes.pdf, p. 2", "apuntes.pdf, p. 1; apuntes.pdf, p. 2",
    ]
    assert "caso_aplicado: function" in ACTIVITY_JS and "case-solution" in ACTIVITY_JS
    # La solución la valora el docente: se registra el porcentaje, pero la actividad queda completada.
    assert "selfAssessed && window.scorm5e && window.scorm5e.complete" in ACTIVITY_JS


def test_the_unit_document_prints_the_case_a_space_to_solve_it_and_the_criteria():
    html = UnitDocumentExporter().export([approved_case()], {"code": "RED"}, {"number": 1, "title": "T"})
    content = html.content.decode()
    assert "Para aplicar" in content and "Caso aplicado" in content and "Un colegio de Trujillo" in content
    assert "<strong>Consigna:</strong> Propón qué protocolo usar" in content and "Tu solución:" in content
    assert "☐ Justifica el uso de TCP" in content and "Fuente: p. 1, p. 2" in content
    assert "Clave de respuestas" not in content
