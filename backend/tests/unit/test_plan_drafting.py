"""GEN-P1 (T006, T007): planificador por reglas y con Gemini (specs/006-plan-de-generacion/research.md R4).

El planificador por reglas usa el material real de T068 (corpus_t067) con la búsqueda por palabras del servidor. El de
Gemini es el adaptador real con un transporte HTTP falso: sin red ni clave real.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx
import pytest

from platform5e.application.ports.outbound.evidence_provider_port import EvidenceQuery
from platform5e.application.services.generation.plan_drafting import (
    RULES_PLANNER_DESCRIPTION,
    GenerationPlanner,
    RuleBasedPlanner,
    build_plan_prompt,
    plan_response_schema,
)
from platform5e.domain.generation.generation_plan import (
    PlanEvidence,
    PlanFragment,
    PlanInputs,
    RequestedType,
)
from platform5e.domain.generation.plan_validation import split_covers, validate_items
from platform5e.domain.generation.topic_coverage import concept_key
from platform5e.infrastructure.adapters.resource_catalog_adapter import StaticResourceCatalogAdapter
from platform5e.infrastructure.llm.gemini_language_model import GeminiLanguageModel
from tests.unit.test_llm_call_deadline import SlowProvider
from tests.unit.test_topic_coverage import CASES, CorpusEvidence

CATALOG = {entry.id: entry for entry in StaticResourceCatalogAdapter().entries()}
KNOWN = {entry_id: entry.stage for entry_id, entry in CATALOG.items()}
C01 = CASES["C-01"]


def evidence_for(case: dict, top_k: int = 12) -> PlanEvidence:
    source = CorpusEvidence(case["documents"])
    retrieval = source.retrieve(EvidenceQuery("docente-a", "u1", f"Redes {case['instructions']}", top_k))
    return PlanEvidence(retrieval.retrieval_mode, "2026-11-22T10:00:00+00:00", tuple(
        PlanFragment(f.chunk_id, f.document_id, f.document_name, f.location, f.text, f.relevance, None, None)
        for f in retrieval.fragments
    ))


def inputs(*requested: tuple[str, int | None], instructions: str = C01["instructions"],
           modality: str | None = None) -> PlanInputs:
    return PlanInputs(instructions=instructions, audience="", competency="", outcome_id=None, modality=modality,
                      resource_types=tuple(RequestedType(t, q) for t, q in requested))


EVIDENCE = evidence_for(C01)


# Planificador por reglas (T006)


def test_one_item_cites_evidence_and_owns_concepts_from_the_material():
    [item] = RuleBasedPlanner(CATALOG).draft(inputs(("explicacion", 1)), EVIDENCE)
    assert (item.position, item.stage, item.resource_type, item.quantity) == (1, "explain", "explicacion", 1)
    assert item.covers and item.fragment_ids and set(item.fragment_ids) <= EVIDENCE.fragment_ids
    assert "modelo osi" in {concept_key(c) for c in item.covers}  # el tema pedido está en el material
    assert item.purpose.startswith(CATALOG["explicacion"].name) and "5E" not in item.purpose
    assert "modelo" not in {concept_key(c) for c in item.covers}  # ya está dentro de «modelo osi»


def test_several_items_follow_the_stage_order_and_never_share_a_concept():
    items = RuleBasedPlanner(CATALOG).draft(
        inputs(("item_opcion_multiple", 1), ("pregunta_detonante", 1), ("explicacion", 1), ("glosario", 1)),
        EVIDENCE,
    )
    assert [i.resource_type for i in items] == ["pregunta_detonante", "explicacion", "glosario", "item_opcion_multiple"]
    assert [i.position for i in items] == [1, 2, 3, 4]
    keys = [concept_key(c) for i in items for c in i.covers]
    assert len(keys) == len(set(keys))
    assert validate_items(items, EVIDENCE.fragment_ids, None, KNOWN) == []


def test_a_quantity_splits_the_concepts_into_one_block_per_resource():
    [item] = RuleBasedPlanner(CATALOG).draft(inputs(("explicacion", 3)), EVIDENCE)
    assert item.quantity == 3 and len(item.covers) >= 3
    blocks = split_covers(item.covers, item.quantity)
    assert len(blocks) == 3 and all(blocks)


def test_without_a_quantity_the_planner_chooses_one_from_the_concepts():
    [item] = RuleBasedPlanner(CATALOG).draft(inputs(("glosario", None)), EVIDENCE)
    assert 1 <= item.quantity <= 3 and len(item.covers) >= item.quantity


def test_the_rule_based_plan_is_deterministic():
    requested = inputs(("pregunta_detonante", 1), ("explicacion", 2))
    assert RuleBasedPlanner(CATALOG).draft(requested, EVIDENCE) == RuleBasedPlanner(CATALOG).draft(requested, EVIDENCE)


def test_with_too_few_concepts_it_lowers_the_quantity_or_reports_the_problem():
    tiny = PlanEvidence("bm25_fallback", "t", (EVIDENCE.fragments[0],))
    items = RuleBasedPlanner(CATALOG).draft(inputs(("explicacion", 5)), tiny)
    [item] = items
    assert item.quantity <= len(item.covers) or "NOT_ENOUGH_CONCEPTS" in [
        p.code for p in validate_items(items, tiny.fragment_ids, None, KNOWN)
    ]


# Gemini (T007)


def gemini_answer(payload: dict[str, Any]) -> dict[str, Any]:
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(payload, ensure_ascii=False)}]},
                            "finishReason": "STOP"}]}


class Recorder(SlowProvider):
    """El transporte falso de QA-06, que además guarda el cuerpo de cada pedido."""

    def __init__(self, *answers) -> None:
        super().__init__(*answers)
        self.bodies: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        return super().__call__(request)


def gemini(provider: Recorder, deadline: float = 60.0) -> GeminiLanguageModel:
    return GeminiLanguageModel("gemini", "clave-de-prueba", model="gemini-3.5-flash-lite", client=provider.client(),
                               call_deadline_seconds=deadline)


REQUESTED = inputs(("pregunta_detonante", 1), ("explicacion", 1))
VALID_AI_PLAN = {"items": [
    {"resourceType": "explicacion", "quantity": 1, "purpose": "Explicar las capas del modelo OSI.",
     "covers": ["capas del modelo OSI", "funciones de cada capa"], "fragmentos": ["F1", "F2"]},
    {"resourceType": "pregunta_detonante", "quantity": 1, "purpose": "Abrir la clase con una pregunta.",
     "covers": ["para qué sirve un modelo de referencia"], "fragmentos": ["F1"]},
]}


def test_the_plan_schema_requires_items_with_covers_and_fragments():
    schema = plan_response_schema(REQUESTED)
    items = schema["properties"]["items"]
    assert schema["required"] == ["items"] and (items["minItems"], items["maxItems"]) == ("1", "2")
    item = items["items"]
    assert item["required"] == ["resourceType", "quantity", "purpose", "covers", "fragmentos"]
    assert item["properties"]["resourceType"]["enum"] == ["pregunta_detonante", "explicacion"]
    assert item["properties"]["covers"]["minItems"] == "1" and item["properties"]["fragmentos"]["minItems"] == "1"


def test_a_valid_ai_plan_is_used_with_its_tags_resolved_and_the_stage_order():
    provider = Recorder(gemini_answer(VALID_AI_PLAN))
    items, generator = GenerationPlanner(gemini(provider), CATALOG).draft(REQUESTED, EVIDENCE)
    assert generator == {"description": "Gemini · gemini-3.5-flash-lite", "usesAi": True, "fallback": False,
                         "fallbackReason": None}
    assert [i.resource_type for i in items] == ["pregunta_detonante", "explicacion"]
    assert items[1].fragment_ids == (EVIDENCE.fragments[0].id, EVIDENCE.fragments[1].id)
    [body] = provider.bodies
    assert body["generationConfig"]["responseSchema"] == plan_response_schema(REQUESTED)
    prompt = body["contents"][0]["parts"][0]["text"]
    assert "[F1]" in prompt and C01["instructions"] in prompt


@pytest.mark.parametrize(
    ("answers", "reason"),
    [
        # Un concepto en dos ítems: plan inválido.
        ((gemini_answer({"items": [
            {**VALID_AI_PLAN["items"][0], "covers": ["capas del modelo OSI"]},
            {**VALID_AI_PLAN["items"][1], "covers": ["Capas del modelo  OSI"]},
        ]}),), "Gemini · gemini-3.5-flash-lite devolvió un plan no válido (CONCEPT_OWNED_TWICE). Se armó el plan con reglas."),
        # Falta un tipo pedido.
        ((gemini_answer({"items": VALID_AI_PLAN["items"][:1]}),),
         "Gemini · gemini-3.5-flash-lite devolvió un plan no válido (faltan tipos pedidos). Se armó el plan con reglas."),
        # No es JSON, dos veces.
        (({"candidates": [{"content": {"parts": [{"text": "no es json"}]}}]},
          {"candidates": [{"content": {"parts": [{"text": "tampoco"}]}}]}),
         "Gemini · gemini-3.5-flash-lite no respondió (La respuesta del modelo no es JSON válido (7 caracteres).). "
         "Se armó el plan con reglas."),
    ],
    ids=["concepto-repetido", "falta-un-tipo", "json-invalido"],
)
def test_an_invalid_ai_plan_falls_back_to_the_rules_with_its_reason(answers, reason):
    items, generator = GenerationPlanner(gemini(Recorder(*answers)), CATALOG).draft(REQUESTED, EVIDENCE)
    assert generator == {"description": RULES_PLANNER_DESCRIPTION, "usesAi": False, "fallback": True,
                         "fallbackReason": reason}
    assert items == RuleBasedPlanner(CATALOG).draft(REQUESTED, EVIDENCE)


def test_a_timeout_falls_back_within_the_deadline():
    provider = Recorder(None)  # respuesta que gotea durante 10 s
    started = time.monotonic()
    items, generator = GenerationPlanner(gemini(provider, deadline=0.5), CATALOG).draft(REQUESTED, EVIDENCE)
    assert time.monotonic() - started < 0.5 + 2.0
    assert generator["fallback"] is True
    assert generator["fallbackReason"] == ("Gemini · gemini-3.5-flash-lite no respondió (Gemini no respondió en 0,5 s). "
                                           "Se armó el plan con reglas.")
    assert items
    for stream in provider.streams:
        stream.released.set()


def test_without_ai_the_rules_plan_has_no_fallback():
    items, generator = GenerationPlanner(None, CATALOG).draft(REQUESTED, EVIDENCE)
    assert generator == {"description": RULES_PLANNER_DESCRIPTION, "usesAi": False, "fallback": False,
                         "fallbackReason": None}
    assert len(items) == 2


def test_the_prompt_never_asks_to_mention_the_methodology():
    prompt = build_plan_prompt(REQUESTED, EVIDENCE, CATALOG)
    assert "No menciones el modelo 5E" in prompt.system  # la única mención: la prohibición
    assert "5E" not in prompt.system.replace("No menciones el modelo 5E", "") and "5E" not in prompt.user
