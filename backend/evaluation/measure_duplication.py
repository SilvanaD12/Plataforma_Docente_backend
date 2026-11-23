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

Métricas de contenido (segunda corrida de P4, research R7), la evidencia principal de «no repetición»:
- **Oraciones casi repetidas:** la parte de las oraciones (normalizadas, de 8 palabras o más) que tienen una casi igual
  en otro recurso de la misma generación: coseno de embeddings ≥ --sentence-threshold (0,92 por defecto, a calibrar),
  o Jaccard ≥ 0,6 sin embeddings.
- **Conceptos explicados otra vez:** los conceptos que se definen o se desarrollan (en dos oraciones, o con una
  definición, la regla de `plan_coverage.develops_concept`) en más de un recurso. `conceptReexplanation` usa los
  conceptos del plan si hay plan y los de la evidencia si no; `conceptReexplanationEvidence` usa en los dos modos los
  conceptos candidatos de la evidencia del pedido (la extracción del planificador por reglas), así se comparan igual.
  Los dos modos piden 12 fragmentos (`topK`), la misma evidencia.

Calibración (--calibrate --from informe.json …): con los recursos guardados en informes anteriores (o leídos de la API
si el informe no los trae), calcula la similitud de pares que no repiten contenido (tipos distintos de ítems distintos
del plan, y pares de corpus distintos si hay informes de otro corpus) y de pares repetidos (el mismo texto con sus
oraciones en otro orden, y medio recurso copiado), en recursos y en oraciones, y sugiere los umbrales.

Además, por cada corrida, cuántos pasos redactó la IA (`aiSteps`), cuántos el respaldo por reglas porque la IA falló
(`fallbackSteps`), cuántos el generador por reglas como principal (`rulesSteps`), y los avisos de solapamiento del
plan (`planWarnings`: recursos de la IA entregados aunque no respetaron del todo su plan, research R5). Así la
comparación muestra si la duplicación baja con recursos de la IA o porque los redactó el respaldo.

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
import re
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
DEFAULT_RUNS = 5
TOP_K = 12  # los dos modos piden la misma evidencia: el plan recupera 12 fragmentos por defecto
MIN_SENTENCE_WORDS = 8
# Umbrales de oración casi repetida hasta calibrarlos (--calibrate): coseno de embeddings y Jaccard léxico.
DEFAULT_SENTENCE_THRESHOLDS = {"embeddings": 0.92, "lexical": 0.6}
MAX_MEASURED_CONCEPTS = 20
MAX_EXAMPLES = 5
MAX_CALIBRATION_SENTENCE_PAIRS = 500
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


def resource_sentences(text: str) -> list[str]:
    """Las oraciones del recurso con 8 palabras o más, sin espacios repetidos."""
    from platform5e.domain.materials.chunking import extract_sentences

    sentences = [" ".join(sentence.split()) for sentence in extract_sentences(text or "")]
    return [sentence for sentence in sentences if len(re.findall(r"\w+", sentence)) >= MIN_SENTENCE_WORDS]


def near_duplicate_sentences(
    by_resource: Sequence[Sequence[str]], similarity: Similarity, threshold: float
) -> dict[str, Any]:
    """La parte de las oraciones que tienen una casi igual en otro recurso de la misma generación."""
    owners = [index for index, sentences in enumerate(by_resource) for _ in sentences]
    sentences = [sentence for group in by_resource for sentence in group]
    if not sentences:
        return {"sentences": 0, "nearDuplicateSentences": 0, "rate": None, "threshold": threshold, "examples": []}
    matrix = similarity(sentences)
    repeated: set[int] = set()
    examples: list[dict[str, Any]] = []
    for i in range(len(sentences)):
        for j in range(i + 1, len(sentences)):
            if owners[i] != owners[j] and matrix[i][j] >= threshold:
                repeated.update((i, j))
                if len(examples) < MAX_EXAMPLES:
                    examples.append({"first": sentences[i], "second": sentences[j],
                                     "similarity": round(matrix[i][j], 4)})
    return {
        "sentences": len(sentences),
        "nearDuplicateSentences": len(repeated),
        "rate": round(len(repeated) / len(sentences), 4),
        "threshold": threshold,
        "examples": examples,
    }


