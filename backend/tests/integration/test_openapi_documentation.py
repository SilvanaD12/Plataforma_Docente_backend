"""Tarea 8: cada operación de la API queda documentada en OpenAPI (Swagger en /docs, ReDoc en /redoc).

Falla mientras a un endpoint le falte resumen, descripción, etiqueta, modelo de respuesta o el 401.
También comprueba que las rutas y las claves del JSON estén en inglés y que docs/api/openapi.json esté al día.
"""

from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from platform5e.main import create_application

SPEC = create_application().openapi()
DECLARED_TAGS = {tag["name"] for tag in SPEC.get("tags", [])}
OPERATIONS = [
    (method.upper(), path, operation)
    for path, operations in SPEC["paths"].items()
    for method, operation in operations.items()
]
FILE_CONTENT = {"application/zip", "application/xml", "application/pdf", "text/plain; charset=utf-8",
                "image/svg+xml", "image/png", "image/jpeg", "audio/mpeg", "audio/wav"}
VERSIONED_SPEC = Path(__file__).resolve().parents[3] / "docs" / "api" / "openapi.json"
SPANISH_SEGMENTS = {"cuentas", "sesiones", "cursos", "documentos", "generaciones", "solicitudes", "unidades",
                    "recursos", "descargas", "resumen", "salud", "ia", "procesar", "fragmentos", "archivo"}


def success_response(operation: dict) -> tuple[str, dict]:
    code = next(c for c in operation["responses"] if c.startswith("2"))
    return code, operation["responses"][code]


@pytest.mark.parametrize("method,path,operation", OPERATIONS, ids=[f"{m} {p}" for m, p, _ in OPERATIONS])
def test_every_operation_is_documented(method: str, path: str, operation: dict):
    problems = []
    if not operation.get("summary"):
        problems.append("falta summary")
    if len(operation.get("description", "")) < 20:
        problems.append("falta la descripción (docstring)")
    if not operation.get("tags") or not set(operation["tags"]) <= DECLARED_TAGS:
        problems.append(f"etiqueta no declarada en openapi_tags: {operation.get('tags')}")
    code, success = success_response(operation)
    content = success.get("content", {})
    if code != "204" and not FILE_CONTENT & set(content):
        schema = content.get("application/json", {}).get("schema", {})
        if "$ref" not in schema and "$ref" not in schema.get("items", {}):
            problems.append(f"la respuesta {code} no tiene response_model")
    if operation.get("security") and "401" not in operation["responses"]:
        problems.append("pide sesión y no documenta el 401")
    assert not problems, f"{method} {path}: " + ", ".join(problems)


def test_api_metadata_and_tags():
    assert SPEC["info"]["title"] == "Platform 5E API" and len(SPEC["info"].get("description", "")) > 100
    assert DECLARED_TAGS == {"accounts", "sessions", "courses", "documents", "generations", "resources", "downloads",
                             "exports", "system", "catalog"}
    assert all(tag.get("description") for tag in SPEC["tags"])


def test_paths_are_english():
    segments = {s for path in SPEC["paths"] for s in re.split(r"[/{}]", path) if s}
    assert not segments & SPANISH_SEGMENTS, f"Rutas en español: {sorted(segments & SPANISH_SEGMENTS)}"


def test_json_keys_are_camel_case():
    snake_case = sorted(
        f"{name}.{field}"
        for name, schema in SPEC["components"]["schemas"].items()
        if name not in {"HTTPValidationError", "ValidationError"}
        for field in schema.get("properties", {})
        if "_" in field
    )
    assert not snake_case, "Claves en snake_case en el JSON: " + ", ".join(snake_case)


def test_versioned_openapi_is_up_to_date():
    """Si falla: desde backend/, `python scripts/export_openapi.py` y subir docs/api/openapi.json."""
    assert json.loads(VERSIONED_SPEC.read_text(encoding="utf-8")) == json.loads(json.dumps(SPEC))
