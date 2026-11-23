"""
GEN-P2: comprobación de cobertura del plan, léxica y sin IA (specs/006-plan-de-generacion, research R5).

Cada recurso de un ítem debe desarrollar su bloque de conceptos y no los de los demás recursos del plan. Reglas
corregidas tras la medición de P4 con Gemini:

- **Conceptos propios.** Un concepto cuenta como desarrollado si al menos el 60 % de sus palabras útiles aparecen en un
  mismo párrafo (el título, un párrafo del contenido, un texto de la estructura o una opción), no solo la frase exacta:
  así cuenta una paráfrasis («un saludo en tres pasos» para «saludo de tres vías»). Las palabras se comparan por su
  raíz: sin plural y, si tienen seis letras o más, por sus seis primeras («confirma» y «confirmación»).
- **Conceptos ajenos.** Cuentan solo si el recurso los desarrolla: el término completo (sus palabras útiles seguidas)
  aparece en al menos dos oraciones, o en una oración que lo define («El protocolo UDP es…», «Datagrama: …»). Nombrarlo
  una vez no cuenta, tampoco en un recurso corto. Si solo aparece dentro de un concepto propio («capas» dentro de
  «capa de transporte»), no cuenta. La retroalimentación de las opciones no se cuenta.
- **Conceptos de fondo.** Un concepto del plan que está en los fragmentos de la mitad o más de los ítems es contexto
  compartido de la unidad, no de un solo recurso (`backbone_concepts`): quien llama no lo pasa como ajeno.

Los textos se comparan con la normalización de QA-05: minúsculas, sin tildes y sin palabras vacías.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from platform5e.domain.generation.generation_plan import PlanItem
from platform5e.domain.generation.topic_coverage import concept_key, normalize
from platform5e.domain.materials.chunking import extract_sentences

# Parte de las palabras útiles de un concepto propio que deben estar en un mismo párrafo.
MIN_OWN_SHARE: float = 0.6
# Oraciones en que debe aparecer un concepto ajeno para contar como desarrollado (si ninguna lo define).
MIN_FOREIGN_SENTENCES: int = 2
# Letras con que dos palabras largas se consideran la misma («confirma» y «confirmación»), como en la verificación.
SHARED_PREFIX: int = 6
# Un concepto es de fondo si está en los fragmentos de al menos esta parte de los ítems (y de 2 ítems o más).
BACKBONE_SHARE: float = 0.5
# Una oración que define el concepto: «(El|La…) concepto es/son/se define…» o «Concepto: …».
_DEFINITION_VERBS = r"(?:es|son|se define|se definen|consiste|consisten|significa|se refiere|se denomina|se llama)"


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


def _same_word(first: str, second: str) -> bool:
    if first == second:
        return True
    return len(first) >= SHARED_PREFIX and len(second) >= SHARED_PREFIX and first[:SHARED_PREFIX] == second[:SHARED_PREFIX]


def mentions(text: str, concept: str) -> bool:
    """True si todas las palabras útiles del concepto aparecen en el texto (en cualquier orden)."""
    words = concept_words(concept)
    present = set(text_words(text))
    return bool(words) and all(word in present for word in words)


def concept_share(text: str, concept: str) -> float:
    """La parte de las palabras útiles del concepto (sin repetir) que aparecen en el texto, comparadas por su raíz."""
    words = list(dict.fromkeys(concept_words(concept)))
    if not words:
        return 0.0
    tokens = set(text_words(text))
    return sum(any(_same_word(word, token) for token in tokens) for word in words) / len(words)


def _contains_words(tokens: Sequence[str | None], words: list[str]) -> bool:
    size = len(words)
    return bool(words) and any(list(tokens[start:start + size]) == words for start in range(len(tokens) - size + 1))


def contains_term(text: str, concept: str) -> bool:
    """True si el concepto aparece completo en el texto: sus palabras útiles, seguidas y en orden."""
    return _contains_words(text_words(text), concept_words(concept))


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


def defines(sentence: str, concept: str) -> bool:
    """True si la oración define el concepto: empieza por él (con o sin artículo) seguido de «es», «son», «se
    define»… o de dos puntos, como una entrada de glosario."""
    words = re.findall(r"[a-z0-9ñ]+", normalize(concept))
    if not words:
        return False
    term = r"\s+".join(re.escape(word) for word in words)
    pattern = rf"^\W*(?:(?:el|la|los|las|un|una)\s+)?{term}\w*\s*(?::|\s{_DEFINITION_VERBS}\b)"
    return re.search(pattern, normalize(sentence)) is not None


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
    contra su bloque de conceptos (`own`) y los de los demás recursos del plan (`foreign`, sin los de fondo)."""
    title = str(resource.get("titulo") or "")
    body = str(resource.get("contenido") or "")
    blocks = [*_paragraphs(body), *_structure_texts(resource.get("estructura")), *_option_texts(resource)]
    own_tuple, foreign_tuple = tuple(own), tuple(foreign)

    paragraphs = [title, *blocks, *_feedback_texts(resource)]
    if own_tuple and not any(
        concept_share(paragraph, concept) >= MIN_OWN_SHARE for paragraph in paragraphs for concept in own_tuple
    ):
        return PlanCoverage(False, own_tuple, foreign_tuple, title, missing_own=True)

    sentences = [sentence for block in blocks for sentence in extract_sentences(block)]
    # Un concepto ajeno que solo aparece dentro de uno propio («capas» en «capa de transporte») no cuenta.
    masked = [_without(list(text_words(sentence)), own_tuple) for sentence in sentences]
    developed: list[str] = []
    for concept in foreign_tuple:
        words = concept_words(concept)
        appearances = [i for i, tokens in enumerate(masked) if _contains_words(tokens, words)]
        if len(appearances) >= MIN_FOREIGN_SENTENCES or any(defines(sentences[i], concept) for i in appearances):
            developed.append(concept)
    if developed:
        return PlanCoverage(False, own_tuple, foreign_tuple, title, developed=developed)
    return PlanCoverage(True, own_tuple, foreign_tuple, title)


