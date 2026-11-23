"""GEN-P2 (corrección tras P4): los conceptos del plan son frases nominales cortas, de 2 a 4 palabras útiles tomadas
del material, nunca oraciones ni listas (specs/006-plan-de-generacion, research R4 y data-model, `CONCEPT_NOT_SHORT`).

Los casos largos son los que escribió el planificador con Gemini en la medición de P4 (backend/p4.db). La evidencia es
la del corpus de T067. Gemini es falso: transporte HTTP falso, sin red.
"""

from __future__ import annotations

import pytest

from platform5e.application.services.generation.plan_drafting import (
    GenerationPlanner,
    RuleBasedPlanner,
    build_plan_prompt,
    items_from_model,
    plan_response_schema,
)
from platform5e.domain.generation.generation_plan import PlanItem
from platform5e.domain.generation.plan_coverage import contains_term
from platform5e.domain.generation.plan_validation import short_concept_problem, validate_items
from tests.unit.test_plan_drafting import (
    CATALOG,
    EVIDENCE,
    KNOWN,
    REQUESTED,
    Recorder,
    gemini,
    gemini_answer,
    inputs,
)

# Conceptos que escribió Gemini en p4.db y que el plan ya no acepta.
P4_LONG_CONCEPTS = [
    "no hay confirmacion de entrega o recepcion",
    "no mantiene estado de conexion alguno",
    "puerto de origen, puerto de destino, longitud y suma de verificación",
    "transmision sin conexion de datagramas y alternativa al protocolo TCP",
    "eleccion entre ambos es una decision de diseño que equilibra fiabilidad y latencia",
    "TCP y UDP no compiten resuelven necesidades distintas",
    "socket",
    "latencia",
]
P4_SHORT_CONCEPTS = [
    "saludo de tres vias", "control de flujo", "cabecera de 8 bytes", "numeros de puerto", "estrictos requisitos de "
    "retardo", "entrega best-effort", "control de congestion", "UDP", "TCP", "IPv4",
]


@pytest.mark.parametrize("concept", P4_SHORT_CONCEPTS)
def test_short_noun_phrases_and_acronyms_are_concepts(concept):
    assert short_concept_problem(concept) is None


@pytest.mark.parametrize("concept", P4_LONG_CONCEPTS)
def test_sentences_lists_and_single_common_words_are_not_concepts(concept):
    assert short_concept_problem(concept) == (
        f"«{concept}» no es un concepto corto: usa una frase de 2 a 4 palabras del material, no una oración ni una "
        "lista.")


def test_validation_reports_each_long_concept_of_its_item():
    item = PlanItem(1, "explore", "guia_exploracion", 1, "Analizar la cabecera UDP",
                    ("numeros de puerto", P4_LONG_CONCEPTS[2]), (EVIDENCE.fragments[0].id,))
    problems = validate_items((item,), EVIDENCE.fragment_ids, None, KNOWN)
    assert [(p.code, p.item_position) for p in problems] == [("CONCEPT_NOT_SHORT", 1)]
    assert "5E" not in problems[0].message


def test_the_rule_based_planner_only_proposes_short_concepts_from_the_material():
    items = RuleBasedPlanner(CATALOG).draft(
        inputs(("pregunta_detonante", 1), ("explicacion", 2), ("item_opcion_multiple", 1)), EVIDENCE)
    concepts = [concept for item in items for concept in item.covers]
    assert concepts and all(short_concept_problem(concept) is None for concept in concepts), concepts
    # Tomados del material: sus palabras, seguidas y en orden, sin contar signos («normalización (ISO)»).
    evidence = " ".join(f.text for f in EVIDENCE.fragments)
    assert all(contains_term(evidence, concept) for concept in concepts), concepts
    assert not validate_items(items, EVIDENCE.fragment_ids, None, KNOWN)


def test_the_gemini_prompt_and_schema_ask_for_short_concepts():
    prompt = build_plan_prompt(REQUESTED, EVIDENCE, CATALOG)
    assert "de 2 a 4 palabras" in prompt.user and "nunca una oración" in prompt.user
    covers = plan_response_schema(REQUESTED)["properties"]["items"]["items"]["properties"]["covers"]
    assert "2 a 4 palabras" in covers["items"]["description"]


def test_long_concepts_from_the_ai_are_dropped_and_too_few_left_fall_back_to_rules():
    raw = {"items": [
        {"resourceType": "explicacion", "quantity": 1, "purpose": "Explicar el modelo OSI.",
         "covers": ["capas del modelo OSI", P4_LONG_CONCEPTS[4]], "fragmentos": ["F1"]},
        {"resourceType": "pregunta_detonante", "quantity": 1, "purpose": "Abrir la clase.",
         "covers": [P4_LONG_CONCEPTS[0], "modelo de referencia"], "fragmentos": ["F1"]},
    ]}
    items = items_from_model(raw, REQUESTED, EVIDENCE, CATALOG)
    assert [i.covers for i in items] == [("modelo de referencia",), ("capas del modelo OSI",)]

    only_long = {"items": [{**raw["items"][0], "covers": [P4_LONG_CONCEPTS[4]]}, raw["items"][1]]}
    provider = Recorder(gemini_answer(only_long), gemini_answer(only_long))  # el plan y su reintento
    planned, generator = GenerationPlanner(gemini(provider), CATALOG).draft(REQUESTED, EVIDENCE)
    assert generator["fallback"] is True and "NOT_ENOUGH_CONCEPTS" in generator["fallbackReason"]
    assert all(short_concept_problem(c) is None for item in planned for c in item.covers)


def test_candidate_concepts_are_the_rule_based_extraction_of_the_evidence():
    from platform5e.application.services.generation.plan_drafting import candidate_concepts

    texts = [f.text for f in EVIDENCE.fragments]
    concepts = candidate_concepts("¿Qué es el modelo OSI y cuántas capas lo conforman?", texts, limit=10)
    assert 0 < len(concepts) <= 10 and "modelo osi" in {c.lower() for c in concepts}
    assert all(short_concept_problem(c) is None for c in concepts)
    assert candidate_concepts("¿Qué es el modelo OSI y cuántas capas lo conforman?", texts, limit=10) == concepts
