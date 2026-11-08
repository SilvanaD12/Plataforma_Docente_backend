"""
Fiabilidad de los distractores (HU-019): un distractor que la evidencia muestra como correcto se descarta.
Alimenta el indicador I5 (error de fiabilidad: distractores que también son correctos / evaluados, meta ≤ 5 %).

Un distractor es «también correcto» si:
- una oración del material contiene todas sus palabras y la mayor parte de las palabras del enunciado, sin negación
  (el material lo afirma como respuesta a la pregunta), o
- dice prácticamente lo mismo que la respuesta correcta.

Son reglas por palabras y explicables, como la verificación de anclaje (ADR-014): no entienden sinónimos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from platform5e.domain.generation.grounding import terms_support
from platform5e.domain.generation.sequence import content_similarity
from platform5e.domain.materials.text_analysis import extract_terms, normalize_text

# Proporción mínima de las palabras del enunciado que debe tener la oración del material.
STEM_COVERAGE: float = 0.6
# Similitud con la clave a partir de la cual el distractor dice lo mismo que la respuesta correcta.
KEY_SIMILARITY: float = 0.8
NEGATIONS: frozenset[str] = frozenset("no nunca ni sin tampoco jamas excepto salvo".split())
_SENTENCE_END = re.compile(r"(?<=[.;!?])\s+|\n+")


@dataclass(frozen=True)
class ReliabilityIssue:
    """Por qué un distractor no es fiable y en qué parte del material se ve."""

    reason: str
    fragment_id: str | None = None


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text or "") if s.strip()]


def _is_negated(sentence: str) -> bool:
    return any(word in NEGATIONS for word in re.findall(r"[a-zñ]+", normalize_text(sentence)))


def _short(text: str, limit: int = 140) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def assess_distractor(
    stem: str,
    key_text: str,
    distractor_text: str,
    fragments_by_id: dict[str, str],
) -> ReliabilityIssue | None:
    """Devuelve el problema de fiabilidad del distractor, o None si la evidencia no lo muestra como correcto."""
    if content_similarity(distractor_text, key_text) >= KEY_SIMILARITY:
        return ReliabilityIssue(f"Dice prácticamente lo mismo que la respuesta correcta («{_short(key_text, 80)}»).")

    distractor_terms = set(extract_terms(distractor_text))
    if not distractor_terms:
        return None
    # Solo cuentan las palabras del enunciado que existen en el material: las de la consigna («según», «término»,
    # «completa»…) no ayudan a decidir y bajarían la cobertura.
    vocabulary = " ".join(fragments_by_id.values())
    key_terms = set(extract_terms(key_text))
    stem_terms = {
        term
        for term in set(extract_terms(stem)) - distractor_terms - key_terms
        if terms_support({term}, [vocabulary]) == 1.0
    }
    if not stem_terms:
        return None

    for fragment_id, text in fragments_by_id.items():
        for sentence in _sentences(text):
            if _is_negated(sentence):
                continue
            if terms_support(distractor_terms, [sentence]) == 1.0 and terms_support(stem_terms, [sentence]) >= STEM_COVERAGE:
                return ReliabilityIssue(
                    f"El material también lo presenta como respuesta: «{_short(sentence.rstrip('.'))}».", fragment_id
                )
    return None


def reliability_report(resources: list[dict[str, Any]]) -> dict[str, Any]:
    """I5 automático: distractores descartados por ser también correctos / distractores evaluados."""
    distractors = [o for r in resources for o in (r.get("options") or []) if not o.get("isCorrect")]
    also_correct = sum(1 for o in distractors if o.get("reliabilityWarning"))
    return {
        "evaluatedDistractors": len(distractors),
        "discardedAsCorrect": also_correct,
        "reliabilityErrorRate": round(also_correct / len(distractors), 4) if distractors else None,
    }
