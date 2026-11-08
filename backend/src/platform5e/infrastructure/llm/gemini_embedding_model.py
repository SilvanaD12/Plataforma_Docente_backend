"""
Embeddings con la API de Gemini (EN-013): 768 dimensiones, sin modelo local (Render gratuito tiene 512 MB).

Usa `batchEmbedContents` para pedir hasta 100 textos por llamada. Con menos de 3072 dimensiones Gemini no
devuelve vectores normalizados, así que aquí se normalizan: la distancia coseno de pgvector los compara bien igual,
pero normalizados también sirven para el producto interno.
"""

from __future__ import annotations

import math
from typing import Any

import httpx

from platform5e.application.ports.outbound.embedding_port import EmbeddingGeneratorPort
from platform5e.infrastructure.llm.gemini_language_model import AIProviderError

DEFAULT_EMBEDDING_MODEL: str = "gemini-embedding-001"
EMBEDDING_DIMENSIONS: int = 768  # la columna ep002_fragmentos.embedding es vector(768)
GEMINI_BASE_URL: str = "https://generativelanguage.googleapis.com/v1beta"
MAX_TEXTS_PER_CALL: int = 100
MAX_TEXT_CHARS: int = 8000  # ~2000 tokens, el máximo de entrada del modelo


def normalize(vector: list[float]) -> list[float]:
    """Vector de largo 1 (si es todo ceros, se devuelve igual)."""
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


class GeminiEmbeddingModel(EmbeddingGeneratorPort):
    """Adaptador de EmbeddingGeneratorPort con la API REST de Gemini."""

    dimensions: int = EMBEDDING_DIMENSIONS

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model or DEFAULT_EMBEDDING_MODEL
        self._api_key = api_key
        self._base_url = (base_url or GEMINI_BASE_URL).rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), MAX_TEXTS_PER_CALL):
            vectors += self._embed(texts[start : start + MAX_TEXTS_PER_CALL], "RETRIEVAL_DOCUMENT")
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "RETRIEVAL_QUERY")[0]

    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        if not texts:
            return []
        payload: dict[str, Any] = {
            "requests": [
                {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": text[:MAX_TEXT_CHARS]}]},
                    "taskType": task_type,
                    "outputDimensionality": self.dimensions,
                }
                for text in texts
            ]
        }
        try:
            response = self._client.post(
                f"{self._base_url}/models/{self.model}:batchEmbedContents",
                headers={"Content-Type": "application/json", "x-goog-api-key": self._api_key},
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise AIProviderError(f"sin conexión con Gemini (embeddings): {exc.__class__.__name__}") from exc

        if response.status_code >= 400:
            if response.status_code == 429:
                raise AIProviderError("límite de uso de Gemini alcanzado en los embeddings (429).", 429)
            try:
                detail = response.json().get("error", {}).get("message", "")
            except (ValueError, AttributeError):
                detail = response.text[:200]
            raise AIProviderError(
                f"Gemini respondió {response.status_code} en los embeddings: {str(detail)[:200]}",
                response.status_code,
            )

        embeddings = response.json().get("embeddings") or []
        vectors = [item.get("values") or [] for item in embeddings]
        if len(vectors) != len(texts) or any(len(vector) != self.dimensions for vector in vectors):
            raise AIProviderError(
                f"Gemini devolvió {len(vectors)} vectores para {len(texts)} textos o con otra dimensión "
                f"(se esperaban {self.dimensions})."
            )
        return [normalize([float(value) for value in vector]) for vector in vectors]
