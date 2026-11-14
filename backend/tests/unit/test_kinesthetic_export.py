"""T059 (REV-01): la actividad kinestésica en el documento de la unidad y en el paquete SCORM.

GEN-01 la genera desde HU-024 (T054). Antes de T059 el documento la mostraba como «Pregunta de opción múltiple» en
«Para evaluar» y el SCORM no tenía cómo mostrarla. Estructura en research R11 de GEN-01: `guidedSteps` (al menos 3,
con pregunta opcional) y, junto a ellos, `materials`, `estimatedMinutes` y `space`.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from xml.etree import ElementTree as ET

from platform5e.domain.generation.resource_catalog import RESOURCE_TYPES
from platform5e.infrastructure.exporters.scorm_package_exporter import ACTIVITY_JS, ScormPackageExporter
from platform5e.infrastructure.exporters.unit_document_exporter import RESOURCE_LABELS, UnitDocumentExporter
from tests.unit.test_explore_agent import TCP, TCP_STEP, UDP, UDP_STEP

COURSE = {"code": "RED"}
UNIT = {"number": 1, "title": "Transporte"}
THIRD_STEP = {
    "title": "Conexión con el cuerpo",
    "instruction": "Representen en parejas cómo TCP confirma cada entrega antes de seguir.",
    "question": "",
    "fragmentIds": ["f1", "f2"],
}


def approved_activity() -> dict:
    return {
        "id": "k1", "type": "actividad_kinestesica", "stage": "explore", "status": "aprobado", "format": "interactive",
        "title": "Protocolos en movimiento", "body": "Formen grupos y hagan los pasos.", "options": None,
        "createdAt": "2026-11-14T10:00",
        "structure": {
            "guidedSteps": [TCP_STEP, UDP_STEP, THIRD_STEP],
            "materials": ["Tarjetas", "Cinta <adhesiva>"],
            "estimatedMinutes": 25,
            "space": "Aula & patio",
        },
        "evidence": [
            {"id": "f1", "text": TCP, "location": "p. 1", "documentName": "apuntes.pdf"},
            {"id": "f2", "text": UDP, "location": "p. 2", "documentName": "apuntes.pdf"},
        ],
    }


# Documento de la unidad


def _document() -> str:
    return UnitDocumentExporter().export([approved_activity()], COURSE, UNIT).content.decode()


def test_every_catalog_type_has_its_own_label_in_the_unit_document():
    """Ningún tipo cae en la etiqueta por defecto de la pregunta de opción múltiple."""
    assert [entry.id for entry in RESOURCE_TYPES if entry.id not in RESOURCE_LABELS] == []
    assert RESOURCE_LABELS["actividad_kinestesica"] == ("Para explorar", "Actividad kinestésica")


def test_the_unit_document_shows_the_activity_under_explore_and_not_as_a_multiple_choice_question():
    html = _document()
    assert "<h2>Para explorar</h2>" in html and "Actividad kinestésica" in html
    assert "Pregunta de opción múltiple" not in html and "Para evaluar" not in html


def test_the_unit_document_shows_materials_time_and_space_before_the_steps():
    html = _document()
    for text in ("Tarjetas", "Cinta &lt;adhesiva&gt;", "25 minutos", "Aula &amp; patio"):
        assert text in html, text
    assert "<adhesiva>" not in html and "Aula & patio" not in html  # todo el texto va escapado
    first_step = html.index(TCP_STEP["title"])
    assert max(html.index("Tarjetas"), html.index("25 minutos"), html.index("Aula &amp; patio")) < first_step


def test_the_unit_document_prints_each_step_with_its_source_and_skips_an_empty_question():
    html = _document()
    for step in (TCP_STEP, UDP_STEP, THIRD_STEP):
        assert step["title"] in html and step["instruction"] in html
    assert TCP_STEP["question"] in html
    assert "Fuente: p. 1" in html and "Fuente: p. 1, p. 2" in html
    assert "<em></em>" not in html


# Paquete SCORM


def _package() -> zipfile.ZipFile:
    exported = ScormPackageExporter().export([approved_activity()], COURSE, UNIT)
    return zipfile.ZipFile(io.BytesIO(exported.content))


def _page() -> str:
    archive = _package()
    return next(archive.read(n).decode() for n in archive.namelist() if n.startswith("sco/"))


def test_the_scorm_page_is_an_activity_with_each_step_and_its_source():
    page = _page()
    assert 'data-kind="activity"' in page
    data = json.loads(re.search(r'id="activity-data">(.*?)</script>', page, re.S).group(1))
    assert data["type"] == "actividad_kinestesica"
    steps = data["structure"]["guidedSteps"]
    assert [step["title"] for step in steps] == [TCP_STEP["title"], UDP_STEP["title"], THIRD_STEP["title"]]
    assert [step["source"] for step in steps] == [
        "apuntes.pdf, p. 1", "apuntes.pdf, p. 2", "apuntes.pdf, p. 1; apuntes.pdf, p. 2",
    ]
    assert "Pregunta de opción múltiple" not in page


def test_the_scorm_page_shows_materials_time_and_space_before_the_steps():
    page = _page()
    for text in ("Tarjetas", "Cinta &lt;adhesiva&gt;", "25 minutos", "Aula &amp; patio"):
        assert text in page, text
    assert "Cinta <adhesiva>" not in page.split('id="activity-data"')[0]
    assert page.index("25 minutos") < page.index('id="activity"')


def test_the_scorm_script_has_a_did_it_checkbox_an_optional_observation_and_completes_with_all_steps():
    assert "actividad_kinestesica: function" in ACTIVITY_JS
    assert "Lo hicimos" in ACTIVITY_JS and "¿Qué observaron?" in ACTIVITY_JS and "checkbox" in ACTIVITY_JS
    # La pregunta del paso es opcional: solo se muestra si existe.
    assert "if (step.question)" in ACTIVITY_JS
    # Se completa cuando todos los pasos están marcados.
    assert "right === checks.length" in ACTIVITY_JS
    # Todo el texto entra con textContent; nada de innerHTML con datos.
    assert "innerHTML" not in ACTIVITY_JS


def test_the_scorm_manifest_is_still_valid_with_the_activity():
    archive = _package()
    names = set(archive.namelist())
    root = ET.fromstring(archive.read("imsmanifest.xml"))
    ns = {"ims": "http://www.imsproject.org/xsd/imscp_rootv1p1p2"}
    assert root.find("ims:metadata/ims:schemaversion", ns).text == "1.2"
    pages = [resource.get("href") for resource in root.findall(".//ims:resource", ns) if resource.get("href")]
    assert pages and all(page in names for page in pages)
    declared = [file.get("href") for file in root.findall(".//ims:file", ns)]
    assert declared and all(name in names for name in declared)
    assert "shared/activity.js" in names
