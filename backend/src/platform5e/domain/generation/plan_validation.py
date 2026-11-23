"""
GEN-P1: validación del plan, `doesNotCover` y reparto de los conceptos de un ítem
(specs/006-plan-de-generacion/data-model.md, «Reglas de validación»).

Los conceptos se comparan con la normalización de QA-05 (`topic_coverage.concept_key`): minúsculas, sin tildes, sin
espacios repetidos ni palabras vacías. Los mensajes son para el docente y nunca mencionan la metodología 5E.

Corrección tras la medición de P4 (research R4): cada concepto es una frase nominal corta, de 2 a 4 palabras útiles
tomadas del material, o una sigla («UDP», «IPv4»); nunca una oración, una lista ni una palabra suelta común
(`CONCEPT_NOT_SHORT`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from platform5e.domain.generation.generation_plan import (
    MAX_ITEM_QUANTITY,
    MAX_PLAN_TYPES,
    MIN_ITEM_QUANTITY,
    GenerationPlan,
    PlanItem,
    PlanProblem,
)
from platform5e.domain.generation.resource_formats import MODALITY_TYPES
from platform5e.domain.generation.topic_coverage import concept_key, normalize

MIN_CONCEPT_WORDS: int = 2
MAX_CONCEPT_WORDS: int = 4
# Más palabras en total (con las vacías) ya es una oración, aunque tenga pocas útiles.
MAX_CONCEPT_RAW_WORDS: int = 7
CONCEPT_NOT_SHORT_MESSAGE: str = (
    "«{concept}» no es un concepto corto: usa una frase de 2 a 4 palabras del material, no una oración ni una lista."
)
_RAW_WORD = re.compile(r"[a-z0-9ñ]+")
# Separadores de listas y de oraciones.
_LIST_OR_SENTENCE = re.compile(r"[,;:.!?¿¡]")
# Una sigla: «UDP», «TCP», «IPv4», «DNS».
_ACRONYM = re.compile(r"[A-Z]{2,}[A-Za-z0-9]{0,4}")
# Palabras que convierten la frase en una oración (negación y verbos conjugados frecuentes).
_SENTENCE_WORDS = frozenset(
    "no ni es son hay esta estan tiene tienen puede pueden debe deben mantiene mantienen compiten resuelven "
    "equilibra equilibran permite permiten garantiza garantizan usa usan".split()
)


def short_concept_problem(concept: str) -> str | None:
    """Por qué el concepto no es una frase nominal corta, o None si lo es."""
    text = " ".join(str(concept).split())
    words = concept_key(text).split()
    raw = _RAW_WORD.findall(normalize(text))
    acronym = len(text.split()) == 1 and _ACRONYM.fullmatch(text) is not None
    if (
        _LIST_OR_SENTENCE.search(text)
        or any(word in _SENTENCE_WORDS for word in raw)
        or len(raw) > MAX_CONCEPT_RAW_WORDS
        or not (MIN_CONCEPT_WORDS <= len(words) <= MAX_CONCEPT_WORDS or acronym)
    ):
        return CONCEPT_NOT_SHORT_MESSAGE.format(concept=text)
    return None


def does_not_cover(items: Sequence[PlanItem], position: int) -> list[str]:
    """Los `covers` de los demás ítems, en orden y sin repetir (por su forma normalizada)."""
    seen: set[str] = set()
    others: list[str] = []
    for item in items:
        if item.position == position:
            continue
        for concept in item.covers:
            key = concept_key(concept)
            if key not in seen:
                seen.add(key)
                others.append(concept)
    return others


def split_covers(covers: Sequence[str], quantity: int) -> list[list[str]]:
    """Reparte los conceptos de un ítem en `quantity` bloques consecutivos, uno por recurso; los primeros bloques
    reciben uno más si no alcanza para todos por igual."""
    if quantity < 1 or len(covers) < quantity:
        raise ValueError(f"Hacen falta al menos {quantity} conceptos para {quantity} recursos.")
    base, extra = divmod(len(covers), quantity)
    blocks, start = [], 0
    for index in range(quantity):
        size = base + (1 if index < extra else 0)
        blocks.append(list(covers[start:start + size]))
        start += size
    return blocks


def validate_plan(plan: GenerationPlan, known_types: Mapping[str, str]) -> list[PlanProblem]:
    """Problemas del plan, en el orden de los ítems. `known_types` es el catálogo activo (tipo → etapa)."""
    return validate_items(plan.items, plan.evidence.fragment_ids, plan.inputs.modality, known_types)


def validate_items(
    items: Sequence[PlanItem], evidence_ids: set[str], modality: str | None, known_types: Mapping[str, str]
) -> list[PlanProblem]:
    """Las mismas reglas sobre una lista de ítems: la usan el plan guardado y el plan que devuelve la IA."""
    problems: list[PlanProblem] = []
    if not items:
        return [PlanProblem("PLAN_EMPTY", "El plan necesita al menos un recurso.")]

    distinct_types = list(dict.fromkeys(item.resource_type for item in items))
    if len(distinct_types) > MAX_PLAN_TYPES:
        problems.append(PlanProblem(
            "TOO_MANY_TYPES", f"El plan admite hasta {MAX_PLAN_TYPES} tipos de recurso distintos."))

    allowed = MODALITY_TYPES.get(modality or "", None)
    owners: dict[str, int] = {}
    for item in items:
        position = item.position
        if item.resource_type not in known_types:
            problems.append(PlanProblem("TYPE_NOT_IN_CATALOG", "Este tipo de recurso no está en el catálogo.", position))
        elif allowed is not None and item.resource_type not in allowed:
            problems.append(PlanProblem(
                "RESOURCE_TYPE_NOT_IN_MODALITY", f"Este tipo no pertenece a la modalidad {modality}.",
                position))
        if not MIN_ITEM_QUANTITY <= item.quantity <= MAX_ITEM_QUANTITY:
            problems.append(PlanProblem(
                "QUANTITY_OUT_OF_RANGE", f"La cantidad debe estar entre {MIN_ITEM_QUANTITY} y {MAX_ITEM_QUANTITY}.",
                position))
        if not item.purpose.strip():
            problems.append(PlanProblem("PURPOSE_REQUIRED", "Escribe para qué sirve este recurso.", position))
        if not item.fragment_ids:
            problems.append(PlanProblem(
                "ITEM_WITHOUT_EVIDENCE", "Este recurso no se apoya en ningún fragmento del material.", position))
        elif any(fragment_id not in evidence_ids for fragment_id in item.fragment_ids):
            problems.append(PlanProblem(
                "FRAGMENT_NOT_IN_EVIDENCE", "Este recurso cita un fragmento que no está en la evidencia del plan.",
                position))
        if len([c for c in item.covers if c.strip()]) < max(item.quantity, 1):
            problems.append(PlanProblem(
                "NOT_ENOUGH_CONCEPTS",
                f"Hacen falta al menos {max(item.quantity, 1)} conceptos para {item.quantity} recurso(s).", position))
        for concept in item.covers:
            key = concept_key(concept)
            if not key:
                continue
            not_short = short_concept_problem(concept)
            if not_short is not None:
                problems.append(PlanProblem("CONCEPT_NOT_SHORT", not_short, position))
            owner = owners.setdefault(key, position)
            if owner != position:
                problems.append(PlanProblem(
                    "CONCEPT_OWNED_TWICE", f"«{concept}» ya le corresponde al recurso {owner}.", position))
    return problems
