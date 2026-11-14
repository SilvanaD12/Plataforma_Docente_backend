"""Revisión del PR #43, por HTTP: notas de multimedia y `embeddingError` guardados con la redacción anterior.

Se generan una imagen y un audio con el generador por reglas (quedan con su nota de respaldo) y después se escribe en
la base, como lo guardaba la versión anterior, el mensaje de Google con la clave y el proyecto. La base no se toca al
leer: la API devuelve la nota y el error sin la clave, sin el valor de «api_key» y sin el mensaje del proveedor.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
from sqlalchemy import create_engine, text

from tests.e2e.test_multimodal_api import generate, setup

API_KEY = "AIzaSy" + "E" * 33
PROJECT = "123456789012"
GOOGLE = f"Permission denied: Consumer 'api_key:{API_KEY}' has been suspended. Project {PROJECT} cannot use this API."
SECRETS = (API_KEY, "AIza", PROJECT, "Consumer", "api_key", "Permission denied")


def _rewrite(database_url: str, table: str, row_id: str, change) -> dict[str, Any]:
    """Cambia la columna JSON `datos` de una fila como la habría guardado la versión anterior."""
    engine = create_engine(database_url)
    cast = "CAST(:datos AS JSON)" if engine.dialect.name == "postgresql" else ":datos"
    try:
        with engine.begin() as connection:
            stored = connection.execute(text(f"SELECT datos FROM {table} WHERE id = :id"), {"id": row_id}).scalar_one()
            data = json.loads(stored) if isinstance(stored, str) else dict(stored)
            change(data)
            connection.execute(text(f"UPDATE {table} SET datos = {cast} WHERE id = :id"),
                               {"id": row_id, "datos": json.dumps(data, ensure_ascii=False)})
    finally:
        engine.dispose()
    return data


def _stored(database_url: str, table: str, row_id: str) -> str:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            stored = connection.execute(text(f"SELECT datos FROM {table} WHERE id = :id"), {"id": row_id}).scalar_one()
    finally:
        engine.dispose()
    return stored if isinstance(stored, str) else json.dumps(stored, ensure_ascii=False)


def test_old_provider_text_is_returned_without_the_key_or_the_provider_message(server: str, e2e_database_url: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        h, unit = setup(api)
        illustration = generate(api, h, unit, "explore", "imagen_ilustrativa")
        podcast = generate(api, h, unit, "explain", "podcast_resumen")
        [document] = [d for d in api.get("/api/v1/documents", headers=h).json() if d["unitId"] == unit["id"]]

        notes = {}
        for resource in (illustration, podcast):
            generic = resource["media"]["note"]  # «Sin imagen generada: …» o «Sin audio generado: …»
            notes[resource["id"]] = generic
            _rewrite(e2e_database_url, "ep002_recursos", resource["id"],
                     lambda data, g=generic: data["media"].update(note=f"{g} (Gemini respondió 403: {GOOGLE})"))
        _rewrite(e2e_database_url, "ep002_documentos", document["id"],
                 lambda data: data.update(embeddingError=f"Gemini respondió 403 en los embeddings: {GOOGLE}"))

        base = f"/api/v1/units/{unit['id']}/resources"
        listed = api.get(base, headers=h)  # la API no tiene GET de un solo recurso: Revisión lee la lista
        documents = api.get("/api/v1/documents", headers=h)

    for response in (listed, documents):
        assert response.status_code == 200, response.text
        for secret in SECRETS:
            assert secret not in response.text, secret
    by_id = {r["id"]: r for r in listed.json()}
    for resource_id, generic in notes.items():
        assert by_id[resource_id]["media"]["note"] == f"{generic} (Gemini respondió 403)"
    [returned] = [d for d in documents.json() if d["id"] == document["id"]]
    assert returned["embeddingError"] == "Gemini respondió 403 en los embeddings"

    # La base no cambia: se oculta al leer.
    assert API_KEY in _stored(e2e_database_url, "ep002_documentos", document["id"])
    assert all(API_KEY in _stored(e2e_database_url, "ep002_recursos", resource_id) for resource_id in notes)
