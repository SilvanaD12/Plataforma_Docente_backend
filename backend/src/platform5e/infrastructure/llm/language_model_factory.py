"""
Fábrica del generador principal (modelo de lenguaje) y del de respaldo (por reglas), según las
variables LLM_* descritas en platform5e.infrastructure.settings.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from platform5e.application.ports.outbound.language_model_port import ResourceGeneratorPort
from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.application.ports.outbound.media_port import MediaGeneratorPort
from platform5e.application.ports.outbound.embedding_port import EmbeddingGeneratorPort
from platform5e.infrastructure.llm.gemini_embedding_model import GeminiEmbeddingModel
from platform5e.infrastructure.llm.gemini_language_model import GeminiLanguageModel
from platform5e.infrastructure.llm.gemini_media_generator import GeminiMediaGenerator
from platform5e.infrastructure.settings import read_flag, read_setting

RULES_PROVIDERS = {"rules", "reglas"}  # «reglas»: nombre anterior, se acepta mientras se actualizan los paneles


def create_generators(
    environment: Mapping[str, str] | None = None,
) -> tuple[ResourceGeneratorPort, ResourceGeneratorPort]:
    """Crea los generadores principal y de respaldo (fallback). Si no hay clave, usa reglas."""

    def setting(name: str) -> str:
        return read_setting(name, "", environment).strip()

    fallback_generator = RuleBasedGenerator()
    api_key = setting("LLM_API_KEY")
    provider = (setting("LLM_PROVIDER") or ("gemini" if api_key else "rules")).lower()

    if provider in RULES_PROVIDERS or not api_key:
        return fallback_generator, fallback_generator

    primary_generator = GeminiLanguageModel(
        provider=provider,
        api_key=api_key,
        model=setting("LLM_MODEL") or None,
        base_url=setting("LLM_BASE_URL") or None,
        timeout=float(setting("LLM_TIMEOUT_SECONDS") or 90.0),
    )
    return primary_generator, fallback_generator


def create_media_generator(environment: Mapping[str, str] | None = None) -> MediaGeneratorPort | None:
    """Imágenes y voz con Gemini. Sin clave de Gemini (o con MEDIA_GENERATION_ENABLED=false) se usan los respaldos."""

    def setting(name: str) -> str:
        return read_setting(name, "", environment).strip()

    api_key = setting("LLM_API_KEY")
    provider = (setting("LLM_PROVIDER") or ("gemini" if api_key else "rules")).lower()
    if provider != "gemini" or not api_key or not read_flag("MEDIA_GENERATION_ENABLED", True, environment):
        return None
    return GeminiMediaGenerator(
        api_key=api_key,
        image_model=setting("IMAGE_MODEL") or None,
        speech_model=setting("SPEECH_MODEL") or None,
        voice=setting("SPEECH_VOICE") or None,
        timeout=float(setting("LLM_TIMEOUT_SECONDS") or 120.0),
    )


def create_embedding_generator(environment: Mapping[str, str] | None = None) -> EmbeddingGeneratorPort | None:
    """EN-013: embeddings de Gemini (768 dimensiones). Sin clave de Gemini, o con EMBEDDINGS_ENABLED=false, no hay
    vectores y la recuperación sigue solo por palabras (BM25)."""

    def setting(name: str) -> str:
        return read_setting(name, "", environment).strip()

    api_key = setting("LLM_API_KEY")
    provider = (setting("LLM_PROVIDER") or ("gemini" if api_key else "rules")).lower()
    if provider != "gemini" or not api_key or not read_flag("EMBEDDINGS_ENABLED", True, environment):
        return None
    return GeminiEmbeddingModel(
        api_key=api_key,
        model=setting("EMBEDDING_MODEL") or None,
        timeout=float(setting("LLM_TIMEOUT_SECONDS") or 60.0),
    )


def describe_generator(generator: ResourceGeneratorPort) -> dict[str, Any]:
    """Retorna los metadatos de configuración del generador activo para la UI."""
    return {
        "description": generator.description,
        "usesAi": bool(getattr(generator, "uses_ai", False)),
        "provider": getattr(generator, "provider", "rules"),
        "model": getattr(generator, "model", None),
    }