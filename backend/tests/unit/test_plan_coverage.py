"""GEN-P2 (T013): comprobación de cobertura del plan, léxica y sin IA (specs/006-plan-de-generacion, research R5).

Corrección tras la medición de P4:
- **Concepto propio desarrollado:** al menos el 60 % de sus palabras útiles (normalizadas como en QA-05, comparadas por
  su raíz) aparecen en un mismo párrafo, no solo la frase exacta.
- **Concepto ajeno desarrollado:** aparece en al menos dos oraciones, o en una oración que lo define («X es…»,
  «X: …»). Nombrarlo una vez no cuenta, ni en un recurso corto.
- **Conceptos de fondo:** los que están en los fragmentos de la mitad o más de los ítems son contexto compartido, no de
  un solo recurso (`backbone_concepts`).
"""

from __future__ import annotations

from platform5e.domain.generation.generation_plan import PlanItem
from platform5e.domain.generation.plan_coverage import backbone_concepts, check_plan_coverage, concept_share

OWN = ("control de flujo", "retransmisión")
FOREIGN = ("protocolo UDP", "datagrama")


def resource(body: str, title: str = "Recurso", options: list[dict] | None = None, structure=None) -> dict:
    return {"titulo": title, "contenido": body, "alternativas": options or [], "estructura": structure}


def test_a_resource_that_develops_its_own_concepts_passes():
    result = check_plan_coverage(resource(
        "El control de flujo regula cuánto envía el emisor.\n\nLa retransmisión recupera lo perdido."), OWN, FOREIGN)
    assert result.accepted and result.problem is None


def test_own_concepts_are_compared_without_accents_case_or_stopwords():
    assert check_plan_coverage(resource("El CONTROL del Flujo evita saturar al receptor."), OWN, FOREIGN).accepted


def test_an_own_concept_counts_when_most_of_its_words_share_a_paragraph():
    # «saludo de tres vías» parafraseado: «saludo» y «tres» (2 de 3 palabras, 67 %).
    paraphrase = resource("TCP abre la conexión con un saludo en tres pasos: SYN, SYN-ACK y ACK.")
    assert concept_share("TCP abre la conexión con un saludo en tres pasos.", "saludo de tres vías") >= 0.6
    assert check_plan_coverage(paraphrase, ("saludo de tres vías",), ()).accepted
    # La raíz cuenta: «confirma» y «confirmación» comparten sus seis primeras letras.
    assert check_plan_coverage(resource("UDP no confirma la entrega de los mensajes."),
                               ("confirmación de entrega",), ()).accepted
    # Las palabras repartidas en párrafos distintos no cuentan como el concepto.
    scattered = resource("TCP envía un saludo al empezar.\n\nLuego llegan las tres respuestas.\n\nHay vías alternas.")
    assert check_plan_coverage(scattered, ("saludo de tres vías",), ()).accepted is False


def test_a_resource_that_mentions_none_of_its_concepts_is_rejected_with_the_concepts():
    result = check_plan_coverage(resource("El enrutador decide el camino de cada paquete.", "Rutas"), OWN, FOREIGN)
    assert not result.accepted
    assert result.problem == "«Rutas»: no desarrolla ninguno de sus conceptos del plan («control de flujo», «retransmisión»)."
    assert "control de flujo" in result.instruction and "protocolo UDP" in result.instruction


def test_a_foreign_concept_in_two_sentences_is_developed():
    developed = resource(
        "El control de flujo regula el envío.\n\nEl protocolo UDP no confirma la entrega.\n\n"
        "Por eso el protocolo UDP es más rápido.", "TCP frente a UDP")
    result = check_plan_coverage(developed, OWN, FOREIGN)
    assert not result.accepted
    assert result.problem == "«TCP frente a UDP»: desarrolla «protocolo UDP», que el plan asigna a otro recurso."
    assert result.developed == ["protocolo UDP"]


def test_a_foreign_concept_defined_in_one_sentence_is_developed():
    defined = resource("El control de flujo regula el envío. El protocolo UDP es un protocolo sin conexión del "
                       "nivel de transporte.")
    glossary = resource("Control de flujo: regula el envío.\nDatagrama: unidad de datos de UDP.")
    assert check_plan_coverage(defined, OWN, FOREIGN).developed == ["protocolo UDP"]
    assert check_plan_coverage(glossary, OWN, FOREIGN).developed == ["datagrama"]