def reexplained_concepts(texts: Sequence[str], concepts: Sequence[str], titles: Sequence[str]) -> dict[str, Any]:
    """Los conceptos que se definen o se desarrollan en más de un recurso de la generación."""
    from platform5e.domain.generation.plan_coverage import develops_concept

    items = []
    for concept in concepts:
        explainers = [index for index, text in enumerate(texts) if develops_concept(text, concept)]
        if len(explainers) > 1:
            items.append({"concept": concept, "resources": len(explainers),
                          "titles": [titles[index] for index in explainers]})
    return {
        "concepts": len(concepts),
        "reexplained": len(items),
        "rate": round(len(items) / len(concepts), 4) if concepts else None,
        "items": items,
    }


def generator_counts(steps: Sequence[dict[str, Any]]) -> dict[str, int]:
    """Pasos redactados por la IA, por el respaldo por reglas, por reglas como generador principal y sin generador."""
    counts = {"aiSteps": 0, "fallbackSteps": 0, "rulesSteps": 0, "stepsWithoutGenerator": 0}
    for step in steps:
        generator = step.get("generator")
        if not generator:
            counts["stepsWithoutGenerator"] += 1
        elif generator.get("fallback"):
            counts["fallbackSteps"] += 1
        elif generator.get("usesAi"):
            counts["aiSteps"] += 1
        else:
            counts["rulesSteps"] += 1
    return counts


