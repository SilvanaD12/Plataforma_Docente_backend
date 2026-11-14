"""
Generador de recursos pedagógicos con modelos LLM vía HTTP (HU-018).
Soporta proveedores: Gemini, Anthropic y OpenAI (o compatibles como Groq/OpenRouter).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from platform5e.application.ports.outbound.language_model_port import ResourceGeneratorPort
from platform5e.application.services.generation.prompt_drafting import (
    build_prompt_instructions,
    parse_json_response,
)

DEFAULT_MODELS: dict[str, str] = {
    "gemini": "gemini-3.8-flash",  # gemini-2.5-flash responde 404 a las claves nuevas
    "anthropic": "claude-sonnet-5-5",
    "openai": "gpt-5.4-mini",
}
PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "gemini": "Gemini",
    "anthropic": "Anthropic",
    "openai": "OpenAI",
}
DEFAULT_BASE_URLS: dict[str, str] = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com/v1",
}
RETRY_PROMPT_SUFFIX: str = (
    "\n\nTu respuesta anterior no era JSON válido. Responde solo con el objeto JSON pedido."
)
# Caracteres del comienzo y del final de una respuesta inválida que se guardan en el registro.
INVALID_TEXT_PREVIEW_CHARS: int = 300
ATTEMPTS: int = 2

logger = logging.getLogger("platform5e.llm")

_STRING_TYPE: dict[str, str] = {"type": "STRING"}
_TAGS_ARRAY_TYPE: dict[str, Any] = {"type": "ARRAY", "items": _STRING_TYPE}

def _object_list(*fields: str, flags: tuple[str, ...] = ()) -> dict[str, Any]:
    properties: dict[str, Any] = {name: _STRING_TYPE for name in fields}
    properties.update({name: {"type": "BOOLEAN"} for name in flags})
    return {"type": "ARRAY", "items": {"type": "OBJECT", "properties": properties}}


# Contenido estructurado de los recursos visuales, de audio e interactivos (todos los campos son opcionales).
_STRUCTURE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "guion": _STRING_TYPE,
        "descripcion_imagen": _STRING_TYPE,
        "texto_alternativo": _STRING_TYPE,
        "leyenda": _STRING_TYPE,
        "central": _STRING_TYPE,
        "nodos": _object_list("etiqueta", "detalle"),
        "puntos": _object_list("titulo", "texto"),
        "pasos": _object_list("titulo", "texto"),
        "pasos_guiados": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "titulo": _STRING_TYPE,
                    "consigna": _STRING_TYPE,
                    "pregunta": _STRING_TYPE,
                    "fragmentos": _TAGS_ARRAY_TYPE,
                },
            },
        },
        "predicciones": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "pregunta": _STRING_TYPE,
                    "correcta": _STRING_TYPE,
                    "otra": _STRING_TYPE,
                    "extra": _STRING_TYPE,
                    "revelacion": _STRING_TYPE,
                    "fragmentos": _TAGS_ARRAY_TYPE,
                },
            },
        },
        "materiales": _TAGS_ARRAY_TYPE,
        "minutos_estimados": {"type": "INTEGER"},
        "espacio": _STRING_TYPE,
        "situacion": _STRING_TYPE,
        "consigna": _STRING_TYPE,
        "criterios": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "criterio": _STRING_TYPE,
                    "fragmentos": _TAGS_ARRAY_TYPE,
                },
            },
        },
        "pares": _object_list("termino", "definicion"),
        "secuencia": _TAGS_ARRAY_TYPE,
        "afirmaciones": _object_list("texto", "retroalimentacion", flags=("verdadera",)),
        "espacios": _object_list("oracion", "respuesta"),
    },
}

# Esquema estructurado para Gemini
GEMINI_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "recursos": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "titulo": _STRING_TYPE,
                    "contenido": _STRING_TYPE,
                    "citas": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "afirmacion": _STRING_TYPE,
                                "fragmentos": _TAGS_ARRAY_TYPE,
                            },
                            "required": ["afirmacion", "fragmentos"],
                        },
                    },
                    "alternativas": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "texto": _STRING_TYPE,
                                "correcta": {"type": "BOOLEAN"},
                                "retroalimentacion": _STRING_TYPE,
                                "fragmentos": _TAGS_ARRAY_TYPE,
                            },
                            "required": ["texto", "correcta", "retroalimentacion", "fragmentos"],
                        },
                    },
                    "estructura": _STRUCTURE_SCHEMA,
                },
                "required": ["titulo", "contenido", "citas", "alternativas"],
            },
        }
    },
    "required": ["recursos"],
}


class AIProviderError(Exception):
    """Excepción para errores de conectividad, cuota o respuestas inválidas del proveedor de IA."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _grouped(number: int) -> str:
    """65536 -> «65 536»."""
    return f"{number:,}".replace(",", " ")


def response_details(text: str, finish_reason: str | None, output_tokens: int | None) -> str:
    """Diagnóstico corto de una respuesta: por qué terminó, cuántos tokens y cuántos caracteres tiene."""
    parts = [f"finishReason {finish_reason}"] if finish_reason else []
    if isinstance(output_tokens, int) and not isinstance(output_tokens, bool):
        parts.append(f"{_grouped(output_tokens)} tokens")
    parts.append(f"{_grouped(len(text))} caracteres")
    return ", ".join(parts)


