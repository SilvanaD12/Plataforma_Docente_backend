"""GEN-01 (T073): esquema de respuesta de Gemini por tipo de recurso.

Con el esquema compartido, todos los campos de «estructura» eran opcionales y gemini-3.5-flash-lite devolvía la
actividad kinestésica sin pasos, sin tiempo y sin espacio («solo 0 paso(s) completos…»). Ahora la actividad exige
esos campos con sus límites; los demás tipos envían exactamente el esquema de antes. Sin red: respuestas HTTP falsas.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import httpx
import pytest

from platform5e.application.services.generation.prompt_drafting import build_generation_context
from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.application.services.generation.step_drafting import draft_resources
from platform5e.domain.generation.resource_formats import RESOURCE_CATALOG
from platform5e.infrastructure.llm.gemini_language_model import (
    GEMINI_RESPONSE_SCHEMA,
    GeminiLanguageModel,
    response_schema,
)
from tests.unit.test_explore_agent import TCP_STEP, UDP_STEP
from tests.unit.test_generation_with_material import MOCK_COURSE, MOCK_FRAGMENTS, MOCK_UNIT, make_request_dict
from tests.unit.test_kinesthetic_activity import KINESTHETIC, THIRD_STEP, _fragments_context, _model, context

# Huella del esquema compartido antes de este cambio: los demás tipos lo envían sin ningún cambio.
SHARED_SCHEMA_SHA256 = "76d86ad95bec43aa9aa5fae13f9907f5f5f87456ae81e747a98a342d128f505c"


def fingerprint(schema: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()


def type_context(resource_type: str, quantity: int = 1) -> dict[str, Any]:
    request = make_request_dict(stage=RESOURCE_CATALOG[resource_type][0], resourceType=resource_type,
                                quantity=quantity)
    return build_generation_context(MOCK_COURSE, MOCK_UNIT, request, MOCK_FRAGMENTS, {})


class FakeGemini:
    """Responde cada llamada con la siguiente respuesta de la lista y guarda el cuerpo de cada pedido."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.bodies.append(json.loads(request.content))
        return self.responses.pop(0)

    def model(self) -> GeminiLanguageModel:
        return GeminiLanguageModel("gemini", "clave-de-prueba", model="gemini-3.5-flash-lite",
                                   client=httpx.Client(transport=httpx.MockTransport(self)))


def answer(payload: dict[str, Any]) -> httpx.Response:
    text = json.dumps(payload, ensure_ascii=False)
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]})


# 1. Los demás tipos: el mismo esquema de antes


def test_the_shared_schema_is_the_one_before_this_change():
    assert fingerprint(GEMINI_RESPONSE_SCHEMA) == SHARED_SCHEMA_SHA256


@pytest.mark.parametrize("resource_type", sorted(t for t in RESOURCE_CATALOG if t != KINESTHETIC))
def test_every_other_type_sends_exactly_the_shared_schema(resource_type):
    fake = FakeGemini(answer({"recursos": []}))
    fake.model().generate(type_context(resource_type))
    sent = fake.bodies[0]["generationConfig"]["responseSchema"]
    assert sent == GEMINI_RESPONSE_SCHEMA and fingerprint(sent) == SHARED_SCHEMA_SHA256


# 2. La actividad kinestésica exige sus campos, con límites


def test_the_kinesthetic_schema_requires_its_fields_with_limits():
    schema = response_schema(KINESTHETIC, 2)
    resources = schema["properties"]["recursos"]
    assert resources["maxItems"] == "2"  # la cantidad pedida
    item = resources["items"]
    assert set(item["required"]) == {"titulo", "contenido", "citas", "alternativas", "estructura"}
    structure = item["properties"]["estructura"]
    assert structure["required"] == ["pasos_guiados", "minutos_estimados", "espacio", "materiales"]
    assert set(structure["properties"]) == {"pasos_guiados", "minutos_estimados", "espacio", "materiales"}
    steps = structure["properties"]["pasos_guiados"]
    assert (steps["minItems"], steps["maxItems"]) == ("3", "5")
    assert steps["items"]["required"] == ["titulo", "consigna", "fragmentos"]
    assert "pregunta" in steps["items"]["properties"]  # opcional
    assert steps["items"]["properties"]["fragmentos"] == {"type": "ARRAY", "items": {"type": "STRING"}, "maxItems": "3"}
    assert structure["properties"]["materiales"] == {"type": "ARRAY", "items": {"type": "STRING"}, "maxItems": "8"}
    assert structure["properties"]["minutos_estimados"] == {"type": "INTEGER"}
    assert structure["properties"]["espacio"] == {"type": "STRING"}
    # Las citas y las alternativas siguen como en el esquema compartido.
    shared_item = GEMINI_RESPONSE_SCHEMA["properties"]["recursos"]["items"]
    assert item["properties"]["citas"] == shared_item["properties"]["citas"]
    assert item["properties"]["alternativas"] == shared_item["properties"]["alternativas"]


