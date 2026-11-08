"""Paquete SCORM 1.2 para Chamilo: manifiesto en la raíz, SCO en orden 5E y sin distractores descartados.

Los ítems de opción múltiple van juntos en el SCO «Evaluación por niveles» (HU-051).
"""
import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile

from platform5e.infrastructure.exporters.scorm_package_exporter import ScormPackageExporter

NS = {"cp": "http://www.imsproject.org/xsd/imscp_rootv1p1p2", "adlcp": "http://www.adlnet.org/xsd/adlcp_rootv1p2"}
COURSE = {"code": "RED-301"}
UNIT = {"number": 2, "title": "Capa de transporte"}
QUESTION = {
    "id": "r2", "stage": "evaluate", "title": "TCP o UDP", "createdAt": "2026-10-10T10:00", "body": "¿Cuál tiene menos retardo?",
    "options": [
        {"id": "a", "text": "UDP", "isCorrect": True, "feedback": "No espera confirmaciones.", "decision": "pendiente"},
        {"id": "b", "text": "TCP <confiable>", "isCorrect": False, "feedback": "Retransmite.", "decision": "aceptado"},
        {"id": "c", "text": "ICMP", "isCorrect": False, "feedback": "", "decision": "descartado"},
    ],
    "evidence": [{"documentName": "protocolos.pdf", "location": "p. 3"}],
}
TRIGGER = {"id": "r1", "stage": "engage", "title": "¿Por qué se corta una llamada?", "createdAt": "2026-10-10T09:00",
           "body": "Piensa en tu última videollamada.", "options": None, "evidence": []}


def package(resources):
    exported = ScormPackageExporter().export(resources, COURSE, UNIT)
    return exported, zipfile.ZipFile(io.BytesIO(exported.content))


def test_manifest_at_root_with_scos_in_5e_order():
    exported, archive = package([QUESTION, TRIGGER])
    assert exported.file_name == "red-301-unidad-2-scorm.zip" and exported.media_type == "application/zip"
    assert archive.namelist()[0] == "imsmanifest.xml"
    root = ET.fromstring(archive.read("imsmanifest.xml"))
    default = root.find("cp:organizations", NS).get("default")
    items = root.findall(f"cp:organizations/cp:organization[@identifier='{default}']/cp:item", NS)
    resources = {r.get("identifier"): r for r in root.findall("cp:resources/cp:resource", NS)}
    assert [i.find("cp:title", NS).text for i in items] == ["¿Por qué se corta una llamada?", "Evaluación por niveles"]
    for item in items:
        sco = resources[item.get("identifierref")]
        assert sco.get(f"{{{NS['adlcp']}}}scormtype") == "sco" and sco.get("href") in archive.namelist()
    for resource in resources.values():
        assert all(f.get("href") in archive.namelist() for f in resource.findall("cp:file", NS))


def test_question_page_grades_and_leaves_out_discarded_distractors():
    _, archive = package([QUESTION])
    page = archive.read("sco/01.html").decode()
    assert 'data-kind="quiz"' in page and "ICMP" not in page
    assert "TCP &lt;confiable&gt;" in page and page.count('data-correct="true"') == 1
    assert "protocolos.pdf, p. 3" in page


def test_same_resources_give_the_same_file():
    assert package([QUESTION, TRIGGER])[0].content == package([QUESTION, TRIGGER])[0].content


def _item(item_id, title, difficulty=None, created="2026-10-10T11:00"):
    item = {**QUESTION, "id": item_id, "title": title, "createdAt": created}
    return {**item, "params": {"difficulty": difficulty}} if difficulty else item


def test_multiple_choice_items_become_one_leveled_quiz_with_points_and_badges():
    """HU-051 C01: los ítems se presentan por niveles, con puntaje, cronómetro e insignia."""
    trivia = {"id": "r9", "stage": "evaluate", "type": "verdadero_falso", "title": "Verdadero o falso",
              "createdAt": "2026-10-10T10:30", "body": "", "options": None, "evidence": [],
              "structure": {"statements": [{"text": "UDP confirma", "isTrue": False}]}}
    resources = [
        _item("q3", "Ventana deslizante", "avanzada", "2026-10-10T10:00"),
        trivia,
        _item("q1", "Puertos", "basica", "2026-10-10T11:00"),
        _item("q2", "Sin dificultad", None, "2026-10-10T12:00"),
        TRIGGER,
    ]
    _, archive = package(resources)
    root = ET.fromstring(archive.read("imsmanifest.xml"))
    titles = [i.find("cp:title", NS).text for i in root.iter(f"{{{NS['cp']}}}item")]
    assert titles == ["¿Por qué se corta una llamada?", "Evaluación por niveles", "Verdadero o falso"]
    shared = root.find("cp:resources/cp:resource[@identifier='SHARED']", NS)
    assert "shared/quiz.js" in [f.get("href") for f in shared.findall("cp:file", NS)]
    assert "shared/quiz.js" in archive.namelist()

    page = archive.read("sco/02.html").decode()
    assert re.findall(r"<h2>(Nivel [^<]+?) <span", page) == ["Nivel 1 · Básico", "Nivel 2 · Intermedio", "Nivel 3 · Avanzado"]
    assert re.findall(r'data-points="(\d+)"', page) == ["10", "20", "30"]
    assert re.findall(r"<h3>Pregunta \d+\. ([^<]+)</h3>", page) == ["Puertos", "Sin dificultad", "Ventana deslizante"]
    assert "Puntaje <strong id=\"quiz-score\">0</strong> de 60" in page and 'id="quiz-clock"' in page
    first_level, locked_levels = page.split('data-level="2"')[0], page.split('data-level="2"')[1]
    assert " disabled" not in first_level.split('data-level="1"')[1]  # el nivel 1 se puede responder
    assert locked_levels.count('type="radio"') == locked_levels.count(" disabled") - 2  # los demás, bloqueados
    config = json.loads(re.search(r'id="quiz-data">(.+?)</script>', page).group(1))
    assert config == {"total": 60, "passing": 60, "badges": [[90, "Oro"], [75, "Plata"], [60, "Bronce"]]}


def test_scorm_api_records_the_session_time():
    _, archive = package([QUESTION])
    assert "cmi.core.session_time" in archive.read("shared/scorm.js").decode()
    assert "window.scorm5e.time(seconds)" in archive.read("shared/quiz.js").decode()
