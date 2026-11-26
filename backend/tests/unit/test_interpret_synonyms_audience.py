"""GEN-C13 (spec 002, T075): sinónimos de tipos y audiencia sin rótulo en la interpretación de pedidos (HU-038).

Cambio C del «Plan de cambios v2» de Juan: en producción, «una pregunta detonante y un resumen … para primer ciclo» solo
dio la pregunta detonante y perdió el resumen y la audiencia. Sin red ni proveedores: solo reglas.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from platform5e.application.ports.outbound.unit_membership_port import OutcomeRef, UnitContext, UnitMembershipPort
from platform5e.application.use_cases.generation.interpret_generation_request import (
    InterpretGenerationCommand,
    InterpretGenerationRequest,
)
from platform5e.application.use_cases.generation.interpretation_synonyms import AMBIGUOUS_SYNONYMS, TYPE_SYNONYMS
from platform5e.domain.generation.resource_catalog import RESOURCE_TYPES
from platform5e.domain.generation.sequence import MAX_SEQUENCE_TYPES
from platform5e.domain.materials.text_analysis import normalize_text

PRODUCTION = "Quiero una pregunta detonante y un resumen sobre el control de flujo en TCP para primer ciclo"
CATALOG_IDS = {entry.id for entry in RESOURCE_TYPES}


def interpreter(education_level: str | None = None, academic_cycle: str | None = None):
    membership = Mock(spec=UnitMembershipPort)
    membership.get_unit_context.return_value = UnitContext(
        "course-1", "Redes", "", "", "unit-1", 1, "TCP/IP",
        (OutcomeRef("outcome-1", "RA1.1", "Comparar TCP y UDP"),),
        education_level=education_level, academic_cycle=academic_cycle,
    )
    use_case = InterpretGenerationRequest(membership, Mock(return_value=[{"unitId": "unit-1", "label": "TCP/IP"}]))
    return lambda message: use_case.execute(InterpretGenerationCommand("teacher-1", "unit-1", message))


# Tipos


def test_the_production_sentence_yields_both_types_and_the_audience():
    result = interpreter()(PRODUCTION)
    assert result["draft"]["resourceTypes"] == ["pregunta_detonante", "resumen_ideas_clave"]
    assert result["draft"]["mode"] == "sequence" and result["draft"]["audience"] == "primer ciclo"
    assert [s["stage"] for s in result["stages"]] == ["engage", "explain"]
    assert result["issues"] == []


@pytest.mark.parametrize(("message", "expected"), [
    ("Un resumen del tema", "resumen_ideas_clave"),
    ("Una síntesis de la unidad", "resumen_ideas_clave"),
    ("Un quiz sobre TCP", "item_opcion_multiple"),
    ("Un cuestionario de repaso", "item_opcion_multiple"),
    ("Cinco preguntas de alternativas", "item_opcion_multiple"),
    ("Un glosario de términos", "glosario"),
    ("El vocabulario de la unidad", "glosario"),
    ("Una pregunta motivadora", "pregunta_detonante"),
    ("Una evaluación diagnóstica", "sondeo_diagnostico"),
    ("Un mapa mental", "mapa_conceptual"),
    ("Un cuadro comparativo de TCP y UDP", "comparacion_conceptos"),
    ("Un ticket de salida", "ticket_salida"),
    ("Un boleto de salida", "ticket_salida"),
    ("Preguntas abiertas", "respuesta_corta"),
    ("Un verdadero y falso sobre TCP", "verdadero_falso"),
    ("Unos espacios en blanco para completar", "completar_espacios"),
    ("Un diagrama de flujo del saludo", "diagrama_proceso"),
    ("Un podcast del tema", "podcast_resumen"),
    ("Una analogía", "analogia_comentada"),
    ("Una autoevaluación", "autoevaluacion_guiada"),
    ("Un cuento corto sobre redes", "historia_corta"),
    ("Ejercicios prácticos", "ejercicio_aplicacion"),
])
def test_common_teacher_words_map_to_one_catalog_type(message, expected):
    result = interpreter()(message)
    assert result["draft"]["resourceTypes"] == [expected], result
    assert not [issue for issue in result["issues"] if issue["field"] == "resourceTypes"]


def test_every_synonym_points_to_a_real_catalog_type_and_does_not_replace_an_existing_alias():
    existing = {normalize_text(label).replace("_", " ") for entry in RESOURCE_TYPES
                for label in (entry.id, entry.name, entry.singular, *entry.count)}
    assert TYPE_SYNONYMS and AMBIGUOUS_SYNONYMS
    for word, type_id in TYPE_SYNONYMS.items():
        assert type_id in CATALOG_IDS, word
        assert normalize_text(word) not in existing, f"«{word}» ya es un alias del catálogo"
    for word, options in AMBIGUOUS_SYNONYMS.items():
        assert len(options) > 1 and set(options) <= CATALOG_IDS, word
        assert normalize_text(word) not in existing, word


@pytest.mark.parametrize(("message", "options"), [
    ("Un caso de estudio sobre TCP", ["caso_indagacion", "caso_aplicado", "analisis_caso_evaluativo"]),
    ("Unos problemas de enrutamiento", ["ejercicio_aplicacion", "problema_abierto"]),
    ("Un examen de la unidad", ["item_opcion_multiple", "verdadero_falso", "completar_espacios",
                                "respuesta_corta"]),
])
def test_an_ambiguous_word_returns_its_options_instead_of_guessing(message, options):
    result = interpreter()(message)
    assert result["draft"]["resourceTypes"] == [] and "mode" not in result["draft"]
    [issue] = [i for i in result["issues"] if i["field"] == "resourceTypes"]
    assert issue["kind"] == "ambiguous" and sorted(o["value"] for o in issue["options"]) == sorted(options)
    assert all(o["label"] for o in issue["options"])


def test_an_ambiguous_word_keeps_the_types_that_were_clear():
    result = interpreter()("Un glosario y un caso de estudio")
    assert result["draft"]["resourceTypes"] == ["glosario"]
    assert [i["kind"] for i in result["issues"] if i["field"] == "resourceTypes"] == ["ambiguous"]


def test_the_modality_narrows_an_ambiguous_word():
    # «Organizador gráfico» puede ser mapa conceptual, infografía o comparación; en Textual solo queda la comparación.
    assert interpreter()("Un organizador gráfico en modalidad textual")["draft"]["resourceTypes"] == [
        "comparacion_conceptos"]
    [issue] = [i for i in interpreter()("Un organizador gráfico en modalidad multimedia")["issues"]
               if i["field"] == "resourceTypes"]
    assert sorted(o["value"] for o in issue["options"]) == ["infografia", "mapa_conceptual"]


def test_a_synonym_outside_the_modality_is_reported_like_any_other_type():
    result = interpreter()("Un resumen en modalidad multimedia")
    assert result["draft"]["resourceTypes"] == []
    assert any(i["kind"] == "not_allowed" and "Resumen de ideas clave" in i["message"] for i in result["issues"])


def test_every_requested_type_reaches_the_draft_up_to_the_limit():
    message = ("Un quiz, un glosario de términos, un resumen, una pregunta motivadora, un mapa mental, "
               "un ticket de salida, una analogía y un cuadro comparativo")
    result = interpreter()(message)
    assert len(result["draft"]["resourceTypes"]) == MAX_SEQUENCE_TYPES == 8, result


# Audiencia


@pytest.mark.parametrize(("message", "audience"), [
    ("Un glosario para primer ciclo", "primer ciclo"),
    ("Un glosario para estudiantes de 3.er ciclo", "tercer ciclo"),
    ("Un glosario para alumnos del séptimo ciclo", "séptimo ciclo"),
    ("Un glosario para el ciclo III", "tercer ciclo"),
    ("Un glosario para pregrado", "pregrado"),
    ("Un glosario para estudiantes de secundaria", "secundaria"),
    ("Un glosario para docentes", "docentes"),
    ("Para primer ciclo, un glosario sobre TCP", "primer ciclo"),
])
def test_unlabeled_audience_phrases_fill_the_audience(message, audience):
    result = interpreter()(message)
    assert result["draft"]["audience"] == audience, result
    assert result["draft"]["resourceTypes"] == ["glosario"]
    assert "suggestedUnit" not in result and not [i for i in result["issues"] if i["field"] == "unitId"]


@pytest.mark.parametrize("message", [
    "Un glosario para explicar TCP",
    "Un glosario para repasar el control de flujo",
    "Un glosario para la clase del lunes",
    "2 glosarios para RA1.1",
])
def test_topic_phrases_with_para_are_not_audiences(message):
    assert "audience" not in interpreter()(message)["draft"]


def test_the_labeled_audience_wins_over_an_unlabeled_one():
    result = interpreter()("Un glosario para primer ciclo; Audiencia: Tercer ciclo")
    assert result["draft"]["audience"] == "Tercer ciclo" and result["issues"] == []


def test_two_different_unlabeled_audiences_are_ambiguous():
    result = interpreter()("Un glosario para primer ciclo y otro para pregrado")
    assert "audience" not in result["draft"]
    [issue] = [i for i in result["issues"] if i["field"] == "audience"]
    assert issue["kind"] == "ambiguous" and [o["value"] for o in issue["options"]] == ["primer ciclo", "pregrado"]


@pytest.mark.parametrize(("level", "cycle", "message"), [
    (None, "7.º ciclo", "Un glosario para primer ciclo"),
    (None, "VII", "Un glosario para estudiantes de 3.er ciclo"),
    ("Pregrado", None, "Un glosario para secundaria"),
])
def test_an_audience_that_conflicts_with_the_course_level_is_an_issue_and_not_applied(level, cycle, message):
    result = interpreter(level, cycle)(message)
    assert "audience" not in result["draft"]  # el formulario conserva la audiencia del curso
    [issue] = [i for i in result["issues"] if i["field"] == "audience"]
    assert issue["kind"] == "ambiguous" and len(issue["options"]) == 2


@pytest.mark.parametrize(("level", "cycle", "message", "audience"), [
    ("Pregrado", "1.er ciclo", "Un glosario para primer ciclo", "primer ciclo"),
    ("Pregrado", "VII", "Un glosario para pregrado", "pregrado"),
    ("Secundaria", None, "Un glosario para primer ciclo", "primer ciclo"),  # otra dimensión: no se compara
])
def test_an_audience_that_matches_the_course_is_applied(level, cycle, message, audience):
    result = interpreter(level, cycle)(message)
    assert result["draft"]["audience"] == audience and result["issues"] == []


def test_the_audience_does_not_eat_the_quantity_or_a_topic_about_cycles():
    result = interpreter()("Quiero dos glosarios para 3.er ciclo")
    assert (result["draft"]["quantity"], result["draft"]["audience"]) == (2, "tercer ciclo")
    assert "audience" not in interpreter()("Un glosario para el ciclo de vida de una conexión TCP")["draft"]
