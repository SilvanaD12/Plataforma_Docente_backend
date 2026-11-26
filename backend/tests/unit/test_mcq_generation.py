"""T027 (a), spec 006: el ítem de opción múltiple caía al respaldo por reglas con Gemini, con plan y sin plan
(backend/p4.db: rechazos «structure», «hace falta 1 correcta y 3 distractores, cada uno con su retroalimentación y su
error conceptual»).

Causa: el esquema de respuesta compartido (`GEMINI_RESPONSE_SCHEMA`) no declara `error_conceptual` en las
alternativas. Con el esquema impuesto, Gemini solo devuelve los campos declarados, así que ningún distractor traía su
error conceptual y `_validate_alternatives` los descartaba todos. Ahora el ítem tiene su propio esquema, como la
actividad kinestésica (T073). Todo con dobles: sin red ni proveedores reales.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from platform5e.application.services.generation.prompt_drafting import build_prompt_instructions
from platform5e.application.services.generation.step_drafting import fallback_warning
from platform5e.domain.generation.generation_plan import PlanItem
from platform5e.domain.generation.generation_request import StepStatus
from platform5e.infrastructure.llm.gemini_language_model import GEMINI_RESPONSE_SCHEMA, response_schema
from tests.unit.test_gemini_schema_per_type import FakeGemini, answer, type_context
from tests.unit.test_planned_generation import (  # noqa: F401  (fixtures de pytest)
    TEXTS,
    Capturing,
    engine,
    plans,
    requests,
    run_plan,
    tag,
)

FIXTURE = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "gemini_mcq_without_misconception.json")
                     .read_text(encoding="utf-8"))
MCQ = "item_opcion_multiple"
MCQ_ITEM = PlanItem(1, "evaluate", MCQ, 1, "Comprobar qué regula el envío en TCP", ("control de flujo",), ("f1", "f6"))
MISCONCEPTIONS = {
    "La compresión de cabeceras": "Confunde regular el envío con reducir el tamaño de los datos.",
    "El cifrado de extremo a extremo": "Confunde la seguridad con el control del ritmo de envío.",
    "La fragmentación en la red": "Atribuye a la capa de red una función del transporte.",
}


def valid_mcq(context: dict) -> dict:
    """La respuesta del fixture, con el error conceptual de cada distractor y sus etiquetas del contexto."""
    data = deepcopy(FIXTURE["response"])
    item = data["recursos"][0]
    item["titulo"] = "Evaluación del control de flujo"
    f1 = tag(context, "f1")
    item["citas"][0]["fragmentos"] = [f1]
    for option in item["alternativas"]:
        option["fragmentos"] = [f1]
        if not option["correcta"]:
            option["error_conceptual"] = MISCONCEPTIONS[option["texto"]]
    return data


def without_misconception(context: dict) -> dict:
    data = valid_mcq(context)
    for option in data["recursos"][0]["alternativas"]:
        option.pop("error_conceptual", None)
    data["recursos"][0]["titulo"] = FIXTURE["response"]["recursos"][0]["titulo"]
    return data


# El esquema


def test_the_mcq_schema_requires_one_correct_and_three_distractors_with_feedback_and_misconception():
    schema = response_schema(MCQ, 1, 4)
    resources = schema["properties"]["recursos"]
    assert resources["maxItems"] == "1"
    options = resources["items"]["properties"]["alternativas"]
    assert (options["minItems"], options["maxItems"]) == ("4", "4")
    option = options["items"]
    assert option["properties"]["error_conceptual"] == {"type": "STRING"}
    assert option["required"] == ["texto", "correcta", "retroalimentacion", "error_conceptual", "fragmentos"]
    assert "alternativas" in resources["items"]["required"]
    assert "error_conceptual" not in json.dumps(GEMINI_RESPONSE_SCHEMA)  # el compartido no cambia


def test_gemini_sends_the_mcq_schema_with_the_requested_option_count():
    fake = FakeGemini(answer({"recursos": []}))
    context = type_context(MCQ)
    context["solicitud"]["alternativas"] = 3
    fake.model().generate(context)
    sent = fake.bodies[0]["generationConfig"]["responseSchema"]["properties"]["recursos"]["items"]
    assert sent["properties"]["alternativas"]["minItems"] == "3"
    assert "error_conceptual" in sent["properties"]["alternativas"]["items"]["required"]


# Con plan


def test_a_planned_mcq_with_a_valid_response_is_delivered_without_fallback(requests, plans):
    done, [resource], _ = run_plan(requests, plans, Capturing(valid_mcq), MCQ_ITEM)
    [step] = done.steps
    assert step.status == StepStatus.SUCCEEDED and step.rejections == () and step.generator["fallback"] is False
    assert len(resource["options"]) == 4 and sum(o["isCorrect"] for o in resource["options"]) == 1
    assert all(o["misconception"] for o in resource["options"] if not o["isCorrect"])
    assert resource["title"] == "Evaluación del control de flujo"


def test_a_planned_mcq_without_misconceptions_is_rejected_as_structure_with_its_reason(requests, plans):
    from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator

    done, _, _ = run_plan(requests, plans, Capturing(without_misconception), MCQ_ITEM, fallback=RuleBasedGenerator())
    [step] = done.steps
    structure = [r for r in step.rejections if r["kind"] == "structure"]
    assert structure and structure[0]["reason"] == (
        "«Evaluaci3n de protocolos de transporte y transmisi3n»: las alternativas no son válidas: hace falta 1 correcta "
        "y 3 distractores, cada uno con su retroalimentación y su error conceptual.")
    # El motivo público del respaldo dice lo que pasó: la estructura, no las citas.
    assert step.generator["fallback"] is True
    assert "sin la estructura que pide el tipo" in step.generator["fallbackReason"]
    assert "citas válidas" not in step.generator["fallbackReason"]


def test_the_planned_mcq_prompt_keeps_the_brevity_to_the_stem(requests, plans):
    model = Capturing(valid_mcq)
    run_plan(requests, plans, model, MCQ_ITEM)
    _, user = build_prompt_instructions(model.contexts[0])
    assert "La brevedad es del enunciado" in user
    assert "error_conceptual" in user and "exactamente 4 alternativas" in user


# El motivo público según el rechazo que más pesa


def test_the_fallback_reason_follows_the_dominant_rejection_kind():
    name = "Gemini · gemini-3.5-flash-lite"
    def kinds(*values):
        return [{"kind": value, "title": "t", "reason": "r"} for value in values]

    assert fallback_warning(name, kinds("structure", "structure", "grounding")) == (
        f"{name} devolvió recursos sin la estructura que pide el tipo.")
    assert fallback_warning(name, kinds("grounding")) == f"{name} no devolvió recursos con citas válidas del material."
    assert fallback_warning(name, kinds("distractor", "distractor")) == (
        f"{name} devolvió ítems sin distractores fiables según el material.")
    assert fallback_warning(name, kinds("repetition")) == f"{name} devolvió recursos que repetían otros de la secuencia."
    assert fallback_warning(name, kinds("plan")) == f"{name} devolvió recursos que no respetaban el plan."
    assert fallback_warning(name, []) == f"{name} no devolvió recursos válidos."
    # En un empate, el orden fijo: estructura, citas, distractores, plan, repetición.
    assert fallback_warning(name, kinds("grounding", "structure")).endswith("sin la estructura que pide el tipo.")


# Los títulos conservan sus tildes


def test_titles_keep_their_accents_through_parsing_and_rejections(requests, plans):
    def accented(context):
        data = without_misconception(context)
        data["recursos"][0]["titulo"] = "Evaluación e identificación de la transmisión"
        return data

    done, _, _ = run_plan(requests, plans, Capturing(accented), MCQ_ITEM)
    [step] = done.steps
    assert step.rejections[0]["title"] == "Evaluación e identificación de la transmisión"
    # La respuesta llega como JSON con \\u00f3 o con «ó»: las dos se leen igual.
    from platform5e.application.services.generation.prompt_drafting import parse_json_response

    for raw in (json.dumps({"t": "Evaluación"}), json.dumps({"t": "Evaluación"}, ensure_ascii=False)):
        assert parse_json_response(raw)["t"] == "Evaluación"
