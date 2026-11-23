"""Extractor de referentes académicos/técnicos usando Gemini con esquema JSON estructurado (MAT-P2)."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

import httpx

from platform5e.application.ports.outbound.referent_extractor_port import ReferentExtractorPort
from platform5e.application.services.generation.prompt_drafting import parse_json_response
from platform5e.domain.generation.generation_plan import PlanFragment, Referent
from platform5e.infrastructure.llm.gemini_language_model import DEFAULT_BASE_URLS, DEFAULT_MODELS

logger = logging.getLogger("platform5e.referents")

_REFERENTS_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "referents": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING"},
                    "description": {"type": "STRING"},
                    "fragmentIds": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                },
                "required": ["name", "description", "fragmentIds"],
            },
        }
    },
    "required": ["referents"],
}


class GeminiReferentExtractor(ReferentExtractorPort):
    """Identifica autores o referentes principales del tema a partir de fragmentos de evidencia."""

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model or DEFAULT_MODELS["gemini"]
        self._base_url = (base_url or DEFAULT_BASE_URLS["gemini"]).rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)

    def extract_referents(self, topic: str, fragments: Sequence[PlanFragment]) -> list[Referent]:
        if not fragments:
            return []

        allowed_ids = {fragment.id for fragment in fragments}
        compact_fragments = [
            {
                "id": fragment.id,
                "documentName": fragment.document_name,
                "location": fragment.location,
                "text": fragment.text[:1200],
            }
            for fragment in fragments[:20]
        ]

        system_instruction = (
            "Eres un asistente académico. A partir de los fragmentos proporcionados y el tema, "
            "identifica únicamente autores, investigadores o referentes teóricos/técnicos principales "
            "que aparezcan o respalden directamente el contenido. Si no hay referentes claros, devuelve {\"referents\": []}."
        )
        user_prompt = json.dumps({"topic": topic, "fragments": compact_fragments}, ensure_ascii=False)

        try:
            response = self._client.post(
                f"{self._base_url}/models/{self._model}:generateContent",
                headers={"Content-Type": "application/json", "x-goog-api-key": self._api_key},
                json={
                    "systemInstruction": {"parts": [{"text": system_instruction}]},
                    "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                    "generationConfig": {
                        "responseMimeType": "application/json",
                        "responseSchema": _REFERENTS_SCHEMA,
                    },
                },
            )
            response.raise_for_status()
            payload = response.json()
            candidates = payload.get("candidates") or []
            if not candidates:
                return []
            parts = (candidates[0].get("content") or {}).get("parts") or []
            raw_text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
            parsed = parse_json_response(raw_text)
        except Exception as exc:
            logger.warning("Fallo al extraer referentes con Gemini: %s", exc.__class__.__name__)
            return []

        raw_items = parsed.get("referents", []) if isinstance(parsed, dict) else []
        results: list[Referent] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            description = str(item.get("description") or "").strip()[:300]
            valid_fids = tuple(
                dict.fromkeys(
                    str(fid)
                    for fid in (item.get("fragmentIds") or [])
                    if str(fid) in allowed_ids
                )
            )
            results.append(Referent(name=name, description=description, fragment_ids=valid_fids))

        return results