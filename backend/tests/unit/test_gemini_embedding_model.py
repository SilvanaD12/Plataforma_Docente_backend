"""EN-013 C03: embeddings de Gemini a 768 dimensiones por API, con la fábrica que decide cuándo se usan."""

from __future__ import annotations

import json
import math

import httpx
import pytest

from platform5e.infrastructure.llm.gemini_embedding_model import (
    EMBEDDING_DIMENSIONS,
    MAX_TEXTS_PER_CALL,
    GeminiEmbeddingModel,
    normalize,
)
from platform5e.infrastructure.llm.gemini_language_model import AIProviderError
from platform5e.infrastructure.llm.language_model_factory import create_embedding_generator


def gemini_client(status: int = 200, dimensions: int = EMBEDDING_DIMENSIONS, missing: int = 0):
    """Cliente falso de Gemini que responde un vector [3, 4, 0, …] por texto y guarda cada pedido."""
    requests: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append({"url": str(request.url), "key": request.headers.get("x-goog-api-key"), "body": body})
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "fallo simulado"}})
        vector = [3.0, 4.0] + [0.0] * (dimensions - 2)
        count = len(body["requests"]) - missing
        return httpx.Response(200, json={"embeddings": [{"values": vector} for _ in range(count)]})

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


def test_documents_are_requested_in_one_batch_with_768_dimensions():
    client, requests = gemini_client()
    vectors = GeminiEmbeddingModel("clave", client=client).embed_documents(["TCP es confiable", "UDP es rápido"])

    [sent] = requests
    assert sent["url"].endswith("/models/gemini-embedding-001:batchEmbedContents") and sent["key"] == "clave"
    first = sent["body"]["requests"][0]
    assert first["model"] == "models/gemini-embedding-001"
    assert first["taskType"] == "RETRIEVAL_DOCUMENT" and first["outputDimensionality"] == 768
    assert first["content"]["parts"][0]["text"] == "TCP es confiable"
    assert len(vectors) == 2 and len(vectors[0]) == 768


def test_vectors_are_normalized_to_length_one():
    client, _ = gemini_client()
    [vector] = GeminiEmbeddingModel("clave", client=client).embed_documents(["TCP"])
    assert vector[:2] == pytest.approx([0.6, 0.8]) and math.isclose(math.hypot(*vector), 1.0)
    assert normalize([0.0, 0.0]) == [0.0, 0.0]


def test_more_than_one_hundred_texts_are_split_into_several_calls():
    client, requests = gemini_client()
    vectors = GeminiEmbeddingModel("clave", client=client).embed_documents(["texto"] * (MAX_TEXTS_PER_CALL + 5))
    assert [len(r["body"]["requests"]) for r in requests] == [MAX_TEXTS_PER_CALL, 5] and len(vectors) == 105


def test_a_query_uses_the_retrieval_query_task():
    client, requests = gemini_client()
    vector = GeminiEmbeddingModel("clave", model="otro-modelo", client=client).embed_query("¿qué es TCP?")
    assert requests[0]["body"]["requests"][0]["taskType"] == "RETRIEVAL_QUERY"
    assert "/models/otro-modelo:" in requests[0]["url"] and len(vector) == 768


@pytest.mark.parametrize(
    "client_args,message",
    [
        ({"status": 429}, "límite de uso"),
        ({"status": 400}, "respondió 400"),
        ({"dimensions": 3072}, "otra dimensión"),
        ({"missing": 1}, "1 vectores para 2 textos"),
    ],
)
def test_errors_and_unexpected_vectors_raise_a_clear_error(client_args, message):
    client, _ = gemini_client(**client_args)
    with pytest.raises(AIProviderError, match=message):
        GeminiEmbeddingModel("clave", client=client).embed_documents(["uno", "dos"])


def test_without_connection_the_error_says_so():
    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red")

    model = GeminiEmbeddingModel("clave", client=httpx.Client(transport=httpx.MockTransport(offline)))
    with pytest.raises(AIProviderError, match="sin conexión con Gemini"):
        model.embed_query("TCP")


def test_the_factory_only_creates_embeddings_with_a_gemini_key():
    assert create_embedding_generator({}) is None
    assert create_embedding_generator({"LLM_API_KEY": "k", "LLM_PROVIDER": "rules"}) is None
    assert create_embedding_generator({"LLM_API_KEY": "k", "LLM_PROVIDER": "openai"}) is None
    assert create_embedding_generator({"LLM_API_KEY": "k", "EMBEDDINGS_ENABLED": "false"}) is None
    generator = create_embedding_generator({"LLM_API_KEY": "k", "EMBEDDING_MODEL": "otro-modelo"})
    assert generator is not None and generator.model == "otro-modelo" and generator.dimensions == 768
    assert create_embedding_generator({"LLM_API_KEY": "k"}).model == "gemini-embedding-001"
