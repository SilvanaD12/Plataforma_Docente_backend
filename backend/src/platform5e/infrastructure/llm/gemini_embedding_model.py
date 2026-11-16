"""
Embeddings con la API de Gemini (EN-013): 768 dimensiones, sin modelo local (Render gratuito tiene 512 MB).

Usa `batchEmbedContents` para pedir hasta 100 textos por llamada. Con menos de 3072 dimensiones Gemini no
devuelve vectores normalizados, así que aquí se normalizan: la distancia coseno de pgvector los compara bien igual,
pero normalizados también sirven para el producto interno.
"""

from __future__ import annotations

import math
import time
from typing import Any

import httpx

from platform5e.application.ports.outbound.embedding_port import EmbeddingGeneratorPort
from platform5e.infrastructure.llm.call_deadline import (
    DEFAULT_CALL_DEADLINE_SECONDS,
    CallDeadlineExceeded,
    post_with_deadline,
    seconds_label,
)
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
        call_deadline_seconds: float = DEFAULT_CALL_DEADLINE_SECONDS,
    ) -> None:
        self.model = model or DEFAULT_EMBEDDING_MODEL
        self.call_deadline_seconds = call_deadline_seconds  # QA-06: límite total de cada lote
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
            response = post_with_deadline(
                self._client,
                f"{self._base_url}/models/{self.model}:batchEmbedContents",
                time.monotonic() + self.call_deadline_seconds,
                {"Content-Type": "application/json", "x-goog-api-key": self._api_key},
                payload,
            )
        except CallDeadlineExceeded as exc:
            reason = f"Gemini no respondió en {seconds_label(self.call_deadline_seconds)} s en los embeddings"
            raise AIProviderError(f"{reason} (tiempo límite por llamada).", public_reason=reason) from exc
        except httpx.HTTPError as exc:
            message = f"sin conexión con Gemini (embeddings): {exc.__class__.__name__}"
            raise AIProviderError(message, public_reason=message) from exc

        if response.status_code >= 400:
            if response.status_code == 429:
                message = "límite de uso de Gemini alcanzado en los embeddings (429)."
                raise AIProviderError(message, 429, public_reason=message)
            try:
                detail = response.json().get("error", {}).get("message", "")
            except (ValueError, AttributeError):
                detail = response.text[:200]
            # El texto del proveedor va solo al registro: puede traer la clave o datos del proyecto.
            raise AIProviderError(
                f"Gemini respondió {response.status_code} en los embeddings: {str(detail)[:200]}",
                response.status_code,
                public_reason=f"Gemini respondió {response.status_code} en los embeddings",
            )

        embeddings = response.json().get("embeddings") or []
        vectors = [item.get("values") or [] for item in embeddings]
        if len(vectors) != len(texts) or any(len(vector) != self.dimensions for vector in vectors):
            message = (
                f"Gemini devolvió {len(vectors)} vectores para {len(texts)} textos o con otra dimensión "
                f"(se esperaban {self.dimensions})."
            )
            raise AIProviderError(message, public_reason=message)
        return [normalize([float(value) for value in vector]) for vector in vectors]
