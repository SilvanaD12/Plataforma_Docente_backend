"""Revisión del PR #43: textos del proveedor guardados antes de la corrección.

Las notas de respaldo de la multimedia y `embeddingError` guardados con la redacción anterior pueden traer el mensaje
de Google («Consumer 'api_key:AIza…'», el número del proyecto). No se cambia la base: al devolverlos, la API oculta las
claves y quita el mensaje del proveedor que sigue a «respondió NNN:», y deja solo la parte genérica.
"""

from __future__ import annotations

import pytest

from platform5e.application.services.provider_errors import sanitize_stored_reason
from platform5e.infrastructure.http.schemas.documents import DocumentResponse
from platform5e.infrastructure.http.schemas.resources import MediaResponse

API_KEY = "AIzaSy" + "D" * 33
PROJECT = "123456789012"
GOOGLE = f"Permission denied: Consumer 'api_key:{API_KEY}' has been suspended. Project {PROJECT} cannot use this API."
IMAGE_NOTE = "Sin imagen generada: se muestra la descripción de la ilustración."
SECRETS = (API_KEY, "AIza", PROJECT, "Consumer", "api_key", "Permission denied")


def assert_safe(text: str) -> None:
    assert not any(secret in text for secret in SECRETS), text


@pytest.mark.parametrize(
    ("stored", "returned"),
    [
        # Nota de la imagen o del audio con la redacción anterior (el detalle iba entre paréntesis).
        (f"{IMAGE_NOTE} (Gemini respondió 403: {GOOGLE})", f"{IMAGE_NOTE} (Gemini respondió 403)"),
        # La redacción anterior recortaba el detalle a 120 caracteres: puede no cerrar el paréntesis del proveedor.
        (f"{IMAGE_NOTE} (Gemini respondió 403: {GOOGLE[:70]})", f"{IMAGE_NOTE} (Gemini respondió 403)"),
        # embeddingError anterior.
        (f"Gemini respondió 403 en los embeddings: {GOOGLE}", "Gemini respondió 403 en los embeddings"),
        # Otro proveedor del adaptador de texto.
        (f"OpenAI respondió 401: Incorrect API key provided: api_key:sk-prueba", "OpenAI respondió 401"),
    ],
    ids=["nota", "nota-recortada", "embeddings", "otro-proveedor"],
)
def test_old_wording_keeps_only_the_generic_part(stored, returned):
    assert sanitize_stored_reason(stored) == returned
    assert_safe(sanitize_stored_reason(stored))


@pytest.mark.parametrize(
    "text",
    [
        f"{IMAGE_NOTE} (Gemini respondió 403)",
        "Sin audio generado: el guion se escucha con la voz del navegador. (límite de uso de Gemini alcanzado (429). "
        "Espera un minuto.)",
        "Gemini respondió 403 en los embeddings",
        "error del proveedor: ConnectionError",
        "Cambiaste la descripción: la imagen anterior ya no se usa.",
    ],
)
def test_text_that_is_already_safe_is_returned_unchanged(text):
    assert sanitize_stored_reason(text) == text


def test_a_key_outside_the_provider_message_is_still_hidden():
    assert sanitize_stored_reason(f"{IMAGE_NOTE} (clave {API_KEY})") == f"{IMAGE_NOTE} (clave [clave oculta])"


def test_the_media_response_returns_the_old_note_without_the_provider_text():
    media = MediaResponse.model_validate({"status": "fallback", "note": f"{IMAGE_NOTE} (Gemini respondió 403: {GOOGLE})"})
    assert media.note == f"{IMAGE_NOTE} (Gemini respondió 403)"
    assert MediaResponse.model_validate({"status": "fallback", "note": None}).note is None


def test_the_document_response_returns_the_old_embedding_error_without_the_provider_text():
    document = DocumentResponse.model_validate({
        "id": "doc-1", "fileName": "tcp.txt", "kind": "txt", "sizeBytes": 10, "unitId": "u1", "documentType": "x",
        "status": "procesado", "registeredAt": "2026-11-14T00:00:00+00:00",
        "embeddingError": f"Gemini respondió 403 en los embeddings: {GOOGLE}",
    })
    assert document.embedding_error == "Gemini respondió 403 en los embeddings"
    assert_safe(document.model_dump_json(by_alias=True))
