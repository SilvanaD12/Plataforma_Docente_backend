"""
GEN-P2 y CUR-P2: reglas de los tipos de texto del catálogo configurable (specs/006-plan-de-generacion, research R6).

- **Extensión (`lengthHint`).** `{minWords, maxWords}` enteros, `minWords` ≥ 20, `maxWords` ≤ 600 y
  `minWords` ≤ `maxWords`. Es una guía del prompt («entre X y Y palabras»), nunca una regla de rechazo; una entrada
  que no cumple las reglas se trata como si no tuviera `lengthHint`.
- **Verificación.** `strict`: cada párrafo se contrasta con el material, como en `explicacion`. `framed`: las
  oraciones de ambientación (la escena, los personajes, el formato) no necesitan cita, pero cada oración sobre un
  concepto sí, y hacen falta al menos 2 con respaldo.
- **Evidencia que necesita un tipo `strict`.** Si la evidencia del ítem no tiene lo que el tipo necesita, el recurso no
  se redacta y se rechaza con el motivo: la frase célebre comentada necesita una cita textual en el material; los
  demás tipos `strict` necesitan que el material trate al menos uno de sus conceptos.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from platform5e.domain.generation.plan_coverage import mentions

MIN_HINT_WORDS: int = 20
MAX_HINT_WORDS: int = 600
VERIFICATION_STRICT: str = "strict"
VERIFICATION_FRAMED: str = "framed"
VERIFICATION_MODES: frozenset[str] = frozenset({VERIFICATION_STRICT, VERIFICATION_FRAMED})
# Una cita textual: entre comillas latinas, inglesas o rectas, con al menos 4 palabras.
MIN_QUOTE_WORDS: int = 4
_QUOTES = re.compile(r"«([^»]+)»|“([^”]+)”|\"([^\"]+)\"")
LITERAL_QUOTE: str = "literal_quote"
# Lo que necesita en la evidencia cada tipo `strict` con una exigencia propia (catálogo de CUR-P2, PR #70).
EVIDENCE_REQUIREMENTS: dict[str, str] = {"frase_celebre_comentada": LITERAL_QUOTE}
NO_QUOTE_MESSAGE: str = "El material no tiene una cita textual para este tema."
NO_CONCEPT_MESSAGE: str = "El material no trata {concepts}: este tipo solo usa lo que dice el material."


@dataclass(frozen=True)
class LengthHint:
    min_words: int
    max_words: int

    def instruction(self) -> str:
        return f"Extensión: entre {self.min_words} y {self.max_words} palabras."

    def to_payload(self) -> dict[str, int]:
        return {"minWords": self.min_words, "maxWords": self.max_words}


def _whole_number(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def length_hint_from(raw: Any) -> LengthHint | None:
    """El `lengthHint` de una entrada del catálogo, o None si falta o no cumple las reglas."""
    if not isinstance(raw, dict):
        return None
    low, high = raw.get("minWords"), raw.get("maxWords")
    if not (_whole_number(low) and _whole_number(high)):
        return None
    if low < MIN_HINT_WORDS or high > MAX_HINT_WORDS or low > high:
        return None
    return LengthHint(low, high)


def verification_mode(raw: Any) -> str | None:
    """`strict`, `framed` o None si la entrada no trae uno de los dos."""
    return raw if raw in VERIFICATION_MODES else None


def literal_quotes(text: str) -> list[str]:
    """Las citas textuales del texto: lo que está entre comillas, con al menos 4 palabras."""
    quotes = []
    for match in _QUOTES.finditer(text or ""):
        quote = next(group for group in match.groups() if group is not None).strip()
        if len(quote.split()) >= MIN_QUOTE_WORDS:
            quotes.append(quote)
    return quotes


def evidence_gap(
    resource_type: str, verification: str | None, concepts: Sequence[str], fragment_texts: Sequence[str]
) -> str | None:
    """Por qué un tipo `strict` no se puede redactar con esta evidencia, o None si se puede (o si no es `strict`)."""
    if verification != VERIFICATION_STRICT:
        return None
    if EVIDENCE_REQUIREMENTS.get(resource_type) == LITERAL_QUOTE:
        if not any(literal_quotes(text) for text in fragment_texts):
            return NO_QUOTE_MESSAGE
    if concepts:
        evidence = " ".join(fragment_texts)
        if not any(mentions(evidence, concept) for concept in concepts):
            return NO_CONCEPT_MESSAGE.format(concepts=", ".join(f"«{concept}»" for concept in concepts))
    return None
