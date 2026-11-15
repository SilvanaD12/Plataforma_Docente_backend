"""GEN-01: la actividad kinestésica caía siempre al generador por reglas con Gemini, sin decir por qué.

Los recursos que el modelo devolvía incompletos (sin tiempo estimado, sin espacio, sin pasos o con un recurso por
paso) se descartaban sin rechazo. Ahora cada descarte queda como rechazo `structure` con su motivo, el motivo del
respaldo queda en `steps[].generator.fallbackReason` y el prompt de la actividad pide un solo recurso con sus pasos
dentro de «pasos_guiados». Sin proveedores reales: Gemini es el adaptador real con un transporte HTTP falso.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import httpx
import pytest

from platform5e.application.services.generation.prompt_drafting import (
    build_prompt_instructions,
    normalize_generated_resources,
)
from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.application.use_cases.generation.run_generation_request import RunGenerationRequest
from platform5e.application.use_cases.generation.start_generation_request import StartGenerationCommand
from platform5e.domain.generation.generation_request import GenerationMode, GenerationParameters, RequestStatus
from platform5e.infrastructure.adapters.review_verification_adapter import ReviewVerificationAdapter
from platform5e.infrastructure.llm.gemini_language_model import GeminiLanguageModel
from tests.unit.test_generation_with_material import MOCK_COURSE, MOCK_FRAGMENTS, MOCK_UNIT, make_request_dict
from tests.unit.test_kinesthetic_activity import (
    KINESTHETIC,
    THIRD_STEP,
    _corpus_fragments,
    _drafted,
    _fragments_context,
    _model,
    context,
    model_step,
)
from tests.unit.test_explore_agent import TCP_STEP, UDP_STEP
from tests.unit.test_start_regeneration import Setup
from platform5e.application.services.generation.prompt_drafting import build_generation_context

TITLE = "Protocolos en movimiento"
STEPS = [(TCP_STEP, "F1"), (UDP_STEP, "F2"), (THIRD_STEP, "F1")]


def activity(**structure_changes: Any) -> dict[str, Any]:
    drafted = _drafted(*[_model(step, tag) for step, tag in STEPS])
    drafted["estructura"].update(structure_changes)
    return drafted


def per_step_resources() -> list[dict[str, Any]]:
    """Lo que devolvió Gemini: cada paso como un recurso aparte, sin «pasos_guiados»."""
    return [
        {
            "titulo": f"Paso {number}: {step['title']}",
            "contenido": step["instruction"],
            "citas": [{"afirmacion": step["instruction"], "fragmentos": [tag]}],
            "alternativas": [],
        }
        for number, (step, tag) in enumerate(STEPS, 1)
    ]


def rejected(items: list[Any] | Any, context_data: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    rejections: list[dict[str, Any]] = []
    payload = {"recursos": items} if isinstance(items, list) else items
    assert normalize_generated_resources(payload, context_data or _fragments_context(), rejections) == []
    return rejections


# 1-2. Cada descarte queda como rechazo con su motivo


def test_a_complete_activity_is_still_kept_without_rejections():
    rejections: list[dict[str, Any]] = []
    [resource] = normalize_generated_resources({"recursos": [activity()]}, _fragments_context(), rejections)
    assert resource["estructura"]["estimatedMinutes"] == 20 and rejections == []


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"minutos_estimados": None}, f"«{TITLE}»: falta el tiempo estimado (entero de 5 a 90 minutos)."),
        ({"minutos_estimados": 120}, f"«{TITLE}»: falta el tiempo estimado (entero de 5 a 90 minutos); llegó «120»."),
        ({"minutos_estimados": "20 min"},
         f"«{TITLE}»: falta el tiempo estimado (entero de 5 a 90 minutos); llegó «20 min»."),
        ({"espacio": "  "}, f"«{TITLE}»: falta el espacio donde se hace la actividad."),
        ({"minutos_estimados": 0, "espacio": ""},
         f"«{TITLE}»: falta el tiempo estimado (entero de 5 a 90 minutos); llegó «0»; falta el espacio donde se hace "
         "la actividad."),
    ],
)
def test_missing_time_or_space_is_a_structure_rejection_with_its_reason(changes, reason):
    [rejection] = rejected([activity(**changes)])
    assert rejection == {"title": TITLE, "reason": reason, "kind": "structure"}


def test_fewer_than_three_complete_steps_is_rejected_with_the_count():
    incomplete = model_step("Sin consigna", "", "", ["F1"])
    [rejection] = rejected([activity(pasos_guiados=[_model(TCP_STEP, "F1"), _model(UDP_STEP, "F2"), incomplete])])
    assert rejection["kind"] == "structure"
    assert rejection["reason"] == (
        f"«{TITLE}»: solo 2 paso(s) completos (título y consigna); la actividad necesita al menos 3."
    )


def test_a_resource_without_guided_steps_says_that_steps_go_inside_one_resource():
    without = activity()
    del without["estructura"]["pasos_guiados"]
    [rejection] = rejected([without])
    assert rejection["reason"] == (
        f"«{TITLE}»: no trae los pasos dentro de «pasos_guiados»: la actividad es un solo recurso con todos sus "
        "pasos, no un recurso por paso."
    )


def test_one_resource_per_step_is_rejected_with_a_clear_reason_for_each():
    rejections = rejected(per_step_resources())
    assert [r["title"] for r in rejections] == [f"Paso {n}: {step['title']}" for n, (step, _) in enumerate(STEPS, 1)]
    for rejection in rejections:
        assert rejection["kind"] == "structure"
        assert "no un recurso por paso" in rejection["reason"]
        assert "falta el tiempo estimado" in rejection["reason"] and "falta el espacio" in rejection["reason"]


def test_an_incomplete_structure_of_another_type_names_the_type_and_its_minimum():
    request = make_request_dict(stage="explain", resourceType="diagrama_proceso")
    diagram_context = build_generation_context(MOCK_COURSE, MOCK_UNIT, request, MOCK_FRAGMENTS, {})
    item = {"titulo": "Diagrama", "contenido": "El protocolo TCP garantiza una entrega confiable.",
            "citas": [{"afirmacion": "TCP garantiza una entrega confiable", "fragmentos": ["F1"]}],
            "alternativas": [], "estructura": {"pasos": [{"titulo": "Uno", "texto": "Solo un paso"}]}}
    [rejection] = rejected([item], diagram_context)
    assert rejection == {
        "title": "Diagrama", "kind": "structure",
        "reason": "«Diagrama»: la estructura de «Diagrama de proceso» está incompleta o no es válida "
                  "(necesita al menos 3 elementos completos).",
    }


def test_an_empty_content_or_an_item_that_is_not_an_object_is_rejected():
    rejections = rejected([{**activity(), "contenido": "  "}, "texto suelto"])
    assert rejections == [
        {"title": TITLE, "reason": f"«{TITLE}»: llegó sin contenido.", "kind": "structure"},
        {"title": "Actividad kinestésica 2",
         "reason": "El elemento 2 de la respuesta no es un recurso (se esperaba un objeto JSON).", "kind": "structure"},
    ]


def test_a_response_without_the_resource_list_is_rejected():
    assert rejected({"otra_cosa": []}) == [{
        "title": "Actividad kinestésica",
        "reason": "La respuesta del modelo no trae la lista «recursos».",
        "kind": "structure",
    }]


def test_invalid_multiple_choice_options_are_rejected_with_their_reason():
    request = make_request_dict(stage="evaluate", resourceType="item_opcion_multiple", optionCount=4)
    item_context = build_generation_context(MOCK_COURSE, MOCK_UNIT, request, MOCK_FRAGMENTS, {})
    item = {"titulo": "Ítem", "contenido": "¿Qué protocolo garantiza una entrega confiable?",
            "citas": [{"afirmacion": "TCP garantiza una entrega confiable", "fragmentos": ["F1"]}],
            "alternativas": [{"texto": "TCP", "correcta": True, "retroalimentacion": "Sí.", "fragmentos": ["F1"]}]}
    [rejection] = rejected([item], item_context)
    assert rejection == {
        "title": "Ítem", "kind": "structure",
        "reason": "«Ítem»: las alternativas no son válidas: hace falta 1 correcta y 3 distractores, cada uno con su "
                  "retroalimentación y su error conceptual.",
    }


# 4. Prompt de la actividad kinestésica


def test_the_kinesthetic_prompt_asks_for_one_resource_with_its_steps_time_and_space():
    _, user_prompt = build_prompt_instructions(context())
    assert "Es UN solo recurso: todos sus pasos van dentro de «pasos_guiados»; nunca un recurso por paso." in user_prompt
    assert "«minutos_estimados» (entero de 5 a 90) y «espacio» son obligatorios." in user_prompt
    assert "La consigna de cada paso se basa en una oración del fragmento que cita" in user_prompt


def test_other_types_keep_their_prompt():
    request = make_request_dict(stage="explore", resourceType="exploracion_guiada")
    _, user_prompt = build_prompt_instructions(
        build_generation_context(MOCK_COURSE, MOCK_UNIT, request, MOCK_FRAGMENTS, {})
    )
    assert "UN solo recurso" not in user_prompt and "minutos_estimados" not in user_prompt
    assert "Cada paso cita en «fragmentos» la etiqueta del fragmento en que se apoya" in user_prompt


# 3 y 5. Gemini con un recurso por paso: rechazos con motivo, respaldo por reglas y su motivo guardado


def fake_gemini(payload: dict[str, Any]) -> GeminiLanguageModel:
    """El adaptador real de Gemini con una respuesta HTTP falsa (sin red ni clave real)."""
    answer = {"candidates": [{"content": {"parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}}]}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=answer))
    return GeminiLanguageModel("gemini", "clave-de-prueba", model="gemini-3.5-flash-lite",
                               client=httpx.Client(transport=transport))


@pytest.fixture
def setup(tmp_path) -> Setup:
    setup = Setup(tmp_path)
    setup.evidence.fragments = _corpus_fragments()
    return setup


def run(setup: Setup, primary, fallback, key: str):
    request = setup.use_case._start_generation.execute(
        StartGenerationCommand("docente-a", "u1", GenerationMode.INDIVIDUAL, key,
                               GenerationParameters(resource_types=(KINESTHETIC,), modality="Kinestésico"))
    ).request
    RunGenerationRequest(setup.repository, setup.membership, setup.evidence, setup.review,
                         ReviewVerificationAdapter(), primary, fallback, heartbeat_seconds=0).execute(request.id)
    return setup.repository.get("docente-a", request.id)  # leído de la base


def test_gemini_with_one_resource_per_step_falls_back_and_keeps_why(setup):
    gemini = fake_gemini({"recursos": per_step_resources()})
    finished = run(setup, gemini, RuleBasedGenerator(), "clave-kinestesica-respaldo")

    [step] = finished.steps
    assert finished.status == RequestStatus.SUCCEEDED and step.resource_ids  # el generador por reglas la redactó
    assert step.generator == {
        "description": RuleBasedGenerator().description, "usesAi": False, "fallback": True,
        "fallbackReason": "Gemini · gemini-3.5-flash-lite no devolvió recursos con citas válidas del material. "
                          "Se usó el generador por reglas.",
    }
    structure_rejections = [r for r in step.rejections if r["kind"] == "structure"]
    assert [r["title"] for r in structure_rejections][:1] == ["Paso 1: " + TCP_STEP["title"]]
    assert all("no un recurso por paso" in r["reason"] for r in structure_rejections)


def test_a_failing_provider_keeps_its_error_as_the_reason(setup):
    transport = httpx.MockTransport(lambda request: httpx.Response(429, json={"error": {"message": "cuota"}}))
    gemini = GeminiLanguageModel("gemini", "clave-de-prueba", model="gemini-3.5-flash-lite",
                                 client=httpx.Client(transport=transport))
    [step] = run(setup, gemini, RuleBasedGenerator(), "clave-kinestesica-429").steps
    assert step.generator["fallback"] is True
    assert step.generator["fallbackReason"].startswith("Gemini · gemini-3.5-flash-lite no respondió (")
    assert step.generator["fallbackReason"].endswith(" Se usó el generador por reglas.")


def test_without_fallback_the_reason_is_null(setup):
    gemini = fake_gemini({"recursos": [activity()]})
    setup.evidence.fragments = _fragments_from_test_context()
    [step] = run(setup, gemini, RuleBasedGenerator(), "clave-kinestesica-ia").steps
    assert step.resource_ids and step.generator["usesAi"] is True
    assert step.generator["fallback"] is False and step.generator["fallbackReason"] is None

    [step] = run(setup, RuleBasedGenerator(), None, "clave-kinestesica-reglas").steps
    assert step.generator["fallback"] is False and step.generator["fallbackReason"] is None


def _fragments_from_test_context():
    """Los fragmentos f1 y f2 de las pruebas de la actividad, para que los pasos de Gemini se apoyen en ellos."""
    from platform5e.application.ports.outbound.evidence_provider_port import EvidenceFragment

    return tuple(
        EvidenceFragment(chunk_id=f["id"], document_id="d1", document_name="redes.pdf", location="p. 1",
                         text=f["texto"], relevance=0.9, source_url=None, license=None)
        for f in deepcopy(_fragments_context()["fragmentos"])
    )
