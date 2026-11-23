"""REV-P2 · Pruebas unitarias de estructura y validación de paquete SCORM 1.2 (REV-R14)."""

import io
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Mapping
from typing import Any

import pytest

from platform5e.infrastructure.exporters.scorm_package_exporter import (
    ScormPackageExporter,
    build_scorm_pages,
)

COURSE = {"code": "CC-101", "name": "Algoritmos"}
UNIT = {"number": 1, "title": "Introducción"}


def _sample_resources() -> list[dict[str, Any]]:
    return [
        {
            "id": "rec-1",
            "type": "explicacion",
            "stage": "explain",
            "title": "Explicación de memoria caché",
            "body": "La memoria caché es rápida y almacena datos de uso frecuente.\n\nReduce la latencia del procesador.",
            "status": "aprobado",
            "createdAt": "2026-11-20T10:00:00Z",
            "evidence": [{"documentName": "separata.pdf", "location": "p. 5"}],
        },
        {
            "id": "rec-2",
            "type": "imagen_ilustrativa",
            "stage": "explore",
            "title": "Diagrama de jerarquía de memoria",
            "body": "Observa la jerarquía de memorias.",
            "structure": {
                "prompt": "Pirámide con registros, caché, RAM y disco.",
                "alt": "Pirámide de jerarquía de memoria",
                "caption": "Jerarquía clásica de memorias en arquitectura de computadoras.",
            },
            "status": "aprobado",
            "createdAt": "2026-11-20T09:00:00Z",
            "evidence": [{"documentName": "separata.pdf", "location": "p. 3"}],
        },
        {
            "id": "rec-3",
            "type": "item_opcion_multiple",
            "stage": "evaluate",
            "title": "Pregunta sobre latencia de caché",
            "body": "¿Cuál de las siguientes memorias tiene menor tiempo de acceso?",
            "options": [
                {"id": "opt-1", "text": "Registros del procesador", "isCorrect": True, "decision": "aceptado"},
                {"id": "opt-2", "text": "Disco rígido magnético", "isCorrect": False, "decision": "aceptado"},
                {"id": "opt-3", "text": "Memoria principal RAM", "isCorrect": False, "decision": "aceptado"},
            ],
            "status": "aprobado",
            "createdAt": "2026-11-20T11:00:00Z",
            "evidence": [{"documentName": "separata.pdf", "location": "p. 8"}],
        },
    ]


def test_scorm_package_structure_and_manifest_validity():
    exporter = ScormPackageExporter()
    resources = _sample_resources()

    exported = exporter.export(resources, COURSE, UNIT)
    assert exported.media_type == "application/zip"
    assert exported.file_name == "cc-101-unidad-1-scorm.zip"

    with zipfile.ZipFile(io.BytesIO(exported.content), "r") as zf:
        file_names = set(zf.namelist())
        assert "imsmanifest.xml" in file_names
        assert "shared/scorm.js" in file_names
        assert "shared/style.css" in file_names

        # 1. Validar XML de imsmanifest.xml
        manifest_bytes = zf.read("imsmanifest.xml")
        root = ET.fromstring(manifest_bytes)
        assert root.tag.endswith("manifest")

        ns = {
            "imscp": "http://www.imsproject.org/xsd/imscp_rootv1p1p2",
            "adlcp": "http://www.adlnet.org/xsd/adlcp_rootv1p2",
        }

        # 2. Unicidad de identificadores
        item_ids = [elem.attrib["identifier"] for elem in root.findall(".//imscp:item", ns)]
        assert len(item_ids) == len(set(item_ids)), "Item identifiers must be unique"

        res_ids = [elem.attrib["identifier"] for elem in root.findall(".//imscp:resource", ns)]
        assert len(res_ids) == len(set(res_ids)), "Resource identifiers must be unique"

        # 3. Referencias biunívocas:
        # Cada resource href debe existir en el zip
        resource_hrefs = [
            elem.attrib["href"] for elem in root.findall(".//imscp:resource", ns) if "href" in elem.attrib
        ]
        for href in resource_hrefs:
            assert href in file_names, f"Manifest resource href '{href}' not found in zip"

        # Todos los archivos declarados en <file href="..."> deben existir en el zip
        file_hrefs = {elem.attrib["href"] for elem in root.findall(".//imscp:file", ns)}
        for href in file_hrefs:
            assert href in file_names, f"Manifest file href '{href}' not found in zip"

        # Todo archivo en el zip (excepto imsmanifest.xml) debe estar declarado en el manifiesto
        zip_non_manifest = file_names - {"imsmanifest.xml"}
        assert zip_non_manifest == file_hrefs, f"Undeclared files in zip: {zip_non_manifest - file_hrefs}"

        # 4. Orden de ítems coincide con etapas 5E (explore -> explain -> evaluate)
        item_titles = [
            elem.find("imscp:title", ns).text for elem in root.findall(".//imscp:item", ns)  # type: ignore
        ]
        # explore es la imagen, explain es la explicacion, evaluate es la evaluacion
        assert "Diagrama de jerarquía de memoria" in item_titles[0]
        assert "Explicación de memoria caché" in item_titles[1]
        assert "Evaluación por niveles" in item_titles[2]

        # 5. Seguridad en páginas HTML: scripts permitidos y sin manejadores inline
        inline_event_handler_regex = re.compile(r"\son\w+\s*=", re.IGNORECASE)
        allowed_scripts = {
            "../shared/scorm.js",
            "../shared/activity.js",
            "../shared/quiz.js",
        }

        for fname in file_names:
            if fname.endswith(".html"):
                html_content = zf.read(fname).decode("utf-8")
                # Sin manejadores on*=
                assert not inline_event_handler_regex.search(
                    html_content
                ), f"Inline event handler found in {fname}"

                # Scripts en script tags
                script_srcs = re.findall(r'<script\s+[^>]*src=["\']([^"\']+)["\']', html_content)
                for src in script_srcs:
                    assert src in allowed_scripts, f"Unauthorized script src '{src}' in {fname}"