def summarize(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Promedios de las corridas terminadas: tasa de duplicación, similitud máxima media y recursos por pedido; y los
    totales de pasos por generador y de avisos del plan."""
    done = [run for run in runs if run.get("metrics")]
    totals = {key: sum((run.get("generators") or {}).get(key, 0) for run in done)
              for key in ("aiSteps", "fallbackSteps", "rulesSteps", "stepsWithoutGenerator")}
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
        "steps": sum(totals.values()),
        **totals,
        "planWarnings": sum(len(run.get("planWarnings") or []) for run in done),
        **content_summary(done),
    }


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def content_summary(done: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Promedios de las métricas de contenido y de dónde salió el plan (IA o reglas)."""
    sentences = [run["sentences"] for run in done if run.get("sentences")]
    total = sum(s["sentences"] for s in sentences)
    near = sum(s["nearDuplicateSentences"] for s in sentences)
    concepts = [run["conceptReexplanation"]["reexplained"] for run in done if run.get("conceptReexplanation")]
    evidence = [run["conceptReexplanationEvidence"]["reexplained"] for run in done
                if run.get("conceptReexplanationEvidence")]
    sources = [run["planGenerator"]["source"] for run in done if run.get("planGenerator")]
    return {
        "sentenceNearDuplicateRate": round(near / total, 4) if total else None,
        "meanSentenceRatePerRun": _mean([s["rate"] for s in sentences if s["rate"] is not None]),
        "meanReexplainedConcepts": _mean(concepts),
        "meanReexplainedEvidenceConcepts": _mean(evidence),
        "planGenerators": {"ai": sources.count("ai"), "rules": sources.count("rules")},
    }


def compare(baseline: dict[str, Any], planned: dict[str, Any]) -> dict[str, Any]:
    """Meta de P4: duplicación con plan ≤ 5 % y al menos 50 % menos que la línea base, sin perder recursos."""
    before, after = baseline.get("duplicateRate"), planned.get("duplicateRate")
    reduction = None if not before or after is None else round(1 - after / before, 4)
    fewer = (planned.get("resourcesPerRequest") or 0) < (baseline.get("resourcesPerRequest") or 0)

    def reduction_of(key: str) -> float | None:
        old, new = baseline.get(key), planned.get(key)
        return None if not old or new is None else round(1 - new / old, 4)

    return {
        "sentenceReduction": reduction_of("sentenceNearDuplicateRate"),
        "reexplainedConceptsReduction": reduction_of("meanReexplainedEvidenceConcepts"),
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
            "instructions": INSTRUCTIONS, "topK": TOP_K}


def plan_body(unit_id: str, types: Sequence[str], quantity: int) -> dict[str, Any]:
    return {"unitId": unit_id, "instructions": INSTRUCTIONS, "topK": TOP_K,
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


def request_evidence_texts(client: httpx.Client, headers: dict, request_id: str) -> list[str]:
    response = client.get(f"{REQUESTS_PATH}/{request_id}/evidence", headers=headers)
    if response.status_code != 200:
        return []
    return [str(fragment.get("text") or "") for fragment in response.json().get("fragments", [])]


def plan_details(client: httpx.Client, headers: dict, plan_id: str | None) -> dict[str, Any] | None:
    if not plan_id:
        return None
    response = client.get(f"{PLANS_PATH}/{plan_id}", headers=headers)
    return response.json() if response.status_code == 200 else None


def plan_generator_info(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    """De dónde salió el plan: la IA (en uno o dos intentos) o el planificador por reglas."""
    if plan is None:
        return None
    generator = plan.get("generator") or {}
    return {"usesAi": bool(generator.get("usesAi")), "fallback": bool(generator.get("fallback")),
            "attempts": generator.get("attempts"), "source": "ai" if generator.get("usesAi") else "rules"}


def content_metrics(
    resources: Sequence[dict[str, Any]],
    plan: dict[str, Any] | None,
    evidence_texts: Sequence[str],
    similarity: Similarity,
    sentence_threshold: float,
) -> dict[str, Any]:
    """Oraciones casi repetidas y conceptos explicados otra vez (con los conceptos del plan y con los de la
    evidencia)."""
    from platform5e.application.services.generation.plan_drafting import candidate_concepts

    texts = [resource_text(r) for r in resources]
    titles = [str(r.get("title") or "") for r in resources]
    evidence_concepts = candidate_concepts(INSTRUCTIONS, list(evidence_texts), MAX_MEASURED_CONCEPTS)
    plan_concepts = [c for item in (plan or {}).get("items", []) for c in item.get("covers", [])]
    by_evidence = {"source": "evidence", **reexplained_concepts(texts, evidence_concepts, titles)}
    by_plan = {"source": "plan", **reexplained_concepts(texts, plan_concepts, titles)} if plan else by_evidence
    return {
        "sentences": near_duplicate_sentences([resource_sentences(text) for text in texts], similarity,
                                              sentence_threshold),
        "conceptReexplanation": by_plan,
        "conceptReexplanationEvidence": by_evidence,
    }


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
    sentence_threshold: float = DEFAULT_SENTENCE_THRESHOLDS["lexical"],
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
    steps = status.get("steps", [])
    plan = plan_details(client, headers, status.get("planId") or record.get("planId"))
    content = content_metrics(resources, plan, request_evidence_texts(client, headers, request_id), similarity,
                              sentence_threshold)
    return {
        **record,
        "status": status.get("status"),
        "steps": [{"resourceType": s.get("resourceType"), "planItemPosition": s.get("planItemPosition"),
                   "delivered": len(s.get("resourceIds", [])), "usesAi": (s.get("generator") or {}).get("usesAi"),
                   "fallback": (s.get("generator") or {}).get("fallback"),
                   "planWarnings": len(s.get("planWarnings") or [])} for s in steps],
        "generators": generator_counts(steps),
        "planWarnings": [warning for s in steps for warning in s.get("planWarnings") or []],
        "rejectionKinds": {kind: rejections.count(kind) for kind in sorted(set(rejections))},
        "planGenerator": plan_generator_info(plan),
        "metrics": metrics,
        **content,
        # Los textos quedan en el informe para calibrar los umbrales después (--calibrate --from).
        "resources": [{"id": r.get("id"), "title": r.get("title"), "type": r.get("type"),
                       "planItemPosition": (r.get("params") or {}).get("planItemPosition"),
                       "text": resource_text(r)} for r in resources],
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


def percentile(values: Sequence[float], p: float) -> float | None:
    """Percentil con interpolación lineal entre rangos."""
    ordered = sorted(values)
    if not ordered:
        return None
    rank = (len(ordered) - 1) * p / 100
    low, high = math.floor(rank), math.ceil(rank)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (rank - low), 4)


def distribution(values: Sequence[float]) -> dict[str, Any]:
    return {"count": len(values), "min": round(min(values), 4) if values else None,
            **{f"p{p}": percentile(values, p) for p in (5, 25, 50, 75, 95)},
            "max": round(max(values), 4) if values else None}


def suggest_threshold(unrelated: Sequence[float], repeated: Sequence[float]) -> dict[str, Any]:
    """El umbral entre los dos grupos: el punto medio entre el p95 de los pares sin repetición y el p5 de los
    repetidos. Si se mezclan, se sugiere el p95 de los pares sin repetición y se avisa (`overlap`)."""
    low, high = percentile(unrelated, 95), percentile(repeated, 5)
    if low is None or high is None:
        return {"threshold": None, "overlap": None}
    if high > low:
        return {"threshold": round((low + high) / 2, 3), "overlap": False}
    return {"threshold": low, "overlap": True}


def _reordered(text: str) -> str:
    """El mismo contenido con sus oraciones en orden inverso: un recurso repetido con otra forma."""
    from platform5e.domain.materials.chunking import extract_sentences

    return " ".join(reversed(extract_sentences(text))) or text


def _half_copy(text: str, other: str) -> str:
    """La primera mitad de un recurso pegada a la segunda mitad de otro: contenido repetido a medias."""
    from platform5e.domain.materials.chunking import extract_sentences

    mine, theirs = extract_sentences(text), extract_sentences(other)
    return " ".join(mine[: max(1, len(mine) // 2 + len(mine) % 2)] + theirs[len(theirs) // 2:])


def _paraphrased_sentence(sentence: str) -> str:
    """Una oración casi igual: sin signos, en minúsculas, sin su primera palabra y con sus dos mitades cambiadas."""
    words = re.findall(r"\w+", sentence.lower())[1:]
    middle = len(words) // 2
    return " ".join(words[middle:] + words[:middle])


def calibrate(
    reports: Sequence[dict[str, Any]], similarity: Similarity, label: str
) -> dict[str, Any]:
    """Distribuciones de similitud de pares sin repetición y de pares repetidos, y los umbrales sugeridos."""
    unrelated: list[float] = []
    repeated: list[float] = []
    sentence_unrelated: list[float] = []
    sentence_repeated: list[float] = []
    for report in reports:
        for run in report.get("runs", []):
            resources = [r for r in run.get("resources") or [] if r.get("text")]
            texts = [r["text"] for r in resources]
            matrix = similarity(texts) if len(texts) > 1 else []
            for i in range(len(resources)):
                for j in range(i + 1, len(resources)):
                    a, b = resources[i], resources[j]
                    if (a.get("planItemPosition") is not None and b.get("planItemPosition") is not None
                            and a["planItemPosition"] != b["planItemPosition"] and a.get("type") != b.get("type")):
                        unrelated.append(matrix[i][j])
            for i, text in enumerate(texts):
                other = texts[(i + 1) % len(texts)]
                for copy in (_reordered(text), _half_copy(text, other)):
                    repeated.append(similarity([text, copy])[0][1])
            sentences = [(i, s) for i, r in enumerate(resources) for s in resource_sentences(r["text"])]
            pairs = [(x, y) for n, x in enumerate(sentences) for y in sentences[n + 1:]
                     if x[0] != y[0] and resources[x[0]].get("planItemPosition") != resources[y[0]].get(
                         "planItemPosition") and resources[x[0]].get("type") != resources[y[0]].get("type")]
            for x, y in pairs[:MAX_CALIBRATION_SENTENCE_PAIRS]:
                sentence_unrelated.append(similarity([x[1], y[1]])[0][1])
            for _, sentence in sentences:
                sentence_repeated.append(similarity([sentence, _paraphrased_sentence(sentence)])[0][1])
    cross = 0
    for n, first in enumerate(reports):
        for second in reports[n + 1:]:
            if first.get("corpus") and second.get("corpus") and first["corpus"] != second["corpus"]:
                a = [r["text"] for run in first.get("runs", []) for r in run.get("resources") or [] if r.get("text")]
                b = [r["text"] for run in second.get("runs", []) for r in run.get("resources") or [] if r.get("text")]
                for x in a:
                    for y in b:
                        unrelated.append(similarity([x, y])[0][1])
                        cross += 1
    pair_suggestion = suggest_threshold(unrelated, repeated)
    sentence_suggestion = suggest_threshold(sentence_unrelated, sentence_repeated)
    return {
        "calibration": "P4 · umbrales de duplicación (research R7)",
        "similarity": label,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "resourcePairs": {"unrelated": distribution(unrelated), "repeated": distribution(repeated)},
        "sentencePairs": {"unrelated": distribution(sentence_unrelated), "repeated": distribution(sentence_repeated)},
        "crossCorpusPairs": cross,
        "suggested": {
            "pairThreshold": pair_suggestion["threshold"], "pairOverlap": pair_suggestion["overlap"],
            "sentenceThreshold": sentence_suggestion["threshold"], "sentenceOverlap": sentence_suggestion["overlap"],
        },
        "notes": [
            "Sin repetición: recursos de tipos distintos en ítems distintos del plan (y de otro corpus, si se pasó un "
            "informe de otro corpus). Repetidos: el mismo recurso con sus oraciones en otro orden y medio recurso "
            "copiado; en oraciones, la misma oración sin su primera palabra y con sus mitades cambiadas.",
            "Si `overlap` es true, los dos grupos se mezclan: el umbral sugerido es el p95 de los pares sin repetición "
            "y la métrica de pares no distingue bien «mismo tema» de «contenido repetido».",
        ],
    }


def fetch_run_resources(client: httpx.Client, headers: dict, run: dict[str, Any]) -> list[dict[str, Any]]:
    """Los recursos de una corrida de un informe que no guardó sus textos, leídos de la API por su pedido."""
    response = client.get(f"{REQUESTS_PATH}/{run['requestId']}", headers=headers)
    if response.status_code != 200:
        return []
    status = response.json()
    resources = delivered_resources(client, headers, status["unitId"], status)
    return [{"id": r.get("id"), "title": r.get("title"), "type": r.get("type"),
             "planItemPosition": (r.get("params") or {}).get("planItemPosition"), "text": resource_text(r)}
            for r in resources]


def run_calibration(args: argparse.Namespace, embedder_factory: Callable[[], Any] | None) -> dict[str, Any]:
    if not args.reports:
        raise SystemExit("--calibrate necesita al menos un informe con --from.")
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.reports]
    missing = [run for report in reports for run in report.get("runs", [])
               if not run.get("resources") and run.get("requestId")]
    if missing:  # informes anteriores sin textos: se leen de la API (el mismo backend y la misma base)
        email, password = os.environ.get("EVAL_EMAIL"), os.environ.get("EVAL_PASSWORD")
        if not email or not password:
            raise SystemExit("Los informes no traen los textos: define EVAL_EMAIL y EVAL_PASSWORD para leerlos.")
        collect = load_collect_samples()
        with httpx.Client(base_url=args.api, timeout=120) as client:
            headers = collect.login(client, email, password)
            for run in missing:
                run["resources"] = fetch_run_resources(client, headers, run)
    similarity, label = choose_similarity(args.similarity, embedder_factory)
    calibration = calibrate(reports, similarity, label)
    calibration["reports"] = [path.name for path in args.reports]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(calibration, ensure_ascii=False, indent=2), encoding="utf-8")
    suggested = calibration["suggested"]
    print(f"Umbral sugerido de pares: {suggested['pairThreshold']} (se mezclan: {suggested['pairOverlap']}) · "
          f"de oraciones: {suggested['sentenceThreshold']} (se mezclan: {suggested['sentenceOverlap']}). "
          f"Informe: {args.out}")
    return calibration


def build_report(args: argparse.Namespace, similarity_label: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "measure": "P4 · duplicación entre recursos de una misma generación",
        "mode": args.mode,
        "api": args.api,
        "corpus": str(args.corpus),
        "resourceTypes": list(args.types),
        "quantity": args.quantity,
        "threshold": args.threshold,
        "sentenceThreshold": args.sentence_threshold,
        "similarity": similarity_label,
        "server": SERVER_SETTING[args.mode],
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "summary": summarize(runs),
        "runs": runs,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mide la duplicación con y sin plan (P4, GEN-P2).")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="URL base del backend (sin / al final)")
    parser.add_argument("--mode", choices=MODES, help="obligatorio salvo con --calibrate")
    parser.add_argument("--corpus", type=Path, default=HERE / "corpus_t067")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--quantity", type=int, default=2, help="recursos por tipo (de 1 a 5)")
    parser.add_argument("--types", nargs="+", default=list(SEQUENCE_TYPES))
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="τ: similitud de un duplicado")
    parser.add_argument("--similarity", choices=SIMILARITIES, default="auto")
    parser.add_argument("--sentence-threshold", type=float, default=None,
                        help="similitud de una oración casi repetida (0,92 con embeddings y 0,6 léxica por defecto)")
    parser.add_argument("--calibrate", action="store_true",
                        help="calcula las distribuciones de similitud y sugiere los umbrales (con --from)")
    parser.add_argument("--from", dest="reports", type=Path, nargs="*", default=[],
                        help="informes de corridas anteriores para --calibrate")
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    parser.add_argument("--poll", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=30 * 60, help="segundos máximos por corrida")
    parser.add_argument("--out", type=Path, required=True, help="archivo JSON del informe")
    parser.add_argument("--compare", type=Path, default=None,
                        help="informe de la línea base: agrega la comparación con la meta de P4")
    return parser


def main(argv: Sequence[str] | None = None, embedder_factory: Callable[[], Any] | None = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    if args.calibrate:
        return run_calibration(args, embedder_factory)
    if args.mode is None:
        raise SystemExit("Indica --mode plan o --mode baseline (o --calibrate).")
    if not 1 <= args.quantity <= 5:
        raise SystemExit("--quantity va de 1 a 5.")
    if not 0 < args.threshold <= 1:
        raise SystemExit("--threshold va de 0 a 1.")
    email, password = os.environ.get("EVAL_EMAIL"), os.environ.get("EVAL_PASSWORD")
    if not email or not password:
        raise SystemExit("Define EVAL_EMAIL y EVAL_PASSWORD.")
    similarity, label = choose_similarity(args.similarity, embedder_factory)
    if args.sentence_threshold is None:
        args.sentence_threshold = DEFAULT_SENTENCE_THRESHOLDS["lexical" if label == LEXICAL_LABEL else "embeddings"]
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
                                    similarity, args.threshold, args.poll, time.monotonic() + args.timeout,
                                    args.sentence_threshold))
    report = build_report(args, label, runs)
    if args.compare is not None:
        baseline = json.loads(args.compare.read_text(encoding="utf-8"))
        report["comparison"] = compare(baseline["summary"], report["summary"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = report["summary"]
    print(f"Tasa de duplicación: {summary['duplicateRate']} · similitud máxima media: {summary['meanMaxSimilarity']} "
          f"· recursos por pedido: {summary['resourcesPerRequest']} ({label}).")
    print(f"Oraciones casi repetidas: {summary['sentenceNearDuplicateRate']} · conceptos explicados otra vez "
          f"(evidencia): {summary['meanReexplainedEvidenceConcepts']} · pasos IA/respaldo: {summary['aiSteps']}/"
          f"{summary['fallbackSteps']} · planes IA/reglas: {summary['planGenerators']}. Informe: {args.out}")
    return report


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
