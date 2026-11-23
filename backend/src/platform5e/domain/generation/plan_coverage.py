"""
GEN-P2: comprobación de cobertura del plan, léxica y sin IA (specs/006-plan-de-generacion, research R5).

Cada recurso de un ítem debe desarrollar su bloque de conceptos y no los de los demás recursos del plan:

- **Conceptos propios.** El recurso menciona al menos uno: todas sus palabras útiles aparecen en el recurso (título,
  contenido, estructura, opciones o retroalimentación).
- **Conceptos ajenos, en un recurso de varios párrafos.** Un concepto ajeno que aparece como término completo (sus
  palabras útiles seguidas) en más de un párrafo cuenta como desarrollado. Puede nombrarse una vez. Si solo aparece
  dentro de un concepto propio («capas» dentro de «capa de transporte»), no cuenta.
- **Conceptos ajenos, en un recurso de un solo párrafo** (pregunta detonante, ítem de opción múltiple y otros tipos
  cortos, decidido por el contenido entregado y no por el tipo): la regla anterior nunca se cumpliría, así que basta
  con que aparezca completo en el enunciado o en una opción. La retroalimentación de las opciones no se cuenta.

Los textos se comparan con la normalización de QA-05: minúsculas, sin tildes y sin palabras vacías. Las palabras se
comparan también sin la «s» o «es» del plural.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from platform5e.domain.generation.topic_coverage import concept_key

def _stem(word: str) -> str:
    """La palabra sin la terminación de plural más común («segmentos» → «segmento», «redes» → «red»)."""
    if len(word) > 4 and word.endswith("es"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s"):
        return word[:-1]
    return word


def concept_words(concept: str) -> list[str]:
    """Las palabras útiles del concepto, normalizadas y sin plural."""
    return [_stem(word) for word in concept_key(concept).split()]


def text_words(text: str) -> list[str]:
    """Las palabras del texto, normalizadas, sin las palabras vacías de los conceptos y sin plural."""
    return [_stem(word) for word in concept_key(text).split()]


def mentions(text: str, concept: str) -> bool:
    """True si todas las palabras útiles del concepto aparecen en el texto (en cualquier orden)."""
    words = concept_words(concept)
    present = set(text_words(text))
    return bool(words) and all(word in present for word in words)


def _contains_words(tokens: list[str | None], words: list[str]) -> bool:
    size = len(words)
    return bool(words) and any(tokens[start:start + size] == words for start in range(len(tokens) - size + 1))


def contains_term(text: str, concept: str) -> bool:
    """True si el concepto aparece completo en el texto: sus palabras útiles, seguidas y en orden."""
    return _contains_words(list(text_words(text)), concept_words(concept))


def _without(tokens: list[str | None], concepts: Sequence[str]) -> list[str | None]:
    """Las palabras del texto con las apariciones de esos conceptos tapadas (de los más largos a los más cortos)."""
    masked = list(tokens)
    for concept in sorted(concepts, key=lambda c: -len(concept_words(c))):
        words = concept_words(concept)
        size = len(words)
        for start in range(len(masked) - size + 1):
            if size and masked[start:start + size] == words:
                masked[start:start + size] = [None] * size
    return masked


def _paragraphs(body: str) -> list[str]:
    """Los párrafos del contenido: separados por una línea en blanco o, si no hay ninguna, uno por línea (las
    entradas del glosario), como `split_statements` de la verificación de anclaje."""
    text = body or ""
    parts = re.split(r"\n\s*\n", text) if re.search(r"\n\s*\n", text) else text.split("\n")
    return [part.strip() for part in parts if part.strip()]


def _structure_texts(value: Any) -> list[str]:
    """Los textos de la estructura del recurso (pasos, pares, afirmaciones…), uno por elemento de texto."""
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        return [text for item in value.values() for text in _structure_texts(item)]
    if isinstance(value, list):
        return [text for item in value for text in _structure_texts(item)]
    return []


def _option_texts(resource: dict[str, Any]) -> list[str]:
    return [str(option.get("texto") or "") for option in resource.get("alternativas") or [] if isinstance(option, dict)]


def _feedback_texts(resource: dict[str, Any]) -> list[str]:
    return [
        str(option.get("retroalimentacion") or "")
        for option in resource.get("alternativas") or []
        if isinstance(option, dict)
    ]


def _quoted(concepts: Iterable[str]) -> str:
    return ", ".join(f"«{concept}»" for concept in concepts)


@dataclass(frozen=True)
class PlanCoverage:
    """Resultado de la comprobación: `problem` es el motivo para el docente; `instruction`, la indicación del
    reintento al generador."""

    accepted: bool
    own: tuple[str, ...]
    foreign: tuple[str, ...]
    title: str = ""
    missing_own: bool = False
    developed: list[str] = field(default_factory=list)

    @property
    def problem(self) -> str | None:
        if self.accepted:
            return None
        if self.missing_own:
            return f"«{self.title}»: no desarrolla ninguno de sus conceptos del plan ({_quoted(self.own)})."
        return f"«{self.title}»: desarrolla {_quoted(self.developed)}, que el plan asigna a otro recurso."

    @property
    def instruction(self) -> str:
        """Indicación para pedir el recurso otra vez."""
        parts = [f"Tu recurso anterior no respetó el plan: {self.problem}"] if not self.accepted else []
        if self.own:
            parts.append(f"Desarrolla solo estos conceptos: {_quoted(self.own)}.")
        if self.foreign:
            parts.append(f"No desarrolles estos, que son de otros recursos del plan: {_quoted(self.foreign)}.")
        return " ".join(parts)


def check_plan_coverage(
    resource: dict[str, Any], own: Sequence[str], foreign: Sequence[str]
) -> PlanCoverage:
    """Comprueba un recurso redactado (formato del generador: `titulo`, `contenido`, `alternativas`, `estructura`)
    contra su bloque de conceptos (`own`) y los de los demás recursos del plan (`foreign`)."""
    title = str(resource.get("titulo") or "")
    body = str(resource.get("contenido") or "")
    paragraphs = _paragraphs(body)
    structure = _structure_texts(resource.get("estructura"))
    options = _option_texts(resource)
    own_tuple, foreign_tuple = tuple(own), tuple(foreign)

    everything = " ".join([title, body, *structure, *options, *_feedback_texts(resource)])
    if own_tuple and not any(mentions(everything, concept) for concept in own_tuple):
        return PlanCoverage(False, own_tuple, foreign_tuple, title, missing_own=True)

    single_paragraph = len(paragraphs) <= 1 and not structure
    # Un concepto ajeno que solo aparece dentro de uno propio («capas» en «capa de transporte») no cuenta.
    parts = [_without(list(text_words(part)), own_tuple) for part in [*paragraphs, *structure, *options]]
    developed: list[str] = []
    for concept in foreign_tuple:
        appearances = sum(_contains_words(part, concept_words(concept)) for part in parts)
        if appearances >= 2 or (single_paragraph and appearances >= 1):
            developed.append(concept)
    if developed:
        return PlanCoverage(False, own_tuple, foreign_tuple, title, developed=developed)
    return PlanCoverage(True, own_tuple, foreign_tuple, title)
