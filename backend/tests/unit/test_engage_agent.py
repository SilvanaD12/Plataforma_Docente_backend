"""
HU-047: el agente de Enganchar genera un recurso gamificado, el reto de predicción, además de los textuales que ya
existían (C01), y cada recurso cita su fragmento de origen (C02): en el reto, cada predicción.
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
from platform5e.domain.generation.grounding import link_prediction_sources
from platform5e.domain.generation.resource_catalog import RESOURCE_TYPES
from platform5e.domain.generation.resource_formats import normalize_structure, resource_format, structure_problems
from platform5e.infrastructure.exporters.scorm_package_exporter import ACTIVITY_JS, SCORM_JS, ScormPackageExporter
from platform5e.infrastructure.exporters.unit_document_exporter import UnitDocumentExporter
from platform5e.infrastructure.llm.gemini_language_model import GEMINI_RESPONSE_SCHEMA
from tests.unit.test_generation_with_material import MOCK_COURSE, MOCK_FRAGMENTS, MOCK_UNIT, make_request_dict
from tests.unit.test_multimodal_resources import context_for

TCP = "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable."
UDP = "El protocolo UDP no establece conexión y es más rápido."
FRAGMENTS = {"f1": TCP, "f2": UDP}

TCP_PREDICTION = {
    "question": "¿Qué protocolo crees que confirma que los datos llegaron?",
    "correctOption": "TCP",
    "otherOption": "UDP",
    "extraOption": "Ninguno: Internet siempre entrega todo",
    "reveal": "El protocolo TCP está orientado a la conexión y garantiza una entrega confiable.",
    "fragmentIds": ["f1"],
}
UDP_PREDICTION = {
    "question": "Para un videojuego en línea, ¿qué protocolo crees que conviene?",
    "correctOption": "UDP",
    "otherOption": "TCP",
    "extraOption": "",
    "reveal": "El protocolo UDP no establece conexión y por eso es más rápido.",
    "fragmentIds": ["f2"],
}
INVENTED_PREDICTION = {
    "question": "¿En qué año se creó ARPANET?",
    "correctOption": "1969",
    "otherOption": "1990",
    "extraOption": "",
    "reveal": "ARPANET se creó en 1969 entre universidades de California y Utah.",
    "fragmentIds": ["f1"],
}


def context(**overrides):
    request = make_request_dict(**{"stage": "engage", "resourceType": "reto_prediccion", **overrides})
    return build_generation_context(MOCK_COURSE, MOCK_UNIT, request, MOCK_FRAGMENTS, {})


def model_prediction(prediction: dict, tags: list[str] | str) -> dict:
    return {
        "pregunta": prediction["question"],
        "correcta": prediction["correctOption"],
        "otra": prediction["otherOption"],
        "extra": prediction["extraOption"],
        "revelacion": prediction["reveal"],
        "fragmentos": tags,
    }


def challenge(*predictions: dict, title: str = "Reto: TCP o UDP") -> dict:
    return {
        "titulo": title,
        "contenido": "Elige lo que crees en cada pregunta antes de la clase.",
        "citas": [{"afirmacion": "TCP garantiza una entrega confiable", "fragmentos": ["F1"]}],
        "alternativas": [],
        "estructura": {"predicciones": list(predictions)},
    }


# --- C01: un recurso gamificado y uno textual para Enganchar ---------------------------------------------------------


def test_engage_offers_a_gamified_challenge_besides_the_text_resources():
    engage = {entry.id: entry.format for entry in RESOURCE_TYPES if entry.stage == "engage"}
    assert engage["reto_prediccion"] == "interactive"
    assert {"pregunta_detonante", "sondeo_diagnostico"} <= {k for k, v in engage.items() if v == "text"}
    assert resource_format("reto_prediccion") == "interactive"


def test_a_prediction_needs_a_question_two_different_options_and_the_reveal():
    structure = normalize_structure("reto_prediccion", {"predictions": [TCP_PREDICTION, UDP_PREDICTION, TCP_PREDICTION]})
    assert [p["correctOption"] for p in structure["predictions"]] == ["TCP", "UDP", "TCP"]
    assert structure_problems("reto_prediccion", structure) == []
    same_options = {**UDP_PREDICTION, "otherOption": "udp"}
    no_reveal = {**UDP_PREDICTION, "reveal": ""}
    assert normalize_structure("reto_prediccion", {"predictions": [TCP_PREDICTION, UDP_PREDICTION, same_options]}) is None
    assert normalize_structure("reto_prediccion", {"predictions": [TCP_PREDICTION, UDP_PREDICTION, no_reveal]}) is None
    problems = structure_problems("reto_prediccion", {"predictions": [TCP_PREDICTION, UDP_PREDICTION]})
    assert problems and "al menos 3" in problems[0]


def test_the_prompt_and_the_gemini_schema_ask_for_predictions_with_their_fragments():
    _, prompt = build_prompt_instructions(context())
    assert '"predicciones"' in prompt and '"revelacion"' in prompt and "Reto de predicción" in prompt
    schema = GEMINI_RESPONSE_SCHEMA["properties"]["recursos"]["items"]["properties"]["estructura"]["properties"]
    assert set(schema["predicciones"]["items"]["properties"]) == {
        "pregunta", "correcta", "otra", "extra", "revelacion", "fragmentos",
    }


def test_the_model_predictions_are_translated_and_their_tags_resolved():
    raw = {"predicciones": [model_prediction(TCP_PREDICTION, ["F1"]), model_prediction(UDP_PREDICTION, "F2"),
                            model_prediction(TCP_PREDICTION, ["F9"])]}
    structure = structure_from_model("reto_prediccion", raw, "", "", {"F1": "f1", "F2": "f2"})
    assert [p["fragmentIds"] for p in structure["predictions"]] == [["f1"], ["f2"], []]
    assert structure["predictions"][0] == TCP_PREDICTION


# --- C02: cada predicción cita su fragmento de origen ----------------------------------------------------------------


def test_a_prediction_whose_answer_is_in_its_fragment_keeps_its_citation():
    result = link_prediction_sources([TCP_PREDICTION, UDP_PREDICTION], FRAGMENTS)
    assert [p["fragmentIds"] for p in result.predictions] == [["f1"], ["f2"]] and result.corrected == 0


def test_a_prediction_citing_the_wrong_fragment_is_linked_to_the_one_with_the_answer():
    result = link_prediction_sources([{**UDP_PREDICTION, "fragmentIds": ["f1"]}], FRAGMENTS)
    assert result.predictions[0]["fragmentIds"] == ["f2"] and result.corrected == 1


def test_a_prediction_whose_answer_is_not_in_the_material_is_removed_with_its_reason():
    result = link_prediction_sources([TCP_PREDICTION, INVENTED_PREDICTION], FRAGMENTS)
    assert [p["correctOption"] for p in result.predictions] == ["TCP"]
    [removed] = result.removed
    assert removed["question"] == INVENTED_PREDICTION["question"] and "mínimo 50 %" in removed["reason"]
    assert result.summary() == {
        "predictionThreshold": 0.5, "checkedPredictions": 2, "supportedPredictions": 1,
        "correctedPredictions": 0, "removedPredictions": [removed],
    }


def test_the_wrong_options_are_not_checked_against_the_material():
    # La opción equivocada a propósito no está en el material; solo cuentan la respuesta y lo que se revela.
    tricky = {**TCP_PREDICTION, "extraOption": "Lo decide el router de cada ciudad"}
    assert link_prediction_sources([tricky], FRAGMENTS).predictions[0]["fragmentIds"] == ["f1"]


def test_normalization_links_each_prediction_and_drops_the_invented_one():
    payload = {"recursos": [challenge(
        model_prediction(TCP_PREDICTION, ["F1"]),
        model_prediction(UDP_PREDICTION, ["F1"]),  # cita equivocada
        model_prediction({**TCP_PREDICTION, "question": "¿TCP establece conexión?"}, ["F1"]),
        model_prediction(INVENTED_PREDICTION, ["F1"]),
    )]}
    rejections: list[dict] = []
    [resource] = normalize_generated_resources(payload, context(), rejections)
    predictions = resource["estructura"]["predictions"]
    assert [p["fragmentIds"] for p in predictions] == [["f1"], ["f2"], ["f1"]]
    verification = resource["verificacion"]
    assert (verification["checkedPredictions"], verification["supportedPredictions"],
            verification["correctedPredictions"]) == (4, 3, 1)
    assert verification["removedPredictions"][0]["question"] == INVENTED_PREDICTION["question"] and rejections == []


def test_a_challenge_with_less_than_three_supported_predictions_is_rejected_with_its_reason():
    payload = {"recursos": [challenge(
        model_prediction(TCP_PREDICTION, ["F1"]),
        model_prediction(UDP_PREDICTION, ["F2"]),
        model_prediction(INVENTED_PREDICTION, ["F1"]),
        title="Inventado",
    )]}
    rejections: list[dict] = []
    assert normalize_generated_resources(payload, context(), rejections) == []
    assert rejections[0]["title"] == "Inventado" and "solo 2 predicción(es)" in rejections[0]["reason"]
    assert rejections[0]["grounding"]["removedPredictions"][0]["question"] == INVENTED_PREDICTION["question"]


def test_the_rule_based_fallback_cites_a_fragment_in_every_prediction():
    ctx = context_for("reto_prediccion", 1)  # el corpus de protocolos de evaluation/corpus
    [resource] = normalize_generated_resources(RuleBasedGenerator().generate(ctx), ctx)
    predictions = resource["estructura"]["predictions"]
    assert len(predictions) >= 3
    for p in predictions:
        assert p["fragmentIds"] and p["question"].startswith("¿") and "________" in p["question"]
        assert p["correctOption"] not in (p["otherOption"], p["extraOption"])
    assert resource["verificacion"]["supportedPredictions"] == len(predictions)


# --- Exportación -----------------------------------------------------------------------------------------------------


def approved_challenge() -> dict:
    return {
        "id": "r1", "type": "reto_prediccion", "stage": "engage", "status": "aprobado", "format": "interactive",
        "title": "Reto: TCP o UDP", "body": "Elige antes de la clase.", "createdAt": "2026-11-04T10:00", "options": None,
        "structure": {"predictions": [TCP_PREDICTION, UDP_PREDICTION, {**TCP_PREDICTION, "fragmentIds": ["f1", "f2"]}]},
        "evidence": [
            {"id": "f1", "text": TCP, "location": "p. 1", "documentName": "apuntes.pdf"},
            {"id": "f2", "text": UDP, "location": "p. 2", "documentName": "apuntes.pdf"},
        ],
    }


def test_the_scorm_page_is_a_game_with_points_streak_badges_and_the_source_of_each_answer():
    exported = ScormPackageExporter().export([approved_challenge()], {"code": "RED"}, {"number": 1, "title": "T"})
    archive = zipfile.ZipFile(io.BytesIO(exported.content))
    page = next(archive.read(n).decode() for n in archive.namelist() if n.startswith("sco/"))
    assert 'data-kind="activity"' in page and "Para iniciar la clase" in page
    data = json.loads(re.search(r'id="activity-data">(.*?)</script>', page, re.S).group(1))
    assert data["type"] == "reto_prediccion"
    assert [p["source"] for p in data["structure"]["predictions"]] == [
        "apuntes.pdf, p. 1", "apuntes.pdf, p. 2", "apuntes.pdf, p. 1; apuntes.pdf, p. 2",
    ]
    assert data["badges"] == [{"min": 90, "name": "Oro"}, {"min": 75, "name": "Plata"}, {"min": 60, "name": "Bronce"}]
    assert "reto_prediccion: function" in ACTIVITY_JS and "STREAK_BONUS" in ACTIVITY_JS
    # Para iniciar la clase: se registra el puntaje, pero la actividad queda completada, no aprobada o desaprobada.
    assert "scorm5e.complete(percent)" in ACTIVITY_JS and "'completed'" in SCORM_JS


def test_the_unit_document_prints_the_options_and_a_key_with_what_the_material_says():
    html = UnitDocumentExporter().export([approved_challenge()], {"code": "RED"}, {"number": 1, "title": "T"})
    content = html.content.decode()
    assert "Reto de predicción" in content and "¿Qué protocolo crees que confirma que los datos llegaron?" in content
    assert "a) Ninguno: Internet siempre entrega todo b) TCP c) UDP" in content  # en orden alfabético
    assert "1. TCP. El protocolo TCP está orientado a la conexión" in content and "(Fuente: p. 1)" in content
