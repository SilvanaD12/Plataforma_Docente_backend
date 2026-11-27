"""GEN-C14 (spec 002, T076, research R14) y T029 (spec 006): generación anclada al resultado de aprendizaje elegido.

Cambio B del «Plan de cambios v2» de Juan: en producción, con «RA1.1: Reconoce…» elegido, el recurso habló del
Renacimiento y pidió analizar y comparar. Se reproduce con el corpus real de T067 («Modelo OSI.txt») y un documento
distractor sobre el Renacimiento que la búsqueda trae primero. Sin red ni proveedores: reglas y Gemini falso.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from platform5e.application.ports.outbound.evidence_provider_port import EvidenceFragment
from platform5e.application.ports.outbound.unit_membership_port import OutcomeRef, UnitContext
from platform5e.application.services.generation.concept_extraction import outcome_concepts
from platform5e.application.services.generation.plan_drafting import (
    GenerationPlanner,
    RuleBasedPlanner,
    build_plan_prompt,
)
from platform5e.application.services.generation.prompt_drafting import (
    build_generation_context,
    build_prompt_instructions,
    normalize_generated_resources,
    outcome_anchor,
)
from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.application.use_cases.generation.run_generation_request import RunGenerationRequest
from platform5e.application.use_cases.generation.start_generation_request import StartGenerationCommand
from platform5e.domain.generation.generation_request import GenerationMode, GenerationParameters
from platform5e.domain.generation.outcome_alignment import (
    ANALYZE,
    MISALIGNED_KIND,
    RECALL,
    UNDERSTAND,
    anchor_terms,
    is_aligned,
    split_outcome,
    verb_level,
)
from platform5e.domain.generation.plan_coverage import mentions
from platform5e.infrastructure.adapters.review_verification_adapter import ReviewVerificationAdapter
from tests.support.generation_fakes import FakeEvidence
from tests.unit.test_generation_plan_use_cases import command, creator
from tests.unit.test_generation_plan_use_cases import repository as repository  # noqa: F401 (fixture)
from tests.unit.test_plan_drafting import CATALOG, EVIDENCE, Recorder, gemini, gemini_answer, inputs
from tests.unit.test_start_regeneration import Setup
from tests.unit.test_topic_coverage import _corpus_fragments

RECOGNIZE = "Reconoce las capas del modelo OSI y la función de cada una"
OUTCOME = {"id": "ra-1", "code": "RA1.1", "text": RECOGNIZE}
UNIT = {"number": 1, "title": "Modelo OSI", "outcomes": [OUTCOME]}
COURSE = {"name": "Redes"}
OUTCOME_TERMS = ("capas", "modelo", "OSI")
# El documento distractor: otro tema, sin ningún término del resultado ni de la unidad.
RENAISSANCE = [
    "El Renacimiento fue un movimiento cultural que surgió en Italia durante el siglo XV y se extendió por Europa.",
    "Los artistas del Renacimiento estudiaron la perspectiva para representar el espacio con profundidad.",
    "Leonardo da Vinci fue un pintor e inventor que estudió la anatomía humana con gran detalle en sus cuadernos.",
    "Miguel Ángel pintó la bóveda de la Capilla Sixtina entre los años 1508 y 1512 en la ciudad de Roma.",
    "La imprenta de Gutenberg permitió difundir los libros del Renacimiento a un costo mucho menor que antes.",
    "Los mecenas como la familia Médici financiaron a los artistas y a los arquitectos de la ciudad de Florencia.",
]
DISTRACTOR = {"id": "ren-0", "documentId": "renacimiento", "text": " ".join(RENAISSANCE)}
OSI = [{"id": c["id"], "documentId": "osi", "text": c["text"]} for c in _corpus_fragments(["Modelo OSI.txt"])[:6]]


def context(resource_type: str, outcome: dict | None = OUTCOME, chunks=None, quantity: int = 1) -> dict:
    unit = {**UNIT, "outcomes": [outcome] if outcome else []}
    request = {"stage": "engage", "resourceType": resource_type, "quantity": quantity,
               "outcomeId": outcome["id"] if outcome else None}
    return build_generation_context(COURSE, unit, request, chunks or [DISTRACTOR, *OSI], {})


def draft(resource_type: str, **kwargs) -> dict:
    [resource] = RuleBasedGenerator().generate(context(resource_type, **kwargs))["recursos"]
    return resource


def cited(resource: dict) -> list[str]:
    return [c["afirmacion"] for c in resource["citas"]]


def mentions_outcome(text: str) -> bool:
    return any(mentions(text, term) for term in OUTCOME_TERMS)


# Reglas del dominio


@pytest.mark.parametrize(("outcome", "level"), [
    ("Reconoce las capas del modelo OSI", RECALL),
    ("RA1.1: Identifica los protocolos de la capa de transporte", RECALL),
    ("Define qué es un datagrama", RECALL),
    ("El estudiante reconoce las capas del modelo OSI", RECALL),
    ("Explica el saludo de tres vías", UNDERSTAND),
    ("Describir el formato del segmento UDP", UNDERSTAND),
    ("Analiza el control de congestión", ANALYZE),
    ("Compara TCP y UDP", ANALYZE),
    ("Evalúa la elección del protocolo de transporte", ANALYZE),
    ("Aplica el modelo OSI a una red doméstica", None),  # fuera de la tabla: la consigna de siempre
    ("Las capas del modelo OSI", None),
])
def test_the_explicit_verb_table_gives_the_level(outcome, level):
    assert verb_level(outcome) == level


def test_anchor_terms_drop_the_code_and_the_verb_and_add_the_unit_title():
    assert split_outcome("RA1.1: Reconoce las capas del modelo OSI") == ("reconoce", "las capas del modelo OSI")
    assert split_outcome("Distingue TCP y UDP") == (None, "TCP y UDP")  # verbo fuera de la tabla: igual se quita
    assert split_outcome("TCP y UDP") == (None, "TCP y UDP")
    assert anchor_terms("RA1.1: Reconoce las capas del modelo OSI", "Protocolos de transporte") == [
        "capas", "modelo", "OSI", "Protocolos", "transporte"]
    assert is_aligned(["La capa física transmite bits."], ["capas"])  # singular y plural
    assert not is_aligned(RENAISSANCE, anchor_terms(RECOGNIZE, "Modelo OSI"))
    assert is_aligned(RENAISSANCE, [])  # sin términos no hay nada que comprobar


def test_without_a_chosen_outcome_nothing_is_anchored():
    assert outcome_anchor(context("explicacion", outcome=None)) == ([], None)
    assert outcome_anchor(context("explicacion")) == (["capas", "modelo", "OSI"], RECALL)  # «función» y «cada» no son del tema


# El caso de producción, con el generador por reglas


@pytest.mark.parametrize("resource_type", ["pregunta_detonante", "guia_exploracion", "caso_indagacion",
                                           "item_opcion_multiple"])
def test_the_production_case_drifted_to_the_distractor_without_the_outcome_and_is_anchored_with_it(resource_type):
    # Sin resultado elegido (como antes del cambio), la oración del Renacimiento gana por la frecuencia de sus palabras.
    assert not mentions_outcome(cited(draft(resource_type, outcome=None))[0])
    # Con «Reconoce…» elegido, el recurso cita primero el material del resultado y menciona sus términos.
    resource = draft(resource_type)
    assert mentions_outcome(cited(resource)[0]), cited(resource)
    assert not any("Renacimiento" in text for text in cited(resource))
    assert "desalineado" not in resource


def test_a_recall_outcome_asks_a_recall_question_and_not_to_analyze_or_compare():
    trigger = draft("pregunta_detonante")["contenido"]
    assert "Pregunta detonante: ¿Qué es modelo OSI según el material? Escríbelo en una oración breve." in trigger
    guide = draft("guia_exploracion")["contenido"]
    assert "4. Identifica qué dice cada fragmento sobre" in guide and "Compara ambos fragmentos" not in guide
    case = draft("caso_indagacion")["contenido"]
    assert "1. ¿Qué es" in case and "¿Qué pasaría si cambiara" not in case and "3." not in case.split("indagación")[1]
    for text in (trigger, guide, case):
        assert "Analiza" not in text and "Compara" not in text


def test_a_recall_outcome_keeps_the_explanation_to_one_idea():
    assert len(draft("explicacion")["citas"]) <= 2 < len(draft("explicacion", outcome=None)["citas"])


@pytest.mark.parametrize(("outcome_text", "expected"), [
    ("Explica las capas del modelo OSI", "Explica con tus palabras qué es modelo OSI y para qué sirve"),
    ("Compara las capas del modelo OSI", "Analiza la relación entre modelo OSI y"),
    ("Aplica las capas del modelo OSI", "¿Dónde has visto modelo OSI en tu vida diaria"),  # fuera de la tabla
])
def test_the_trigger_question_follows_the_verb_level(outcome_text, expected):
    resource = draft("pregunta_detonante", outcome={**OUTCOME, "text": outcome_text})
    assert expected in resource["contenido"]


def test_a_misaligned_candidate_is_replaced_by_the_next_one():
    # Ordenar los pasos conserva el orden del material, así que su primera ventana es del Renacimiento.
    first_window = RENAISSANCE[:5]
    resource = draft("ordenar_pasos")
    assert cited(resource) != first_window and any(mentions_outcome(text) for text in cited(resource))
    assert "desalineado" not in resource
    assert cited(draft("ordenar_pasos", outcome=None)) == first_window  # sin resultado, como antes


def test_when_no_candidate_mentions_the_outcome_the_best_one_is_delivered_with_a_warning():
    ctx = context("pregunta_detonante", chunks=[DISTRACTOR])
    raw = RuleBasedGenerator().generate(ctx)
    [resource] = raw["recursos"]
    assert resource["desalineado"] is True and "Renacimiento" in resource["contenido"]
    rejections: list = []
    [delivered] = normalize_generated_resources(raw, ctx, rejections)
    assert rejections == []  # no se rechaza
    warning = delivered["avisoPlan"]
    assert warning["kind"] == MISALIGNED_KIND and "«capas», «modelo», «OSI»" in warning["reason"]


def test_a_plan_concept_also_anchors_so_the_check_does_not_fight_the_approved_plan():
    ctx = context("explicacion")
    ctx["plan"] = {"proposito": "Explicar el Renacimiento", "conceptos": ["Renacimiento"], "noDesarrollar": []}
    resource = RuleBasedGenerator().generate(ctx)["recursos"][0]
    assert "desalineado" not in resource


# El pedido completo: el aviso llega al recurso y al paso


def test_the_warning_reaches_the_resource_and_the_step(tmp_path):
    setup = Setup(tmp_path)
    unit = UnitContext("c1", "Redes", "", "", "u1", 1, "Modelo OSI", (OutcomeRef("ra-1", "RA1.1", RECOGNIZE),))
    setup.membership.units[("docente-a", "u1")] = unit
    evidence = FakeEvidence((EvidenceFragment("ren-0", "ren", "renacimiento.txt", "p. 1", DISTRACTOR["text"], 0.9,
                                              None, None),))
    setup.use_case._start_generation._evidence = evidence
    request = setup.use_case._start_generation.execute(StartGenerationCommand(
        "docente-a", "u1", GenerationMode.INDIVIDUAL, "clave-anclaje-0001",
        GenerationParameters(resource_types=("pregunta_detonante",), outcome_id="ra-1"),
    )).request
    RunGenerationRequest(setup.repository, setup.membership, evidence, setup.review, ReviewVerificationAdapter(),
                         RuleBasedGenerator(), heartbeat_seconds=0).execute(request.id)
    [step] = setup.repository.get("docente-a", request.id).steps
    [resource] = setup.review.all()
    assert resource["planWarning"]["kind"] == MISALIGNED_KIND
    assert step.plan_warnings == ({"title": resource["title"], "reason": resource["planWarning"]["reason"],
                                   "resourceId": resource["id"]},)


# Plan por reglas (T029), con el corpus de T067


def test_the_outcome_gives_its_phrases_and_acronyms_without_the_verb():
    assert outcome_concepts("RA1.1: Reconoce las capas del modelo OSI") == ["modelo osi", "capas del modelo"]
    assert outcome_concepts("Distingue TCP y UDP") == ["TCP", "UDP"]  # siglas sueltas: ninguna frase las contiene
    assert outcome_concepts("") == []


def test_the_rule_planner_takes_the_outcome_concepts_first():
    requested = inputs(("pregunta_detonante", 1), ("explicacion", 1), instructions="Protocolos TCP y UDP")
    without = RuleBasedPlanner(CATALOG).draft(requested, EVIDENCE)
    anchored = RuleBasedPlanner(CATALOG).draft(requested, EVIDENCE, "RA1.1: Reconoce las capas del modelo OSI")
    assert without == RuleBasedPlanner(CATALOG).draft(requested, EVIDENCE, "")  # sin resultado, el plan de siempre
    # «capas del modelo» no aparece seguido en la evidencia de C-01, así que solo entra «modelo osi».
    assert anchored[0].covers[0] == "modelo osi" != without[0].covers[0]
    assert not any("osi" in concept.lower() for item in without for concept in item.covers[:1])


def test_creating_a_plan_passes_the_chosen_outcome_to_the_planner(repository):  # noqa: F811
    calls: list[str] = []

    class Recording(GenerationPlanner):
        def draft(self, *args, **kwargs):
            calls.append(args[-1])
            return super().draft(*args, **kwargs)

    use_case = creator(repository)
    use_case._planner = Recording(None, use_case._planner._catalog)
    chosen = inputs(("explicacion", 1), ("pregunta_detonante", 1), instructions="Diferencias entre TCP y UDP")
    use_case.execute(command("clave-plan-ra-1", replace(chosen, outcome_id="ra-1")))
    use_case.execute(command("clave-plan-sin-ra", chosen))
    assert calls == ["RA1.1: Distingue TCP y UDP", ""]


# Gemini: el prompt nombra el resultado y su nivel; los esquemas no cambian


def test_the_resource_prompt_names_the_chosen_outcome_and_its_verb_level():
    _, user = build_prompt_instructions(context("explicacion"))
    assert f"RESULTADO ELEGIDO: RA1.1: {RECOGNIZE}. El recurso debe tratar este resultado." in user
    assert "NIVEL DEL VERBO: recordar; el recurso pide reconocer o recordar una idea" in user
    _, unknown = build_prompt_instructions(context("explicacion", outcome={**OUTCOME, "text": "Aplica el modelo OSI"}))
    assert "RESULTADO ELEGIDO: RA1.1: Aplica el modelo OSI." in unknown and "NIVEL DEL VERBO" not in unknown
    _, without = build_prompt_instructions(context("explicacion", outcome=None))
    assert "RESULTADO ELEGIDO" not in without and "NIVEL DEL VERBO" not in without


def test_the_gemini_plan_prompt_names_the_outcome_and_keeps_the_schema():
    requested = inputs(("pregunta_detonante", 1), ("explicacion", 1))
    plain = build_plan_prompt(requested, EVIDENCE, CATALOG)
    anchored = build_plan_prompt(requested, EVIDENCE, CATALOG, outcome="RA1.1: Reconoce las capas del modelo OSI")
    assert "RESULTADO DE APRENDIZAJE ELEGIDO: RA1.1: Reconoce las capas del modelo OSI." in anchored.user
    assert "RESULTADO DE APRENDIZAJE ELEGIDO" not in plain.user
    assert anchored.schema == plain.schema and anchored.system == plain.system
    provider = Recorder(gemini_answer({"items": {}}), gemini_answer({"items": {}}))
    GenerationPlanner(gemini(provider), CATALOG).draft(requested, EVIDENCE, outcome="RA1.1: Reconoce las capas")
    assert all("RESULTADO DE APRENDIZAJE ELEGIDO: RA1.1: Reconoce las capas." in body["contents"][-1]["parts"][0]["text"]
               for body in provider.bodies)