class GeminiLanguageModel(ResourceGeneratorPort):
    """Adaptador de infraestructura que implementa la generación con modelos de lenguaje por API REST."""

    uses_ai: bool = True

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 90.0,
        client: httpx.Client | None = None,
    ) -> None:
        if provider not in DEFAULT_MODELS:
            raise ValueError(
                f"Proveedor de IA desconocido: {provider}. Usa gemini, anthropic u openai."
            )
        self.provider = provider
        self.model = model or DEFAULT_MODELS[provider]
        self._api_key = api_key
        self._base_url = (base_url or DEFAULT_BASE_URLS[provider]).rstrip("/")
        self._client = client or httpx.Client(timeout=timeout)
        self._enforce_schema = provider == "gemini"
        self.description = f"{PROVIDER_DISPLAY_NAMES[provider]} · {self.model}"

    def generate(self, context: dict[str, Any]) -> dict[str, Any]:
        """Envía el contexto estructurado y extrae el JSON validado."""
        system_instruction, user_prompt = build_prompt_instructions(context)
        try:
            parsed_data = self._complete_json(system_instruction, user_prompt, attempt=1)
        except ValueError:
            # Si también falla el reintento, su error (con su diagnóstico) es el que se informa.
            parsed_data = self._complete_json(system_instruction, user_prompt + RETRY_PROMPT_SUFFIX, attempt=2)

        return parsed_data if isinstance(parsed_data, dict) else {"recursos": parsed_data}

    def _complete_json(self, system_instruction: str, user_prompt: str, attempt: int) -> Any:
        """Pide la respuesta y la lee como JSON. Si no lo es, el error dice por qué terminó la respuesta y cuánto
        medía (un JSON cortado por el límite de tokens termina con finishReason MAX_TOKENS), y el registro guarda su
        comienzo y su final. Nunca se registran la clave ni el prompt."""
        raw_text, finish_reason, output_tokens = self._complete(system_instruction, user_prompt)
        try:
            return parse_json_response(raw_text)
        except ValueError as exc:
            details = response_details(raw_text, finish_reason, output_tokens)
            logger.warning(
                "%s: respuesta que no es JSON válido (intento %d de %d; %s). Comienzo: %r · Final: %r",
                self.description,
                attempt,
                ATTEMPTS,
                details,
                raw_text[:INVALID_TEXT_PREVIEW_CHARS],
                raw_text[-INVALID_TEXT_PREVIEW_CHARS:],
            )
            raise ValueError(f"{str(exc).rstrip('.')} ({details}).") from exc

    def _complete(self, system_instruction: str, user_prompt: str) -> tuple[str, str | None, int | None]:
        """Invoca el endpoint del proveedor. Devuelve el texto y, si el proveedor los informa (Gemini), por qué terminó
        la respuesta (finishReason) y cuántos tokens tiene; si no, None."""
        if self.provider == "gemini":
            generation_config: dict[str, Any] = {"responseMimeType": "application/json"}
            if self._enforce_schema:
                generation_config["responseSchema"] = GEMINI_RESPONSE_SCHEMA

            try:
                response_data = self._post_request(
                    f"{self._base_url}/models/{self.model}:generateContent",
                    {"x-goog-api-key": self._api_key},
                    {
                        "systemInstruction": {"parts": [{"text": system_instruction}]},
                        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                        "generationConfig": generation_config,
                    },
                )
            except AIProviderError as exc:
                if exc.status_code != 400 or not self._enforce_schema:
                    raise
                self._enforce_schema = False  # El modelo rechazó el esquema: reintento en JSON libre
                return self._complete(system_instruction, user_prompt)

            candidates = response_data.get("candidates") or []
            if not candidates:
                block_reason = (response_data.get("promptFeedback") or {}).get(
                    "blockReason", "sin candidatos"
                )
                raise AIProviderError(f"Gemini no devolvió texto ({block_reason}).")
            parts = (candidates[0].get("content") or {}).get("parts") or []
            text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
            output_tokens = (response_data.get("usageMetadata") or {}).get("candidatesTokenCount")
            return text, candidates[0].get("finishReason"), output_tokens

        if self.provider == "anthropic":
            response_data = self._post_request(
                f"{self._base_url}/v1/messages",
                {"x-api-key": self._api_key, "anthropic-version": "2023-06-01"},
                {
                    "model": self.model,
                    "max_tokens": 8000,
                    "system": system_instruction,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            )
            text = "".join(
                block.get("text", "")
                for block in response_data.get("content", [])
                if block.get("type") == "text"
            )
            return text, None, None

        # openai o compatibles
        response_data = self._post_request(
            f"{self._base_url}/chat/completions",
            {"Authorization": f"Bearer {self._api_key}"},
            {
                "model": self.model,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        return response_data["choices"][0]["message"]["content"] or "", None, None

    def _post_request(self, endpoint_url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        """Envía la petición HTTP post con manejo de excepciones y errores de tasa límite."""
        try:
            response = self._client.post(
                endpoint_url,
                headers={"Content-Type": "application/json", **headers},
                json=payload,
            )
        except httpx.HTTPError as exc:
            provider_name = PROVIDER_DISPLAY_NAMES[self.provider]
            raise AIProviderError(
                f"sin conexión con {provider_name}: {exc.__class__.__name__}"
            ) from exc

        if response.status_code >= 400:
            provider_name = PROVIDER_DISPLAY_NAMES[self.provider]
            try:
                error_detail = response.json().get("error", {})
                detail_msg = (
                    error_detail.get("message", "")
                    if isinstance(error_detail, dict)
                    else str(error_detail)
                )
            except ValueError:
                detail_msg = response.text[:200]

            if response.status_code == 429:
                raise AIProviderError(
                    f"límite de uso de {provider_name} alcanzado (429). Espera un minuto.", 429
                )
            raise AIProviderError(
                f"{provider_name} respondió {response.status_code}: {detail_msg[:200]}",
                response.status_code,
            )

        return response.json()