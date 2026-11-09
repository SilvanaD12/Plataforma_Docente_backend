"""
Secuencia de la clase (HU-003): orden de las etapas 5E, el agente de cada etapa y la regla que evita repetir contenido.

Un pedido con varios tipos de recurso se reparte entre los agentes de etapa. Todos trabajan sobre la misma evidencia
y conocen lo que redactaron los anteriores; un recurso demasiado parecido a otro de la secuencia se rechaza.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from platform5e.domain.generation.resource_formats import RESOURCE_CATALOG, resource_stage
from platform5e.domain.materials.text_analysis import extract_terms

STAGE_ORDER: tuple[str, ...] = ("engage", "explore", "explain", "elaborate", "evaluate")

# Agente responsable de cada etapa (se guarda en el recurso para saber quién lo redactó).
STAGE_AGENTS: dict[str, str] = {
    "engage": "Agente de Enganchar",
    "explore": "Agente de Explorar",
    "explain": "Agente de Explicar",
    "elaborate": "Agente de Elaborar",
    "evaluate": "Agente de Evaluar",
}

# Proporción de palabras compartidas a partir de la cual dos recursos se consideran repetidos.
SIMILARITY_THRESHOLD: float = 0.6
MAX_SEQUENCE_TYPES: int = 8
# GEN-R2: cantidad común por tipo de recurso en un pedido.
MIN_QUANTITY_PER_TYPE: int = 1
MAX_QUANTITY_PER_TYPE: int = 5
# GEN-01: modos del pedido. La secuencia admite varios tipos; los demás, exactamente uno.
SEQUENCE_MODE: str = "sequence"
SINGLE_TYPE_MODES: frozenset[str] = frozenset({"individual", "regeneration"})
# HU-050: partes del caso aplicado que se comparan con los recursos de las etapas anteriores.
CASE_FIELDS: tuple[str, ...] = ("scenario", "task")


class SequenceError(ValueError):
    """Pedido de secuencia inválido (tipos desconocidos o vacíos)."""


def order_resource_types(resource_types: list[str]) -> list[str]:
    """Quita repetidos y ordena los tipos según la etapa de la clase; dentro de una etapa respeta el orden pedido."""
    unique = list(dict.fromkeys(resource_types))
    unknown = [rtype for rtype in unique if rtype not in RESOURCE_CATALOG]
    if unknown:
        raise SequenceError(f"Tipos de recurso desconocidos: {', '.join(unknown)}.")
    if not unique:
        raise SequenceError("La secuencia necesita al menos un tipo de recurso.")
    if len(unique) > MAX_SEQUENCE_TYPES:
        raise SequenceError(f"La secuencia admite hasta {MAX_SEQUENCE_TYPES} tipos de recurso.")
    return sorted(unique, key=lambda rtype: STAGE_ORDER.index(resource_stage(rtype)))


def stage_agent(resource_type: str) -> str:
    """Nombre del agente que redacta ese tipo de recurso."""
    return STAGE_AGENTS[resource_stage(resource_type)]


@dataclass(frozen=True)
class PlannedStep:
    """Un paso del pedido (GEN-01): un tipo de recurso, su etapa 5E, su agente y la cantidad común."""

    position: int
    stage: str
    resource_type: str
    agent: str
    quantity: int


def plan_steps(mode: str, resource_types: list[str], quantity: int) -> list[PlannedStep]:
    """GEN-R1 y GEN-R2: los pasos del pedido en el orden de la clase, uno por tipo de recurso.

    El modo individual (y la regeneración) es una secuencia de un solo paso: exige exactamente un tipo, contando los
    repetidos una sola vez. La secuencia admite de 1 a `MAX_SEQUENCE_TYPES` tipos distintos. Todos los pasos usan la
    misma cantidad, de `MIN_QUANTITY_PER_TYPE` a `MAX_QUANTITY_PER_TYPE`.
    """
    if mode != SEQUENCE_MODE and mode not in SINGLE_TYPE_MODES:
        raise SequenceError(f"Modo de generación desconocido: {mode}.")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or not (
        MIN_QUANTITY_PER_TYPE <= quantity <= MAX_QUANTITY_PER_TYPE
    ):
        raise SequenceError(
            f"La cantidad por tipo debe estar entre {MIN_QUANTITY_PER_TYPE} y {MAX_QUANTITY_PER_TYPE}."
        )
    ordered_types = order_resource_types(resource_types)
    if mode in SINGLE_TYPE_MODES and len(ordered_types) != 1:
        raise SequenceError("La generación individual necesita exactamente un tipo de recurso.")
    return [
        PlannedStep(
            position=position,
            stage=resource_stage(resource_type),
            resource_type=resource_type,
            agent=stage_agent(resource_type),
            quantity=quantity,
        )
        for position, resource_type in enumerate(ordered_types)
    ]


def resource_text(resource: dict[str, Any]) -> str:
    """Texto comparable de un recurso: título, contenido y textos de su estructura o alternativas.

    HU-050: en el caso aplicado lo que debe ser nuevo es la situación y la consigna. Sus criterios de logro citan el
    material a propósito y sus instrucciones para el estudiante son las mismas en todos los casos; si se compararan,
    diluirían el parecido y un caso que copia la explicación de una etapa anterior no se rechazaría.
    """
    title = str(resource.get("titulo") or resource.get("title") or "")
    structure = resource.get("estructura") or resource.get("structure") or {}
    case_parts = [structure.get(key) for key in CASE_FIELDS]
    if all(isinstance(part, str) and part for part in case_parts):
        return " ".join([title, *case_parts])
    parts: list[str] = [title, str(resource.get("contenido") or resource.get("body") or "")]
    for alternative in resource.get("alternativas") or resource.get("options") or []:
        parts.append(str(alternative.get("texto") or alternative.get("text") or ""))
    for value in structure.values():
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(v) if not isinstance(v, dict) else " ".join(map(str, v.values())) for v in value)
    return " ".join(parts)


def content_similarity(first: str, second: str) -> float:
    """Proporción de palabras útiles compartidas (Jaccard) entre dos textos, de 0 a 1."""
    first_terms, second_terms = set(extract_terms(first)), set(extract_terms(second))
    if not first_terms or not second_terms:
        return 0.0
    return len(first_terms & second_terms) / len(first_terms | second_terms)


def most_similar(candidate: dict[str, Any], accepted: list[dict[str, Any]]) -> tuple[float, dict[str, Any] | None]:
    """El recurso aceptado más parecido al candidato y su similitud."""
    text = resource_text(candidate)
    best: tuple[float, dict[str, Any] | None] = (0.0, None)
    for previous in accepted:
        score = content_similarity(text, resource_text(previous))
        if score > best[0]:
            best = (score, previous)
    return best
