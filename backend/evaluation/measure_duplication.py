"""Mide la duplicación entre los recursos de una misma generación, con y sin plan (P4, GEN-P2, T019).

Las dos corridas usan el mismo servidor, el mismo código y la misma base; solo cambia GENERATION_IMPLICIT_PLAN al
arrancar el backend local (con Gemini, la clave local en la terminal del backend, nunca en Render). Los comandos
completos están en specs/006-plan-de-generacion/plan.md, «Medición de P4». Desde backend/:
    export EVAL_EMAIL=... EVAL_PASSWORD=...
    # backend con GENERATION_IMPLICIT_PLAN=false (solo para medir)
    python evaluation/measure_duplication.py --mode baseline --corpus evaluation/corpus_t067 --runs 3 --quantity 2 \\
        --out ../docs/evidence/GEN-P4/gemini-baseline.json
    # el mismo backend y la misma base, reiniciado con GENERATION_IMPLICIT_PLAN=true (por defecto)
    python evaluation/measure_duplication.py --mode plan --corpus evaluation/corpus_t067 --runs 3 --quantity 2 \\
        --out ../docs/evidence/GEN-P4/gemini-plan.json --compare ../docs/evidence/GEN-P4/gemini-baseline.json

Modos (specs/006-plan-de-generacion, research R7):
- `plan`: por cada corrida crea el plan (POST /api/v1/generation-plans), lo aprueba sin cambios y genera desde él
  (`{planId, planVersion}`).
- `baseline`: pide la misma secuencia con el cuerpo anterior. El servidor debe estar con GENERATION_IMPLICIT_PLAN=false,
  que redacta como antes de GEN-P1 (sin plan implícito, sin comprobación del plan, con los prompts de entonces). Si el
  pedido vuelve con un plan, el servidor tiene el interruptor encendido: la medición se detiene sin escribir el
  informe.

Las dos piden la misma secuencia (8 tipos de texto × --quantity recursos, la de measure_generation_load.py) con las
mismas indicaciones, sobre una unidad con el corpus de T067. Por cada generación calcula, entre cada par de recursos
entregados:
- la tasa de duplicación: pares con similitud ≥ --threshold (0,85 mientras REV-P3 no fije otro) ÷ total de pares;
- la similitud máxima media: el promedio, sobre los recursos, de su similitud más alta con otro de la generación.

La similitud es el coseno de los embeddings del título y el contenido si hay modelo de embeddings (`--similarity
embeddings`, o `auto` con LLM_API_KEY y EMBEDDINGS_ENABLED distinto de false); si no, la similitud léxica de
`most_similar` (Jaccard de palabras útiles, `domain/generation/sequence.py`), que el informe registra como
provisional. El informe JSON (--out) no guarda el correo, la contraseña ni el token.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx

HERE = Path(__file__).resolve().parent
REQUESTS_PATH = "/api/v1/generation-requests"
PLANS_PATH = "/api/v1/generation-plans"
FINAL_STATUSES = {"succeeded", "partially_succeeded", "failed", "interrupted"}
# La secuencia de 8 tipos de texto de measure_generation_load.py (research R7).
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
INSTRUCTIONS = "Protocolos de transporte TCP y UDP: conexión, confiabilidad, control de flujo y datagramas"
DEFAULT_THRESHOLD = 0.85
MODES = ("baseline", "plan")
SIMILARITIES = ("auto", "embeddings", "lexical")
IMPLICIT_PLAN_ON = (
    "El pedido de la línea base volvió con un plan: reinicia el backend con GENERATION_IMPLICIT_PLAN=false (solo para "
    "medir) y vuelve a correr --mode baseline."
)
SERVER_SETTING = {
    "plan": "GENERATION_IMPLICIT_PLAN=true (plan aprobado sin cambios)",
    "baseline": "GENERATION_IMPLICIT_PLAN=false (cuerpo anterior, redactado como antes de GEN-P1)",
}
LEXICAL_LABEL = "lexical (provisional: Jaccard de most_similar, sin REV-P3)"
EMBEDDINGS_LABEL = "embeddings (coseno)"

Similarity = Callable[[Sequence[str]], list[list[float]]]


# --------------------------------------------------------------------------- métricas (sin red)


def resource_text(resource: dict[str, Any]) -> str:
    """Texto comparable de un recurso tal como lo guarda Revisión: título, contenido, opciones y estructura."""
    parts = [str(resource.get("title") or ""), str(resource.get("body") or "")]
    parts += [str(option.get("text") or "") for option in resource.get("options") or []]

    def flatten(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict):
            for item in value.values():
                flatten(item)
        elif isinstance(value, list):
            for item in value:
                flatten(item)

    flatten(resource.get("structure"))
    return "\n".join(part for part in parts if part.strip())


def cosine(first: Sequence[float], second: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(first, second))
    norm = math.sqrt(sum(a * a for a in first)) * math.sqrt(sum(b * b for b in second))
    return dot / norm if norm else 0.0


def lexical_matrix(texts: Sequence[str]) -> list[list[float]]:
    """Similitud léxica de cada par: la de `most_similar` (proporción de palabras útiles compartidas)."""
    from platform5e.domain.generation.sequence import content_similarity

    return [[1.0 if i == j else content_similarity(a, b) for j, b in enumerate(texts)] for i, a in enumerate(texts)]


def embedding_matrix(embedder: Any) -> Similarity:
    """Similitud coseno de los embeddings de cada recurso (un vector por texto, en una sola llamada)."""

    def matrix(texts: Sequence[str]) -> list[list[float]]:
        vectors = embedder.embed_documents(list(texts)) if texts else []
        return [[cosine(a, b) for b in vectors] for a in vectors]

    return matrix


def duplication(texts: Sequence[str], similarity: Similarity, threshold: float) -> dict[str, Any]:
    """Pares duplicados y similitud máxima media de una generación."""
    count = len(texts)
    matrix = similarity(texts) if count > 1 else []
    pairs = [(i, j, matrix[i][j]) for i in range(count) for j in range(i + 1, count)]
    duplicated = [(i, j, round(score, 4)) for i, j, score in pairs if score >= threshold]
    maxima = [max(matrix[i][j] for j in range(count) if j != i) for i in range(count)] if count > 1 else []
    return {
        "resources": count,
        "pairs": len(pairs),
        "duplicatePairs": len(duplicated),
        "duplicateRate": round(len(duplicated) / len(pairs), 4) if pairs else 0.0,
        "meanMaxSimilarity": round(sum(maxima) / len(maxima), 4) if maxima else None,
        "duplicates": [{"first": i, "second": j, "similarity": score} for i, j, score in duplicated],
    }


def summarize(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Promedios de las corridas terminadas: tasa de duplicación, similitud máxima media y recursos por pedido."""
    done = [run for run in runs if run.get("metrics")]
    rates = [run["metrics"]["duplicateRate"] for run in done]
    maxima = [run["metrics"]["meanMaxSimilarity"] for run in done if run["metrics"]["meanMaxSimilarity"] is not None]
    resources = [run["metrics"]["resources"] for run in done]
    pairs = sum(run["metrics"]["pairs"] for run in done)
    duplicated = sum(run["metrics"]["duplicatePairs"] for run in done)
    return {
        "runs": len(runs),
        "finishedRuns": len(done),
        "duplicateRate": round(duplicated / pairs, 4) if pairs else None,
        "meanDuplicateRatePerRun": round(sum(rates) / len(rates), 4) if rates else None,
        "meanMaxSimilarity": round(sum(maxima) / len(maxima), 4) if maxima else None,
        "resourcesPerRequest": round(sum(resources) / len(resources), 2) if resources else None,
    }


