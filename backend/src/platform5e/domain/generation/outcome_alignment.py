"""
GEN-C14 (spec 002, T076, research R14): anclaje de la redacción al resultado de aprendizaje elegido, sin IA.

En producción, con «RA1.1: Reconoce…» elegido, el recurso habló del Renacimiento y pidió analizar y comparar: el
resultado y el título de la unidad solo servían para recuperar la evidencia. Aquí están las reglas léxicas que usan el
generador por reglas, el planificador por reglas y el prompt de Gemini:

- **Términos de anclaje.** Los del resultado elegido (sin su código ni su verbo) y los del título de la unidad, con la
  regla de término de QA-05. Se comparan sin tildes y con singular y plural (`plan_coverage.mentions`).
- **Nivel del verbo.** Una tabla explícita, `VERB_LEVELS`; un verbo fuera de ella no tiene nivel y la consigna no cambia.
- **Alineación.** Un recurso está alineado si alguna de sus oraciones citadas menciona un término de anclaje; si no,
  se entrega con el aviso `outcome_misaligned`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any

from platform5e.domain.generation.plan_coverage import mentions
from platform5e.domain.generation.topic_coverage import is_topic_term, normalize

RECALL: str = "recordar"
UNDERSTAND: str = "comprender"
ANALYZE: str = "analizar"

# Verbo del resultado (tercera persona e infinitivo, sin tildes) → nivel.
VERB_LEVELS: dict[str, str] = {
    **dict.fromkeys(
        ("reconoce", "reconocer", "identifica", "identificar", "define", "definir", "nombra", "nombrar", "enumera",
         "enumerar"),
        RECALL,
    ),
    **dict.fromkeys(("explica", "explicar", "describe", "describir", "resume", "resumir"), UNDERSTAND),
    **dict.fromkeys(
        ("analiza", "analizar", "compara", "comparar", "evalua", "evaluar", "contrasta", "contrastar", "justifica",
         "justificar"),
        ANALYZE,
    ),
}
# Lo que pide cada nivel, para el prompt de Gemini.
LEVEL_INSTRUCTIONS: dict[str, str] = {
    RECALL: "pide reconocer o recordar una idea: un enunciado breve o una pregunta de recuerdo; no pidas analizar, "
    "comparar ni evaluar.",
    UNDERSTAND: "pide explicar o describir con sus palabras una idea del material.",
    ANALYZE: "plantea una pregunta compleja que pida analizar, comparar o evaluar ideas del material.",
}
# El verbo se busca entre las primeras palabras («El estudiante reconoce…»).
VERB_POSITIONS: int = 3
MISALIGNED_KIND: str = "outcome_misaligned"

_CODE = re.compile(r"^\s*[A-Za-z]{1,4}\s*\d+(?:\.\d+)*\s*[:.)-]\s*")  # «RA1.1: »
_WORD = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+")


def split_outcome(text: str) -> tuple[str | None, str]:
    """El verbo de la tabla (sin tildes) y el resto del resultado, sin su código («RA1.1: »). Un resultado empieza por
    su verbo: si no está en la tabla («Distingue TCP y UDP»), se devuelve None y el resto sin la primera palabra,
    salvo que sea una sigla."""
    body = _CODE.sub("", text or "", count=1).strip()
    words = list(_WORD.finditer(body))
    for match in words[:VERB_POSITIONS]:
        verb = normalize(match.group())
        if verb in VERB_LEVELS:
            return verb, body[match.end():].strip()
    if words and not words[0].group().isupper():
        return None, body[words[0].end():].strip()
    return None, body


def verb_level(outcome_text: str) -> str | None:
    """El nivel del verbo del resultado, o None si el verbo no está en la tabla."""
    verb, _ = split_outcome(outcome_text)
    return VERB_LEVELS.get(verb) if verb else None


def anchor_terms(outcome_text: str, unit_title: str) -> list[str]:
    """Los términos del resultado (sin código ni verbo) y del título de la unidad, como se escribieron, sin repetir."""
    _, outcome_body = split_outcome(outcome_text)
    terms: list[str] = []
    seen: set[str] = set()
    for word in _WORD.findall(f"{outcome_body} {unit_title or ''}"):
        key = normalize(word)
        if is_topic_term(word) and key not in VERB_LEVELS and key not in seen:
            seen.add(key)
            terms.append(word)
    return terms


def anchor_score(text: str, terms: Sequence[str]) -> int:
    """Cuántos términos de anclaje menciona el texto."""
    return sum(mentions(text, term) for term in terms)


def is_aligned(texts: Iterable[str], terms: Sequence[str]) -> bool:
    """True si algún texto menciona un término de anclaje, o si no hay términos que comprobar."""
    return not terms or any(anchor_score(text, terms) for text in texts)


def misaligned_warning(terms: Sequence[str]) -> dict[str, Any]:
    """El aviso de un recurso entregado sin mencionar el resultado ni la unidad (forma de `planWarning`)."""
    shown = ", ".join(f"«{term}»" for term in terms[:6])
    return {
        "kind": MISALIGNED_KIND,
        "reason": (
            f"Ninguna oración del material que cita este recurso menciona el resultado de aprendizaje ni la unidad "
            f"({shown}). Revisa que trate el tema antes de aprobarlo."
        ),
        "developedConcepts": [],
        "missingOwnConcepts": [],
    }
