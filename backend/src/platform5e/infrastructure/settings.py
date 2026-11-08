"""
Variables de entorno del backend. Los nombres están en inglés; los nombres anteriores en español se
siguen leyendo mientras se actualizan los paneles de Render y los archivos .env (Sprint 2: quitar LEGACY_NAMES).

CORS_ALLOWED_ORIGINS        orígenes del frontend publicado, separados por comas
LLM_PROVIDER                gemini | anthropic | openai | rules (por defecto: gemini si hay clave, si no rules)
LLM_API_KEY                 clave de API del proveedor
LLM_MODEL                   opcional; por defecto gemini-3.8-flash, claude-sonnet-5-5 o gpt-5.4-mini
LLM_BASE_URL                opcional; para proxies o servicios compatibles con OpenAI
LLM_TIMEOUT_SECONDS         tiempo de espera por respuesta (por defecto 90)
TOPIC_SEARCH_ENABLED        true (por defecto) | false: búsqueda de material por tema en Wikipedia
MEDIA_GENERATION_ENABLED    true (por defecto) | false: imágenes y voz con Gemini (necesita LLM_PROVIDER=gemini)
IMAGE_MODEL                 opcional; por defecto gemini-3.1-flash-lite-image (requiere facturación en Google AI)
SPEECH_MODEL                opcional; por defecto gemini-3.8-flash-tts
SPEECH_VOICE                opcional; voz de Gemini, por defecto Kore
EMBEDDINGS_ENABLED          true (por defecto) | false: embeddings de los fragmentos con Gemini (EN-013)
EMBEDDING_MODEL             opcional; por defecto gemini-embedding-001 (768 dimensiones)
BOOTSTRAP_TEACHER_EMAIL     opcional; cuenta inicial configurada en el servidor
BOOTSTRAP_TEACHER_PASSWORD  opcional; su contraseña
DEMO_CATALOG                solo pruebas: cuenta y curso de ejemplo
DATABASE_URL                conexión a PostgreSQL (Neon) o SQLite
"""

from __future__ import annotations

import os
from collections.abc import Mapping

LEGACY_NAMES: dict[str, str] = {
    "CORS_ALLOWED_ORIGINS": "CORS_ORIGENES",
    "LLM_PROVIDER": "IA_PROVEEDOR",
    "LLM_API_KEY": "IA_API_KEY",
    "LLM_MODEL": "IA_MODELO",
    "LLM_BASE_URL": "IA_URL_BASE",
    "LLM_TIMEOUT_SECONDS": "IA_TIEMPO_MAX",
    "TOPIC_SEARCH_ENABLED": "BUSQUEDA_POR_TEMA",
    "BOOTSTRAP_TEACHER_EMAIL": "EP002_DOCENTE_EMAIL",
    "BOOTSTRAP_TEACHER_PASSWORD": "EP002_DOCENTE_PASSWORD",
    "DEMO_CATALOG": "CATALOGO_DEMO",
}


def read_setting(name: str, default: str = "", environment: Mapping[str, str] | None = None) -> str:
    """Valor de la variable `name`; si no existe, el de su nombre anterior en español; si tampoco, `default`."""
    env = os.environ if environment is None else environment
    value = env.get(name)
    if value is None and name in LEGACY_NAMES:
        value = env.get(LEGACY_NAMES[name])
    return default if value is None else value


def read_flag(name: str, default: bool, environment: Mapping[str, str] | None = None) -> bool:
    """true/false sin distinguir mayúsculas; cualquier otro valor deja el valor por defecto."""
    value = read_setting(name, "", environment).strip().lower()
    return {"true": True, "false": False}.get(value, default)
