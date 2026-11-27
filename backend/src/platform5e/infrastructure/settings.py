"""
Variables de entorno del backend. Los nombres están en inglés; los nombres anteriores en español se
siguen leyendo mientras se actualizan los paneles de Render y los archivos .env (Sprint 2: quitar LEGACY_NAMES).

CORS_ALLOWED_ORIGINS        orígenes del frontend publicado, separados por comas
LLM_PROVIDER                gemini | anthropic | openai | rules (por defecto: gemini si hay clave, si no rules)
LLM_API_KEY                 clave de API del proveedor
LLM_MODEL                   opcional; por defecto gemini-3.8-flash, claude-sonnet-5-5 o gpt-5.4-mini
LLM_BASE_URL                opcional; para proxies o servicios compatibles con OpenAI
LLM_TIMEOUT_SECONDS         tiempo de espera de cada operación de red con el proveedor (conectar, cada lectura); nunca
                            pasa de LLM_CALL_DEADLINE_SECONDS. En Render debe ser 60 o menos
LLM_CALL_DEADLINE_SECONDS   QA-06: tiempo límite total de cada llamada a Gemini (texto, imagen, voz y cada lote de
                            embeddings), de punta a punta (por defecto 60, máximo 60). Al vencer se usa el respaldo
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
GENERATION_MAX_WORKERS      hilos que ejecutan pedidos de generación por proceso (por defecto 2)
GENERATION_REQUEST_DEADLINE_SECONDS  tiempo máximo de un pedido de generación (por defecto 900)
GENERATION_REGENERATION_WAIT_SECONDS  segundos que la regeneración desde Revisión espera el pedido antes de responder
                            `running` (por defecto 10; 0 responde enseguida)
GENERATION_REQUIRE_PLAN     GEN-P2: true (por defecto desde T021) | false. Con true, POST /generation-requests solo
                            acepta {planId, planVersion} de un plan aprobado y el cuerpo anterior responde 422
                            PLAN_REQUIRED. La regeneración desde Revisión no es un pedido nuevo y sigue igual. Con
                            false, el cuerpo anterior crea un plan implícito aprobado y genera desde él: solo para
                            pruebas y mediciones que lo usan a propósito
GENERATION_IMPLICIT_PLAN    GEN-P2, SOLO PARA MEDIR P4: true (por defecto) | false. Con false, el cuerpo anterior se
                            redacta como antes de GEN-P1: sin plan implícito, sin comprobación del plan y con los
                            prompts de entonces. Sirve para la línea base de measure_duplication.py --mode baseline en
                            el mismo servidor y la misma base (specs/006-plan-de-generacion/plan.md, «Medición de P4»).
                            Nunca en false en Render ni en producción. GENERATION_REQUIRE_PLAN=true tiene prioridad: el
                            pedido sin plan se rechaza igual
TOPIC_COVERAGE_THRESHOLD    QA-05: parte de los términos de las indicaciones que debe aparecer en la evidencia antes de
                            redactar, de 0 a 1 (por defecto 0.5). Si no llega y tampoco aparece ninguna frase del tema,
                            el pedido falla con INSUFFICIENT_EVIDENCE. 0 apaga la comprobación
REVIEW_DUPLICATE_THRESHOLD  REV-P3: umbral de similitud para reportar duplicados, de 0 a 1 (por defecto 0.70)
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from platform5e.infrastructure.llm.call_deadline import DEFAULT_CALL_DEADLINE_SECONDS, MAX_CALL_DEADLINE_SECONDS
from platform5e.domain.generation.topic_coverage import DEFAULT_COVERAGE_THRESHOLD
from platform5e.domain.review.duplication import DEFAULT_DUPLICATE_THRESHOLD

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


# T021: el frontend del plan (GEN-P3) ya está integrado; todo pedido parte de un plan aprobado.
DEFAULT_GENERATION_REQUIRE_PLAN: bool = True


DEFAULT_GENERATION_IMPLICIT_PLAN: bool = True


def generation_implicit_plan(environment: Mapping[str, str] | None = None) -> bool:
    """GEN-P2: si el cuerpo anterior crea un plan implícito (por defecto sí). `false` es solo para medir la línea base
    de P4 en el mismo servidor; nunca en Render. GENERATION_REQUIRE_PLAN=true tiene prioridad."""
    return read_flag("GENERATION_IMPLICIT_PLAN", DEFAULT_GENERATION_IMPLICIT_PLAN, environment)


def generation_require_plan(environment: Mapping[str, str] | None = None) -> bool:
    """GEN-P2: si el pedido de generación exige un plan aprobado (por defecto sí, desde T021)."""
    return read_flag("GENERATION_REQUIRE_PLAN", DEFAULT_GENERATION_REQUIRE_PLAN, environment)


def read_flag(name: str, default: bool, environment: Mapping[str, str] | None = None) -> bool:
    """true/false sin distinguir mayúsculas; cualquier otro valor deja el valor por defecto."""
    value = read_setting(name, "", environment).strip().lower()
    return {"true": True, "false": False}.get(value, default)


DEFAULT_GENERATION_MAX_WORKERS: int = 2
DEFAULT_GENERATION_REQUEST_DEADLINE_SECONDS: int = 900
# Research R3: el ejecutor renueva el latido de sus pedidos cada 15 s y el barrido periódico interrumpe, cada 30 s, los
# que llevan más de 60 s sin latido.
DEFAULT_GENERATION_HEARTBEAT_SECONDS: float = 15.0
DEFAULT_GENERATION_SWEEP_INTERVAL_SECONDS: int = 30
GENERATION_STALE_REQUEST_SECONDS: int = 60
# T029: la regeneración desde Revisión espera hasta 10 s el resultado antes de responder `running`.
DEFAULT_GENERATION_REGENERATION_WAIT_SECONDS: float = 10.0


def read_positive_int(name: str, default: int, environment: Mapping[str, str] | None = None) -> int:
    """Entero mayor que cero; un valor vacío, no numérico o menor que 1 deja el valor por defecto."""
    value = read_setting(name, "", environment).strip()
    try:
        number = int(value)
    except ValueError:
        return default
    return number if number > 0 else default


def generation_max_workers(environment: Mapping[str, str] | None = None) -> int:
    return read_positive_int("GENERATION_MAX_WORKERS", DEFAULT_GENERATION_MAX_WORKERS, environment)


def generation_request_deadline_seconds(environment: Mapping[str, str] | None = None) -> int:
    return read_positive_int(
        "GENERATION_REQUEST_DEADLINE_SECONDS", DEFAULT_GENERATION_REQUEST_DEADLINE_SECONDS, environment
    )


def generation_sweep_interval_seconds(environment: Mapping[str, str] | None = None) -> int:
    return read_positive_int(
        "GENERATION_SWEEP_INTERVAL_SECONDS", DEFAULT_GENERATION_SWEEP_INTERVAL_SECONDS, environment
    )


def llm_call_deadline_seconds(environment: Mapping[str, str] | None = None) -> float:
    """QA-06: segundos de la llamada completa a Gemini, mayor que 0 y como máximo 60. Un valor vacío, no numérico o
    fuera de rango deja 60."""
    value = read_setting("LLM_CALL_DEADLINE_SECONDS", "", environment).strip()
    try:
        seconds = float(value)
    except ValueError:
        return DEFAULT_CALL_DEADLINE_SECONDS
    if not seconds > 0:  # también descarta NaN
        return DEFAULT_CALL_DEADLINE_SECONDS
    return min(seconds, MAX_CALL_DEADLINE_SECONDS)


def llm_read_timeout_seconds(default: float, environment: Mapping[str, str] | None = None) -> float:
    """Timeout de httpx por operación: LLM_TIMEOUT_SECONDS (o `default`), sin pasar del tiempo límite de la llamada."""
    value = read_setting("LLM_TIMEOUT_SECONDS", "", environment).strip()
    try:
        seconds = float(value)
    except ValueError:
        seconds = default
    if not seconds > 0:
        seconds = default
    return min(seconds, llm_call_deadline_seconds(environment))


def topic_coverage_threshold(environment: Mapping[str, str] | None = None) -> float:
    """QA-05: umbral de cobertura del tema, de 0 a 1. Un valor vacío, no numérico o fuera de rango deja 0.5."""
    value = read_setting("TOPIC_COVERAGE_THRESHOLD", "", environment).strip()
    try:
        threshold = float(value)
    except ValueError:
        return DEFAULT_COVERAGE_THRESHOLD
    return threshold if 0 <= threshold <= 1 else DEFAULT_COVERAGE_THRESHOLD


def generation_regeneration_wait_seconds(environment: Mapping[str, str] | None = None) -> float:
    """Segundos (0 o más) que la regeneración espera el pedido. Un valor vacío, no numérico o negativo deja 10."""
    value = read_setting("GENERATION_REGENERATION_WAIT_SECONDS", "", environment).strip()
    try:
        seconds = float(value)
    except ValueError:
        return DEFAULT_GENERATION_REGENERATION_WAIT_SECONDS
    return seconds if seconds >= 0 and seconds == seconds else DEFAULT_GENERATION_REGENERATION_WAIT_SECONDS


DEFAULT_REVIEW_DUPLICATE_THRESHOLD: float = DEFAULT_DUPLICATE_THRESHOLD


def review_duplicate_threshold(environment: Mapping[str, str] | None = None) -> float:
    """REV-P3: umbral de similitud para reportar contenido duplicado, de 0 a 1 (por defecto 0.70)."""
    value = read_setting("REVIEW_DUPLICATE_THRESHOLD", "", environment).strip()
    try:
        threshold = float(value)
    except ValueError:
        return DEFAULT_REVIEW_DUPLICATE_THRESHOLD
    return threshold if 0.0 <= threshold <= 1.0 else DEFAULT_REVIEW_DUPLICATE_THRESHOLD