def compare(baseline: dict[str, Any], planned: dict[str, Any]) -> dict[str, Any]:
    """Meta de P4: duplicación con plan ≤ 5 % y al menos 50 % menos que la línea base, sin perder recursos."""
    before, after = baseline.get("duplicateRate"), planned.get("duplicateRate")
    reduction = None if not before or after is None else round(1 - after / before, 4)
    fewer = (planned.get("resourcesPerRequest") or 0) < (baseline.get("resourcesPerRequest") or 0)
    return {
        "reduction": reduction,
        "meetsTarget": after is not None and after <= 0.05 and (before == 0 or (reduction or 0) >= 0.5)
        and not fewer,
        "resourcesKept": not fewer,
    }


# --------------------------------------------------------------------------- HTTP


def load_collect_samples() -> ModuleType:
    """Importa evaluation/collect_samples.py (no es un paquete) para reutilizar la cuenta, la unidad y el corpus."""
    spec = importlib.util.spec_from_file_location("collect_samples", HERE / "collect_samples.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def baseline_body(unit_id: str, types: Sequence[str], quantity: int) -> dict[str, Any]:
    return {"mode": "sequence", "unitId": unit_id, "resourceTypes": list(types), "quantity": quantity,
            "instructions": INSTRUCTIONS}


def plan_body(unit_id: str, types: Sequence[str], quantity: int) -> dict[str, Any]:
    return {"unitId": unit_id, "instructions": INSTRUCTIONS,
            "resourceTypes": [{"type": resource_type, "quantity": quantity} for resource_type in types]}


def _failure(response: httpx.Response, stage: str) -> dict[str, Any]:
    try:
        error = response.json().get("error") or {}
    except ValueError:
        error = {}
    return {"stage": stage, "status": response.status_code, "code": error.get("code"), "message": error.get("message")}


def start_run(
    client: httpx.Client, headers: dict, unit_id: str, mode: str, types: Sequence[str], quantity: int, key: str
) -> tuple[str | None, dict[str, Any]]:
    """Inicia la generación de una corrida. Devuelve (id del pedido o None, datos de la corrida)."""
    record: dict[str, Any] = {"key": key}
    if mode == "baseline":
        body = baseline_body(unit_id, types, quantity)
    else:
        created = client.post(PLANS_PATH, headers={**headers, "Idempotency-Key": f"{key}-plan"},
                              json=plan_body(unit_id, types, quantity))
        if created.status_code not in (200, 201):
            return None, {**record, "failure": _failure(created, "plan")}
        plan = created.json()
        approved = client.post(f"{PLANS_PATH}/{plan['id']}/approve", headers=headers,
                               json={"expectedVersion": plan["version"]})
        if approved.status_code != 200:
            return None, {**record, "failure": _failure(approved, "approve")}
        record.update(planId=plan["id"], planGenerator=plan.get("generator"), planItems=len(plan.get("items", [])))
        body = {"planId": plan["id"], "planVersion": approved.json()["version"]}
    started = client.post(REQUESTS_PATH, headers={**headers, "Idempotency-Key": key}, json=body)
    if started.status_code not in (200, 202):
        return None, {**record, "failure": _failure(started, "generate")}
    plan_id = started.json().get("planId")
    if mode == "baseline" and plan_id:
        raise SystemExit(IMPLICIT_PLAN_ON)
    return started.json()["id"], {**record, "requestId": started.json()["id"], "requestPlanId": plan_id}


def wait_final(client: httpx.Client, headers: dict, request_id: str, poll: float, deadline: float) -> dict | None:
    while True:
        response = client.get(f"{REQUESTS_PATH}/{request_id}", headers=headers)
        if response.status_code == 200 and response.json().get("status") in FINAL_STATUSES:
            return response.json()
        if time.monotonic() >= deadline:
            return None
        time.sleep(min(poll, max(0.0, deadline - time.monotonic())))


def delivered_resources(client: httpx.Client, headers: dict, unit_id: str, status: dict) -> list[dict[str, Any]]:
    """Los recursos que entregó el pedido, en el orden de sus pasos, tal como los guarda Revisión."""
    stored = {r["id"]: r for r in client.get(f"/api/v1/units/{unit_id}/resources", headers=headers).json()}
    ids = [rid for step in status.get("steps", []) for rid in step.get("resourceIds", [])]
    return [stored[rid] for rid in ids if rid in stored]


def measure_run(
    client: httpx.Client,
    headers: dict,
    unit_id: str,
    mode: str,
    types: Sequence[str],
    quantity: int,
    key: str,
    similarity: Similarity,
    threshold: float,
    poll: float,
    deadline: float,
) -> dict[str, Any]:
    """Una corrida: genera, espera el estado final y mide la duplicación entre sus recursos."""
    request_id, record = start_run(client, headers, unit_id, mode, types, quantity, key)
    if request_id is None:
        return record
    status = wait_final(client, headers, request_id, poll, deadline)
    if status is None:
        return {**record, "failure": {"stage": "wait", "code": "TIMEOUT"}}
    resources = delivered_resources(client, headers, unit_id, status)
    metrics = duplication([resource_text(r) for r in resources], similarity, threshold)
    titles = [r.get("title") for r in resources]
    for pair in metrics["duplicates"]:
        pair["titles"] = [titles[pair["first"]], titles[pair["second"]]]
    rejections = [r["kind"] for step in status.get("steps", []) for r in step.get("rejections", [])]
    return {
        **record,
        "status": status.get("status"),
        "steps": [{"resourceType": s.get("resourceType"), "planItemPosition": s.get("planItemPosition"),
                   "delivered": len(s.get("resourceIds", [])), "usesAi": (s.get("generator") or {}).get("usesAi"),
                   "fallback": (s.get("generator") or {}).get("fallback")} for s in status.get("steps", [])],
        "rejectionKinds": {kind: rejections.count(kind) for kind in sorted(set(rejections))},
        "metrics": metrics,
    }


def choose_similarity(name: str, embedder_factory: Callable[[], Any] | None = None) -> tuple[Similarity, str]:
    """La similitud pedida. `auto` usa embeddings si hay modelo; si no, la léxica (provisional)."""
    if name in ("auto", "embeddings"):
        factory = embedder_factory
        if factory is None:
            from platform5e.infrastructure.llm.language_model_factory import create_embedding_generator

            factory = create_embedding_generator
        embedder = factory()
        if embedder is not None:
            return embedding_matrix(embedder), f"{EMBEDDINGS_LABEL}, {getattr(embedder, 'model', 'modelo')}"
        if name == "embeddings":
            raise SystemExit("No hay modelo de embeddings: define LLM_API_KEY y EMBEDDINGS_ENABLED, o usa "
                             "--similarity lexical.")
    return lexical_matrix, LEXICAL_LABEL


def build_report(args: argparse.Namespace, similarity_label: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "measure": "P4 · duplicación entre recursos de una misma generación",
        "mode": args.mode,
        "api": args.api,
        "corpus": str(args.corpus),
        "resourceTypes": list(args.types),
        "quantity": args.quantity,
        "threshold": args.threshold,
        "similarity": similarity_label,
        "server": SERVER_SETTING[args.mode],
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "summary": summarize(runs),
        "runs": runs,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mide la duplicación con y sin plan (P4, GEN-P2).")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="URL base del backend (sin / al final)")
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--corpus", type=Path, default=HERE / "corpus_t067")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--quantity", type=int, default=2, help="recursos por tipo (de 1 a 5)")
    parser.add_argument("--types", nargs="+", default=list(SEQUENCE_TYPES))
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="τ: similitud de un duplicado")
    parser.add_argument("--similarity", choices=SIMILARITIES, default="auto")
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    parser.add_argument("--poll", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=30 * 60, help="segundos máximos por corrida")
    parser.add_argument("--out", type=Path, required=True, help="archivo JSON del informe")
    parser.add_argument("--compare", type=Path, default=None,
                        help="informe de la línea base: agrega la comparación con la meta de P4")
    return parser