def test_without_a_known_quantity_the_resource_list_has_no_limit():
    assert "maxItems" not in response_schema(KINESTHETIC, None)["properties"]["recursos"]


def test_building_the_kinesthetic_schema_does_not_change_the_shared_one():
    before = deepcopy(GEMINI_RESPONSE_SCHEMA)
    response_schema(KINESTHETIC, 1)
    assert GEMINI_RESPONSE_SCHEMA == before
    assert response_schema("explicacion", 1) is GEMINI_RESPONSE_SCHEMA


def test_the_kinesthetic_request_sends_its_schema():
    fake = FakeGemini(answer({"recursos": []}))
    fake.model().generate(context())
    assert fake.bodies[0]["generationConfig"]["responseSchema"] == response_schema(KINESTHETIC, 1)


def test_a_400_for_the_schema_still_retries_without_it():
    rejected = httpx.Response(400, json={"error": {"message": "Invalid JSON payload: unknown field maxItems"}})
    fake = FakeGemini(rejected, answer({"recursos": []}))
    assert fake.model().generate(context()) == {"recursos": []}
    assert "responseSchema" in fake.bodies[0]["generationConfig"]
    assert "responseSchema" not in fake.bodies[1]["generationConfig"]


# 4. Respuestas falsas de Gemini a través de la redacción del paso


def test_an_empty_structure_is_still_a_structure_rejection():
    empty = {"recursos": [{"titulo": "Representación corporal de protocolos de transporte",
                           "contenido": "Hagan los pasos en grupos.",
                           "citas": [{"afirmacion": "TCP garantiza una entrega confiable", "fragmentos": ["F1"]}],
                           "alternativas": [], "estructura": {}}]}
    fake = FakeGemini(answer(empty))
    rejections: list[dict[str, Any]] = []
    resources, generator, _ = draft_resources(_fragments_context(), fake.model(), None, rejections)
    assert resources == []
    assert rejections == [{
        "title": "Representación corporal de protocolos de transporte", "kind": "structure",
        "reason": "«Representación corporal de protocolos de transporte»: no trae los pasos dentro de «pasos_guiados»: "
                  "la actividad es un solo recurso con todos sus pasos, no un recurso por paso; falta el tiempo "
                  "estimado (entero de 5 a 90 minutos); falta el espacio donde se hace la actividad.",
    }]


def test_a_valid_kinesthetic_answer_is_drafted_by_gemini():
    steps = [_model(TCP_STEP, "F1"), _model(UDP_STEP, "F2"), _model(THIRD_STEP, "F1")]
    valid = {"recursos": [{
        "titulo": "Protocolos en movimiento", "contenido": "Hagan los pasos en grupos y comenten lo que observaron.",
        "citas": [{"afirmacion": "TCP garantiza una entrega confiable", "fragmentos": ["F1"]}], "alternativas": [],
        "estructura": {"pasos_guiados": steps, "materiales": ["Tarjetas"], "minutos_estimados": 25,
                       "espacio": "Patio"},
    }]}
    gemini = FakeGemini(answer(valid)).model()
    rejections: list[dict[str, Any]] = []
    [resource], generator, warning = draft_resources(_fragments_context(), gemini, RuleBasedGenerator(), rejections)
    assert generator is gemini and warning is None and rejections == []
    activity = resource["estructura"]
    assert len(activity["guidedSteps"]) == 3 and activity["estimatedMinutes"] == 25 and activity["space"] == "Patio"
