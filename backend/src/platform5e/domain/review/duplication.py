"""
REV-P3 · Detección de duplicidad de recursos y preguntas (REV-R15).

Algoritmo en Python puro basado en la combinación de n-gramas de caracteres (n=3..5)
y similitud de Jaccard sobre conjuntos de palabras: score = max(coseno, jaccard).
Sin dependencias externas ni consumo de modelos de lenguaje (LLM_PROVIDER=rules).
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

DEFAULT_DUPLICATE_THRESHOLD: float = 0.75

SPANISH_STOPWORDS: frozenset[str] = frozenset(
    {
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "unos",
        "unas",
        "de",
        "del",
        "que",
        "en",
        "y",
        "o",
        "a",
        "por",
        "para",
        "con",
        "se",
        "es",
        "como",
        "cual",
        "cuales",
        "su",
        "sus",
        "al",
        "lo",
        "este",
        "esta",
        "estos",
        "estas",
    }
)

_PUNCTUATION_OR_SPECIAL = re.compile(r"[^\w\s]|_", re.UNICODE)


def normalize(text: str | None) -> str:
    """Normaliza texto eliminando diacríticos, puntuación, mayúsculas y stopwords en español."""
    if not isinstance(text, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()
    cleaned = _PUNCTUATION_OR_SPECIAL.sub(" ", without_accents)
    tokens = [token for token in cleaned.split() if token not in SPANISH_STOPWORDS]
    return " ".join(tokens)


def _char_ngrams(text: str) -> Counter[str]:
    """Genera n-gramas de caracteres para n=3, 4 y 5."""
    counts: Counter[str] = Counter()
    length = len(text)
    for n in (3, 4, 5):
        if length >= n:
            for i in range(length - n + 1):
                counts[text[i : i + n]] += 1
    return counts


def _cosine_similarity(counts_a: Counter[str], counts_b: Counter[str]) -> float:
    """Calcula la similitud coseno entre dos frecuencias de n-gramas."""
    if not counts_a or not counts_b:
        return 0.0
    dot_product = sum(counts_a[key] * counts_b[key] for key in counts_a if key in counts_b)
    if dot_product == 0:
        return 0.0
    norm_a = math.sqrt(sum(count * count for count in counts_a.values()))
    norm_b = math.sqrt(sum(count * count for count in counts_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot_product / (norm_a * norm_b)


def _word_jaccard(tokens_a: set[str], tokens_b: set[str]) -> float:
    """Calcula el coeficiente Jaccard entre dos conjuntos de palabras."""
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return intersection / union if union > 0 else 0.0


def similarity(a: str | None, b: str | None) -> float:
    """Similitud combinada max(coseno, jaccard) redondeada a 3 decimales."""
    normalized_a = normalize(a)
    normalized_b = normalize(b)
    if not normalized_a or not normalized_b:
        return 0.0
    if normalized_a == normalized_b:
        return 1.0

    ngrams_a = _char_ngrams(normalized_a)
    ngrams_b = _char_ngrams(normalized_b)
    cosine = _cosine_similarity(ngrams_a, ngrams_b)

    words_a = set(normalized_a.split())
    words_b = set(normalized_b.split())
    jaccard = _word_jaccard(words_a, words_b)

    score = max(cosine, jaccard)
    return min(1.0, max(0.0, round(score, 3)))


def _extract_strings(data: Any) -> list[str]:
    """Extrae recursivamente todas las cadenas no vacías de una estructura anidada."""
    extracted: list[str] = []
    if isinstance(data, str):
        stripped = data.strip()
        if stripped:
            extracted.append(stripped)
    elif isinstance(data, Mapping):
        for value in data.values():
            extracted.extend(_extract_strings(value))
    elif isinstance(data, (list, tuple, set)):
        for item in data:
            extracted.extend(_extract_strings(item))
    return extracted


def resource_text(resource: Mapping[str, Any]) -> str:
    """Extrae el contenido textual completo del recurso (título, cuerpo, estructura y opciones)."""
    parts: list[str] = []
    title = resource.get("title")
    if isinstance(title, str) and title.strip():
        parts.append(title.strip())

    body = resource.get("body")
    if isinstance(body, str) and body.strip():
        parts.append(body.strip())

    structure = resource.get("structure")
    if structure:
        parts.extend(_extract_strings(structure))

    options = resource.get("options")
    if options:
        parts.extend(_extract_strings(options))

    return " ".join(parts)


def question_texts(resource: Mapping[str, Any]) -> list[str]:
    """Extrae enunciados de preguntas o ítems del recurso."""
    questions: list[str] = []
    resource_type = str(resource.get("type") or "")
    body = resource.get("body")

    is_question_type = (
        resource_type.startswith("item_")
        or resource_type in {"pregunta_detonante", "sondeo_diagnostico", "pregunta_abierta"}
    )
    if is_question_type and isinstance(body, str) and body.strip():
        questions.append(body.strip())

    structure = resource.get("structure")
    if isinstance(structure, Mapping):
        for key in ("statement", "question", "enunciado", "pregunta", "prompt"):
            val = structure.get(key)
            if isinstance(val, str) and val.strip() and val.strip() not in questions:
                questions.append(val.strip())

        items = structure.get("items") or structure.get("questions")
        if isinstance(items, list):
            for item in items:
                if isinstance(item, Mapping):
                    for key in ("statement", "question", "enunciado", "pregunta", "prompt", "body"):
                        val = item.get(key)
                        if isinstance(val, str) and val.strip() and val.strip() not in questions:
                            questions.append(val.strip())
                elif isinstance(item, str) and item.strip() and item.strip() not in questions:
                    questions.append(item.strip())

    return questions


def _excerpt(text: str, max_length: int = 160) -> str:
    """Genera un extracto de texto con longitud máxima de 160 caracteres."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_length:
        return collapsed
    return collapsed[: max_length - 3] + "..."


