"""T027 (b), spec 006: el generador del plan (research R4).

- El plan de Gemini con 8 tipos fallaba la validación dos veces (NOT_ENOUGH_CONCEPTS, CONCEPT_OWNED_TWICE): el esquema y
  el prompt no decían el número exacto de conceptos por tipo, los conceptos largos se descartaban en silencio y el
  reintento no decía cuáles. Ahora el esquema va por tipo con su mínimo, el reintento nombra los ítems y los conceptos,
  y un concepto repetido se quita del ítem posterior si le sobran (reparación registrada en `generator.repairs`).
- El planificador por reglas armaba conceptos pegados entre signos («destino longitud», «ftp sftp»), con palabras de
  encabezado («redes página») o pedazos de oración («udp proporciona»), y daba a cada ítem fragmentos que no
  mencionaban sus conceptos. Se prueba con el texto real del corpus de T067, como test_plan_coverage_p4.

Gemini es falso (transporte HTTP falso): sin red ni proveedores reales.
"""

from __future__ import annotations

import pytest

from platform5e.application.services.generation.concept_extraction import concept_phrases, evidence_concepts_from
from platform5e.application.services.generation.plan_drafting import (
    GenerationPlanner,
    RuleBasedPlanner,
    plan_response_schema,
)
from platform5e.domain.generation.plan_coverage import contains_term
from platform5e.domain.generation.plan_validation import validate_items
from tests.unit.test_plan_drafting import CATALOG, KNOWN, Recorder, evidence_for, gemini, gemini_answer, inputs
from tests.unit.test_topic_coverage import CASES

P4_INSTRUCTIONS = "Protocolos de transporte TCP y UDP: conexión, confiabilidad, control de flujo y datagramas"
P4_TYPES = ["pregunta_detonante", "sondeo_diagnostico", "guia_exploracion", "caso_indagacion", "explicacion",
            "glosario", "ejercicio_aplicacion", "item_opcion_multiple"]
P4_INPUTS = inputs(*[(t, 2) for t in P4_TYPES], instructions=P4_INSTRUCTIONS)
EVIDENCE = evidence_for({**CASES["C-01"], "instructions": P4_INSTRUCTIONS})
# Conceptos malos que dio el planificador por reglas con el corpus de T067 (en p4.db y al reproducirlo).
BAD_CONCEPTS = {"redes página", "https versiones", "ftp sftp", "correo smtp", "bloques desordenados", "destino longitud",
                "udp proporciona", "contiene solo", "solo cuatro", "origen puerto", "bits puerto", "tcp transmission",
                "entrega best", "udp conexión", "ingeniería de redes"}


# Planificador por reglas, con el corpus real de T067


@pytest.fixture(scope="module")
def rule_plan():
    return RuleBasedPlanner(CATALOG).draft(P4_INPUTS, EVIDENCE)


def test_rule_concepts_are_none_of_the_bad_examples_and_keep_acronyms_and_multiword_terms(rule_plan):
    concepts = {c.lower() for item in rule_plan for c in item.covers}
    assert not concepts & BAD_CONCEPTS, concepts & BAD_CONCEPTS
    assert not any("página" in c or "pagina" in c for c in concepts)
    assert {"tcp", "udp"} <= concepts  # las siglas se conservan solas
    assert any(len(c.split()) >= 3 for c in concepts)  # y los términos de varias palabras («control de congestión»)
    assert not validate_items(rule_plan, EVIDENCE.fragment_ids, None, KNOWN)
    # Singular y plural no son dos conceptos («bloque de bytes» y «bloques de bytes»).
    singular = [" ".join(word.rstrip("s") for word in c.split()) for c in concepts]
    assert len(set(singular)) == len(singular), sorted(concepts)


def test_every_rule_item_gets_fragments_that_mention_its_own_concepts_ranked_first(rule_plan):
    texts = {f.id: f.text for f in EVIDENCE.fragments}
    for item in rule_plan:
        assert item.fragment_ids, item
        mentions = [sum(contains_term(texts[fid], c) for c in item.covers) for fid in item.fragment_ids]
        assert all(count >= 1 for count in mentions), (item.resource_type, item.covers, mentions)
        assert mentions == sorted(mentions, reverse=True)  # primero los que más conceptos propios mencionan


def test_phrases_never_cross_punctuation_headers_or_acronyms():
    text = ("Protocolos TCP y UDP - Ingeniería de redes  Página 1\nLa cabecera trae el puerto de destino, longitud y "
            "suma de verificación. Servicios como FTP, SFTP y correo (SMTP) usan TCP. El bloqueo de cabeza de línea "
            "afecta a HTTP/2.")
    header = "Protocolos TCP y UDP - Ingeniería de redes  Página 2\nEl control de congestión reduce el envío."
    phrases = [p.lower() for p in concept_phrases(text, headers={"protocolos tcp y udp", "ingeniería de redes"})]
    assert "puerto de destino" in phrases and "suma de verificación" in phrases
    assert "bloqueo de cabeza de línea" in phrases
    assert not {"destino longitud", "ftp sftp", "correo smtp", "redes página", "ingeniería de redes"} & set(phrases)
    concepts = [c.lower() for c in evidence_concepts_from("Control de congestión en TCP", [text, header], limit=20)]
    assert "control de congestión" in concepts and not any("ingeniería" in c for c in concepts)
    assert "smtp" not in concepts  # una sigla cuenta si aparece al menos dos veces; SMTP aparece una


# Planificador con Gemini, 8 tipos


def item(resource_type: str, covers: list[str], quantity: int = 2) -> dict:
    return {"resourceType": resource_type, "quantity": quantity, "purpose": f"Propósito de {resource_type}.",
            "covers": covers, "fragmentos": ["F1"]}


