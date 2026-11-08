"""
Exportador Moodle XML (ADR-005): banco de preguntas de opción múltiple con los ítems aprobados.

Misma estructura que la muestra importada con éxito en Moodle durante SP-003
(tests/fixtures/verified_moodle_sample.xml). Solo se exportan la clave y los distractores que el
docente no descartó. La IA nunca escribe XML: el archivo sale de esta plantilla fija.

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


def _question(resource: Mapping) -> list[str]:
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


class MoodleXmlExporter(UnitExporterPort):
    """Adaptador del formato «moodle_xml»: Moodle solo importa los ítems de opción múltiple."""

    format = "moodle_xml"
    media_type = "application/xml"

    def supports(self, resource: Mapping) -> bool:
        return bool(resource.get("options"))

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
                lines += _question(resource)
        lines.append("</quiz>")
        file_name = f"{_slug(course.get('code', ''))}-unidad-{number}-moodle.xml"
        return ExportedFile(file_name, self.media_type, "\n".join(lines).encode("utf-8"))