def test_a_single_mention_of_a_foreign_concept_is_not_developed_even_in_a_short_resource():
    stem = resource("¿Qué pasaría con el control de flujo si se usara el protocolo UDP?")
    in_option = resource("¿Qué mecanismo regula el envío según el control de flujo?", options=[
        {"texto": "La ventana de recepción", "retroalimentacion": "Correcto."},
        {"texto": "El protocolo UDP", "retroalimentacion": "No regula el envío."},
    ])
    assert check_plan_coverage(stem, OWN, FOREIGN).accepted
    assert check_plan_coverage(in_option, OWN, FOREIGN).accepted


def test_a_single_word_of_a_multiword_foreign_concept_does_not_count():
    body = "¿Qué protocolo usa el control de flujo? Cada protocolo tiene su propio control."
    assert check_plan_coverage(resource(body), OWN, FOREIGN).accepted


def test_structure_texts_count_as_sentences():
    steps = {"guidedSteps": [
        {"title": "Paso 1", "instruction": "Observa el datagrama en la captura.", "question": "¿Qué ves?"},
        {"title": "Paso 2", "instruction": "Compara cada datagrama con un segmento.", "question": "¿Qué cambia?"},
    ]}
    result = check_plan_coverage(resource("Explora el control de flujo.", structure=steps), OWN, FOREIGN)
    assert not result.accepted and result.developed == ["datagrama"]


def test_without_own_concepts_only_the_foreign_rule_applies():
    assert check_plan_coverage(resource("Un texto cualquiera sobre redes."), (), FOREIGN).accepted


def test_a_foreign_concept_inside_one_of_the_own_concepts_does_not_count():
    # «capas» es de otro recurso, pero aquí solo aparece dentro de «capa de transporte», que es propio.
    body = "La capa de transporte recibe los datos. Después, la capa de transporte los divide en segmentos."
    assert check_plan_coverage(resource(body), ("capa de transporte",), ("capas",)).accepted


def test_concepts_in_the_fragments_of_half_the_items_or_more_are_backbone():
    texts = {
        "f1": "La capa de transporte entrega datos entre procesos; TCP es orientado a la conexión.",
        "f2": "UDP es un protocolo de la capa de transporte sin conexión.",
        "f3": "El modelo OSI tiene 7 capas: física, enlace, red, capa de transporte, sesión, presentación y aplicación.",
        "f4": "El control de flujo de TCP usa la ventana del receptor.",
    }
    items = (
        PlanItem(1, "engage", "pregunta_detonante", 1, "p", ("protocolo UDP",), ("f2",)),
        PlanItem(2, "explain", "explicacion", 1, "p", ("capa de transporte",), ("f1",)),
        PlanItem(3, "explain", "glosario", 1, "p", ("control de flujo",), ("f4",)),
        PlanItem(4, "evaluate", "item_opcion_multiple", 1, "p", ("modelo OSI",), ("f3",)),
    )
    # «capa de transporte» está en los fragmentos de 3 de 4 ítems; «modelo OSI» y «control de flujo», en los de uno.
    assert backbone_concepts(items, texts) == {"capa transporte"}
    assert backbone_concepts(items[:1], texts) == set()  # con un solo ítem no hay contexto compartido


def test_develops_concept_uses_the_same_rule_on_any_text():
    from platform5e.domain.generation.plan_coverage import develops_concept

    assert develops_concept("El protocolo UDP es un protocolo sin conexión.", "protocolo UDP")  # lo define
    assert develops_concept("El protocolo UDP no confirma. Por eso el protocolo UDP es rápido.", "protocolo UDP")
    assert not develops_concept("TCP es distinto del protocolo UDP en la conexión.", "protocolo UDP")  # una mención



def test_concept_usage_separates_mentioned_developed_and_defined():
    from platform5e.domain.generation.plan_coverage import concept_usage

    assert concept_usage("TCP es distinto del protocolo UDP.", "protocolo UDP") == {
        "mentioned": True, "developed": False, "defined": False}
    assert concept_usage("El protocolo UDP no confirma. El protocolo UDP es rápido porque no espera.",
                         "protocolo UDP") == {"mentioned": True, "developed": True, "defined": True}
    assert concept_usage("Nada que ver con el tema.", "protocolo UDP") == {
        "mentioned": False, "developed": False, "defined": False}
