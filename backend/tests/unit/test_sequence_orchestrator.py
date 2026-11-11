"""
HU-003: un pedido con varios tipos de recurso se reparte entre los agentes de etapa sin repetir contenido.
Usa los puertos falsos de las pruebas de generación: sin red y sin base de datos.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from platform5e.application.services.generation.step_drafting import NO_REPEAT_INSTRUCTION
from platform5e.application.services.generation.prompt_drafting import (
    build_generation_context,
    build_prompt_instructions,
)
from platform5e.domain.generation.generation_request import StepStatus
from platform5e.domain.generation.resource_formats import RESOURCE_CATALOG
from platform5e.domain.generation.sequence import (
    MAX_SEQUENCE_TYPES,
    PlannedStep,
    SequenceError,
    content_similarity,
    order_resource_types,
    plan_steps,
    stage_agent,
)
from platform5e.infrastructure.http.schemas.generation_requests import StartGenerationRequest
from tests.support.generation_fakes import run_generation
from tests.unit.test_generation_with_material import (
    MOCK_COURSE,
    MOCK_FRAGMENTS,
    MOCK_ITEM,
    MOCK_UNIT,
    make_request_dict,
)

DISTINCT_RESOURCES: dict[str, dict[str, Any]] = {
    "pregunta_detonante": {
        "titulo": "Video en vivo sin esperas",
        "contenido": "¿Por qué una transmisión en vivo tolera perder algunos datos a cambio de rapidez?",
        "citas": [{"afirmacion": "UDP no establece conexión y es más rápido", "fragmentos": ["F2"]}],
        "alternativas": [],
    },
    "explicacion": {
        "titulo": "Entrega confiable con TCP",
        "contenido": "TCP garantiza la entrega: antes de enviar datos establece una conexión.",
        "citas": [{"afirmacion": "TCP garantiza una entrega confiable", "fragmentos": ["F1"]}],
        "alternativas": [],
    },
    "item_opcion_multiple": MOCK_ITEM,
}
REPEATED_RESOURCE = {
    "titulo": "Protocolos TCP y UDP",
    "contenido": "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable; UDP es más rápido.",
    "citas": [{"afirmacion": "TCP garantiza una entrega confiable", "fragmentos": ["F1"]}],
    "alternativas": [],
}


class StageAwareGenerator:
    """Generador falso: responde según el tipo pedido y guarda cada contexto recibido."""

    description = "IA falsa"
    uses_ai = True

    def __init__(self, responses: dict[str, Any] | None = None, retry_responses: dict[str, Any] | None = None):
        self.responses = responses or DISTINCT_RESOURCES
        self.retry_responses = retry_responses or {}
        self.contexts: list[dict[str, Any]] = []

    def generate(self, context: dict[str, Any]) -> dict[str, Any]:
        self.contexts.append(context)
        resource_type = context["solicitud"]["tipo"]
        retrying = NO_REPEAT_INSTRUCTION in context["solicitud"]["indicaciones"]
        if retrying and resource_type in self.retry_responses:
            return {"recursos": [self.retry_responses[resource_type]]}
        return {"recursos": [self.responses[resource_type]]}


def test_types_are_ordered_by_class_stage_without_duplicates():
    assert order_resource_types(["item_opcion_multiple", "pregunta_detonante", "explicacion", "pregunta_detonante"]) == [
        "pregunta_detonante",
        "explicacion",
        "item_opcion_multiple",
    ]
    assert stage_agent("mapa_conceptual") == "Agente de Explicar"
    for invalid in ([], ["tipo_inventado"], list(RESOURCE_CATALOG)[:9]):
        with pytest.raises(SequenceError):
            order_resource_types(invalid)


def test_similarity_is_high_for_the_same_text_and_low_for_different_texts():
    text = "El protocolo TCP garantiza una entrega confiable de los datos"
    assert content_similarity(text, text) == 1.0
    assert content_similarity(text, "La encapsulación agrega encabezados en cada capa") < 0.2
    assert content_similarity("", text) == 0.0


def test_the_prompt_lists_what_previous_agents_wrote():
    request = {**make_request_dict(), "stage": "explain", "resourceType": "explicacion"}
    context = build_generation_context(MOCK_COURSE, MOCK_UNIT, request, MOCK_FRAGMENTS, {"doc1": "apuntes.pdf"})
    context["secuenciaPrevia"] = [{"etapa": "engage", "titulo": "Video en vivo", "resumen": "¿Por qué tolera perder datos?"}]
    _, user_prompt = build_prompt_instructions(context)
    assert "OTROS AGENTES YA REDACTARON" in user_prompt and "- Video en vivo: ¿Por qué tolera perder datos?" in user_prompt
    assert "OTROS AGENTES" not in build_prompt_instructions({**context, "secuenciaPrevia": []})[1]


def test_the_retry_keeps_the_new_resource_when_it_no_longer_repeats(tmp_path):
    """Antes por el servicio síncrono (retirado en T046): ahora por el pedido de generación."""
    generator = StageAwareGenerator(
        {"pregunta_detonante": REPEATED_RESOURCE, "explicacion": REPEATED_RESOURCE},
        retry_responses={"explicacion": DISTINCT_RESOURCES["explicacion"]},
    )
    run = run_generation(tmp_path, "pregunta_detonante", "explicacion", primary=generator)

    assert [r["title"] for r in run.resources] == ["Protocolos TCP y UDP", "Entrega confiable con TCP"]
    explain = run.request.steps[1]
    assert (explain.stage, explain.resource_type, explain.agent) == ("explain", "explicacion", "Agente de Explicar")
    assert explain.status == StepStatus.SUCCEEDED and len(explain.resource_ids) == 1 and explain.rejections == ()


def test_the_request_contract_accepts_one_type_or_a_sequence():
    """El cuerpo de POST /generation-requests (antes el de la ruta síncrona retirada en T046)."""
    single = StartGenerationRequest.model_validate(
        {"mode": "individual", "unitId": "u1", "resourceTypes": ["explicacion"]}
    )
    assert single.to_parameters().resource_types == ("explicacion",)
    sequence = StartGenerationRequest.model_validate(
        {"mode": "sequence", "unitId": "u1", "resourceTypes": ["explicacion", "glosario"]}
    )
    assert sequence.to_parameters().resource_types == ("explicacion", "glosario")
    for invalid in (
        {"mode": "sequence", "unitId": "u1"},
        {"mode": "sequence", "unitId": "u1", "resourceTypes": []},
        {"unitId": "u1", "resourceTypes": ["explicacion"]},
        {"mode": "individual", "resourceTypes": ["explicacion"]},
    ):
        with pytest.raises(ValidationError):
            StartGenerationRequest.model_validate(invalid)


# GEN-01 (T001): plan de pasos del pedido en segundo plano.


def test_a_sequence_plan_follows_the_class_order_with_a_common_quantity():
    steps = plan_steps("sequence", ["item_opcion_multiple", "pregunta_detonante", "explicacion"], 3)
    assert steps == [
        PlannedStep(0, "engage", "pregunta_detonante", "Agente de Enganchar", 3),
        PlannedStep(1, "explain", "explicacion", "Agente de Explicar", 3),
        PlannedStep(2, "evaluate", "item_opcion_multiple", "Agente de Evaluar", 3),
    ]


def test_individual_and_regeneration_plans_have_exactly_one_step():
    assert plan_steps("individual", ["glosario"], 2) == [PlannedStep(0, "explain", "glosario", "Agente de Explicar", 2)]
    assert len(plan_steps("regeneration", ["glosario"], 1)) == 1
    # Un tipo repetido cuenta una vez.
    assert len(plan_steps("individual", ["glosario", "glosario"], 1)) == 1
    with pytest.raises(SequenceError, match="exactamente un tipo"):
        plan_steps("individual", ["glosario", "explicacion"], 1)


def test_plans_reuse_the_sequence_limits_and_reject_invalid_input():
    eight_types = list(RESOURCE_CATALOG)[:MAX_SEQUENCE_TYPES]
    assert len(plan_steps("sequence", eight_types, 5)) == MAX_SEQUENCE_TYPES
    invalid_plans = [
        ("sequence", list(RESOURCE_CATALOG)[: MAX_SEQUENCE_TYPES + 1], 1),
        ("sequence", [], 1),
        ("sequence", ["tipo_inventado"], 1),
        ("individual", ["glosario"], 0),
        ("individual", ["glosario"], 6),
        ("individual", ["glosario"], True),
        ("batch", ["glosario"], 1),
    ]
    for mode, resource_types, quantity in invalid_plans:
        with pytest.raises(SequenceError):
            plan_steps(mode, resource_types, quantity)