def main(argv: Sequence[str] | None = None, embedder_factory: Callable[[], Any] | None = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    if not 1 <= args.quantity <= 5:
        raise SystemExit("--quantity va de 1 a 5.")
    if not 0 < args.threshold <= 1:
        raise SystemExit("--threshold va de 0 a 1.")
    email, password = os.environ.get("EVAL_EMAIL"), os.environ.get("EVAL_PASSWORD")
    if not email or not password:
        raise SystemExit("Define EVAL_EMAIL y EVAL_PASSWORD.")
    similarity, label = choose_similarity(args.similarity, embedder_factory)
    collect = load_collect_samples()
    runs: list[dict[str, Any]] = []
    with httpx.Client(base_url=args.api, timeout=120) as client:
        headers = collect.login(client, email, password)
        unit = collect.ensure_unit(client, headers)
        collect.ensure_materials(client, headers, unit, collect.corpus_files(args.corpus))
        for number in range(1, args.runs + 1):
            key = f"p4-{args.mode}-{args.run_id}-{number}"
            print(f"Corrida {number} de {args.runs} ({args.mode})…")
            runs.append(measure_run(client, headers, unit["id"], args.mode, args.types, args.quantity, key,
                                    similarity, args.threshold, args.poll, time.monotonic() + args.timeout))
    report = build_report(args, label, runs)
    if args.compare is not None:
        baseline = json.loads(args.compare.read_text(encoding="utf-8"))
        report["comparison"] = compare(baseline["summary"], report["summary"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = report["summary"]
    print(f"Tasa de duplicación: {summary['duplicateRate']} · similitud máxima media: {summary['meanMaxSimilarity']} "
          f"· recursos por pedido: {summary['resourcesPerRequest']} ({label}). Informe: {args.out}")
    return report


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
