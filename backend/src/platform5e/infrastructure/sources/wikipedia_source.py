"""
Cliente para búsqueda de material pedagógico por tema en Wikipedia (licencia CC BY-SA 4.0).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

from platform5e.application.ports.outbound.open_educational_resource_port import OpenEducationalResourcePort

# La política de Wikimedia exige un User-Agent con datos de contacto (https://w.wiki/4WJS); sin ellos responde 403.
USER_AGENT_HEADER: str = (
    "Platform5E/1.0 (https://github.com/Yansete/plataforma-5e-taller-integrador; academic project UPAO) python-httpx"
)
_TRAILING_SECTIONS_REGEX: re.Pattern[str] = re.compile(
    r"^\s*={2,}\s*(Véase también|Referencias|Notas|Bibliografía|Enlaces externos|Fuentes)\s*={2,}\s*$",
    re.MULTILINE | re.IGNORECASE,
)
MAX_ARTICLE_CHARS: int = 60000


class WikipediaSource(OpenEducationalResourcePort):
    """Adaptador de infraestructura para consultar artículos educativos libres vía Wikipedia Action API."""

    def __init__(
        self,
        language: str = "es",
        client: httpx.Client | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._language = language
        self._api_endpoint = f"https://{language}.wikipedia.org/w/api.php"
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT_HEADER},
            timeout=timeout,
            follow_redirects=True,
        )

    def _query_api(self, **params: Any) -> dict[str, Any]:
        """Ejecuta una petición GET a la API de Wikipedia con parámetros serializados en JSON."""
        response = self._client.get(
            self._api_endpoint,
            params={"format": "json", "formatversion": 2, **params},
        )
        response.raise_for_status()
        return response.json()

    def search(self, topic: str, limit: int) -> list[dict[str, Any]]:
        """Busca páginas coincidentes con el tema y extrae el texto limpio sin secciones auxiliares."""
        search_response = self._query_api(
            action="query",
            list="search",
            srsearch=topic,
            srlimit=limit,
            srnamespace=0,
        )

        articles_list: list[dict[str, Any]] = []
        for item in search_response.get("query", {}).get("search", []):
            detail_response = self._query_api(
                action="query",
                prop="extracts|info",
                inprop="url",
                explaintext=1,
                exsectionformat="wiki",
                redirects=1,
                titles=item["title"],
            )

            pages = detail_response.get("query", {}).get("pages", [])
            if not pages or pages[0].get("missing"):
                continue

            target_page = pages[0]
            raw_text = target_page.get("extract") or ""
            trailing_match = _TRAILING_SECTIONS_REGEX.search(raw_text)
            cleaned_text = (
                raw_text[: trailing_match.start()] if trailing_match else raw_text
            ).strip()[:MAX_ARTICLE_CHARS]

            if len(cleaned_text) < 300:  # Desambiguaciones o páginas demasiado cortas
                continue

            page_title = target_page.get("title", item["title"])
            full_url = target_page.get("fullurl") or (
                f"https://{self._language}.wikipedia.org/wiki/{quote(page_title.replace(' ', '_'))}"
            )

            articles_list.append(
                {
                    "titulo": page_title,
                    "url": full_url,
                    "texto": cleaned_text,
                    "licencia": "CC BY-SA 4.0",
                    "fuente": "Wikipedia",
                }
            )

        return articles_list