"""GEN-P2 (T013): comprobación de cobertura del plan, léxica y sin IA (specs/006-plan-de-generacion, research R5).

El recurso debe mencionar al menos uno de sus conceptos y no desarrollar los ajenos: en un recurso de varios párrafos,
un concepto ajeno en más de un párrafo; en uno de un solo párrafo, un concepto ajeno completo en el enunciado o en
una opción (no en la retroalimentación).
"""

from __future__ import annotations

from platform5e.domain.generation.plan_coverage import check_plan_coverage

OWN = ("control de flujo", "retransmisión")
FOREIGN = ("protocolo UDP", "datagrama")


def resource(body: str, title: str = "Recurso", options: list[dict] | None = None, structure=None) -> dict:
    return {"titulo": title, "contenido": body, "alternativas": options or [], "estructura": structure}


def test_a_resource_that_develops_its_own_concepts_passes():
    result = check_plan_coverage(resource(
        "El control de flujo regula cuánto envía el emisor.\n\nLa retransmisión recupera lo perdido."), OWN, FOREIGN)
    assert result.accepted and result.problem is None


def test_own_concepts_are_compared_without_accents_case_or_stopwords():
    result = check_plan_coverage(resource("El CONTROL del Flujo evita saturar al receptor."), OWN, FOREIGN)
    assert result.accepted


def test_a_resource_that_mentions_none_of_its_concepts_is_rejected_with_the_concepts():
    result = check_plan_coverage(resource("El enrutador decide el camino de cada paquete.", "Rutas"), OWN, FOREIGN)
    assert not result.accepted
    assert result.problem == "«Rutas»: no desarrolla ninguno de sus conceptos del plan («control de flujo», «retransmisión»)."
    assert "control de flujo" in result.instruction and "protocolo UDP" in result.instruction


def test_in_several_paragraphs_a_foreign_concept_in_more_than_one_paragraph_is_developed():
    named_once = resource(
        "El control de flujo regula el envío, a diferencia del protocolo UDP.\n\nLa retransmisión recupera datos.")
    developed = resource(
        "El control de flujo regula el envío.\n\nEl protocolo UDP no confirma la entrega.\n\n"
        "Por eso el protocolo UDP es más rápido.", "TCP frente a UDP")
    assert check_plan_coverage(named_once, OWN, FOREIGN).accepted
    result = check_plan_coverage(developed, OWN, FOREIGN)
    assert not result.accepted
    assert result.problem == "«TCP frente a UDP»: desarrolla «protocolo UDP», que el plan asigna a otro recurso."
    assert result.developed == ["protocolo UDP"]


def test_in_a_single_paragraph_a_foreign_concept_named_in_the_stem_is_developed():
    question = resource("¿Qué pasaría con el control de flujo si se usara el protocolo UDP?", "Pregunta")
    assert not check_plan_coverage(question, OWN, FOREIGN).accepted


def test_in_a_single_paragraph_a_foreign_concept_in_an_option_counts_but_not_in_its_feedback():
    stem = "¿Qué mecanismo regula el envío según el control de flujo?"
    in_option = resource(stem, options=[
        {"texto": "La ventana de recepción", "retroalimentacion": "Correcto."},
        {"texto": "El protocolo UDP", "retroalimentacion": "No regula el envío."},
    ])
    in_feedback = resource(stem, options=[
        {"texto": "La ventana de recepción", "retroalimentacion": "Correcto."},
        {"texto": "El reloj del sistema", "retroalimentacion": "Lo confunde con el protocolo UDP."},
    ])
    assert not check_plan_coverage(in_option, OWN, FOREIGN).accepted
    assert check_plan_coverage(in_feedback, OWN, FOREIGN).accepted


def test_a_single_word_of_a_multiword_foreign_concept_does_not_count():
    result = check_plan_coverage(resource("¿Qué protocolo usa el control de flujo?"), OWN, FOREIGN)
    assert result.accepted


def test_structure_texts_count_as_paragraphs():
    steps = {"guidedSteps": [
        {"title": "Paso 1", "instruction": "Observa el datagrama en la captura.", "question": "¿Qué ves?"},
        {"title": "Paso 2", "instruction": "Compara cada datagrama con un segmento.", "question": "¿Qué cambia?"},
    ]}
    result = check_plan_coverage(resource("Explora el control de flujo.", structure=steps), OWN, FOREIGN)
    assert not result.accepted and result.developed == ["datagrama"]


def test_without_own_concepts_only_the_foreign_rule_applies():
    assert check_plan_coverage(resource("Un texto cualquiera sobre redes."), (), FOREIGN).accepted


def test_a_body_with_one_entry_per_line_counts_each_line_as_a_paragraph():
    glossary = resource("Control de flujo: regula el envío.\nProtocolo UDP: no establece conexión.\n"
                        "Retransmisión: reenvía lo perdido.")
    assert check_plan_coverage(glossary, OWN, FOREIGN).accepted  # «protocolo UDP» en una sola entrada
    twice = resource("Control de flujo: regula el envío.\nProtocolo UDP: no establece conexión.\n"
                     "Datagrama del protocolo UDP: su unidad de datos.")
    assert check_plan_coverage(twice, OWN, FOREIGN).developed == ["protocolo UDP"]


def test_a_foreign_concept_inside_one_of_the_own_concepts_does_not_count():
    # «capas» es de otro recurso, pero aquí solo aparece dentro de «capa de transporte», que es propio.
    stem = resource("¿Qué hace la capa de transporte con los datos de la aplicación?")
    assert check_plan_coverage(stem, ("capa de transporte",), ("capas",)).accepted
    alone = resource("¿Qué hace la capa de transporte frente a las demás capas?")
    assert check_plan_coverage(alone, ("capa de transporte",), ("capas",)).developed == ["capas"]