def find_duplicates(
    resources: Sequence[Mapping[str, Any]],
    threshold: float = 0.75,
) -> dict[str, Any]:
    """
    Compara todos los pares de recursos y preguntas dentro de la colección.
    Retorna pares ordenados con score >= threshold, total comparado y tasa de duplicidad.
    """
    resource_list = list(resources)
    num_resources = len(resource_list)
    flagged_pairs: list[dict[str, Any]] = []

    resource_pairs_count = num_resources * (num_resources - 1) // 2
    for i in range(num_resources):
        resource_a = resource_list[i]
        id_a = str(resource_a.get("id") or resource_a.get("exampleId") or f"resource-{i}")
        text_a = resource_text(resource_a)
        for j in range(i + 1, num_resources):
            resource_b = resource_list[j]
            id_b = str(resource_b.get("id") or resource_b.get("exampleId") or f"resource-{j}")
            text_b = resource_text(resource_b)
            score = similarity(text_a, text_b)
            if score >= threshold:
                flagged_pairs.append(
                    {
                        "resourceIdA": id_a,
                        "resourceIdB": id_b,
                        "scope": "resource",
                        "score": score,
                        "excerptA": _excerpt(text_a),
                        "excerptB": _excerpt(text_b),
                    }
                )

    all_questions: list[tuple[str, int, str]] = []
    for resource in resource_list:
        res_id = str(resource.get("id") or resource.get("exampleId") or "")
        for idx, q_text in enumerate(question_texts(resource)):
            all_questions.append((res_id, idx, q_text))

    num_questions = len(all_questions)
    question_pairs_count = num_questions * (num_questions - 1) // 2
    for a in range(num_questions):
        res_id_a, idx_a, q_text_a = all_questions[a]
        for b in range(a + 1, num_questions):
            res_id_b, idx_b, q_text_b = all_questions[b]
            score = similarity(q_text_a, q_text_b)
            if score >= threshold:
                flagged_pairs.append(
                    {
                        "resourceIdA": res_id_a,
                        "resourceIdB": res_id_b,
                        "scope": "question",
                        "score": score,
                        "excerptA": _excerpt(q_text_a),
                        "excerptB": _excerpt(q_text_b),
                    }
                )

    flagged_pairs.sort(key=lambda p: (p["score"], p["resourceIdA"], p["resourceIdB"]), reverse=True)
    total_compared = resource_pairs_count + question_pairs_count
    duplicate_pair_rate = (
        round(len(flagged_pairs) / total_compared, 3) if total_compared > 0 else 0.0
    )

    return {
        "threshold": threshold,
        "comparedPairs": total_compared,
        "flaggedPairs": flagged_pairs,
        "duplicatePairRate": duplicate_pair_rate,
    }
