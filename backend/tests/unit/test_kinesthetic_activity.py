"""HU-024 (T054 y T055): actividad kinestésica de la etapa Explorar y línea de la modalidad en el prompt.

Caso GEN-C11. La estructura sigue la de la exploración guiada (research R11 y data-model `actividad_kinestesica`):
`guidedSteps` con al menos 3 pasos citados y, dentro de `structure`, `materials`, `estimatedMinutes` y `space`.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from platform5e.application.services.generation.prompt_drafting import (
    MODALITY_INTENTS,
    build_generation_context,
    build_prompt_instructions,
    normalize_generated_resources,
    structure_from_model,
)
from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.application.use_cases.generation.run_generation_request import RunGenerationRequest
from platform5e.application.use_cases.generation.start_generation_request import StartGenerationCommand
from platform5e.domain.generation.generation_request import GenerationMode, GenerationParameters, RequestStatus
from platform5e.domain.generation.resource_catalog import RESOURCE_TYPES
from platform5e.domain.generation.resource_formats import (
    MIN_ITEMS,
    MODALITIES,
    MODALITY_TYPES,
    modalities_of,
    normalize_structure,
    resource_format,
    resource_stage,
    structure_problems,
)
from platform5e.domain.review.content_fingerprint import content_fingerprint
from platform5e.domain.review.resource_verification import verify_resource
from platform5e.infrastructure.adapters.review_verification_adapter import ReviewVerificationAdapter
from platform5e.infrastructure.llm.gemini_language_model import GEMINI_RESPONSE_SCHEMA
from tests.unit.test_explore_agent import FRAGMENTS, TCP_STEP, UDP_STEP
from platform5e.application.ports.outbound.evidence_provider_port import EvidenceFragment
from tests.unit.test_generation_with_material import MOCK_COURSE, MOCK_FRAGMENTS, MOCK_UNIT, make_request_dict
from tests.unit.test_multimodal_resources import context_for
from tests.unit.test_start_regeneration import Setup

KINESTHETIC = "actividad_kinestesica"

THIRD_STEP = {
    "title": "Conexión con el cuerpo",
    "instruction": "Representen en parejas cómo el protocolo TCP es orientado a la conexión y garantiza una entrega.",
    "question": "¿Qué hicieron para que la entrega fuera confiable?",
    "fragmentIds": ["f1", "f2"],
}
STRUCTURE: dict[str, Any] = {
    "guidedSteps": [TCP_STEP, UDP_STEP, THIRD_STEP],
    "materials": ["Tarjetas", "Cinta adhesiva"],
    "estimatedMinutes": 25,
    "space": "Aula con las mesas a un lado",
}


def structure(**overrides: Any) -> dict[str, Any]:
    return {**deepcopy(STRUCTURE), **overrides}


# T054 · Catálogo y modalidad


def test_the_kinesthetic_activity_is_an_interactive_explore_type_only_in_kinesthetic():
    [entry] = [entry for entry in RESOURCE_TYPES if entry.id == KINESTHETIC]
    assert (entry.name, entry.singular, entry.group) == ("Actividad kinestésica", "Actividad kinestésica", "Para explorar")
    assert entry.count == ("actividad kinestésica", "actividades kinestésicas")
    assert resource_stage(KINESTHETIC) == "explore" and resource_format(KINESTHETIC) == "interactive"
    assert MODALITY_TYPES["Kinestésico"] == {KINESTHETIC}
    assert modalities_of(KINESTHETIC) == ["Kinestésico"]
    assert MIN_ITEMS[KINESTHETIC] == 3
    # Va justo después de la exploración guiada, en el orden de la clase.
    ids = [item.id for item in RESOURCE_TYPES]
    assert ids.index(KINESTHETIC) == ids.index("exploracion_guiada") + 1


# T054 · Estructura


def test_the_structure_keeps_the_steps_materials_time_and_space():
    normalized = normalize_structure(KINESTHETIC, structure())
    assert list(normalized) == ["guidedSteps", "materials", "estimatedMinutes", "space"]
    assert normalized["guidedSteps"] == [TCP_STEP, UDP_STEP, THIRD_STEP]
    assert normalized["materials"] == ["Tarjetas", "Cinta adhesiva"]
    assert normalized["estimatedMinutes"] == 25 and normalized["space"] == "Aula con las mesas a un lado"
    assert structure_problems(KINESTHETIC, normalized) == []


def test_the_question_of_a_step_is_optional_and_materials_may_be_empty():
    without_question = {**THIRD_STEP, "question": ""}
    normalized = normalize_structure(
        KINESTHETIC, structure(guidedSteps=[TCP_STEP, UDP_STEP, without_question], materials=[])
    )
    assert normalized["guidedSteps"][2]["question"] == "" and normalized["materials"] == []


def test_materials_are_cleaned_and_repeated_ones_removed():
    normalized = normalize_structure(
        KINESTHETIC, structure(materials=["  Tarjetas ", "tarjetas", "", 7, None, "Plumones"])
    )
    assert normalized["materials"] == ["Tarjetas", "Plumones"]


@pytest.mark.parametrize("minutes", [4, 91, 0, -10, None, True, "veinte", 25.5])
def test_an_estimated_time_outside_5_to_90_minutes_is_rejected(minutes):
    assert normalize_structure(KINESTHETIC, structure(estimatedMinutes=minutes)) is None


@pytest.mark.parametrize("minutes", [5, 90, "30"])
def test_the_estimated_time_accepts_the_limits_and_whole_numbers_as_text(minutes):
    assert normalize_structure(KINESTHETIC, structure(estimatedMinutes=minutes))["estimatedMinutes"] == int(minutes)


@pytest.mark.parametrize("space", ["", "   ", None])
def test_without_a_space_the_activity_is_rejected(space):
    assert normalize_structure(KINESTHETIC, structure(space=space)) is None


def test_fewer_than_three_steps_is_rejected():
    assert normalize_structure(KINESTHETIC, structure(guidedSteps=[TCP_STEP, UDP_STEP])) is None
    assert structure_problems(KINESTHETIC, structure(guidedSteps=[TCP_STEP])) != []


def test_the_fingerprint_covers_materials_time_and_space():
    """La huella de REV-01 se calcula sobre la estructura normalizada: editar los tres campos cambia la huella."""
    base = {"type": KINESTHETIC, "title": "Actividad", "body": "Consigna", "citations": [], "structure": structure()}
    reference = content_fingerprint(base)
    for field, value in [("materials", ["Pelotas"]), ("estimatedMinutes", 40), ("space", "Patio")]:
        assert content_fingerprint({**base, "structure": structure(**{field: value})}) != reference, field


# T054 · Redacción con el modelo


def context(**overrides: Any) -> dict[str, Any]:
    request = make_request_dict(**{"stage": "explore", "resourceType": KINESTHETIC, **overrides})
    return build_generation_context(MOCK_COURSE, MOCK_UNIT, request, MOCK_FRAGMENTS, {})


def model_structure(*steps: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "pasos_guiados": list(steps),
        "materiales": ["Tarjetas", "Cinta adhesiva"],
        "minutos_estimados": 20,
        "espacio": "Aula",
        **extra,
    }


def model_step(title: str, instruction: str, question: str, tags: list[str]) -> dict[str, Any]:
    return {"titulo": title, "consigna": instruction, "pregunta": question, "fragmentos": tags}


def test_the_prompt_asks_for_steps_materials_time_and_space():
    system_prompt, user_prompt = build_prompt_instructions(context())
    assert "«Actividad kinestésica»" in user_prompt
    for key in ("pasos_guiados", "materiales", "minutos_estimados", "espacio", "fragmentos"):
        assert key in user_prompt, key
    assert "con el cuerpo" in user_prompt
    assert "Cada afirmación importante debe citar" in system_prompt


def test_the_model_answer_is_converted_and_its_tags_resolved():
    raw = model_structure(
        model_step("A", "Formen grupos", "¿Qué?", ["F1"]),
        model_step("B", "Caminen", "", ["F2"]),
        model_step("C", "Comparen", "¿Y?", ["F1", "F2"]),
    )
    converted = structure_from_model(KINESTHETIC, raw, "", "Título", {"F1": "f1", "F2": "f2"})
    assert [step["fragmentIds"] for step in converted["guidedSteps"]] == [["f1"], ["f2"], ["f1", "f2"]]
    assert converted["guidedSteps"][1]["question"] == ""
    assert (converted["materials"], converted["estimatedMinutes"], converted["space"]) == (
        ["Tarjetas", "Cinta adhesiva"], 20, "Aula",
    )


def test_the_gemini_schema_accepts_the_new_fields():
    fields = GEMINI_RESPONSE_SCHEMA["properties"]["recursos"]["items"]["properties"]["estructura"]["properties"]
    assert fields["materiales"] == {"type": "ARRAY", "items": {"type": "STRING"}}
    assert fields["minutos_estimados"] == {"type": "INTEGER"}
    assert fields["espacio"] == {"type": "STRING"}


def _drafted(*steps: dict[str, Any]) -> dict[str, Any]:
    return {
        "titulo": "Protocolos en movimiento",
        "contenido": "Hagan los pasos en grupos y comenten lo que observaron.",
        "citas": [{"afirmacion": "TCP garantiza una entrega confiable", "fragmentos": ["F1"]}],
        "alternativas": [],
        "estructura": model_structure(*steps),
    }


def _fragments_context() -> dict[str, Any]:
    fragments = [
        {"id": fragment_id, "text": text, "documentId": "d1", "location": "p. 1"}
        for fragment_id, text in FRAGMENTS.items()
    ]
    request = make_request_dict(stage="explore", resourceType=KINESTHETIC)
    return build_generation_context(MOCK_COURSE, MOCK_UNIT, request, fragments, {"d1": "redes.pdf"})


def _model(step: dict[str, Any], tag: str) -> dict[str, Any]:
    return model_step(step["title"], step["instruction"], step["question"], [tag])


def test_each_step_is_linked_to_its_fragment_and_unsupported_steps_are_removed():
    invented = model_step(
        "Historia de ARPANET", "Investiguen quién diseñó ARPANET en 1969.", "¿Cuántos nodos tenía?", ["F1"]
    )
    raw = {"recursos": [_drafted(_model(TCP_STEP, "F1"), _model(UDP_STEP, "F2"), _model(THIRD_STEP, "F1"), invented)]}
    [resource] = normalize_generated_resources(raw, _fragments_context())
    steps = resource["estructura"]["guidedSteps"]
    assert [step["title"] for step in steps] == [TCP_STEP["title"], UDP_STEP["title"], THIRD_STEP["title"]]
    assert all(step["fragmentIds"] for step in steps)
    # Los datos de la actividad no se contrastan con el material, pero se conservan.
    assert resource["estructura"]["estimatedMinutes"] == 20 and resource["estructura"]["space"] == "Aula"


def test_with_fewer_than_three_supported_steps_the_activity_is_rejected_with_its_reason():
    invented = model_step("Historia", "Investiguen ARPANET en 1969.", "¿Cuántos nodos?", ["F1"])
    raw = {"recursos": [_drafted(_model(TCP_STEP, "F1"), _model(UDP_STEP, "F2"), invented)]}
    rejections: list[dict[str, Any]] = []
    assert normalize_generated_resources(raw, _fragments_context(), rejections) == []
    [rejection] = rejections
    assert rejection["kind"] == "grounding" and "al menos 3" in rejection["reason"]


# T054 · Generador por reglas


def test_the_rule_based_builder_writes_three_cited_steps_with_materials_time_and_space():
    ctx = context_for(KINESTHETIC, 1)  # el corpus de protocolos de evaluation/corpus
    raw = RuleBasedGenerator().generate(ctx)
    [resource] = normalize_generated_resources(raw, ctx)
    activity = resource["estructura"]
    assert len(activity["guidedSteps"]) >= 3 and all(step["fragmentIds"] for step in activity["guidedSteps"])
    assert 1 <= len(activity["materials"]) <= 5 and all(len(material) <= 80 for material in activity["materials"])
    assert 5 <= activity["estimatedMinutes"] <= 90 and activity["space"]
    assert resource["citas"]


# T054 · Pedido completo: copia histórica y verificación


@pytest.fixture
def setup(tmp_path) -> Setup:
    return Setup(tmp_path)


def _run_rules(setup: Setup, request_id: str):
    RunGenerationRequest(
        setup.repository,
        setup.membership,
        setup.evidence,
        setup.review,
        ReviewVerificationAdapter(),
        RuleBasedGenerator(),
        heartbeat_seconds=0,
    ).execute(request_id)
    return setup.repository.get("docente-a", request_id)


def _corpus_fragments() -> tuple[EvidenceFragment, ...]:
    """Los fragmentos del corpus de protocolos: los dos de prueba no alcanzan para 3 pasos del generador por reglas."""
    return tuple(
        EvidenceFragment(
            chunk_id=fragment["id"], document_id="doc1", document_name="protocolos.txt", location="p. 1",
            text=fragment["texto"], relevance=0.9, source_url=None, license=None,
        )
        for fragment in context_for(KINESTHETIC, 1)["fragmentos"]
    )


def test_a_kinesthetic_request_delivers_a_current_activity_with_the_cited_fragments_copied(setup):
    setup.evidence.fragments = _corpus_fragments()
    request = setup.use_case._start_generation.execute(
        StartGenerationCommand(
            "docente-a", "u1", GenerationMode.INDIVIDUAL, "clave-kinestesica-1",
            GenerationParameters(resource_types=(KINESTHETIC,), modality="Kinestésico"),
        )
    ).request
    finished = _run_rules(setup, request.id)

    [resource] = setup.review.all()
    assert finished.status == RequestStatus.SUCCEEDED
    assert resource["type"] == KINESTHETIC and resource["params"]["modality"] == "Kinestésico"
    activity = resource["structure"]
    assert len(activity["guidedSteps"]) >= 3 and activity["space"] and 5 <= activity["estimatedMinutes"] <= 90
    step_fragments = {f for step in activity["guidedSteps"] for f in step["fragmentIds"]}
    assert step_fragments <= {fragment["id"] for fragment in resource["evidence"]}
    assert resource["verification"]["status"] == "current"


def _verified_activity(**changes: Any) -> dict[str, Any]:
    resource = {
        "type": KINESTHETIC, "title": "Protocolos en movimiento", "body": "Consigna", "version": 1,
        "citations": [{"claim": "TCP garantiza una entrega confiable", "fragmentIds": ["f1"]}],
        "structure": structure(), "evidence": [{"id": key, "text": text} for key, text in FRAGMENTS.items()],
    }
    resource.update(changes)
    return resource


def test_review_marks_a_supported_activity_as_current():
    assert verify_resource(_verified_activity(), 0.6, 1)["status"] == "current"


def test_review_rejects_an_edited_activity_whose_steps_are_not_in_the_material():
    invented = {
        "title": "Historia de ARPANET",
        "instruction": "Investiguen quién diseñó ARPANET en 1969 y en qué universidades se instaló.",
        "question": "¿Cuántos nodos tenía la primera red militar?",
        "fragmentIds": ["f1"],
    }
    edited = _verified_activity(structure=structure(guidedSteps=[TCP_STEP, invented, {**invented, "title": "Otra"}]))
    assert verify_resource(edited, 0.6, 1)["status"] == "insufficient"


def test_review_needs_three_supported_steps_and_gives_the_reason():
    """T059 (REV-01): con solo 2 pasos respaldados, la actividad editada queda insuficiente y el motivo lo explica."""
    invented = {
        "title": "Historia de ARPANET",
        "instruction": "Investiguen quién diseñó ARPANET en 1969 y en qué universidades se instaló.",
        "question": "",
        "fragmentIds": ["f1"],
    }
    edited = _verified_activity(structure=structure(guidedSteps=[TCP_STEP, UDP_STEP, invented]))
    result = verify_resource(edited, 0.6, 1)
    assert result["status"] == "insufficient"
    assert "solo 2 pasos" in result["reason"] and "al menos 3 pasos" in result["reason"]


# T055 · Línea de la modalidad en el prompt


def test_each_modality_has_an_intent():
    assert set(MODALITY_INTENTS) == set(MODALITIES)
    assert "con el cuerpo" in MODALITY_INTENTS["Kinestésico"] and "aula" in MODALITY_INTENTS["Kinestésico"]


@pytest.mark.parametrize("modality", MODALITIES)
def test_the_modality_line_appears_only_when_the_request_has_one(modality):
    resource_type = KINESTHETIC if modality == "Kinestésico" else "glosario"
    stage = "explore" if modality == "Kinestésico" else "explain"
    without_system, without_user = build_prompt_instructions(context(resourceType=resource_type, stage=stage))
    with_system, with_user = build_prompt_instructions(
        context(resourceType=resource_type, stage=stage, modality=modality)
    )

    line = f"Modalidad de la clase: {modality}. {MODALITY_INTENTS[modality]}"
    assert line in with_user and "Modalidad de la clase" not in without_user
    # Solo se agrega esa línea: no cambian las reglas de citas ni de formato.
    assert with_system == without_system
    assert with_user.replace(line + "\n", "") == without_user
