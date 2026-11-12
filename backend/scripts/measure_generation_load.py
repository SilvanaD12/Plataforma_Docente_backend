"""GEN-01 · T044 (quickstart V11, research R4): medición de carga de los pedidos de generación.

Uso (desde backend/, con el servidor en marcha):
    export EVAL_EMAIL=... EVAL_PASSWORD=...
    python scripts/measure_generation_load.py --api http://127.0.0.1:8000

Qué hace:
1. Prepara la cuenta, el curso y la unidad con material con las funciones de evaluation/collect_samples.py.
2. Comprobación de concurrencia: lanza a la vez 3 secuencias con claves distintas. Espera 2 aceptadas (202) y la tercera
   rechazada con 429 TOO_MANY_ACTIVE_REQUESTS y Retry-After. Las dos aceptadas se esperan hasta su estado final y se
   guardan aparte: no entran en los percentiles.
3. Medición: 5 secuencias de 8 tipos x 5 recursos, respetando el límite de 2 pedidos activos (ante un 429 espera
   Retry-After y reenvía con la misma clave). Consulta cada pedido hasta un estado final.
4. Imprime el resumen y guarda los datos en evaluation/results/load-<proveedor>-<fecha>.json (carpeta ignorada por git).

Fallos de red: un envío de la comprobación de concurrencia que falla queda registrado (tipo y mensaje corto) y la
comprobación sale «INCONCLUSO». Un pedido aceptado cuyo estado no se pudo leer, o que no terminó antes de --timeout,
queda en el informe con su último estado conocido (o «unknown») y el error; los percentiles usan solo los pedidos
terminados y, si terminaron menos de 5, la corrida queda marcada como incompleta (`complete: false`).

Llamadas al modelo: la API no las cuenta. El script da una estimación por paso con lo que sí informa la API
(`generator.usesAi`, `generator.fallback` y los rechazos `repetition`); ver `step_model_calls`.

Nunca imprime ni guarda el token de sesión, la contraseña ni claves de API.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import statistics
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx

BACKEND = Path(__file__).resolve().parents[1]
EVALUATION = BACKEND / "evaluation"
RESULTS = EVALUATION / "results"
REQUESTS_PATH = "/api/v1/generation-requests"
FINAL_STATUSES = {"succeeded", "partially_succeeded", "failed", "interrupted"}
# Los 8 tipos de texto del catálogo original: cubren las 5 etapas 5E y no piden imagen ni audio.
SEQUENCE_TYPES: tuple[str, ...] = (
    "pregunta_detonante",
    "sondeo_diagnostico",
    "guia_exploracion",
    "caso_indagacion",
    "explicacion",
    "glosario",
    "ejercicio_aplicacion",
    "item_opcion_multiple",
)
QUANTITY = 5
SEQUENCES = 5
CONCURRENT_STARTS = 3


# --------------------------------------------------------------------------- cálculos (sin red)


def percentile(values: list[float], p: float) -> float | None:
    """Percentil con interpolación lineal entre rangos (como numpy por defecto). None sin valores."""
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * p / 100
    low, high = int(rank), min(int(rank) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def network_error(error: Exception) -> dict[str, str]:
    """Tipo y mensaje corto de un fallo de red. Las excepciones de httpx no incluyen cabeceras (ni la sesión)."""
    return {"type": type(error).__name__, "message": str(error)[:200]}


def parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def request_durations(status: dict) -> tuple[float | None, float | None]:
    """(finishedAt - createdAt, finishedAt - startedAt) en segundos; None si falta alguna marca."""
    created, started, finished = (parse_time(status.get(k)) for k in ("createdAt", "startedAt", "finishedAt"))
    total = (finished - created).total_seconds() if finished and created else None
    run = (finished - started).total_seconds() if finished and started else None
    return total, run


def step_model_calls(step: dict) -> dict[str, Any]:
    """Estimación de llamadas de un paso a partir de lo que informa la API.

    `draft_step` pide una redacción (`draft_resources`) y la repite una vez si algún recurso repite a otro de la
    secuencia. `draft_resources` llama al generador principal y, si no devuelve recursos válidos, al de respaldo.

    - `generatorCalls`: redacciones pedidas, cota inferior. Es 2 solo si se ve un rechazo `repetition`: si el reintento
      sí corrigió la repetición, no queda rastro en la respuesta.
    - `aiCallsMin` / `aiCallsMax`: llamadas al modelo de IA. Solo si el principal es IA (`usesAi`, o `fallback`, que
      solo existe cuando el principal no es el de reglas). La cota superior suma el reintento de repetición posible y el
      reintento interno del adaptador de Gemini cuando la respuesta no es JSON válido.
    - Un paso sin `generator` (no llegó a redactar, por ejemplo por DEADLINE_EXCEEDED) no hizo llamadas.
    """
    generator = step.get("generator")
    if not generator:
        return {"generatorCalls": 0, "aiCallsMin": 0, "aiCallsMax": 0, "repetitionRetry": False}
    repetition = any(r.get("kind") == "repetition" for r in step.get("rejections") or [])
    drafts_min, drafts_max = (2, 2) if repetition else (1, 2)
    ai_primary = bool(generator.get("usesAi") or generator.get("fallback"))
    return {
        "generatorCalls": drafts_min,
        "aiCallsMin": drafts_min if ai_primary else 0,
        "aiCallsMax": drafts_max * 2 if ai_primary else 0,
        "repetitionRetry": repetition,
    }


def request_record(status: dict, key: str, error: dict | None = None) -> dict[str, Any]:
    """Lo que se guarda de un pedido terminado (o del último estado visto, con el último error de consulta)."""
    total, run = request_durations(status)
    steps = []
    for step in status.get("steps") or []:
        error = step.get("error") or {}
        steps.append({
            "position": step.get("position"),
            "stage": step.get("stage"),
            "resourceType": step.get("resourceType"),
            "status": step.get("status"),
            "resources": len(step.get("resourceIds") or []),
            "rejections": [{"kind": r.get("kind"), "reason": r.get("reason")} for r in step.get("rejections") or []],
            "usesAi": (step.get("generator") or {}).get("usesAi"),
            "fallback": (step.get("generator") or {}).get("fallback"),
            "errorCode": error.get("code"),
            "deadlineExceeded": error.get("code") == "DEADLINE_EXCEEDED",
            "modelCalls": step_model_calls(step),
            "startedAt": step.get("startedAt"),
            "finishedAt": step.get("finishedAt"),
        })
    return {
        "id": status.get("id"),
        "idempotencyKey": key,
        "status": status.get("status"),
        "finished": status.get("status") in FINAL_STATUSES,
        "error": error,
        "retrievalMode": status.get("retrievalMode"),
        "failure": status.get("failure"),
        "createdAt": status.get("createdAt"),
        "startedAt": status.get("startedAt"),
        "finishedAt": status.get("finishedAt"),
        "durationSeconds": total,
        "runSeconds": run,
        "steps": steps,
    }


def unknown_record(request_id: str, key: str, error: dict | None) -> dict[str, Any]:
    """Pedido aceptado cuyo estado nunca se pudo leer: queda en el informe como «unknown», sin terminar."""
    return {
        "id": request_id, "idempotencyKey": key, "status": "unknown", "finished": False, "error": error,
        "retrievalMode": None, "failure": None, "createdAt": None, "startedAt": None, "finishedAt": None,
        "durationSeconds": None, "runSeconds": None, "steps": [],
    }


def records_for(ids: dict[str, str], last: dict[str, dict], errors: dict[str, dict]) -> list[dict[str, Any]]:
    """Un registro por pedido aceptado (id → clave), también si su estado no se pudo leer o no terminó."""
    return [
        request_record(last[i], k, errors.get(i)) if i in last else unknown_record(i, k, errors.get(i))
        for i, k in ids.items()
    ]


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "avg": None, "max": None}
    return {"min": min(values), "avg": round(statistics.fmean(values), 2), "max": max(values)}


def summarize(records: list[dict], concurrency: dict | None, expected: int = SEQUENCES) -> dict[str, Any]:
    """Resumen de los pedidos medidos (los de la comprobación de concurrencia no entran). Los percentiles usan solo
    los pedidos que terminaron; la corrida queda incompleta si terminaron menos de `expected`."""
    finished = [r for r in records if r.get("finished", r["status"] in FINAL_STATUSES)]
    totals = [r["durationSeconds"] for r in finished if r["durationSeconds"] is not None]
    runs = [r["runSeconds"] for r in finished if r["runSeconds"] is not None]
    steps = [s for r in records for s in r["steps"]]
    calls = [s["modelCalls"] for s in steps]
    return {
        "requests": len(records),
        "expectedRequests": expected,
        "finishedRequests": len(finished),
        "unfinishedRequests": [r["id"] for r in records if r not in finished],
        "complete": len(finished) >= expected,
        "percentileSample": len(totals),
        "byStatus": {
            status: sum(r["status"] == status for r in records) for status in sorted({r["status"] for r in records})
        },
        "durationSeconds": {"p50": percentile(totals, 50), "p95": percentile(totals, 95)},
        "runSeconds": {"p50": percentile(runs, 50), "p95": percentile(runs, 95)},
        "resources": sum(s["resources"] for s in steps),
        "rejections": sum(len(s["rejections"]) for s in steps),
        "rejectionsByKind": {
            kind: sum(1 for s in steps for r in s["rejections"] if r["kind"] == kind)
            for kind in sorted({r["kind"] for s in steps for r in s["rejections"]})
        },
        "fallbackSteps": sum(bool(s["fallback"]) for s in steps),
        "steps": len(steps),
        "generatorCallsPerStep": _stats([c["generatorCalls"] for c in calls]),
        "aiCallsPerStepMin": _stats([c["aiCallsMin"] for c in calls]),
        "aiCallsPerStepMax": _stats([c["aiCallsMax"] for c in calls]),
        "deadlineExceededSteps": sum(s["deadlineExceeded"] for s in steps),
        "deadlineExceededRequests": sum(any(s["deadlineExceeded"] for s in r["steps"]) for r in records),
        "concurrencyCheck": (concurrency or {}).get("result"),
    }


def format_summary(summary: dict[str, Any], provider: str) -> str:
    def seconds(value: float | None) -> str:
        return "—" if value is None else f"{value:.1f} s"

    def p50_p95(block: dict) -> str:
        return f"{seconds(block['p50'])} / {seconds(block['p95'])}"

    def stats(block: dict) -> str:
        return "—" if block["min"] is None else f"{block['min']} / {block['avg']} / {block['max']}"

    rows = [
        ("Proveedor", provider),
        ("Pedidos medidos", f"{summary['requests']} {summary['byStatus']}"),
        ("Pedidos terminados (usados en percentiles)",
         f"{summary['finishedRequests']} ({summary['percentileSample']})"),
        ("Duración creado→terminado p50 / p95", p50_p95(summary["durationSeconds"])),
        ("Duración iniciado→terminado p50 / p95", p50_p95(summary["runSeconds"])),
        ("Recursos entregados", str(summary["resources"])),
        ("Rechazos", f"{summary['rejections']} {summary['rejectionsByKind']}"),
        ("Pasos con respaldo de redacción", f"{summary['fallbackSteps']} de {summary['steps']}"),
        ("Redacciones por paso (mín / prom / máx, cota inferior)", stats(summary["generatorCallsPerStep"])),
        ("Llamadas a IA por paso, cota inferior (mín / prom / máx)", stats(summary["aiCallsPerStepMin"])),
        ("Llamadas a IA por paso, cota superior (mín / prom / máx)", stats(summary["aiCallsPerStepMax"])),
        ("DEADLINE_EXCEEDED (pasos / pedidos)",
         f"{summary['deadlineExceededSteps']} / {summary['deadlineExceededRequests']}"),
        ("Comprobación 3 simultáneos → 2×202 + 429", summary["concurrencyCheck"] or "—"),
    ]
    width = max(len(label) for label, _ in rows)
    text = "\n".join(f"{label.ljust(width)}  {value}" for label, value in rows)
    if not summary["complete"]:
        text += (f"\nCorrida incompleta: {summary['finishedRequests']} de {summary['expectedRequests']} pedidos "
                 f"terminaron (sin terminar: {', '.join(summary['unfinishedRequests']) or '—'})")
    return text


# --------------------------------------------------------------------------- HTTP


def load_collect_samples() -> ModuleType:
    """Importa evaluation/collect_samples.py (no es un paquete) para reutilizar su preparación."""
    spec = importlib.util.spec_from_file_location("collect_samples", EVALUATION / "collect_samples.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def sequence_body(unit_id: str) -> dict[str, Any]:
    return {"mode": "sequence", "unitId": unit_id, "resourceTypes": list(SEQUENCE_TYPES), "quantity": QUANTITY}


def post_request(client: httpx.Client, headers: dict, key: str, body: dict) -> httpx.Response:
    return client.post(REQUESTS_PATH, headers={**headers, "Idempotency-Key": key}, json=body)


def wait_final(
    client: httpx.Client, headers: dict, ids: dict[str, str], poll: float, deadline: float
) -> tuple[dict[str, dict], dict[str, dict]]:
    """Consulta los pedidos (id → clave) hasta su estado final o hasta `deadline`. Devuelve (último estado leído de
    cada uno, último error de consulta de cada uno). Un fallo de red o una respuesta que no es 200 no corta la
    espera: se reintenta en la consulta siguiente."""
    last: dict[str, dict] = {}
    errors: dict[str, dict] = {}
    pending = set(ids)
    while pending:
        for request_id in sorted(pending):
            try:
                response = client.get(f"{REQUESTS_PATH}/{request_id}", headers=headers)
            except httpx.HTTPError as error:
                errors[request_id] = network_error(error)
                continue
            if response.status_code != 200:
                errors[request_id] = {"type": "HTTP", "message": f"HTTP {response.status_code}"}
                continue
            last[request_id] = response.json()
            errors.pop(request_id, None)
            if last[request_id].get("status") in FINAL_STATUSES:
                pending.discard(request_id)
        if not pending or time.monotonic() >= deadline:
            break
        time.sleep(min(poll, max(0.0, deadline - time.monotonic())))
    return last, errors


def wait_no_active(client: httpx.Client, headers: dict, unit_id: str, poll: float, deadline: float) -> None:
    """Antes de medir, espera a que el docente no tenga pedidos activos (por ejemplo, de una corrida anterior)."""
    while time.monotonic() < deadline:
        active = client.get(REQUESTS_PATH, headers=headers, params={"unitId": unit_id, "active": "true"}).json()
        if not active:
            return
        print(f"  esperando {len(active)} pedido(s) activo(s) de antes")
        time.sleep(poll)


def concurrency_check(api: str, headers: dict, unit_id: str, run_id: str) -> dict[str, Any]:
    """Lanza 3 secuencias a la vez con claves distintas: deben quedar 2 aceptadas (202) y una 429 con Retry-After."""
    barrier = threading.Barrier(CONCURRENT_STARTS)
    answers: list[dict[str, Any]] = [{} for _ in range(CONCURRENT_STARTS)]

    def start(index: int) -> None:
        key = f"load-{run_id}-concurrency-{index}"
        try:
            with httpx.Client(base_url=api, timeout=60) as client:
                barrier.wait(timeout=30)
                response = post_request(client, headers, key, sequence_body(unit_id))
        except httpx.HTTPError as error:  # el envío no llegó o no respondió: se registra y la medición sigue
            answers[index] = {"key": key, "status": None, "retryAfter": None, "requestId": None, "errorCode": None,
                              "error": network_error(error)}
            return
        body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        answers[index] = {
            "key": key,
            "status": response.status_code,
            "retryAfter": response.headers.get("Retry-After"),
            "requestId": body.get("id") if response.status_code in (200, 202) else None,
            "errorCode": (body.get("error") or {}).get("code"),
        }

    threads = [threading.Thread(target=start, args=(i,)) for i in range(CONCURRENT_STARTS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=90)
    for index, answer in enumerate(answers):
        if not answer:  # el hilo no terminó a tiempo
            answers[index] = {"key": f"load-{run_id}-concurrency-{index}", "status": None, "retryAfter": None,
                              "requestId": None, "errorCode": None,
                              "error": {"type": "Timeout", "message": "el envío no terminó a tiempo"}}
    failed = sum(1 for a in answers if a.get("error"))
    if failed:
        sent = "1 envío falló" if failed == 1 else f"{failed} envíos fallaron"
        return {"answers": answers, "result": f"INCONCLUSO: {sent} por red"}
    statuses = sorted(a["status"] for a in answers)
    rejected = [a for a in answers if a["status"] == 429]
    passed = (
        statuses == [202, 202, 429]
        and rejected[0]["errorCode"] == "TOO_MANY_ACTIVE_REQUESTS"
        and bool(rejected[0]["retryAfter"])
    )
    return {"answers": answers, "result": "OK" if passed else f"FALLA (estados {statuses})"}


def submit_measured(
    client: httpx.Client, headers: dict, unit_id: str, run_id: str, poll: float, deadline: float
) -> tuple[dict[str, str], list[dict]]:
    """Envía las secuencias medidas respetando el límite de 2 activos. Devuelve (id → clave, rechazos
    definitivos)."""
    submitted: dict[str, str] = {}
    refused: list[dict] = []
    for number in range(SEQUENCES):
        key = f"load-{run_id}-sequence-{number}"
        while time.monotonic() < deadline:
            response = post_request(client, headers, key, sequence_body(unit_id))
            if response.status_code in (200, 202):
                submitted[response.json()["id"]] = key
                print(f"  secuencia {number + 1}/{SEQUENCES} aceptada ({response.status_code})")
                break
            if response.status_code == 429:
                wait = float(response.headers.get("Retry-After") or poll)
                time.sleep(min(wait, max(0.0, deadline - time.monotonic())))
                continue
            refused.append({"key": key, "status": response.status_code, "body": response.text[:300]})
            print(f"  secuencia {number + 1}/{SEQUENCES} rechazada ({response.status_code})")
            break
    return submitted, refused


def run_measurement(
    client: httpx.Client, api: str, headers: dict, unit_id: str, run_id: str, poll: float, deadline: float
) -> dict[str, Any]:
    """Comprobación de concurrencia y medición. Devuelve las partes del informe (sin escribirlo)."""
    print("Comprobación de concurrencia (3 secuencias a la vez)…")
    concurrency = concurrency_check(api, headers, unit_id, run_id)
    print(f"  {concurrency['result']}")
    accepted = {a["requestId"]: a["key"] for a in concurrency["answers"] if a.get("requestId")}
    warmup, warmup_errors = wait_final(client, headers, accepted, poll, deadline)
    concurrency["requests"] = records_for(accepted, warmup, warmup_errors)

    print(f"Medición: {SEQUENCES} secuencias de {len(SEQUENCE_TYPES)} tipos x {QUANTITY}…")
    submitted, refused = submit_measured(client, headers, unit_id, run_id, poll, deadline)
    final, errors = wait_final(client, headers, submitted, poll, deadline)

    records = records_for(submitted, final, errors)
    summary = summarize(records, concurrency)
    summary["refused"] = len(refused)
    return {
        "complete": summary["complete"],
        "types": list(SEQUENCE_TYPES),
        "quantity": QUANTITY,
        "sequences": SEQUENCES,
        "concurrency": concurrency,
        "requests": records,
        "refused": refused,
        "summary": summary,
    }


def write_report(report: dict[str, Any], provider: str) -> Path:
    """Escribe el informe en evaluation/results/load-<proveedor>-<fecha>.json (sin la sesión ni claves)."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = RESULTS / f"load-{provider}-{stamp}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Mide la carga de los pedidos de generación (GEN-01, T044).")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="URL base del backend (sin / al final)")
    parser.add_argument("--corpus", type=Path, default=EVALUATION / "corpus" / "protocols.txt")
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"),
                        help="marca de la corrida para las claves de idempotencia")
    parser.add_argument("--timeout", type=float, default=40 * 60, help="segundos máximos de toda la medición")
    parser.add_argument("--poll", type=float, default=2.0, help="segundos entre consultas de estado")
    args = parser.parse_args()

    collect = load_collect_samples()
    email, password = os.getenv("EVAL_EMAIL"), os.getenv("EVAL_PASSWORD")
    if not email or not password:
        collect.fail("define EVAL_EMAIL y EVAL_PASSWORD (la contraseña debe tener al menos 8 caracteres)")
    deadline = time.monotonic() + args.timeout
    api = args.api.rstrip("/")

    with httpx.Client(base_url=api, timeout=60) as client:
        headers = collect.login(client, email, password)  # el token solo vive en memoria
        unit = collect.ensure_unit(client, headers)
        collect.ensure_material(client, headers, unit, args.corpus)
        generator = client.get("/api/v1/generator").json()
        provider = str(generator.get("provider") or "desconocido")
        print(f"Generador: {generator.get('description')} · unidad {unit['id']}")
        wait_no_active(client, headers, unit["id"], args.poll, deadline)

        report = run_measurement(client, api, headers, unit["id"], args.run_id, args.poll, deadline)

    report = {"api": api, "runId": args.run_id, "generator": generator, **report}
    output = write_report(report, provider)
    print()
    print(format_summary(report["summary"], provider))
    print(f"Datos: {output.relative_to(BACKEND)}")


if __name__ == "__main__":
    sys.exit(main())
