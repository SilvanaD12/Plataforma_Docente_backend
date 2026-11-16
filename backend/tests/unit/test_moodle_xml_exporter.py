"""Moodle XML: el exportador produce lo que Moodle importó en SP-003, y el validador rechaza lo que Moodle perdería."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from platform5e.infrastructure.exporters.moodle_xml_exporter import MoodleXmlExporter
from tests.support.moodle_xml_validator import VERIFIED_SAMPLE, read_questions, validate

SAMPLE = VERIFIED_SAMPLE.read_text(encoding="utf-8")
COURSE = {"code": "RED-301"}
UNIT = {"number": 1, "title": "Capa de transporte"}
QUESTION = {
    "id": "r1",
    "title": "TCP & UDP",
    "body": "¿Cuál tiene menos retardo? <b>",
    "citations": [{"claim": "UDP no confirma la entrega.", "fragmentIds": ["f1"]}],
    "options": [
        {"id": "a", "text": "UDP", "isCorrect": True, "feedback": "No espera confirmaciones.", "decision": "pendiente"},
        {"id": "b", "text": "TCP", "isCorrect": False, "feedback": "Retransmite lo perdido.", "decision": "aceptado"},
        {"id": "c", "text": "SCTP", "isCorrect": False, "feedback": "Es orientado a la conexión.", "decision": "aceptado"},
        {"id": "d", "text": "DNS", "isCorrect": False, "feedback": "No es de transporte.", "decision": "descartado"},
    ],
}
TEXT = {"id": "r2", "title": "Glosario", "body": "TCP: protocolo de transporte.", "options": None, "citations": []}


def test_exported_file_passes_the_validator_built_from_the_verified_sample():
    exporter = MoodleXmlExporter()
    exported = exporter.export([QUESTION, TEXT], COURSE, UNIT)
    assert exported.file_name == "red-301-unidad-1-moodle.xml" and exported.media_type == "application/xml"
    assert validate(exported.content) == []
    [question] = read_questions(exported.content)  # el glosario no es una pregunta
    assert question.name == "TCP & UDP" and question.prompt == "¿Cuál tiene menos retardo? <b>"
    assert [text for text, _, _ in question.options] == ["UDP", "TCP", "SCTP"]  # sin el distractor descartado
    assert [fraction for _, fraction, _ in question.options] == ["100", "0", "0"]
    assert question.general_feedback == "Para repasar: UDP no confirma la entrega."
    assert exporter.supports(QUESTION) and not exporter.supports(TEXT)


def test_accepts_the_sample_imported_into_moodle_in_sp_003():
    assert validate(SAMPLE) == []
    assert len(read_questions(SAMPLE)) == 2


def test_rejects_two_correct_answers():
    broken = SAMPLE.replace('<answer fraction="0" format="html">', '<answer fraction="100" format="html">', 1)
    assert any("exactamente una alternativa" in e for e in validate(broken))


def test_rejects_an_option_without_feedback():
    start = SAMPLE.index("<feedback", SAMPLE.index('<answer fraction="0"'))
    end = SAMPLE.index("</feedback>", start) + len("</feedback>")
    assert any("no tiene retroalimentación" in e for e in validate(SAMPLE[:start] + SAMPLE[end:]))


def test_rejects_fewer_than_three_options():
    question = SAMPLE.index('<question type="multichoice">')
    answers = [i for i in range(len(SAMPLE)) if SAMPLE.startswith('<answer fraction="0"', i) and i > question]
    end = SAMPLE.index("</answer>", answers[1]) + len("</answer>")
    assert any("alternativas; deben ser entre 3 y 5" in e for e in validate(SAMPLE[: answers[0]] + SAMPLE[end:]))


def test_rejects_unverified_types_and_malformed_xml():
    assert any("no verificado" in e for e in validate(SAMPLE.replace('type="multichoice"', 'type="essay"', 1)))
    assert validate("<quiz><question>")[0].startswith("El XML no está bien formado")
    assert validate("<otro/>") == ["La raíz debe ser <quiz> y es <otro>."]


def test_items_go_in_one_category_per_level_with_the_points_of_their_level():
    """HU-051 C02: el cuestionario de Moodle llega con niveles y puntaje (básico 10, intermedio 20, avanzado 30)."""
    advanced = {**QUESTION, "id": "r3", "title": "Ventana deslizante", "params": {"difficulty": "avanzada"}}
    basic = {**QUESTION, "id": "r4", "title": "Puertos", "params": {"difficulty": "basica"}}
    unknown = {**QUESTION, "id": "r5", "title": "Sin dificultad"}  # recursos antiguos: intermedio
    exported = MoodleXmlExporter().export([advanced, TEXT, unknown, basic], COURSE, UNIT)
    assert validate(exported.content) == []
    root = ET.fromstring(exported.content)
    sequence = [
        (q.findtext("category/text") or "").rsplit("/", 1)[-1] if q.get("type") == "category"
        else (q.findtext("name/text"), q.findtext("defaultgrade"))
        for q in root.findall("question")
    ]
    assert sequence == [
        "Nivel 1 · Básico", ("Puertos", "10.0000000"),
        "Nivel 2 · Intermedio", ("Sin dificultad", "20.0000000"),
        "Nivel 3 · Avanzado", ("Ventana deslizante", "30.0000000"),
    ]
    assert root.find("question/category/text").text == "$course$/top/RED-301 · Unidad 1/Nivel 1 · Básico"


TRUE_FALSE_RESOURCE = {
    "id": "tf1",
    "type": "verdadero_falso",
    "title": "Protocolos de transporte V/F",
    "citations": [{"claim": "UDP no orienta a la conexión.", "fragmentIds": ["f1"]}],
    "structure": {
        "statements": [
            {
                "text": "TCP garantiza la entrega ordenada de paquetes.",
                "isTrue": True,
                "feedback": "Verdadero. TCP usa números de secuencia para ordenar.",
            },
            {
                "text": "UDP realiza un saludo de tres vías antes de enviar datos.",
                "isTrue": False,
                "feedback": "Falso. El saludo de tres vías es exclusivo de TCP.",
            },
        ]
    },
}

MATCHING_RESOURCE = {
    "id": "match1",
    "type": "emparejamiento",
    "title": "Relacionar protocolos y funciones",
    "body": "Relaciona cada protocolo con su función principal.",
    "citations": [{"claim": "TCP y UDP operan en capa de transporte.", "fragmentIds": ["f2"]}],
    "structure": {
        "pairs": [
            {"term": "TCP", "definition": "Transmisión confiable con control de flujo."},
            {"term": "UDP", "definition": "Transmisión rápida sin confirmación."},
            {"term": "SCTP", "definition": "Transmisión orientada a mensajes multi-homing."},
        ]
    },
}


def test_export_true_false_creates_one_question_per_statement_with_correct_fractions():
    exporter = MoodleXmlExporter()
    assert exporter.supports(TRUE_FALSE_RESOURCE)

    exported = exporter.export([TRUE_FALSE_RESOURCE], COURSE, UNIT)
    assert validate(exported.content) == []

    root = ET.fromstring(exported.content)
    tf_questions = root.findall("question[@type='truefalse']")
    assert len(tf_questions) == 2

    # Primera afirmación: verdadera
    q1 = tf_questions[0]
    assert q1.findtext("name/text") == "Protocolos de transporte V/F · 1"
    assert "TCP garantiza" in q1.findtext("questiontext/text")
    answers1 = q1.findall("answer")
    assert len(answers1) == 2
    true_ans1 = next(a for a in answers1 if a.findtext("text") == "true")
    false_ans1 = next(a for a in answers1 if a.findtext("text") == "false")
    assert true_ans1.get("fraction") == "100"
    assert "Verdadero" in true_ans1.findtext("feedback/text")
    assert false_ans1.get("fraction") == "0"
    assert "Incorrecto" in false_ans1.findtext("feedback/text")

    # Segunda afirmación: falsa
    q2 = tf_questions[1]
    assert q2.findtext("name/text") == "Protocolos de transporte V/F · 2"
    assert "UDP realiza" in q2.findtext("questiontext/text")
    answers2 = q2.findall("answer")
    true_ans2 = next(a for a in answers2 if a.findtext("text") == "true")
    false_ans2 = next(a for a in answers2 if a.findtext("text") == "false")
    assert true_ans2.get("fraction") == "0"
    assert "Incorrecto" in true_ans2.findtext("feedback/text")
    assert false_ans2.get("fraction") == "100"
    assert "Falso" in false_ans2.findtext("feedback/text")


def test_export_matching_creates_matching_question_with_subquestions():
    exporter = MoodleXmlExporter()
    assert exporter.supports(MATCHING_RESOURCE)

    exported = exporter.export([MATCHING_RESOURCE], COURSE, UNIT)
    assert validate(exported.content) == []

    root = ET.fromstring(exported.content)
    [match_q] = root.findall("question[@type='matching']")
    assert match_q.findtext("name/text") == "Relacionar protocolos y funciones"
    assert match_q.findtext("shuffleanswers") == "true"
    assert "Para repasar" in match_q.findtext("generalfeedback/text")

    subquestions = match_q.findall("subquestion")
    assert len(subquestions) == 3
    pairs_map = {sq.findtext("text"): sq.findtext("answer/text") for sq in subquestions}
    assert any("TCP" in term and "Transmisión confiable" in definition for term, definition in pairs_map.items())
    assert any("UDP" in term and "sin confirmación" in definition for term, definition in pairs_map.items())
    assert any("SCTP" in term and "multi-homing" in definition for term, definition in pairs_map.items())


def test_matching_requires_at_least_three_pairs_to_be_supported():
    exporter = MoodleXmlExporter()
    too_few_pairs = {
        **MATCHING_RESOURCE,
        "structure": {"pairs": [{"term": "A", "definition": "B"}, {"term": "C", "definition": "D"}]},
    }
    assert not exporter.supports(too_few_pairs)


def test_all_three_types_exported_together_pass_validator():
    exporter = MoodleXmlExporter()
    exported = exporter.export([QUESTION, TRUE_FALSE_RESOURCE, MATCHING_RESOURCE], COURSE, UNIT)
    assert validate(exported.content) == []

    questions = read_questions(exported.content)
    assert len(questions) == 4  # 1 multichoice + 2 truefalse + 1 matching
    kinds = [q.kind for q in questions]
    assert kinds == ["multichoice", "truefalse", "truefalse", "matching"]


def test_xml_escaping_in_all_fields():
    special_chars_resource = {
        "id": "sc1",
        "type": "verdadero_falso",
        "title": "A & B < C > D 'quote' \"double\"",
        "citations": [{"claim": "X & Y > Z", "fragmentIds": ["f1"]}],
        "structure": {
            "statements": [
                {
                    "text": "¿Es A & B < C?",
                    "isTrue": True,
                    "feedback": "Correcto: A & B < C es verdad.",
                }
            ]
        },
    }
    exporter = MoodleXmlExporter()
    exported = exporter.export([special_chars_resource], COURSE, UNIT)
    assert validate(exported.content) == []
    assert b"&amp;" in exported.content or b"<![CDATA[" in exported.content