GOOD_COVERS = {
    "pregunta_detonante": ["entrega best-effort", "transmisión sin conexión"],
    "sondeo_diagnostico": ["control de flujo", "cabecera de 8 bytes"],
    "guia_exploracion": ["números de puerto", "puerto de origen"],
    "caso_indagacion": ["requisitos de retardo", "transmisión de audio"],
    "explicacion": ["saludo de tres vías", "control de congestión"],
    "glosario": ["User Datagram Protocol", "Transmission Control Protocol"],
    "ejercicio_aplicacion": ["fiabilidad y latencia", "elección de protocolo"],
    "item_opcion_multiple": ["suma de verificación", "cabecera TCP"],
}


def plan_with(**changes) -> dict:
    return {"items": [item(t, changes.get(t, GOOD_COVERS[t])) for t in P4_TYPES]}


def test_the_schema_states_the_exact_concept_minimum_of_each_requested_type():
    schema = plan_response_schema(inputs(("explicacion", 3), ("glosario", None), instructions=P4_INSTRUCTIONS))
    by_type = schema["properties"]["items"]
    assert by_type["type"] == "OBJECT" and by_type["required"] == ["explicacion", "glosario"]
    assert by_type["properties"]["explicacion"]["properties"]["covers"]["minItems"] == "3"
    assert by_type["properties"]["glosario"]["properties"]["covers"]["minItems"] == "1"
    assert "quantity" in by_type["properties"]["glosario"]["required"]
    assert "quantity" not in by_type["properties"]["explicacion"]["required"]  # la cantidad pedida no se cambia


def test_an_eight_type_plan_that_fails_validation_is_fixed_by_the_retry_with_specific_feedback():
    # Primer plan: el glosario tiene un concepto largo (se descarta) y le queda 1 de 2: NOT_ENOUGH_CONCEPTS.
    first = plan_with(glosario=["User Datagram Protocol",
                                "el protocolo TCP garantiza la entrega ordenada de los segmentos al receptor"])
    provider = Recorder(gemini_answer(first), gemini_answer(plan_with()))
    items, generator = GenerationPlanner(gemini(provider), CATALOG).draft(P4_INPUTS, EVIDENCE)
    assert generator["usesAi"] is True and generator["attempts"] == 2 and generator["repairs"] == []
    assert len(items) == 8
    retry = provider.bodies[1]["contents"][-1]["parts"][0]["text"]
    assert "El ítem «glosario» tiene 1 concepto válido («User Datagram Protocol») y necesita 2" in retry
    assert "Se descartaron por no ser frases cortas: «el protocolo TCP garantiza la entrega" in retry


def test_a_repeated_concept_is_repaired_in_the_later_item_when_it_has_spare_concepts():
    # El glosario repite «control de flujo», que ya es del sondeo; le quedan 2 conceptos: se quita sin reintento.
    repeated = plan_with(glosario=["User Datagram Protocol", "Control  de flujo", "Transmission Control Protocol"])
    provider = Recorder(gemini_answer(repeated))
    items, generator = GenerationPlanner(gemini(provider), CATALOG).draft(P4_INPUTS, EVIDENCE)
    assert generator["usesAi"] is True and generator["attempts"] == 1 and provider.calls == 1
    assert generator["repairs"] == [{"code": "CONCEPT_OWNED_TWICE", "resourceType": "glosario",
                                     "concept": "Control de flujo", "action": "removed",
                                     "keptIn": "sondeo_diagnostico"}]
    glossary = next(i for i in items if i.resource_type == "glosario")
    assert glossary.covers == ("User Datagram Protocol", "Transmission Control Protocol")


def test_a_repeated_concept_without_spare_concepts_is_sent_back_naming_both_items():
    repeated = plan_with(glosario=["User Datagram Protocol", "control de flujo"])
    provider = Recorder(gemini_answer(repeated), gemini_answer(plan_with()))
    _, generator = GenerationPlanner(gemini(provider), CATALOG).draft(P4_INPUTS, EVIDENCE)
    assert generator["attempts"] == 2 and generator["usesAi"] is True
    retry = provider.bodies[1]["contents"][-1]["parts"][0]["text"]
    assert ("«control de flujo» está en «sondeo_diagnostico» y en «glosario»: déjalo solo en «sondeo_diagnostico» "
            "y pon en «glosario» otro concepto del material") in retry


def test_a_model_chosen_quantity_is_lowered_to_its_concepts_but_a_requested_one_is_not():
    chosen = inputs(("explicacion", None), ("glosario", 2), instructions=P4_INSTRUCTIONS)
    raw = {"items": [item("explicacion", ["control de flujo"], quantity=3),
                     item("glosario", ["User Datagram Protocol", "Transmission Control Protocol"])]}
    items, generator = GenerationPlanner(gemini(Recorder(gemini_answer(raw))), CATALOG).draft(chosen, EVIDENCE)
    explanation = next(i for i in items if i.resource_type == "explicacion")
    assert explanation.quantity == 1 and generator["attempts"] == 1
    assert generator["repairs"] == [{"code": "NOT_ENOUGH_CONCEPTS", "resourceType": "explicacion",
                                     "action": "quantity_lowered", "from": 3, "to": 1}]


def test_the_object_answer_keyed_by_type_is_read_like_the_list():
    keyed = {"items": {t: {k: v for k, v in item(t, GOOD_COVERS[t]).items() if k != "resourceType"} for t in P4_TYPES}}
    items, generator = GenerationPlanner(gemini(Recorder(gemini_answer(keyed))), CATALOG).draft(P4_INPUTS, EVIDENCE)
    assert generator["usesAi"] is True and sorted(i.resource_type for i in items) == sorted(P4_TYPES)
