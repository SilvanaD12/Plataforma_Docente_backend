"""Wikipedia health probe: lightweight query to the same Spanish Wikipedia Action API used for topic import."""

from __future__ import annotations

import time

import httpx

from platform5e.application.ports.outbound.dependency_probe_port import DependencyProbePort, ProbeResult
from platform5e.application.services.provider_errors import redact_secrets
from platform5e.infrastructure.sources.wikipedia_source import USER_AGENT_HEADER

_WIKIPEDIA_API_URL = "https://es.wikipedia.org/w/api.php"


class WikipediaProbeAdapter:
    """Probes Wikipedia with a tiny ``siteinfo`` query (no article text transferred)."""

    dependency_name: str = "wikipedia"

    def __init__(
        self,
        api_url: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_url = api_url or _WIKIPEDIA_API_URL
        self._client = client

    def probe(self, timeout_seconds: float) -> ProbeResult:
        start = time.monotonic()
        try:
            client = self._client or httpx
            response = client.get(
                self._api_url,
                params={"action": "query", "meta": "siteinfo", "format": "json", "formatversion": 2},
                headers={"User-Agent": USER_AGENT_HEADER},
                timeout=timeout_seconds,
            )
            elapsed_ms = (time.monotonic() - start) * 1000

            if response.status_code >= 400:
                return ProbeResult(
                    name=self.dependency_name,
                    status="down",
                    latency_ms=round(elapsed_ms, 1),
                    detail=f"Wikipedia respondió {response.status_code}",
                )

            status = "slow" if elapsed_ms > timeout_seconds * 1000 else "up"
            return ProbeResult(
                name=self.dependency_name,
                status=status,
                latency_ms=round(elapsed_ms, 1),
                detail="consulta de información del sitio exitosa" if status == "up" else "tiempo de respuesta mayor a 3 s",
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
