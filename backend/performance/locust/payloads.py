"""QA-17: cuerpos de las peticiones y configuración del locustfile, sin depender de Locust.

Los cuerpos siguen los de `evaluation/collect_samples.py` y `scripts/measure_generation_load.py` (curso con una unidad
y un resultado, material de la unidad con permiso de uso). Se prueban en `tests/unit/test_locust_payloads.py`, que
corre en la CI sin instalar Locust.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

BACKEND = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = BACKEND / "evaluation" / "corpus" / "protocols.txt"
FINAL_STATUSES = frozenset({"succeeded", "partially_succeeded", "failed", "interrupted"})
# Código del límite de negocio de 2 pedidos activos por docente: no es un error del servidor.
TOO_MANY_ACTIVE_REQUESTS = "TOO_MANY_ACTIVE_REQUESTS"
PROFILES = ("steady", "burst")


def _number(environment: Mapping[str, str], name: str, default: float, minimum: float = 0.0) -> float:
    try:
        value = float(environment.get(name, "") or default)
    except ValueError:
        return default
    return value if value >= minimum else default


@dataclass(frozen=True)
class LoadSettings:
    """Variables de entorno del locustfile (documentadas al inicio de locustfile.py)."""

    profile: str
    wait_min: float
    wait_max: float
    weight_courses: int
    weight_search: int
    weight_generation: int
    health_weight: int
    resource_types: tuple[str, ...]
    search_query: str
    poll_seconds: float
    request_timeout: float
    max_retries_429: int
    email_domain: str
    password: str
    corpus: Path


def load_settings(environment: Mapping[str, str] | None = None) -> LoadSettings:
    env = os.environ if environment is None else environment
    profile = (env.get("LOCUST_PROFILE") or "steady").strip().lower()
    profile = profile if profile in PROFILES else "steady"
    burst = profile == "burst"
    wait_min = _number(env, "LOCUST_WAIT_MIN", 0.0 if burst else 1.0)
    wait_max = max(wait_min, _number(env, "LOCUST_WAIT_MAX", 0.0 if burst else 3.0))
    types = tuple(t.strip() for t in (env.get("LOCUST_RESOURCE_TYPES") or "explicacion").split(",") if t.strip())
    return LoadSettings(
        profile=profile,
        wait_min=wait_min,
        wait_max=wait_max,
        weight_courses=int(_number(env, "LOCUST_WEIGHT_COURSES", 3)),
        weight_search=int(_number(env, "LOCUST_WEIGHT_SEARCH", 3)),
        weight_generation=int(_number(env, "LOCUST_WEIGHT_GENERATION", 1)),
        health_weight=int(_number(env, "LOCUST_HEALTH_WEIGHT", 1 if burst else 0)),
        resource_types=types or ("explicacion",),
        search_query=(env.get("LOCUST_SEARCH_QUERY") or "protocolo TCP").strip(),
        poll_seconds=_number(env, "LOCUST_POLL_SECONDS", 1.0, minimum=0.1),
        request_timeout=_number(env, "LOCUST_REQUEST_TIMEOUT", 120.0, minimum=1.0),
        max_retries_429=int(_number(env, "LOCUST_MAX_RETRIES_429", 5)),
        email_domain=(env.get("LOCUST_EMAIL_DOMAIN") or "correo.pe").strip(),
        password=env.get("LOCUST_PASSWORD") or "clave-locust-local-1",
        corpus=Path(env.get("LOCUST_CORPUS") or DEFAULT_CORPUS),
    )


def unique_email(domain: str) -> str:
    """Un correo por usuario virtual: el límite de inicio de sesión (QA-08) va por correo e IP, así no se cruza."""
    return f"locust.{uuid4().hex[:12]}@{domain}"


def account_body(email: str, password: str) -> dict[str, str]:
    return {"name": "Docente Locust", "email": email, "password": password}


def session_body(email: str, password: str) -> dict[str, str]:
    return {"email": email, "password": password}


def course_body() -> dict[str, Any]:
    """El curso de evaluación de collect_samples.py: una unidad con un resultado de aprendizaje."""
    return {
        "code": "LOCUST-01",
        "name": "Redes de computadoras (carga QA-17)",
        "term": "2026-II",
        "summary": "Curso de redes de computadoras: protocolos de transporte y de red.",
        "learningGoal": "Explica cómo se comunican los equipos en una red.",
        "units": [{"title": "Protocolos de transporte", "outcomes": [{"text": "Distingue TCP, UDP e IP según su función"}]}],
    }


def document_context(unit: dict[str, Any]) -> str:
    """El campo `context` (JSON) de la subida del material, como lo envía collect_samples.py."""
    return json.dumps({
        "unitId": unit["id"],
        "outcomeIds": [outcome["id"] for outcome in unit.get("outcomes") or []],
        "documentType": "Separata o apuntes de clase",
        "suggestedStage": None,
        "usePermission": True,
    })


def generation_body(unit_id: str, resource_types: tuple[str, ...]) -> dict[str, Any]:
    """Pedido individual con un tipo, o secuencia con varios (en orden 5E lo arma el servidor)."""
    mode = "individual" if len(resource_types) == 1 else "sequence"
    return {"mode": mode, "unitId": unit_id, "resourceTypes": list(resource_types), "quantity": 1}


def search_params(query: str, unit_id: str) -> dict[str, Any]:
    return {"query": query, "unitId": unit_id, "topK": 8}


def retry_after_seconds(headers: Mapping[str, str], default: float = 5.0) -> float:
    """Segundos de `Retry-After` (o `default` si falta o no es un número)."""
    try:
        return max(0.0, float(headers.get("Retry-After") or default))
    except ValueError:
        return default


def error_code(body: Any) -> str | None:
    return ((body or {}).get("error") or {}).get("code") if isinstance(body, dict) else None
