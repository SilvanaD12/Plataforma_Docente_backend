"""Mide la duplicación entre los recursos de una misma generación, con y sin plan (P4, GEN-P2, T019).

Las dos corridas usan el mismo servidor, el mismo código y la misma base; solo cambia GENERATION_IMPLICIT_PLAN al
arrancar el backend local (con Gemini, la clave local en la terminal del backend, nunca en Render). Los comandos
completos están en specs/006-plan-de-generacion/plan.md, «Medición de P4». La cuenta de EVAL_EMAIL debe ser siempre la
misma: la que creó los pedidos de los informes que después se recalculan o se calibran. Desde backend/:
    export EVAL_EMAIL=... EVAL_PASSWORD=...
    # backend con GENERATION_IMPLICIT_PLAN=false (solo para medir)
    python evaluation/measure_duplication.py --mode baseline --corpus evaluation/corpus_t067 --runs 5 --quantity 2 \\
        --threshold 0.885 --sentence-threshold 0.865 --out ../docs/evidence/GEN-P4/v4-gemini-baseline.json
    # el mismo backend y la misma base, reiniciado con GENERATION_IMPLICIT_PLAN=true (por defecto)
    python evaluation/measure_duplication.py --mode plan --corpus evaluation/corpus_t067 --runs 5 --quantity 2 \\
        --threshold 0.885 --sentence-threshold 0.865 --out ../docs/evidence/GEN-P4/v4-gemini-plan.json \\
        --compare ../docs/evidence/GEN-P4/v4-gemini-baseline.json

Modos (specs/006-plan-de-generacion, research R7):
- `plan`: por cada corrida crea el plan (POST /api/v1/generation-plans), lo aprueba sin cambios y genera desde él.
- `baseline`: pide la misma secuencia con el cuerpo anterior. El servidor debe estar con GENERATION_IMPLICIT_PLAN=false;
  si el pedido vuelve con un plan, la medición se detiene sin escribir el informe.
- `--recompute --from informe.json --out nuevo.json`: recalcula todas las métricas con los textos guardados en un
  informe (solo embeddings, sin generar), conserva los datos de cada corrida (pasos de la IA y del respaldo, origen
  del plan) y admite --compare. Si el informe no guarda los conceptos (informes v3 y anteriores), los lee de la API
  con la misma cuenta; sin cuenta, las métricas de conceptos quedan vacías.
- `--faithfulness` (en una corrida nueva o con --recompute): la fidelidad de cada recurso entregado, con la métrica
  Faithfulness de Ragas y el juez de evaluation/run_ragas.py (el mismo modelo y la misma configuración). La respuesta es
  el recurso sin su título; el contexto, los textos de los fragmentos que cita (los que muestra Revisión, guardados en
  el informe: un recálculo posterior no usa la API); la pregunta, las indicaciones del pedido. Los recursos sin citas
  se omiten y se cuentan; un error del juez se registra en el recurso y la medición sigue. Las llamadas al juez van en
  paralelo, con --judge-concurrency hilos (2 por defecto). En un recálculo solo se califican los recursos sin puntaje
  (o todos, con otro juez o con --rescore-faithfulness). Necesita GEMINI_API_KEY en la terminal de la medición.
- `--calibrate --from informe.json …`: distribuciones de similitud de pares sin repetición y repetidos, y los umbrales
  sugeridos.

Las dos piden la misma secuencia (8 tipos de texto × --quantity recursos) con las mismas indicaciones y 12 fragmentos
(`topK`), sobre una unidad con el corpus de T067. Por cada generación (y también solo con los recursos que redactó la
IA, `aiOnly`, para que el respaldo no sesgue la comparación):
- **Oraciones casi repetidas (evidencia principal):** la parte de las oraciones de 8 palabras o más que tienen una casi
  igual en otro recurso (coseno de embeddings ≥ --sentence-threshold, o Jaccard ≥ 0,6 sin embeddings). Los títulos y
  los encabezados no son oraciones. Tres cifras: todos los pares, `crossType` (recursos de tipos distintos, la
  principal: la queja del profesor es la repetición entre recursos distintos) y `variants` (los recursos del mismo
  tipo, las variantes de un tipo, aparte).
- **Conceptos explicados otra vez:** los conceptos que se desarrollan (en dos oraciones o con una definición) en más de
  un recurso, y por cada concepto en cuántos recursos se menciona, se desarrolla y se define (`table`), para ver si la
  regla es demasiado estricta. `conceptReexplanationEvidence` usa en los dos modos los conceptos candidatos de la
  evidencia del pedido; `conceptReexplanation`, los del plan si lo hay.
- **Tasa de pares duplicados (secundaria):** pares con similitud ≥ --threshold, con la misma división en todos,
  `crossType` y `variants`.
- **Por corrida:** pasos de la IA, del respaldo (con su motivo) y de reglas; recursos planeados que no se entregaron y
  por qué (los rechazos o el error de su paso); avisos de solapamiento del plan; y si el plan salió de Gemini o de reglas.

La similitud es el coseno de los embeddings si hay modelo (`--similarity embeddings`, o `auto` con LLM_API_KEY); si no,
la léxica de `most_similar`, registrada como provisional. Los embeddings se piden por lotes, una vez por texto. El
informe JSON no guarda el correo, la contraseña ni el token.
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
from concurrent.futures import ThreadPoolExecutor, as_completed
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
EMBEDDING_BATCH = 100
# Campos de la estructura que son títulos o encabezados, no oraciones.
HEADING_KEYS = frozenset({"title", "titulo", "headline", "heading", "central", "label", "caption", "name"})
MODES = ("baseline", "plan")
SIMILARITIES = ("auto", "embeddings", "lexical")
GROUPS = ("all", "crossType", "variants")
IMPLICIT_PLAN_ON = (
    "El pedido de la línea base volvió con un plan: reinicia el backend con GENERATION_IMPLICIT_PLAN=false (solo para "
    "medir) y vuelve a correr --mode baseline."
)
WRONG_ACCOUNT = (
    "GET {path} respondió {status}: la cuenta de EVAL_EMAIL no puede leer el pedido {request_id}. Usa la misma cuenta "
    "que creó los informes y el mismo backend y la misma base."
)
SERVER_SETTING = {
    "plan": "GENERATION_IMPLICIT_PLAN=true (plan aprobado sin cambios)",
    "baseline": "GENERATION_IMPLICIT_PLAN=false (cuerpo anterior, redactado como antes de GEN-P1)",
}
LEXICAL_LABEL = "lexical (provisional: Jaccard de most_similar, sin REV-P3)"
EMBEDDINGS_LABEL = "embeddings (coseno)"
# Meta de P4: el plan no baja la fidelidad de 0,90 (T027 c).
FAITHFULNESS_TARGET = 0.90
DEFAULT_JUDGE_CONCURRENCY = 2
MAX_JUDGE_ERROR = 300

Similarity = Callable[[Sequence[str]], list[list[float]]]


def progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- textos de los recursos


def _flatten(value: Any, parts: list[str], skip_headings: bool) -> None:
    if isinstance(value, str):
        parts.append(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            if not (skip_headings and key in HEADING_KEYS):
                _flatten(item, parts, skip_headings)
    elif isinstance(value, list):
        for item in value:
            _flatten(item, parts, skip_headings)


def resource_text(resource: dict[str, Any]) -> str:
    """Texto comparable de un recurso tal como lo guarda Revisión: título, contenido, opciones y estructura."""
    parts = [str(resource.get("title") or ""), str(resource.get("body") or "")]
    parts += [str(option.get("text") or "") for option in resource.get("options") or []]
    _flatten(resource.get("structure"), parts, skip_headings=False)
    return "\n".join(part for part in parts if part.strip())


def resource_body(resource: dict[str, Any]) -> str:
    """El texto del recurso sin su título ni los encabezados de la estructura: lo que se parte en oraciones.

    Con un recurso de Revisión, el contenido, las opciones y los textos de la estructura que no son títulos. Con un
    recurso guardado en un informe: su `body` si lo trae; si no (informes v3 y anteriores), su `text` sin la primera
    línea cuando es el título."""
    if "text" in resource and "structure" not in resource and "options" not in resource:
        if resource.get("sentenceText") is not None:
            return str(resource["sentenceText"])
        lines = str(resource.get("text") or "").split("\n")
        if lines and resource.get("title") and lines[0].strip() == str(resource["title"]).strip():
            lines = lines[1:]
        return "\n".join(lines)
    parts = [str(resource.get("body") or "")]
    parts += [str(option.get("text") or "") for option in resource.get("options") or []]
    _flatten(resource.get("structure"), parts, skip_headings=True)
    return "\n".join(part for part in parts if part.strip())


def resource_sentences(text: str) -> list[str]:
    """Las oraciones con 8 palabras o más, sin espacios repetidos."""
    from platform5e.domain.materials.chunking import extract_sentences

    sentences = [" ".join(sentence.split()) for sentence in extract_sentences(text or "")]
    return [sentence for sentence in sentences if len(re.findall(r"\w+", sentence)) >= MIN_SENTENCE_WORDS]


# --------------------------------------------------------------------------- similitud


def cosine(first: Sequence[float], second: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(first, second))
    norm = math.sqrt(sum(a * a for a in first)) * math.sqrt(sum(b * b for b in second))
    return dot / norm if norm else 0.0


def lexical_matrix(texts: Sequence[str]) -> list[list[float]]:
    """Similitud léxica de cada par: la de `most_similar` (proporción de palabras útiles compartidas)."""
    from platform5e.domain.generation.sequence import content_similarity

    return [[1.0 if i == j else content_similarity(a, b) for j, b in enumerate(texts)] for i, a in enumerate(texts)]


class EmbeddingSimilarity:
    """Coseno de embeddings. Pide los vectores por lotes de `batch_size` textos y una sola vez por texto."""

    def __init__(self, embedder: Any, batch_size: int = EMBEDDING_BATCH, show_progress: bool = True) -> None:
        self._embedder = embedder
        self._batch_size = batch_size
        self._show_progress = show_progress
        self._cache: dict[str, list[float]] = {}
        self.calls = 0

    def vectors(self, texts: Sequence[str]) -> list[list[float]]:
        missing = [text for text in dict.fromkeys(texts) if text not in self._cache]
        for start in range(0, len(missing), self._batch_size):
            batch = missing[start:start + self._batch_size]
            for text, vector in zip(batch, self._embedder.embed_documents(batch)):
                self._cache[text] = vector
            self.calls += 1
            if self._show_progress and len(missing) > self._batch_size:
                progress(f"Embeddings: {min(start + self._batch_size, len(missing))}/{len(missing)} textos")
        return [self._cache[text] for text in texts]

    def __call__(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self.vectors(texts)
        return [[cosine(a, b) for b in vectors] for a in vectors]

    def scores(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        self.vectors([text for pair in pairs for text in pair])
        return [cosine(self._cache[a], self._cache[b]) for a, b in pairs]


def embedding_matrix(embedder: Any) -> EmbeddingSimilarity:
    """Similitud coseno de los embeddings de cada texto, con los vectores pedidos por lotes."""
    return EmbeddingSimilarity(embedder)


def pair_scores(similarity: Similarity, pairs: Sequence[tuple[str, str]]) -> list[float]:
    """La similitud de cada par. Con embeddings, todos los textos se vectorizan juntos por lotes."""
    if hasattr(similarity, "scores"):
        return similarity.scores(pairs)  # type: ignore[attr-defined]
    if similarity is lexical_matrix:
        from platform5e.domain.generation.sequence import content_similarity

        return [content_similarity(a, b) for a, b in pairs]
    return [similarity([a, b])[0][1] for a, b in pairs]


# --------------------------------------------------------------------------- métricas (sin red)


def _group(i: int, j: int, types: Sequence[str]) -> str:
    return "variants" if types[i] == types[j] else "crossType"


def duplication(
    texts: Sequence[str],
    similarity: Similarity,
    threshold: float,
    types: Sequence[str] | None = None,
    titles: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Pares duplicados y similitud máxima media de una generación: todos los pares, los de tipos distintos
    (`crossType`) y los del mismo tipo (`variants`)."""
    count = len(texts)
    types = list(types) if types is not None else [str(i) for i in range(count)]
    titles = list(titles) if titles is not None else [""] * count
    matrix = similarity(texts) if count > 1 else []
    pairs = [(i, j, matrix[i][j]) for i in range(count) for j in range(i + 1, count)]
    duplicated = [(i, j, round(score, 4)) for i, j, score in pairs if score >= threshold]
    maxima = [max(matrix[i][j] for j in range(count) if j != i) for i in range(count)] if count > 1 else []
    result: dict[str, Any] = {
        "resources": count,
        "pairs": len(pairs),
        "duplicatePairs": len(duplicated),
        "duplicateRate": round(len(duplicated) / len(pairs), 4) if pairs else 0.0,
        "meanMaxSimilarity": round(sum(maxima) / len(maxima), 4) if maxima else None,
        "duplicates": [{"first": i, "second": j, "similarity": score, "titles": [titles[i], titles[j]]}
                       for i, j, score in duplicated],
    }
    for group in ("crossType", "variants"):
        in_group = [(i, j) for i, j, _ in pairs if _group(i, j, types) == group]
        repeated = [(i, j, score) for i, j, score in duplicated if _group(i, j, types) == group]
        result[group] = {
            "pairs": len(in_group),
            "duplicatePairs": len(repeated),
            "duplicateRate": round(len(repeated) / len(in_group), 4) if in_group else None,
            "examples": [{"titles": [titles[i], titles[j]], "types": [types[i], types[j]], "similarity": score}
                         for i, j, score in repeated[:MAX_EXAMPLES]],
        }
    return result


