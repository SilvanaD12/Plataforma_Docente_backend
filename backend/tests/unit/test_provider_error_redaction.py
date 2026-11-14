"""Revisión del PR #43 (seguridad): los errores del proveedor de IA no llegan al docente con el texto de Google.

`steps[].generator.fallbackReason`, las notas de respaldo de la multimedia y `embeddingError` se guardan y la API los
devuelve a cualquier docente, y en la demo cualquiera puede crear una cuenta. Un 403 de Google puede traer
«Consumer 'api_key:AIza…'» y el número del proyecto. Lo guardado y lo devuelto lleva solo un motivo genérico; el
detalle va al registro del servidor (WARNING), con la clave oculta. Sin red: respuestas HTTP falsas.
"""

from __future__ import annotations

import logging

import httpx
import pytest

from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.application.services.media.media_attachment import generate_media
from platform5e.application.services.provider_errors import public_reason, redact_secrets
from platform5e.application.services.materials.chunk_embedding_service import ChunkEmbeddingService
from platform5e.infrastructure.llm.gemini_embedding_model import GeminiEmbeddingModel
from platform5e.infrastructure.llm.gemini_language_model import AIProviderError, GeminiLanguageModel
from platform5e.infrastructure.llm.gemini_media_generator import GeminiMediaGenerator
from tests.unit.test_chunk_embedding_service import VectorChunkRepository
from tests.unit.test_kinesthetic_fallback import run
from tests.unit.test_material_service import build_test_environment
from tests.unit.test_start_regeneration import Setup
from tests.unit.test_kinesthetic_activity import _corpus_fragments

API_KEY = "AIzaSy" + "B" * 33  # forma de una clave de Google: AIza y 35 caracteres más
PROJECT = "123456789012"
GOOGLE_403 = {
    "error": {
        "code": 403,
        "message": f"Permission denied: Consumer 'api_key:{API_KEY}' has been suspended. "
                   f"Project {PROJECT} (projects/{PROJECT}) cannot use this API.",
        "status": "PERMISSION_DENIED",
    }
}
SECRETS = (API_KEY, "AIza", PROJECT, "Consumer", "api_key:")


def forbidden(request: httpx.Request) -> httpx.Response:
    return httpx.Response(403, json=GOOGLE_403)


def assert_safe(text: str) -> None:
    assert not any(secret in text for secret in SECRETS), text


def warning_lines(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]


# Ayuda única de ocultamiento


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"key={API_KEY}&alt=json", "key=[clave oculta]&alt=json"),
        (f"Consumer 'api_key:{API_KEY}' suspended", "Consumer 'api_key:[clave oculta]' suspended"),
        ("Consumer 'api_key:otra-clave_123' suspended", "Consumer 'api_key:[clave oculta]' suspended"),
        ("sin datos sensibles", "sin datos sensibles"),
    ],
)
def test_the_redaction_helper_hides_google_keys_and_api_key_tokens(text, expected):
    assert redact_secrets(text) == expected


def test_a_provider_error_keeps_its_detail_redacted_and_a_generic_public_reason():
    error = AIProviderError(f"Gemini respondió 403: {GOOGLE_403['error']['message']}", 403)
    assert API_KEY not in str(error) and "[clave oculta]" in str(error) and PROJECT in str(error)
    assert public_reason(error) == "el proveedor respondió 403"  # sin public_reason explícito: genérico
    assert public_reason(AIProviderError("detalle", 403, public_reason="Gemini respondió 403")) == "Gemini respondió 403"
    assert public_reason(TimeoutError(f"api_key:{API_KEY}")) == "error del proveedor: TimeoutError"


# fallbackReason: guardado en el paso y devuelto por la API


@pytest.fixture
def setup(tmp_path) -> Setup:
    setup = Setup(tmp_path)
    setup.evidence.fragments = _corpus_fragments()
    return setup


def gemini(handler) -> GeminiLanguageModel:
    return GeminiLanguageModel("gemini", "clave-de-prueba", model="gemini-3.5-flash-lite",
                               client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_a_403_with_the_key_gives_a_generic_fallback_reason_and_a_redacted_log(setup, caplog):
    with caplog.at_level(logging.WARNING):
        finished = run(setup, gemini(forbidden), RuleBasedGenerator(), "clave-403")
    [step] = finished.steps  # leído de la base
    assert step.generator["fallbackReason"] == (
        "Gemini · gemini-3.5-flash-lite no respondió (Gemini respondió 403). Se usó el generador por reglas."
    )
    assert_safe(repr(step.generator))
    assert_safe(repr(step.rejections))

    detail = [line for line in warning_lines(caplog) if "Permission denied" in line]
    assert detail and all(API_KEY not in line and "api_key:[clave oculta]" in line for line in detail)


@pytest.mark.parametrize(
    ("handler", "reason"),
    [
        (lambda request: httpx.Response(429, json={"error": {"message": f"Quota for api_key:{API_KEY}"}}),
         "límite de uso de Gemini alcanzado (429). Espera un minuto."),
        (lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("tiempo agotado", request=request)),
         "sin conexión con Gemini: ReadTimeout"),
    ],
    ids=["429", "timeout"],
)
def test_429_and_timeout_keep_their_safe_wording(setup, handler, reason):
    [step] = run(setup, gemini(handler), RuleBasedGenerator(), f"clave-proveedor-{len(reason)}").steps
    assert step.generator["fallbackReason"] == (
        f"Gemini · gemini-3.5-flash-lite no respondió ({reason}). Se usó el generador por reglas."
    )
    assert_safe(step.generator["fallbackReason"])


# Multimedia: nota de respaldo de la imagen y del audio


@pytest.mark.parametrize(
    ("resource", "note"),
    [
        ({"id": "r-img", "format": "image", "structure": {"prompt": "Una red"}},
         "Sin imagen generada: se muestra la descripción de la ilustración. (Gemini respondió 403)"),
        ({"id": "r-audio", "format": "audio", "structure": {"script": "Hola, clase."}},
         "Sin audio generado: el guion se escucha con la voz del navegador. (Gemini respondió 403)"),
    ],
    ids=["imagen", "audio"],
)
def test_the_media_fallback_note_is_generic_and_the_log_is_redacted(resource, note, caplog):
    media = GeminiMediaGenerator("clave-de-prueba", client=httpx.Client(transport=httpx.MockTransport(forbidden)))
    with caplog.at_level(logging.WARNING):
        assert generate_media(resource, media) is None
    assert resource["media"] == {"status": "fallback", "note": note}
    [line] = [line for line in warning_lines(caplog) if "Medio no generado" in line]
    assert "Permission denied" in line and API_KEY not in line and "api_key:[clave oculta]" in line


# Embeddings: embeddingError del documento


def test_the_embedding_error_of_a_document_is_generic(caplog):
    service, config_repo, chunk_repo = build_test_environment()
    embedder = GeminiEmbeddingModel("clave-de-prueba", client=httpx.Client(transport=httpx.MockTransport(forbidden)))
    service._embedding_service = ChunkEmbeddingService(VectorChunkRepository(chunk_repo), embedder)
    with caplog.at_level(logging.WARNING):
        data = service.process_material("d", "doc1")
    assert data["status"] == "procesado" and data["embeddingError"] == "Gemini respondió 403 en los embeddings"
    assert config_repo.docs["doc1"][0]["embeddingError"] == "Gemini respondió 403 en los embeddings"
    [line] = [line for line in warning_lines(caplog) if "embeddings" in line]
    assert "Permission denied" in line and API_KEY not in line

