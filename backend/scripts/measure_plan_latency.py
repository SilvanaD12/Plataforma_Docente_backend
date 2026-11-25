"""GEN-P1 · T020 (specs/006-plan-de-generacion, quickstart V9): tiempo de creación del plan de generación.

Uso (desde backend/, con el servidor local en marcha):
    export EVAL_EMAIL=... EVAL_PASSWORD=...
    python scripts/measure_plan_latency.py --api http://127.0.0.1:8000            # 20 planes seguidos

Qué hace:
1. Prepara la cuenta, el curso y la unidad con el corpus de T067 procesado, con las funciones de
   evaluation/collect_samples.py (como measure_duplication.py).
2. Crea --plans planes seguidos (20 por defecto) con POST /api/v1/generation-plans, la secuencia de V1
   (`pregunta_detonante`, `explicacion` con cantidad libre e `item_opcion_multiple` × 2) y una clave de idempotencia
   distinta cada vez. Mide el tiempo de cada POST en ms. No aprueba ni genera: los planes quedan en borrador.
3. Informa p50, p95 y máximo de los planes creados (201), cuántos fallaron y qué planificador armó cada plan
   (`generator.usesAi`, `fallback` y `attempts`): con LLM_PROVIDER=rules, todos de reglas.
4. Guarda los datos en evaluation/results/plan-latency-<planificador>-<fecha>.json (carpeta ignorada por git), o en
   --out.

Meta de V9: p95 < 1 s con reglas; con Gemini, p95 < 30 s (opcional, con la clave local, nunca en Render).

Solo contra un backend local (localhost, 127.0.0.1 o ::1): con otra URL se detiene antes de cualquier petición.
Nunca imprime ni guarda el token de sesión, la contraseña ni claves de API.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import time
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit

import httpx

BACKEND = Path(__file__).resolve().parents[1]
EVALUATION = BACKEND / "evaluation"
RESULTS = EVALUATION / "results"
PLANS_PATH = "/api/v1/generation-plans"
DEFAULT_PLANS = 20
# La secuencia de V1 (quickstart): la explicación con cantidad libre, que decide el planificador.
V1_TYPES: tuple[dict[str, Any], ...] = (
    {"type": "pregunta_detonante", "quantity": 1},
    {"type": "explicacion", "quantity": None},
    {"type": "item_opcion_multiple", "quantity": 2},
)
INSTRUCTIONS = "Protocolos de transporte TCP y UDP: conexión, confiabilidad, control de flujo y datagramas"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
# Meta de V9 con reglas (ms).
RULES_P95_TARGET_MS = 1000


def require_local(api: str) -> str:
    """La URL sin / al final, solo si apunta a este equipo. Cualquier otra (Render, un dominio) detiene el script."""
    host = urlsplit(api).hostname or ""
    if host not in LOCAL_HOSTS:
        raise SystemExit(f"Solo contra un backend local (localhost, 127.0.0.1 o ::1): {api} no lo es. Nada se envió.")
    return api.rstrip("/")


def percentile(values: Sequence[float], p: float) -> float | None:
    """Percentil con interpolación lineal entre rangos (el mismo criterio de measure_duplication.py)."""
    ordered = sorted(values)
    if not ordered:
        return None
    rank = (len(ordered) - 1) * p / 100
    low, high = math.floor(rank), math.ceil(rank)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (rank - low), 1)


def plan_body(unit_id: str, instructions: str = INSTRUCTIONS) -> dict[str, Any]:
    return {"unitId": unit_id, "instructions": instructions, "resourceTypes": [dict(t) for t in V1_TYPES]}


def plan_record(number: int, key: str, response: httpx.Response | None, ms: float | None,
                error: str | None = None) -> dict[str, Any]:
    """Lo que se guarda de cada plan: estado HTTP, tiempo y quién lo armó. Nunca el cuerpo completo."""
    body: dict[str, Any] = {}
    if response is not None:
        try:
            body = response.json() if isinstance(response.json(), dict) else {}
        except ValueError:
            body = {}
    generator = body.get("generator") or {}
    created = response is not None and response.status_code == 201
    return {
        "number": number,
        "key": key,
        "status": response.status_code if response is not None else None,
        "ms": round(ms, 1) if ms is not None else None,
        "planner": ("ai" if generator.get("usesAi") else "rules") if created else None,
        "usesAi": generator.get("usesAi") if created else None,
        "fallback": generator.get("fallback") if created else None,
        "attempts": generator.get("attempts") if created else None,
        "valid": (body.get("validation") or {}).get("valid") if created else None,
        "items": len(body.get("items") or []) if created else None,
        "errorCode": ((body.get("error") or {}).get("code")) if not created else None,
        "error": error,
    }


def summarize(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """p50, p95 y máximo de los planes creados, y qué planificador armó cada uno."""
    created = [r for r in records if r["status"] == 201]
    times = [r["ms"] for r in created if r["ms"] is not None]
    planners = Counter(r["planner"] for r in created)
    attempts = Counter(str(r["attempts"]) for r in created if r["usesAi"])
    p95 = percentile(times, 95)
    return {
        "plans": len(records),
        "created": len(created),
        "failed": len(records) - len(created),
        "invalid": sum(1 for r in created if r["valid"] is False),
        "p50Ms": percentile(times, 50),
        "p95Ms": p95,
        "maxMs": round(max(times), 1) if times else None,
        "planners": {"ai": planners.get("ai", 0), "rules": planners.get("rules", 0)},
        "aiFallbacks": sum(1 for r in created if r["fallback"]),
        "aiAttempts": dict(sorted(attempts.items())),
        "rulesTargetMs": RULES_P95_TARGET_MS,
        "meetsRulesTarget": (p95 is not None and p95 < RULES_P95_TARGET_MS) if planners.get("ai", 0) == 0 else None,
    }


def format_summary(summary: dict[str, Any]) -> str:
    planners = summary["planners"]
    lines = [
        f"Planes: {summary['created']} de {summary['plans']} creados ({summary['failed']} fallaron, "
        f"{summary['invalid']} con problemas de validación).",
        f"Tiempo de POST /generation-plans: p50 {summary['p50Ms']} ms · p95 {summary['p95Ms']} ms · "
        f"máximo {summary['maxMs']} ms.",
        f"Planificador: reglas {planners['rules']} · IA {planners['ai']} (respaldo {summary['aiFallbacks']}, "
        f"intentos {summary['aiAttempts'] or '—'}).",
    ]
    if summary["meetsRulesTarget"] is not None:
        verdict = "cumple" if summary["meetsRulesTarget"] else "NO cumple"
        lines.append(f"Meta de V9 con reglas (p95 < {RULES_P95_TARGET_MS} ms): {verdict}.")
    return "\n".join(lines)


def load_collect_samples() -> ModuleType:
    """Importa evaluation/collect_samples.py (no es un paquete) para reutilizar la cuenta, la unidad y el corpus."""
    spec = importlib.util.spec_from_file_location("collect_samples", EVALUATION / "collect_samples.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def create_plans(client: httpx.Client, headers: dict, unit_id: str, count: int, run_id: str,
                 instructions: str = INSTRUCTIONS) -> list[dict[str, Any]]:
    """Crea `count` planes seguidos y mide cada POST. Un fallo de red queda registrado y la medición sigue."""
    records = []
    for number in range(1, count + 1):
        key = f"plan-latency-{run_id}-{number}"
        started = time.perf_counter()
        try:
            response = client.post(PLANS_PATH, headers={**headers, "Idempotency-Key": key},
                                   json=plan_body(unit_id, instructions))
        except httpx.HTTPError as error:
            records.append(plan_record(number, key, None, None, f"{type(error).__name__}"))
            print(f"  plan {number}/{count}: sin respuesta ({type(error).__name__})")
            continue
        elapsed = (time.perf_counter() - started) * 1000
        record = plan_record(number, key, response, elapsed)
        records.append(record)
        print(f"  plan {number}/{count}: {response.status_code} · {elapsed:.0f} ms · {record['planner'] or '—'}")
    return records


def default_output(summary: dict[str, Any]) -> Path:
    planner = "ai" if summary["planners"]["ai"] else "rules"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return RESULTS / f"plan-latency-{planner}-{stamp}.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mide el tiempo de creación del plan de generación (T020, V9).")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="URL base del backend local (sin / al final)")
    parser.add_argument("--corpus", type=Path, default=EVALUATION / "corpus_t067")
    parser.add_argument("--plans", type=int, default=DEFAULT_PLANS, help="planes seguidos (20 por defecto)")
    parser.add_argument("--instructions", default=INSTRUCTIONS, help="tema del plan (debe estar en el material)")
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"),
                        help="marca de la corrida para las claves de idempotencia")
    parser.add_argument("--out", type=Path, default=None, help="archivo JSON del informe")
    return parser


def main(argv: Sequence[str] | None = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    api = require_local(args.api)  # antes de cualquier petición
    if args.plans < 1:
        raise SystemExit("--plans va desde 1.")
    email, password = os.getenv("EVAL_EMAIL"), os.getenv("EVAL_PASSWORD")
    if not email or not password:
        raise SystemExit("Define EVAL_EMAIL y EVAL_PASSWORD (la contraseña debe tener al menos 8 caracteres).")
    collect = load_collect_samples()
    with httpx.Client(base_url=api, timeout=120) as client:
        headers = collect.login(client, email, password)  # el token solo vive en memoria
        unit = collect.ensure_unit(client, headers)
        collect.ensure_materials(client, headers, unit, collect.corpus_files(args.corpus))
        generator = client.get("/api/v1/generator").json()
        print(f"Generador: {generator.get('description')} · unidad {unit['id']} · {args.plans} planes")
        records = create_plans(client, headers, unit["id"], args.plans, args.run_id, args.instructions)
    summary = summarize(records)
    report = {
        "measure": "T020 · tiempo de creación del plan (quickstart V9)",
        "api": api,
        "corpus": str(args.corpus),
        "runId": args.run_id,
        "generator": {"provider": generator.get("provider"), "description": generator.get("description")},
        "resourceTypes": [dict(t) for t in V1_TYPES],
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "plans": records,
    }
    output = args.out or default_output(summary)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(format_summary(summary))
    print(f"Datos: {output}")
    return report


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