def near_duplicate_sentences(
    by_resource: Sequence[Sequence[str]],
    similarity: Similarity,
    threshold: float,
    types: Sequence[str] | None = None,
) -> dict[str, Any]:
    """La parte de las oraciones que tienen una casi igual en otro recurso de la misma generación: en cualquier
    recurso (`all`), en uno de otro tipo (`crossType`) y en otro del mismo tipo (`variants`)."""
    types = list(types) if types is not None else [str(i) for i in range(len(by_resource))]
    owners = [index for index, sentences in enumerate(by_resource) for _ in sentences]
    sentences = [sentence for group in by_resource for sentence in group]
    groups: dict[str, dict[str, Any]] = {name: {"repeated": set(), "examples": []} for name in GROUPS}
    if sentences:
        matrix = similarity(sentences)
        for i in range(len(sentences)):
            for j in range(i + 1, len(sentences)):
                if owners[i] == owners[j] or matrix[i][j] < threshold:
                    continue
                for name in ("all", _group(owners[i], owners[j], types)):
                    groups[name]["repeated"].update((i, j))
                    if len(groups[name]["examples"]) < MAX_EXAMPLES:
                        groups[name]["examples"].append({
                            "first": sentences[i], "second": sentences[j], "similarity": round(matrix[i][j], 4),
                            "types": [types[owners[i]], types[owners[j]]]})
    result: dict[str, Any] = {"sentences": len(sentences), "threshold": threshold}
    for name in GROUPS:
        repeated = groups[name]["repeated"]
        result[name] = {
            "nearDuplicateSentences": len(repeated),
            "rate": round(len(repeated) / len(sentences), 4) if sentences else None,
            "examples": groups[name]["examples"],
        }
    return result