def test_build_scorm_pages_returns_rendered_pages_and_order():
    resources = _sample_resources()
    pages = build_scorm_pages(resources)
    assert len(pages) == 3

    page_numbers = [p[0] for p in pages]
    assert page_numbers == [1, 2, 3]

    titles = [p[1] for p in pages]
    assert titles[0] == "Diagrama de jerarquía de memoria"
    assert titles[1] == "Explicación de memoria caché"
    assert titles[2] == "Evaluación por niveles"

    for _, _, html_content in pages:
        assert "<!doctype html>" in html_content
        assert "scorm5e" in html_content


def test_guided_exploration_with_empty_body_does_not_leak_fragment_ids_or_paragraphs():
    guided_resource = {
        "id": "rec-guided",
        "type": "exploracion_guiada",
        "stage": "explore",
        "title": "Exploración de la memoria caché",
        "body": "",
        "structure": {
            "prompt": "Explora los pasos de acceso a caché.",
            "guidedSteps": [
                {
                    "stepNumber": 1,
                    "title": "Paso 1: Consulta inicial",
                    "instruction": "Verifica si el dato está en caché L1.",
                    "fragmentIds": ["frag-123-abc", "frag-456-def"],
                }
            ],
        },
        "status": "aprobado",
        "createdAt": "2026-11-20T10:00:00Z",
        "evidence": [
            {"id": "frag-123-abc", "documentName": "separata.pdf", "location": "p. 5"},
            {"id": "frag-456-def", "documentName": "separata.pdf", "location": "p. 6"},
        ],
    }
    exporter = ScormPackageExporter()
    exported = exporter.export([guided_resource], COURSE, UNIT)
    with zipfile.ZipFile(io.BytesIO(exported.content), "r") as zf:
        html_content = zf.read("sco/01.html").decode("utf-8")
        assert "<p>frag-" not in html_content
        outside_json = re.sub(
            r'<script\s+type="application/json"[^>]*>.*?</script>', "", html_content, flags=re.DOTALL
        )
        assert "frag-123-abc" not in outside_json
        assert "frag-456-def" not in outside_json


def test_build_scorm_pages_inlines_assets_for_preview():
    from platform5e.infrastructure.exporters.scorm_package_exporter import ACTIVITY_JS

    resources = _sample_resources()
    pages = build_scorm_pages(resources)
    assert len(pages) == 3

    for _, _, html_content in pages:
        assert "../shared/" not in html_content
        assert 'src="../' not in html_content
        assert "<style>" in html_content

    # Página 1 es una imagen: debe contener data:image/ (B3)
    image_page = pages[0][2]
    assert "data:image/" in image_page

    # Página interactiva: debe incrustar ACTIVITY_JS
    interactive_resource = {
        "id": "rec-activity",
        "type": "reto_prediccion",
        "stage": "engage",
        "title": "Reto inicial",
        "body": "Predice el resultado",
        "structure": {"predictions": []},
        "status": "aprobado",
        "createdAt": "2026-11-20T08:00:00Z",
    }
    activity_pages = build_scorm_pages([interactive_resource])
    assert ACTIVITY_JS.strip() in activity_pages[0][2]


def test_exported_zip_preserves_relative_paths_and_content():
    exporter = ScormPackageExporter()
    resources = _sample_resources()
    exported = exporter.export(resources, COURSE, UNIT)
    with zipfile.ZipFile(io.BytesIO(exported.content), "r") as zf:
        manifest = zf.read("imsmanifest.xml").decode("utf-8")
        sco1 = zf.read("sco/01.html").decode("utf-8")

        assert '<link rel="stylesheet" href="../shared/style.css">' in sco1
        assert '<script src="../shared/scorm.js"></script>' in sco1
        assert 'src="../media/01.svg"' in sco1
        assert "data:image/" not in sco1
        assert "ADL SCORM" in manifest
        assert '<file href="sco/01.html"/>' in manifest
