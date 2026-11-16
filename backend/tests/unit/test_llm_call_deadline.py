"""QA-06: ninguna llamada a Gemini queda colgada más del tiempo límite (60 s como máximo).

El timeout de httpx se aplica a cada lectura, no a la llamada completa: un proveedor que envía la respuesta de a poco
nunca lo dispara. Aquí un transporte falso «gotea» bytes (cada lectura tarda menos que el timeout de httpx) y la
llamada completa supera el tiempo límite: debe terminar dentro del límite más un margen pequeño, con el respaldo de
siempre y un motivo genérico. Sin red. Límite corto (0,3 s) para que las pruebas sean rápidas.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import httpx
import pytest

from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.application.services.generation.step_drafting import draft_resources
from platform5e.application.services.media.media_attachment import generate_media
from platform5e.infrastructure.llm.call_deadline import DEFAULT_CALL_DEADLINE_SECONDS, MAX_CALL_DEADLINE_SECONDS
from platform5e.infrastructure.llm.gemini_embedding_model import GeminiEmbeddingModel
from platform5e.infrastructure.llm.gemini_language_model import AIProviderError, GeminiLanguageModel
from platform5e.infrastructure.llm.gemini_media_generator import GeminiMediaGenerator
from platform5e.infrastructure.llm.language_model_factory import (
    create_embedding_generator,
    create_generators,
    create_media_generator,
)
from platform5e.infrastructure.settings import llm_call_deadline_seconds, llm_read_timeout_seconds
from tests.unit.test_kinesthetic_activity import context

DEADLINE = 0.3
MARGIN = 0.25  # lo que puede tardar en devolver el control después del límite
REASON = "Gemini no respondió en 0,3 s"


class TrickleStream(httpx.SyncByteStream):
    """Cuerpo que llega de a poco: un trozo cada 50 ms durante `total` segundos. Cada lectura es corta."""

    def __init__(self, total: float = 5.0, body: bytes = b'{"candidates": []}') -> None:
        self.total, self.body = total, body
        self.closed = threading.Event()

    def __iter__(self):
        started = time.monotonic()
        while time.monotonic() - started < self.total:
            time.sleep(0.05)
            yield b" "
        yield self.body

    def close(self) -> None:
        self.closed.set()


class SlowProvider:
    """Transporte falso: cada pedido recibe la siguiente respuesta de la lista; `None` es una respuesta que gotea."""

    def __init__(self, *answers: dict[str, Any] | None) -> None:
        self.answers = list(answers) or [None]
        self.streams: list[TrickleStream] = []
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        answer = self.answers.pop(0) if self.answers else None
        if answer is not None:
            return httpx.Response(200, json=answer)
        stream = TrickleStream()
        self.streams.append(stream)
        return httpx.Response(200, headers={"content-type": "application/json"}, stream=stream)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self), timeout=10)


def gemini(provider: SlowProvider) -> GeminiLanguageModel:
    return GeminiLanguageModel("gemini", "clave-de-prueba", model="gemini-3.5-flash-lite", client=provider.client(),
                               call_deadline_seconds=DEADLINE)


# Configuración


@pytest.mark.parametrize(
    ("value", "expected"),
    [("", 60.0), ("30", 30.0), ("0.5", 0.5), ("120", 60.0), ("0", 60.0), ("-5", 60.0), ("mucho", 60.0)],
)
def test_the_call_deadline_is_at_most_60_seconds(value, expected):
    assert DEFAULT_CALL_DEADLINE_SECONDS == MAX_CALL_DEADLINE_SECONDS == 60
    assert llm_call_deadline_seconds({"LLM_CALL_DEADLINE_SECONDS": value}) == expected


def test_llm_timeout_seconds_cannot_go_above_the_call_deadline():
    assert llm_read_timeout_seconds(90.0, {"LLM_TIMEOUT_SECONDS": "120"}) == 60.0
    assert llm_read_timeout_seconds(90.0, {}) == 60.0  # el valor por defecto de antes (90) también se recorta
    assert llm_read_timeout_seconds(90.0, {"LLM_TIMEOUT_SECONDS": "30"}) == 30.0
    assert llm_read_timeout_seconds(90.0, {"LLM_TIMEOUT_SECONDS": "40", "LLM_CALL_DEADLINE_SECONDS": "20"}) == 20.0
    assert llm_read_timeout_seconds(90.0, {"LLM_TIMEOUT_SECONDS": "no"}) == 60.0


def test_the_factory_gives_every_gemini_adapter_the_deadline_and_a_capped_timeout():
    environment = {"LLM_PROVIDER": "gemini", "LLM_API_KEY": "k", "LLM_TIMEOUT_SECONDS": "120",
                   "LLM_CALL_DEADLINE_SECONDS": "45"}
    primary, _ = create_generators(environment)
    adapters = [primary, create_media_generator(environment), create_embedding_generator(environment)]
    for adapter in adapters:
        assert adapter.call_deadline_seconds == 45.0
        assert adapter._client.timeout.read == 45.0


# Texto


def test_a_trickling_text_answer_ends_at_the_deadline_with_a_generic_reason():
    provider = SlowProvider(None)
    with pytest.raises(AIProviderError) as error:
        gemini(provider).generate(context())
    assert error.value.public_reason == REASON
    assert "no respondió en 0,3 s" in str(error.value)
    assert provider.calls == 1  # sin tiempo, no hay reintento
    assert provider.streams[0].closed.wait(1.0)  # la lectura de fondo también se detiene


def test_the_call_ends_within_the_deadline_plus_a_small_margin():
    provider = SlowProvider(None)
    started = time.monotonic()
    with pytest.raises(AIProviderError):
        gemini(provider).generate(context())
    assert time.monotonic() - started < DEADLINE + MARGIN


def test_the_retry_after_invalid_json_shares_the_same_deadline():
    invalid = {"candidates": [{"content": {"parts": [{"text": "esto no es json"}]}, "finishReason": "STOP"}]}
    provider = SlowProvider(invalid, None)
    started = time.monotonic()
    with pytest.raises(AIProviderError) as error:
        gemini(provider).generate(context())
    assert provider.calls == 2 and error.value.public_reason == REASON
    assert time.monotonic() - started < DEADLINE + MARGIN


def test_the_step_falls_back_to_the_rules_with_the_reason():
    provider = SlowProvider(None)
    started = time.monotonic()
    _, generator, warning = draft_resources(context(), gemini(provider), RuleBasedGenerator(), [])
    # Redactó el generador por reglas (con los dos fragmentos de prueba puede no alcanzar para la actividad).
    assert isinstance(generator, RuleBasedGenerator)
    assert warning == f"Gemini · gemini-3.5-flash-lite no respondió ({REASON}). Se usó el generador por reglas."
    assert time.monotonic() - started < DEADLINE + MARGIN + 1.0  # más lo que tarda el generador por reglas


def test_a_fast_answer_is_not_affected():
    valid = {"recursos": []}
    answer = {"candidates": [{"content": {"parts": [{"text": json.dumps(valid)}]}, "finishReason": "STOP"}]}
    assert gemini(SlowProvider(answer)).generate(context()) == valid


# Imagen y voz


@pytest.mark.parametrize(
    ("resource", "note"),
    [
        ({"id": "r-img", "format": "image", "structure": {"prompt": "Una red"}},
         f"Sin imagen generada: se muestra la descripción de la ilustración. ({REASON})"),
        ({"id": "r-audio", "format": "audio", "structure": {"script": "Hola, clase."}},
         f"Sin audio generado: el guion se escucha con la voz del navegador. ({REASON})"),
    ],
    ids=["imagen", "voz"],
)
def test_a_trickling_media_answer_falls_back_with_the_reason(resource, note):
    provider = SlowProvider(None)
    media = GeminiMediaGenerator("clave-de-prueba", client=provider.client(), call_deadline_seconds=DEADLINE)
    started = time.monotonic()
    assert generate_media(resource, media) is None
    assert time.monotonic() - started < DEADLINE + MARGIN
    assert resource["media"] == {"status": "fallback", "note": note}


# Embeddings


def test_a_trickling_embedding_answer_ends_at_the_deadline_with_the_reason():
    provider = SlowProvider(None)
    model = GeminiEmbeddingModel("clave-de-prueba", client=provider.client(), call_deadline_seconds=DEADLINE)
    started = time.monotonic()
    with pytest.raises(AIProviderError) as error:
        model.embed_documents(["Texto del material."])
    assert time.monotonic() - started < DEADLINE + MARGIN
    assert error.value.public_reason == "Gemini no respondió en 0,3 s en los embeddings"