def reexplained_concepts(texts: Sequence[str], concepts: Sequence[str], titles: Sequence[str]) -> dict[str, Any]:
    """Los conceptos que se desarrollan en más de un recurso, y por cada concepto en cuántos recursos se menciona, se
    desarrolla y se define (`table`)."""
    from platform5e.domain.generation.plan_coverage import concept_usage

    items, table = [], []
    for concept in concepts:
        usage = [concept_usage(text, concept) for text in texts]
        explainers = [index for index, used in enumerate(usage) if used["developed"]]
        table.append({"concept": concept,
                      "mentioned": sum(used["mentioned"] for used in usage),
                      "developed": len(explainers),
                      "defined": sum(used["defined"] for used in usage)})
        if len(explainers) > 1:
            items.append({"concept": concept, "resources": len(explainers),
                          "titles": [titles[index] for index in explainers]})
    return {
        "concepts": len(concepts),
        "reexplained": len(items),
        "rate": round(len(items) / len(concepts), 4) if concepts else None,
        "items": items,
        "table": table,
    }


def compute_metrics(
    resources: Sequence[dict[str, Any]],
    plan_concepts: Sequence[str] | None,
    evidence_concepts: Sequence[str] | None,
    similarity: Similarity,
    threshold: float,
    sentence_threshold: float,
) -> dict[str, Any]:
    """Todas las métricas de una generación a partir de sus recursos (los de la API o los guardados en un informe)."""
    texts = [r.get("text") or resource_text(r) for r in resources]
    bodies = [resource_body(r) for r in resources]
    titles = [str(r.get("title") or "") for r in resources]
    types = [str(r.get("type") or "") for r in resources]
    metrics: dict[str, Any] = {
        "metrics": duplication(texts, similarity, threshold, types, titles),
        "sentences": near_duplicate_sentences([resource_sentences(body) for body in bodies], similarity,
                                              sentence_threshold, types),
    }
    by_evidence = (None if evidence_concepts is None
                   else {"source": "evidence", **reexplained_concepts(bodies, evidence_concepts, titles)})
    by_plan = ({"source": "plan", **reexplained_concepts(bodies, plan_concepts, titles)} if plan_concepts
               else by_evidence)
    metrics["conceptReexplanation"] = by_plan
    metrics["conceptReexplanationEvidence"] = by_evidence
    return metrics


def drafter_of(step: dict[str, Any]) -> str:
    """Quién redactó los recursos de un paso: la IA, el respaldo por reglas o reglas como generador principal."""
    generator = step.get("generator") if "generator" in step else step
    if not generator:
        return "none"
    if generator.get("fallback"):
        return "fallback"
    return "ai" if generator.get("usesAi") else "rules"


def with_ai_only(run: dict[str, Any], similarity: Similarity, threshold: float, sentence_threshold: float) -> None:
    """Agrega a la corrida las métricas solo con los recursos que redactó la IA (sin los del respaldo)."""
    resources = [r for r in run.get("resources") or [] if r.get("drafter") == "ai"]
    run["aiOnly"] = {"resources": len(resources),
                     **compute_metrics(resources, run.get("planConcepts"), run.get("evidenceConcepts"), similarity,
                                       threshold, sentence_threshold)}


