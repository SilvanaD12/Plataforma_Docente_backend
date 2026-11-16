"""Gemini health probe: fetches model metadata (0 tokens, no content generation).

When ``LLM_PROVIDER=rules`` or no API key is configured the probe reports ``not_configured``,
which does NOT count as a failure.
"""

from __future__ import annotations

import time

import httpx

from platform5e.application.ports.outbound.dependency_probe_port import DependencyProbePort, ProbeResult
from platform5e.application.services.provider_errors import redact_secrets

# The same base URL used by GeminiLanguageModel.
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProbeAdapter:
    """Probes the Gemini API by querying model metadata — no tokens consumed."""

    dependency_name: str = "gemini"

    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = (base_url or _GEMINI_BASE_URL).rstrip("/")
        self._client = client

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    def probe(self, timeout_seconds: float) -> ProbeResult:
        if not self._api_key:
            return ProbeResult(
                name=self.dependency_name,
                status="not_configured",
                latency_ms=0.0,
                detail="proveedor por reglas o sin clave configurada",
            )

        start = time.monotonic()
        try:
            url = f"{self._base_url}/models/{self._model}"
            client = self._client or httpx
            response = client.get(
                url,
                headers={"x-goog-api-key": self._api_key},
                timeout=timeout_seconds,
            )
            elapsed_ms = (time.monotonic() - start) * 1000

            if response.status_code >= 400:
                return ProbeResult(
                    name=self.dependency_name,
                    status="down",
                    latency_ms=round(elapsed_ms, 1),
                    detail=f"Gemini respondió {response.status_code}",
                )

            status = "slow" if elapsed_ms > timeout_seconds * 1000 else "up"
            return ProbeResult(
                name=self.dependency_name,
                status=status,
                latency_ms=round(elapsed_ms, 1),
                detail="metadatos del modelo obtenidos" if status == "up" else "tiempo de respuesta mayor a 3 s",
            )

        except httpx.TimeoutException:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ProbeResult(
                name=self.dependency_name,
                status="slow",
                latency_ms=round(elapsed_ms, 1),
                detail="tiempo de espera agotado (> 3 s)",
            )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ProbeResult(
                name=self.dependency_name,
                status="down",
                latency_ms=round(elapsed_ms, 1),
                detail=redact_secrets(f"error de conexión: {type(exc).__name__}"),
            )