def develops_concept(text: str, concept: str) -> bool:
    """True si el texto desarrolla el concepto con la regla de los conceptos ajenos: el término completo en al menos dos
    oraciones, o en una que lo define. La usa también la medición de P4 (conceptos explicados en más de un recurso)."""
    sentences = [sentence for paragraph in _paragraphs(text) for sentence in extract_sentences(paragraph)]
    words = concept_words(concept)
    appearances = [s for s in sentences if _contains_words(text_words(s), words)]
    return len(appearances) >= MIN_FOREIGN_SENTENCES or any(defines(s, concept) for s in appearances)


def concept_usage(text: str, concept: str) -> dict[str, bool]:
    """Cómo usa el texto el concepto: lo menciona (el término completo en alguna oración), lo desarrolla (la regla de
    `develops_concept`) o lo define (una oración que empieza por él con «es», «son», «:»…). La medición de P4 lo
    informa por concepto para ver si la regla de «desarrollado» es demasiado estricta."""
    sentences = [sentence for paragraph in _paragraphs(text) for sentence in extract_sentences(paragraph)]
    words = concept_words(concept)
    appearances = [s for s in sentences if _contains_words(text_words(s), words)]
    defined = any(defines(s, concept) for s in appearances)
    return {"mentioned": bool(appearances), "developed": len(appearances) >= MIN_FOREIGN_SENTENCES or defined,
            "defined": defined}


def backbone_concepts(items: Sequence[PlanItem], fragments_by_id: Mapping[str, str]) -> set[str]:
    """Los conceptos del plan (por su forma normalizada) que están en los fragmentos de la mitad o más de los ítems, y
    de al menos 2: son contexto compartido de la unidad («capa de transporte»), no de un solo recurso."""
    if len(items) < 2:
        return set()
    texts = [" ".join(fragments_by_id.get(fragment_id, "") for fragment_id in item.fragment_ids) for item in items]
    needed = max(2, math.ceil(len(items) * BACKBONE_SHARE))
    backbone: set[str] = set()
    for concept in dict.fromkeys(concept for item in items for concept in item.covers):
        if sum(contains_term(text, concept) for text in texts) >= needed:
            backbone.add(concept_key(concept))
    return backbone