def generator_counts(steps: Sequence[dict[str, Any]]) -> dict[str, int]:
    """Pasos redactados por la IA, por el respaldo por reglas, por reglas como generador principal y sin generador."""
    counts = {"aiSteps": 0, "fallbackSteps": 0, "rulesSteps": 0, "stepsWithoutGenerator": 0}
    names = {"ai": "aiSteps", "fallback": "fallbackSteps", "rules": "rulesSteps", "none": "stepsWithoutGenerator"}
    for step in steps:
        counts[names[drafter_of(step)]] += 1
    return counts


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def metric_summary(measured: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Promedios de las métricas de una lista de mediciones (corridas completas o su parte `aiOnly`)."""
    pairs = [m["metrics"] for m in measured if m.get("metrics")]
    sentences = [m["sentences"] for m in measured if m.get("sentences")]
    total_sentences = sum(s["sentences"] for s in sentences)
    concepts = [m["conceptReexplanation"]["reexplained"] for m in measured if m.get("conceptReexplanation")]
    evidence = [m["conceptReexplanationEvidence"]["reexplained"] for m in measured
                if m.get("conceptReexplanationEvidence")]
    summary: dict[str, Any] = {
        "duplicateRate": _ratio(sum(p["duplicatePairs"] for p in pairs), sum(p["pairs"] for p in pairs)),
        "meanDuplicateRatePerRun": _mean([p["duplicateRate"] for p in pairs]),
        "meanMaxSimilarity": _mean([p["meanMaxSimilarity"] for p in pairs if p["meanMaxSimilarity"] is not None]),
        "sentenceNearDuplicateRate": _ratio(sum(s["all"]["nearDuplicateSentences"] for s in sentences),
                                            total_sentences),
        "meanSentenceRatePerRun": _mean([s["all"]["rate"] for s in sentences if s["all"]["rate"] is not None]),
        "meanReexplainedConcepts": _mean(concepts),
        "meanReexplainedEvidenceConcepts": _mean(evidence),
    }
    for group in ("crossType", "variants"):
        summary[f"{group}DuplicateRate"] = _ratio(sum(p[group]["duplicatePairs"] for p in pairs if group in p),
                                                  sum(p[group]["pairs"] for p in pairs if group in p))
        summary[f"{group}SentenceRate"] = _ratio(sum(s[group]["nearDuplicateSentences"] for s in sentences),
                                                 total_sentences)
    return summary


def summarize(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Promedios de las corridas terminadas, con todos sus recursos y solo con los de la IA (`aiOnly`); pasos por
    generador, avisos del plan, recursos no entregados y origen del plan."""
    done = [run for run in runs if run.get("metrics")]
    totals = {key: sum((run.get("generators") or {}).get(key, 0) for run in done)
              for key in ("aiSteps", "fallbackSteps", "rulesSteps", "stepsWithoutGenerator")}
    resources = [run["metrics"]["resources"] for run in done]
    sources = [run["planGenerator"]["source"] for run in done if run.get("planGenerator")]
    ai_only = [run["aiOnly"] for run in done if run.get("aiOnly")]
    return {
        "runs": len(runs),
        "finishedRuns": len(done),
        **metric_summary(done),
        "resourcesPerRequest": round(sum(resources) / len(resources), 2) if resources else None,
        "steps": sum(totals.values()),
        **totals,
        "planWarnings": sum(len(run.get("planWarnings") or []) for run in done),
        "undeliveredResources": sum(u["missing"] for run in done for u in run.get("undelivered") or []),
        "planGenerators": {"ai": sources.count("ai"), "rules": sources.count("rules")},
        "aiOnly": {**metric_summary(ai_only), "resources": sum(m["resources"] for m in ai_only)} if ai_only else None,
        "faithfulness": _faithfulness_summary(done),
    }


def _faithfulness_summary(runs: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """La fidelidad de todos los recursos de las corridas terminadas, y la media de las medias por corrida."""
    report = faithfulness_report([r for run in runs for r in run.get("resources") or []])
    if report is None:
        return None
    means = [run["faithfulness"]["mean"] for run in runs
             if run.get("faithfulness") and run["faithfulness"].get("mean") is not None]
    return {**report, "meanPerRun": _mean(means)}


def _reduction(old: Any, new: Any) -> float | None:
    return None if not old or new is None else round(1 - new / old, 4)


def compare(baseline: dict[str, Any], planned: dict[str, Any]) -> dict[str, Any]:
    """Bajas frente a la línea base. Meta de P4 sobre la tasa de pares: ≤ 5 % y al menos 50 % menos, sin perder
    recursos. La evidencia principal es la de oraciones entre tipos distintos y la de conceptos."""
    before, after = baseline.get("duplicateRate"), planned.get("duplicateRate")
    reduction = _reduction(before, after)
    fewer = (planned.get("resourcesPerRequest") or 0) < (baseline.get("resourcesPerRequest") or 0)
    result = {
        "crossTypeSentenceReduction": _reduction(baseline.get("crossTypeSentenceRate"),
                                                 planned.get("crossTypeSentenceRate")),
        "sentenceReduction": _reduction(baseline.get("sentenceNearDuplicateRate"),
                                        planned.get("sentenceNearDuplicateRate")),
        "reexplainedConceptsReduction": _reduction(baseline.get("meanReexplainedEvidenceConcepts"),
                                                   planned.get("meanReexplainedEvidenceConcepts")),
        "crossTypeReduction": _reduction(baseline.get("crossTypeDuplicateRate"), planned.get("crossTypeDuplicateRate")),
        "reduction": reduction,
        "meetsTarget": after is not None and after <= 0.05 and (before == 0 or (reduction or 0) >= 0.5)
        and not fewer,
        "resourcesKept": not fewer,
    }
    faithfulness = compare_faithfulness(baseline.get("faithfulness"), planned.get("faithfulness"))
    if faithfulness is not None:
        result["faithfulness"] = faithfulness
    if baseline.get("aiOnly") and planned.get("aiOnly"):
        result["aiOnly"] = {
            "crossTypeSentenceReduction": _reduction(baseline["aiOnly"].get("crossTypeSentenceRate"),
                                                     planned["aiOnly"].get("crossTypeSentenceRate")),
            "reexplainedConceptsReduction": _reduction(baseline["aiOnly"].get("meanReexplainedEvidenceConcepts"),
                                                       planned["aiOnly"].get("meanReexplainedEvidenceConcepts")),
            "crossTypeReduction": _reduction(baseline["aiOnly"].get("crossTypeDuplicateRate"),
                                             planned["aiOnly"].get("crossTypeDuplicateRate")),
            "reduction": _reduction(baseline["aiOnly"].get("duplicateRate"), planned["aiOnly"].get("duplicateRate")),
        }
    return result


# --------------------------------------------------------------------------- fidelidad (T027 c)


def faithfulness_stats(resources: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Fidelidad media, parte de los recursos con 0,90 o más, y cuántos se calificaron, se omitieron (sin citas) o
    tuvieron un error del juez."""
    records = [r["faithfulness"] for r in resources if r.get("faithfulness")]
    scores = [record["score"] for record in records if record.get("score") is not None]
    return {"mean": _mean(scores),
            "atLeastTarget": _ratio(sum(score >= FAITHFULNESS_TARGET for score in scores), len(scores)),
            "scored": len(scores),
            "skipped": sum("skipped" in record for record in records),
            "errors": sum("error" in record for record in records)}


def faithfulness_report(resources: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """La fidelidad de una lista de recursos: de todos, por tipo y solo de los que redactó la IA (`aiOnly`). None si
    ninguno se calificó todavía."""
    if not any(r.get("faithfulness") for r in resources):
        return None
    types = dict.fromkeys(str(r.get("type") or "") for r in resources)
    return {**faithfulness_stats(resources),
            "byType": {t: faithfulness_stats([r for r in resources if str(r.get("type") or "") == t]) for t in types},
            "aiOnly": faithfulness_stats([r for r in resources if r.get("drafter") == "ai"])}


def compare_faithfulness(baseline: dict[str, Any] | None, planned: dict[str, Any] | None) -> dict[str, Any] | None:
    """La fidelidad con plan frente a la línea base, y si el plan la mantiene en 0,90 o más (meta de P4)."""
    if not baseline or not planned:
        return None

    def part(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        old, new = before.get("mean"), after.get("mean")
        return {"baseline": old, "plan": new,
                "difference": None if old is None or new is None else round(new - old, 4),
                "planMeetsTarget": new is not None and new >= FAITHFULNESS_TARGET,
                "baselineAtLeastTarget": before.get("atLeastTarget"), "planAtLeastTarget": after.get("atLeastTarget")}

    result = part(baseline, planned)
    if baseline.get("aiOnly") and planned.get("aiOnly"):
        result["aiOnly"] = part(baseline["aiOnly"], planned["aiOnly"])
    return result


def _judge_once(evaluate_one: Callable[[dict], dict], row: dict[str, Any]) -> dict[str, Any]:
    try:
        value = evaluate_one(row).get("faithfulness")
    except Exception as error:  # un error del juez con un recurso no detiene la medición
        return {"error": f"{type(error).__name__}: {str(error)[:MAX_JUDGE_ERROR]}"}
    if value is None or value != value:  # NaN: Ragas no pudo calificar
        return {"error": "el juez no devolvió puntaje"}
    return {"score": round(float(value), 4)}


def score_faithfulness(
    runs: Sequence[dict[str, Any]],
    evaluate_one: Callable[[dict], dict],
    instructions: str,
    concurrency: int = DEFAULT_JUDGE_CONCURRENCY,
    rescore: bool = False,
) -> int:
    """Califica con el juez los recursos que citan el material y todavía no tienen puntaje (o todos, con `rescore`).
    Los que no citan quedan como omitidos. Devuelve cuántos se enviaron al juez."""
    pending = []
    for run in runs:
        for resource in run.get("resources") or []:
            if not resource.get("contexts"):
                resource["faithfulness"] = {"skipped": "noCitations"}
            elif rescore or (resource.get("faithfulness") or {}).get("score") is None:
                pending.append(resource)
    if not pending:
        return 0
    progress(f"Fidelidad: {len(pending)} recursos con el juez, {concurrency} a la vez…")
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(_judge_once, evaluate_one, {
            "user_input": instructions, "response": resource_body(resource),
            "retrieved_contexts": list(resource["contexts"])}): resource for resource in pending}
        for done, future in enumerate(as_completed(futures), 1):
            futures[future]["faithfulness"] = future.result()
            progress(f"Fidelidad: {done}/{len(pending)}")
    return len(pending)


def apply_faithfulness(runs: Sequence[dict[str, Any]]) -> None:
    for run in runs:
        if run.get("resources"):
            run["faithfulness"] = faithfulness_report(run["resources"])


def default_judge(model: str) -> Callable[[dict], dict]:
    """El juez de run_ragas.py (Gemini por su endpoint compatible con OpenAI), solo con Faithfulness."""
    if importlib.util.find_spec("ragas") is None:
        raise SystemExit("--faithfulness necesita Ragas: instala evaluation/requirements.txt en el entorno de la "
                         "medición, como para run_ragas.py.")
    ragas = load_run_ragas()
    llm, _ = ragas.build_judge(model, ragas.build_parser().get_default("embedding_model"))
    return ragas.faithfulness_evaluator(llm)


def load_run_ragas() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_ragas", HERE / "run_ragas.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def judge_info(model: str, concurrency: int) -> dict[str, Any]:
    return {"judge": model, "metric": "Faithfulness (Ragas, evaluation/run_ragas.py)",
            "contexts": "cited (los fragmentos que cita cada recurso)", "response": "el recurso sin su título",
            "target": FAITHFULNESS_TARGET, "concurrency": concurrency}


def add_faithfulness(args: argparse.Namespace, report: dict[str, Any],
                     judge_factory: Callable[[str], Callable[[dict], dict]] | None,
                     evaluate_one: Callable[[dict], dict] | None = None) -> None:
    """Califica los recursos del informe (si se pidió --faithfulness) y resume la fidelidad por corrida y en total."""
    runs = report.get("runs", [])
    if args.faithfulness:
        previous = (report.get("faithfulnessJudge") or {}).get("judge")
        evaluate_one = evaluate_one or (judge_factory or default_judge)(args.judge_model)
        score_faithfulness(runs, evaluate_one, report.get("instructions") or INSTRUCTIONS, args.judge_concurrency,
                           rescore=args.rescore_faithfulness or (previous is not None and previous != args.judge_model))
        report["faithfulnessJudge"] = judge_info(args.judge_model, args.judge_concurrency)
    apply_faithfulness(runs)
    report["summary"] = summarize(runs)


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
        record.update(planId=plan["id"], planItems=len(plan.get("items", [])))
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


def evidence_concepts_of(texts: Sequence[str]) -> list[str]:
    from platform5e.application.services.generation.plan_drafting import candidate_concepts

    return candidate_concepts(INSTRUCTIONS, list(texts), MAX_MEASURED_CONCEPTS)


def plan_concepts_of(plan: dict[str, Any] | None) -> list[str] | None:
    return [c for item in plan.get("items", []) for c in item.get("covers", [])] if plan else None


def step_records(steps: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"resourceType": s.get("resourceType"), "planItemPosition": s.get("planItemPosition"),
             "delivered": len(s.get("resourceIds", [])), "usesAi": (s.get("generator") or {}).get("usesAi"),
             "fallback": (s.get("generator") or {}).get("fallback"),
             "fallbackReason": (s.get("generator") or {}).get("fallbackReason"),
             "planWarnings": len(s.get("planWarnings") or [])} for s in steps]


def fallbacks_of(steps: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Los pasos que redactó el respaldo por reglas y por qué (`generator.fallbackReason`)."""
    return [{"resourceType": s.get("resourceType"), "planItemPosition": s.get("planItemPosition"),
             "reason": (s.get("generator") or {}).get("fallbackReason")}
            for s in steps if drafter_of(s) == "fallback"]


def undelivered_of(steps: Sequence[dict[str, Any]], expected: dict[Any, int]) -> list[dict[str, Any]]:
    """Los recursos planeados que no se entregaron, por paso, con los rechazos o el error de su paso."""
    missing = []
    for step in steps:
        key = step.get("planItemPosition") if step.get("planItemPosition") is not None else step.get("resourceType")
        wanted, got = expected.get(key, 0), len(step.get("resourceIds", []))
        if got < wanted:
            missing.append({
                "resourceType": step.get("resourceType"), "planItemPosition": step.get("planItemPosition"),
                "expected": wanted, "delivered": got, "missing": wanted - got, "status": step.get("status"),
                "rejections": [{"kind": r.get("kind"), "title": r.get("title"), "reason": r.get("reason")}
                               for r in step.get("rejections", [])],
                "error": (step.get("error") or {}).get("message"),
            })
    return missing


def stored_resources(resources: Sequence[dict[str, Any]], steps: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Los recursos como quedan en el informe: su texto completo (pares), su texto sin títulos (oraciones) y quién los
    redactó."""
    drafters = {rid: drafter_of(step) for step in steps for rid in step.get("resourceIds", [])}
    return [{"id": r.get("id"), "title": r.get("title"), "type": r.get("type"),
             "planItemPosition": (r.get("params") or {}).get("planItemPosition"),
             "drafter": drafters.get(r.get("id"), "none"),
             "text": resource_text(r), "sentenceText": resource_body(r),
             # Los textos de los fragmentos que cita, como los muestra Revisión: el contexto de la fidelidad.
             "contexts": [str(e.get("text")) for e in r.get("evidence") or [] if e.get("text")]} for r in resources]


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
    steps = status.get("steps", [])
    resources = stored_resources(delivered_resources(client, headers, unit_id, status), steps)
    plan = plan_details(client, headers, status.get("planId") or record.get("planId"))
    expected = ({item["position"]: item.get("quantity", quantity) for item in plan.get("items", [])} if plan
                else {resource_type: quantity for resource_type in types})
    rejections = [r["kind"] for step in steps for r in step.get("rejections", [])]
    run = {
        **record,
        "status": status.get("status"),
        "steps": step_records(steps),
        "generators": generator_counts(steps),
        "fallbacks": fallbacks_of(steps),
        "expectedResources": sum(expected.values()),
        "undelivered": undelivered_of(steps, expected),
        "planWarnings": [warning for s in steps for warning in s.get("planWarnings") or []],
        "rejectionKinds": {kind: rejections.count(kind) for kind in sorted(set(rejections))},
        "planGenerator": plan_generator_info(plan),
        "planConcepts": plan_concepts_of(plan),
        "evidenceConcepts": evidence_concepts_of(request_evidence_texts(client, headers, request_id)),
        # Los textos quedan en el informe para recalcular y calibrar después (--recompute, --calibrate).
        "resources": resources,
    }
    run.update(compute_metrics(resources, run["planConcepts"], run["evidenceConcepts"], similarity, threshold,
                               sentence_threshold))
    with_ai_only(run, similarity, threshold, sentence_threshold)
    return run


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


# --------------------------------------------------------------------------- calibración


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


def _unrelated(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Tipos distintos en ítems distintos del plan: no deberían repetir contenido."""
    return (a.get("planItemPosition") is not None and b.get("planItemPosition") is not None
            and a["planItemPosition"] != b["planItemPosition"] and a.get("type") != b.get("type"))


def calibrate(reports: Sequence[dict[str, Any]], similarity: Similarity, label: str) -> dict[str, Any]:
    """Distribuciones de similitud de pares sin repetición y de pares repetidos, y los umbrales sugeridos. Arma
    primero todos los pares y después los compara juntos (con embeddings, por lotes)."""
    unrelated: list[tuple[str, str]] = []
    repeated: list[tuple[str, str]] = []
    sentence_unrelated: list[tuple[str, str]] = []
    sentence_repeated: list[tuple[str, str]] = []
    for report in reports:
        for run in report.get("runs", []):
            resources = [r for r in run.get("resources") or [] if r.get("text")]
            texts = [r["text"] for r in resources]
            unrelated += [(texts[i], texts[j]) for i in range(len(resources)) for j in range(i + 1, len(resources))
                          if _unrelated(resources[i], resources[j])]
            for i, text in enumerate(texts):
                other = texts[(i + 1) % len(texts)]
                repeated += [(text, _reordered(text)), (text, _half_copy(text, other))]
            sentences = [(i, s) for i, r in enumerate(resources) for s in resource_sentences(resource_body(r))]
            pairs = [(x[1], y[1]) for n, x in enumerate(sentences) for y in sentences[n + 1:]
                     if x[0] != y[0] and _unrelated(resources[x[0]], resources[y[0]])]
            sentence_unrelated += pairs[:MAX_CALIBRATION_SENTENCE_PAIRS]
            sentence_repeated += [(s, _paraphrased_sentence(s)) for _, s in sentences]
    cross = 0
    for n, first in enumerate(reports):
        for second in reports[n + 1:]:
            if first.get("corpus") and second.get("corpus") and first["corpus"] != second["corpus"]:
                a = [r["text"] for run in first.get("runs", []) for r in run.get("resources") or [] if r.get("text")]
                b = [r["text"] for run in second.get("runs", []) for r in run.get("resources") or [] if r.get("text")]
                unrelated += [(x, y) for x in a for y in b]
                cross += len(a) * len(b)
    progress(f"Calibración: {len(unrelated) + len(repeated)} pares de recursos y "
             f"{len(sentence_unrelated) + len(sentence_repeated)} pares de oraciones.")
    scores = {name: pair_scores(similarity, pairs) for name, pairs in (
        ("unrelated", unrelated), ("repeated", repeated),
        ("sentenceUnrelated", sentence_unrelated), ("sentenceRepeated", sentence_repeated))}
    pair_suggestion = suggest_threshold(scores["unrelated"], scores["repeated"])
    sentence_suggestion = suggest_threshold(scores["sentenceUnrelated"], scores["sentenceRepeated"])
    return {
        "calibration": "P4 · umbrales de duplicación (research R7)",
        "similarity": label,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "resourcePairs": {"unrelated": distribution(scores["unrelated"]),
                          "repeated": distribution(scores["repeated"])},
        "sentencePairs": {"unrelated": distribution(scores["sentenceUnrelated"]),
                          "repeated": distribution(scores["sentenceRepeated"])},
        "crossCorpusPairs": cross,
        "suggested": {
            "pairThreshold": pair_suggestion["threshold"], "pairOverlap": pair_suggestion["overlap"],
            "sentenceThreshold": sentence_suggestion["threshold"], "sentenceOverlap": sentence_suggestion["overlap"],
        },
        "notes": [
            "Sin repetición: recursos de tipos distintos en ítems distintos del plan (y de otro corpus, si se pasó un "
            "informe de otro corpus). Repetidos: el mismo recurso con sus oraciones en otro orden y medio recurso "
            "copiado; en oraciones (sin títulos), la misma oración sin su primera palabra y con sus mitades cambiadas.",
            "Si `overlap` es true, los dos grupos se mezclan: el umbral sugerido es el p95 de los pares sin repetición "
            "y la métrica de pares no distingue bien «mismo tema» de «contenido repetido».",
        ],
    }


def _get_or_fail(client: httpx.Client, headers: dict, path: str, request_id: str) -> dict[str, Any]:
    response = client.get(path, headers=headers)
    if response.status_code != 200:
        raise SystemExit(WRONG_ACCOUNT.format(path=path, status=response.status_code, request_id=request_id))
    return response.json()


def fetch_run_resources(client: httpx.Client, headers: dict, run: dict[str, Any]) -> list[dict[str, Any]]:
    """Los recursos de una corrida de un informe que no guardó sus textos, leídos de la API por su pedido. Si la API
    no devuelve el pedido (otra cuenta, otra base), se detiene con el motivo en lugar de seguir sin pares."""
    status = _get_or_fail(client, headers, f"{REQUESTS_PATH}/{run['requestId']}", run["requestId"])
    return stored_resources(delivered_resources(client, headers, status["unitId"], status), status.get("steps", []))


def _api_session(args: argparse.Namespace, why: str) -> tuple[httpx.Client, dict]:
    email, password = os.environ.get("EVAL_EMAIL"), os.environ.get("EVAL_PASSWORD")
    if not email or not password:
        raise SystemExit(f"{why}: define EVAL_EMAIL y EVAL_PASSWORD con la cuenta que creó los informes.")
    client = httpx.Client(base_url=args.api, timeout=120)
    return client, load_collect_samples().login(client, email, password)


def run_calibration(args: argparse.Namespace, embedder_factory: Callable[[], Any] | None) -> dict[str, Any]:
    if not args.reports:
        raise SystemExit("--calibrate necesita al menos un informe con --from.")
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.reports]
    missing = [run for report in reports for run in report.get("runs", [])
               if not run.get("resources") and run.get("requestId")]
    if missing:  # informes anteriores sin textos: se leen de la API (la misma cuenta, el mismo backend y la misma base)
        client, headers = _api_session(args, "Los informes no traen los textos")
        try:
            for number, run in enumerate(missing, 1):
                progress(f"Leyendo los recursos del pedido {number}/{len(missing)}…")
                run["resources"] = fetch_run_resources(client, headers, run)
        finally:
            client.close()
    similarity, label = choose_similarity(args.similarity, embedder_factory)
    calibration = calibrate(reports, similarity, label)
    calibration["reports"] = [path.name for path in args.reports]
    write_json(args.out, calibration)
    suggested = calibration["suggested"]
    print(f"Umbral sugerido de pares: {suggested['pairThreshold']} (se mezclan: {suggested['pairOverlap']}) · "
          f"de oraciones: {suggested['sentenceThreshold']} (se mezclan: {suggested['sentenceOverlap']}). "
          f"Informe: {args.out}")
    return calibration


# --------------------------------------------------------------------------- recálculo


def _drafters_from_steps(run: dict[str, Any]) -> None:
    """Informes v3 y anteriores: quién redactó cada recurso sale del paso de su ítem (con plan) o de su tipo."""
    by_position = {s.get("planItemPosition"): s for s in run.get("steps", []) if s.get("planItemPosition") is not None}
    by_type = {s.get("resourceType"): s for s in run.get("steps", [])}
    for resource in run.get("resources") or []:
        if resource.get("drafter"):
            continue
        step = by_position.get(resource.get("planItemPosition")) or by_type.get(resource.get("type"))
        resource["drafter"] = drafter_of(step) if step else "none"


def recompute_report(
    report: dict[str, Any],
    similarity: Similarity,
    label: str,
    threshold: float,
    sentence_threshold: float,
    fetch_concepts: Callable[[dict[str, Any]], tuple[list[str] | None, list[str] | None]] | None = None,
) -> dict[str, Any]:
    """Recalcula todas las métricas con los textos guardados, sin generar. Conserva los datos de cada corrida."""
    runs = []
    for run in report.get("runs", []):
        run = dict(run)
        if not run.get("resources"):
            runs.append(run)
            continue
        _drafters_from_steps(run)
        if run.get("evidenceConcepts") is None and fetch_concepts is not None:
            run["planConcepts"], run["evidenceConcepts"] = fetch_concepts(run)
        run.update(compute_metrics(run["resources"], run.get("planConcepts"), run.get("evidenceConcepts"),
                                   similarity, threshold, sentence_threshold))
        with_ai_only(run, similarity, threshold, sentence_threshold)
        runs.append(run)
    recomputed = {**report, "runs": runs, "threshold": threshold, "sentenceThreshold": sentence_threshold,
                  "similarity": label, "recomputedAt": datetime.now(timezone.utc).isoformat()}
    recomputed["summary"] = summarize(runs)
    recomputed.pop("comparison", None)
    return recomputed


def fill_contexts(args: argparse.Namespace, report: dict[str, Any], client: httpx.Client | None,
                  headers: dict | None) -> None:
    """Informes v4 y anteriores: los textos citados de cada recurso se leen una vez de la API (la misma cuenta) y quedan
    en el informe recalculado."""
    missing = [run for run in report.get("runs", [])
               if any("contexts" not in r for r in run.get("resources") or [])]
    if not missing:
        return
    own = client is None
    if own:
        client, headers = _api_session(args, "El informe no guarda los textos citados (--faithfulness)")
    try:
        for number, run in enumerate(missing, 1):
            progress(f"Leyendo los textos citados del pedido {number}/{len(missing)}…")
            fetched = {r["id"]: r["contexts"] for r in fetch_run_resources(client, headers, run)}
            for resource in run["resources"]:
                resource.setdefault("contexts", fetched.get(resource.get("id"), []))
    finally:
        if own:
            client.close()


def run_recompute(args: argparse.Namespace, embedder_factory: Callable[[], Any] | None,
                  judge_factory: Callable[[str], Callable[[dict], dict]] | None = None) -> dict[str, Any]:
    if len(args.reports) != 1:
        raise SystemExit("--recompute necesita un informe con --from.")
    report = json.loads(args.reports[0].read_text(encoding="utf-8"))
    similarity, label = choose_similarity(args.similarity, embedder_factory)
    threshold = args.threshold if args.threshold_given else report.get("threshold", DEFAULT_THRESHOLD)
    sentence_threshold = args.sentence_threshold if args.sentence_threshold is not None else (
        report.get("sentenceThreshold") or DEFAULT_SENTENCE_THRESHOLDS[
            "lexical" if label == LEXICAL_LABEL else "embeddings"])
    needs_concepts = any(run.get("resources") and run.get("evidenceConcepts") is None for run in report["runs"])
    client = None
    fetch = None
    if needs_concepts and os.environ.get("EVAL_EMAIL") and os.environ.get("EVAL_PASSWORD"):
        client, headers = _api_session(args, "Los conceptos no están en el informe")

        def fetch(run: dict[str, Any]) -> tuple[list[str] | None, list[str] | None]:
            texts = _get_or_fail(client, headers, f"{REQUESTS_PATH}/{run['requestId']}/evidence",
                                 run["requestId"]).get("fragments", [])
            plan = plan_details(client, headers, run.get("planId") or run.get("requestPlanId"))
            return plan_concepts_of(plan), evidence_concepts_of([str(f.get("text") or "") for f in texts])
    elif needs_concepts:
        progress("El informe no guarda los conceptos y no hay EVAL_EMAIL: las métricas de conceptos quedan vacías.")
    try:
        if args.faithfulness:
            fill_contexts(args, report, client, headers if client is not None else None)
        recomputed = recompute_report(report, similarity, label, threshold, sentence_threshold, fetch)
    finally:
        if client is not None:
            client.close()
    recomputed["recomputedFrom"] = args.reports[0].name
    add_faithfulness(args, recomputed, judge_factory)
    add_comparison(args, recomputed)
    write_json(args.out, recomputed)
    print_summary(recomputed, label, args.out)
    return recomputed


# --------------------------------------------------------------------------- informe


def build_report(args: argparse.Namespace, similarity_label: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "measure": "P4 · duplicación entre recursos de una misma generación",
        "mode": args.mode,
        "api": args.api,
        "corpus": str(args.corpus),
        "resourceTypes": list(args.types),
        "quantity": args.quantity,
        "instructions": INSTRUCTIONS,
        "threshold": args.threshold,
        "sentenceThreshold": args.sentence_threshold,
        "similarity": similarity_label,
        "server": SERVER_SETTING[args.mode],
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "summary": summarize(runs),
        "runs": runs,
    }


def add_comparison(args: argparse.Namespace, report: dict[str, Any]) -> None:
    if args.compare is not None:
        baseline = json.loads(args.compare.read_text(encoding="utf-8"))
        report["comparison"] = compare(baseline["summary"], report["summary"])


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def print_summary(report: dict[str, Any], label: str, out: Path) -> None:
    summary = report["summary"]
    print(f"Oraciones casi repetidas entre tipos distintos: {summary['crossTypeSentenceRate']} (todas: "
          f"{summary['sentenceNearDuplicateRate']}, variantes: {summary['variantsSentenceRate']}) · conceptos "
          f"explicados otra vez (evidencia): {summary['meanReexplainedEvidenceConcepts']}.")
    print(f"Tasa de pares: {summary['duplicateRate']} (entre tipos distintos: {summary['crossTypeDuplicateRate']}) · "
          f"recursos por pedido: {summary['resourcesPerRequest']} · pasos IA/respaldo: {summary['aiSteps']}/"
          f"{summary['fallbackSteps']} · planes IA/reglas: {summary['planGenerators']} ({label}). Informe: {out}")
    faithfulness = summary.get("faithfulness")
    if faithfulness:
        ai = faithfulness["aiOnly"]
        print(f"Fidelidad: media {faithfulness['mean']} · ≥ {FAITHFULNESS_TARGET}: {faithfulness['atLeastTarget']} · "
              f"calificados/omitidos/errores: {faithfulness['scored']}/{faithfulness['skipped']}/"
              f"{faithfulness['errors']} · solo IA: {ai['mean']} ({ai['scored']} recursos).")
    comparison = report.get("comparison", {}).get("faithfulness")
    if comparison:
        print(f"Fidelidad con plan frente a la línea base: {comparison['difference']} · el plan la mantiene en "
              f"{FAITHFULNESS_TARGET} o más: {comparison['planMeetsTarget']}.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mide la duplicación con y sin plan (P4, GEN-P2).")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="URL base del backend (sin / al final)")
    parser.add_argument("--mode", choices=MODES, help="obligatorio salvo con --calibrate o --recompute")
    parser.add_argument("--corpus", type=Path, default=HERE / "corpus_t067")
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    parser.add_argument("--quantity", type=int, default=2, help="recursos por tipo (de 1 a 5)")
    parser.add_argument("--types", nargs="+", default=list(SEQUENCE_TYPES))
    parser.add_argument("--threshold", type=float, default=None, help="τ: similitud de un par duplicado (0,85)")
    parser.add_argument("--similarity", choices=SIMILARITIES, default="auto")
    parser.add_argument("--sentence-threshold", type=float, default=None,
                        help="similitud de una oración casi repetida (0,92 con embeddings y 0,6 léxica por defecto)")
    parser.add_argument("--calibrate", action="store_true",
                        help="calcula las distribuciones de similitud y sugiere los umbrales (con --from)")
    parser.add_argument("--recompute", action="store_true",
                        help="recalcula las métricas con los textos de un informe (con --from), sin generar")
    parser.add_argument("--from", dest="reports", type=Path, nargs="*", default=[],
                        help="informes de corridas anteriores para --calibrate o --recompute")
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
    parser.add_argument("--poll", type=float, default=2.0)
    parser.add_argument("--timeout", type=float, default=30 * 60, help="segundos máximos por corrida")
    parser.add_argument("--out", type=Path, required=True, help="archivo JSON del informe")
    parser.add_argument("--faithfulness", action="store_true",
                        help="califica la fidelidad de cada recurso con el juez de run_ragas.py (GEMINI_API_KEY)")
    parser.add_argument("--judge-model", default=os.getenv("RAGAS_JUDGE_MODEL", "gemini-3.8-flash"),
                        help="modelo del juez, el mismo de run_ragas.py por defecto")
    parser.add_argument("--judge-concurrency", type=int, default=DEFAULT_JUDGE_CONCURRENCY,
                        help="llamadas al juez a la vez (2 por defecto)")
    parser.add_argument("--rescore-faithfulness", action="store_true",
                        help="con --recompute, vuelve a calificar también los recursos que ya tienen puntaje")
    parser.add_argument("--compare", type=Path, default=None,
                        help="informe de la línea base: agrega la comparación (recalcúlalo antes si es anterior)")
    return parser


def main(argv: Sequence[str] | None = None, embedder_factory: Callable[[], Any] | None = None,
         judge_factory: Callable[[str], Callable[[dict], dict]] | None = None) -> dict[str, Any]:
    args = build_parser().parse_args(argv)
    args.threshold_given = args.threshold is not None
    if args.threshold is None:
        args.threshold = DEFAULT_THRESHOLD
    if not 0 < args.threshold <= 1:
        raise SystemExit("--threshold va de 0 a 1.")
    if args.calibrate:
        return run_calibration(args, embedder_factory)
    if args.recompute:
        return run_recompute(args, embedder_factory, judge_factory)
    if args.mode is None:
        raise SystemExit("Indica --mode plan o --mode baseline (o --calibrate, o --recompute).")
    if not 1 <= args.quantity <= 5:
        raise SystemExit("--quantity va de 1 a 5.")
    email, password = os.environ.get("EVAL_EMAIL"), os.environ.get("EVAL_PASSWORD")
    if not email or not password:
        raise SystemExit("Define EVAL_EMAIL y EVAL_PASSWORD.")
    similarity, label = choose_similarity(args.similarity, embedder_factory)
    if args.sentence_threshold is None:
        args.sentence_threshold = DEFAULT_SENTENCE_THRESHOLDS["lexical" if label == LEXICAL_LABEL else "embeddings"]
    # El juez se prepara antes de generar: sin Ragas o sin clave, la medición se detiene sin gastar corridas.
    judge = (judge_factory or default_judge)(args.judge_model) if args.faithfulness else None
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
    add_faithfulness(args, report, judge_factory, judge)
    add_comparison(args, report)
    write_json(args.out, report)
    print_summary(report, label, args.out)
    return report


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
