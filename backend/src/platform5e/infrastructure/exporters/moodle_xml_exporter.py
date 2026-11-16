"""
Exportador Moodle XML (ADR-005, QA-03): banco de preguntas con los ítems aprobados.

Soporta tres tipos de preguntas (QA-03):
- item_opcion_multiple -> <question type="multichoice">
- verdadero_falso -> <question type="truefalse"> (una pregunta por afirmación)
- emparejamiento -> <question type="matching"> (un <subquestion> por par, mínimo 3)

Gamificación (HU-051, ADR-012): los ítems van en una subcategoría por nivel («Nivel 1 · Básico»…) y cada uno
vale los puntos de su nivel en <defaultgrade>. Así el docente arma en Moodle un cuestionario por niveles o
con preguntas aleatorias de cada nivel, y Moodle muestra el puntaje de cada pregunta.
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping, Sequence

from platform5e.application.ports.outbound.unit_exporter_port import ExportedFile, UnitExporterPort
from platform5e.domain.generation.gamification import by_level, item_level

# Quitar "descartado" cuando los valores guardados estén migrados al inglés.
DISCARDED = {"discarded", "descartado"}


def _escape(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _cdata(value: str) -> str:
    return "<![CDATA[" + value.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def _to_html(text: str) -> str:
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text or "") if p.strip()]
    return "".join(f"<p>{_escape(p).replace(chr(10), '<br/>')}</p>" for p in paragraphs)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-") or "curso"


def exported_options(resource: Mapping) -> list[Mapping]:
    """La clave y los distractores que el docente no descartó."""
    return [o for o in resource.get("options") or [] if o.get("isCorrect") or o.get("decision") not in DISCARDED]


def _general_feedback(resource: Mapping) -> str:
    claims = [c.get("claim", "") for c in resource.get("citations") or [] if c.get("claim")]
    return f"Para repasar: {' '.join(claims)}" if claims else ""


def _multichoice_question(resource: Mapping) -> list[str]:
    lines = [
        '  <question type="multichoice">',
        f"    <name><text>{_escape(resource.get('title'))}</text></name>",
        f'    <questiontext format="html"><text>{_cdata(_to_html(resource.get("body", "")))}</text></questiontext>',
        f'    <generalfeedback format="html"><text>{_cdata(_to_html(_general_feedback(resource)))}</text></generalfeedback>',
        f"    <defaultgrade>{item_level(resource).points:.7f}</defaultgrade>",
        "    <penalty>0.3333333</penalty>",
        "    <hidden>0</hidden>",
        "    <idnumber></idnumber>",
        "    <single>true</single>",
        "    <shuffleanswers>true</shuffleanswers>",
        "    <answernumbering>abc</answernumbering>",
        "    <showstandardinstruction>0</showstandardinstruction>",
        f'    <correctfeedback format="html"><text>{_cdata("<p>Respuesta correcta.</p>")}</text></correctfeedback>',
        '    <partiallycorrectfeedback format="html"><text>'
        f'{_cdata("<p>Respuesta parcialmente correcta.</p>")}</text></partiallycorrectfeedback>',
        f'    <incorrectfeedback format="html"><text>{_cdata("<p>Respuesta incorrecta.</p>")}</text></incorrectfeedback>',
        "    <shownumcorrect/>",
    ]
    for option in exported_options(resource):
        lines += [
            f'    <answer fraction="{"100" if option.get("isCorrect") else "0"}" format="html">',
            f"      <text>{_cdata(_to_html(option.get('text', '')))}</text>",
            f'      <feedback format="html"><text>{_cdata(_to_html(option.get("feedback", "")))}</text></feedback>',
            "    </answer>",
        ]
    lines.append("  </question>")
    return lines


def _truefalse_questions(resource: Mapping) -> list[str]:
    structure = resource.get("structure") or {}
    statements = structure.get("statements") or structure.get("afirmaciones") or []
    lines: list[str] = []
    total = len(statements)
    general_fb = _general_feedback(resource)

    for idx, stmt in enumerate(statements, start=1):
        name = resource.get("title") or "Verdadero o falso"
        if total > 1:
            name = f"{name} · {idx}"

        stmt_text = stmt.get("text") or stmt.get("texto") or ""
        is_true = stmt.get("isTrue") if "isTrue" in stmt else bool(stmt.get("verdadera"))
        fb = stmt.get("feedback") or stmt.get("retroalimentacion") or ""

        if is_true:
            true_fraction = "100"
            false_fraction = "0"
            true_fb = fb or "Respuesta correcta."
            false_fb = f"Incorrecto. {fb}".strip() if fb else "Respuesta incorrecta."
        else:
            true_fraction = "0"
            false_fraction = "100"
            true_fb = f"Incorrecto. {fb}".strip() if fb else "Respuesta incorrecta."
            false_fb = fb or "Respuesta correcta."

        lines += [
            '  <question type="truefalse">',
            f"    <name><text>{_escape(name)}</text></name>",
            f'    <questiontext format="html"><text>{_cdata(_to_html(stmt_text))}</text></questiontext>',
            f'    <generalfeedback format="html"><text>{_cdata(_to_html(general_fb))}</text></generalfeedback>',
            f"    <defaultgrade>{item_level(resource).points:.7f}</defaultgrade>",
            "    <penalty>1.0000000</penalty>",
            "    <hidden>0</hidden>",
            "    <idnumber></idnumber>",
            "    <showstandardinstruction>0</showstandardinstruction>",
            f'    <correctfeedback format="html"><text>{_cdata("<p>Respuesta correcta.</p>")}</text></correctfeedback>',
            '    <partiallycorrectfeedback format="html"><text>'
            f'{_cdata("<p>Respuesta parcialmente correcta.</p>")}</text></partiallycorrectfeedback>',
            f'    <incorrectfeedback format="html"><text>{_cdata("<p>Respuesta incorrecta.</p>")}</text></incorrectfeedback>',
            "    <shownumcorrect/>",
            f'    <answer fraction="{true_fraction}" format="html">',
            "      <text>true</text>",
            f'      <feedback format="html"><text>{_cdata(_to_html(true_fb))}</text></feedback>',
            "    </answer>",
            f'    <answer fraction="{false_fraction}" format="html">',
            "      <text>false</text>",
            f'      <feedback format="html"><text>{_cdata(_to_html(false_fb))}</text></feedback>',
            "    </answer>",
            "  </question>",
        ]
    return lines


def _matching_question(resource: Mapping) -> list[str]:
    structure = resource.get("structure") or {}
    pairs = structure.get("pairs") or structure.get("pares") or []
    general_fb = _general_feedback(resource)

    prompt = resource.get("body") or "Relaciona cada término con su definición."

    lines = [
        '  <question type="matching">',
        f"    <name><text>{_escape(resource.get('title'))}</text></name>",
        f'    <questiontext format="html"><text>{_cdata(_to_html(prompt))}</text></questiontext>',
        f'    <generalfeedback format="html"><text>{_cdata(_to_html(general_fb))}</text></generalfeedback>',
        f"    <defaultgrade>{item_level(resource).points:.7f}</defaultgrade>",
        "    <penalty>0.3333333</penalty>",
        "    <hidden>0</hidden>",
        "    <idnumber></idnumber>",
        "    <shuffleanswers>true</shuffleanswers>",
        f'    <correctfeedback format="html"><text>{_cdata("<p>Respuesta correcta.</p>")}</text></correctfeedback>',
        '    <partiallycorrectfeedback format="html"><text>'
        f'{_cdata("<p>Respuesta parcialmente correcta.</p>")}</text></partiallycorrectfeedback>',
        f'    <incorrectfeedback format="html"><text>{_cdata("<p>Respuesta incorrecta.</p>")}</text></incorrectfeedback>',
        "    <shownumcorrect/>",
    ]
    for pair in pairs:
        term = pair.get("term") or pair.get("termino") or ""
        definition = pair.get("definition") or pair.get("definicion") or ""
        lines += [
            '    <subquestion format="html">',
            f"      <text>{_cdata(_to_html(term))}</text>",
            "      <answer>",
            f"        <text>{_escape(definition)}</text>",
            "      </answer>",
            "    </subquestion>",
        ]
    lines.append("  </question>")
    return lines


def _question_for_resource(resource: Mapping) -> list[str]:
    rtype = resource.get("type")
    structure = resource.get("structure") or {}
    if rtype == "verdadero_falso" or bool(structure.get("statements") or structure.get("afirmaciones")):
        return _truefalse_questions(resource)
    if rtype == "emparejamiento" or bool(structure.get("pairs") or structure.get("pares")):
        return _matching_question(resource)
    return _multichoice_question(resource)


class MoodleXmlExporter(UnitExporterPort):
    """Adaptador del formato «moodle_xml»: exporta opción múltiple, verdadero/falso y emparejamiento."""

    format = "moodle_xml"
    media_type = "application/xml"

    def supports(self, resource: Mapping) -> bool:
        rtype = resource.get("type")
        if rtype == "item_opcion_multiple" or bool(resource.get("options")):
            return bool(resource.get("options"))
        structure = resource.get("structure") or {}
        if rtype == "verdadero_falso" or bool(structure.get("statements") or structure.get("afirmaciones")):
            statements = structure.get("statements") or structure.get("afirmaciones") or []
            return bool(statements)
        if rtype == "emparejamiento" or bool(structure.get("pairs") or structure.get("pares")):
            pairs = structure.get("pairs") or structure.get("pares") or []
            return len(pairs) >= 3
        return False

    def export(self, resources: Sequence[Mapping], course: Mapping, unit: Mapping) -> ExportedFile:
        number = unit.get("number", 1)
        category = f"{course.get('code', '')} · Unidad {number}"
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', "<quiz>"]
        for level, items in by_level([r for r in resources if self.supports(r)]):
            path = f"$course$/top/{_escape(category)}/{_escape(level.title)}"
            lines.append(
                f'  <question type="category"><category><text>{path}</text></category>'
                f'<info format="html"><text>{_cdata(f"<p>Cada pregunta vale {level.points} puntos.</p>")}</text></info>'
                "<idnumber></idnumber></question>"
            )
            for resource in items:
                lines += _question_for_resource(resource)
        lines.append("</quiz>")
        file_name = f"{_slug(course.get('code', ''))}-unidad-{number}-moodle.xml"
        return ExportedFile(file_name, self.media_type, "\n".join(lines).encode("utf-8"))
