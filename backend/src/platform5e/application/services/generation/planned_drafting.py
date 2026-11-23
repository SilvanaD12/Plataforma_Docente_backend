"""
GEN-P2 (T012, T013): redacción de cada recurso desde su ítem del plan (specs/006-plan-de-generacion, research R5).

Cada recurso de un ítem se redacta por separado, con:
- su bloque de conceptos (`covers` repartidos en `quantity` bloques), que debe desarrollar completo;
- el propósito del ítem;
- los conceptos de los demás recursos del plan (los otros ítems y los otros bloques del mismo ítem), que no debe
  desarrollar;
- el resumen de lo ya cubierto (`secuenciaPrevia`, con los conceptos de cada recurso);
- la evidencia congelada del plan, con los fragmentos del ítem primero.

Después de la verificación de anclaje de siempre, una comprobación léxica y sin IA (`plan_coverage`) mira que el
recurso desarrolle sus conceptos y no los ajenos. Si falla, se pide otra vez con la indicación del problema. Política
tras la medición de P4 (research R5): si vuelve a fallar solo esa comprobación (el anclaje y la estructura pasaron), el
recurso de la IA se entrega con un aviso de solapamiento (`avisoPlan`, que llega al recurso como `planWarning` y al
paso como `planWarnings`) en lugar de reemplazarlo con reglas; el rechazo `kind: plan` queda solo para el camino por
reglas. Los conceptos de fondo de la unidad (en los fragmentos de la mitad o más de los ítems) no cuentan como ajenos.
El filtro de repetición de GEN-01 sigue activo como red de seguridad.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from platform5e.application.ports.outbound.evidence_provider_port import EvidenceFragment
from platform5e.application.ports.outbound.language_model_port import ResourceGeneratorPort
from platform5e.application.ports.outbound.resource_catalog_port import CatalogEntry
from platform5e.application.services.generation.prompt_drafting import normalize_generated_resources
from platform5e.application.services.generation.step_drafting import (
    NO_REPEAT_INSTRUCTION,
    StepDraft,
    draft_resources,
    filter_repeated,
)
from platform5e.domain.generation.generation_plan import GenerationPlan, PlanItem
from platform5e.domain.generation.plan_coverage import PlanCoverage, backbone_concepts, check_plan_coverage
from platform5e.domain.generation.plan_validation import does_not_cover, split_covers
from platform5e.domain.generation.topic_coverage import concept_key

# Tipos que se entregan en un solo párrafo: su prompt pide no nombrar los conceptos ajenos (research R5).
SHORT_TYPES: frozenset[str] = frozenset({"pregunta_detonante", "item_opcion_multiple", "audio_detonante"})
# Un tipo del catálogo cuya extensión máxima no pasa de estas palabras también es breve.
SHORT_MAX_WORDS: int = 120
PLAN_FALLBACK_WARNING: str = "{name} no respetó el plan del recurso. Se usó el generador por reglas."


@dataclass(frozen=True)
class ResourceBlock:
    """Un recurso del ítem: su bloque de conceptos (`index` desde 0) y los conceptos que no debe desarrollar."""

    item: PlanItem
    index: int
    concepts: tuple[str, ...]
    foreign: tuple[str, ...]


def _unique(concepts: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result = []
    for concept in concepts:
        key = concept_key(concept)
        if key and key not in seen:
            seen.add(key)
            result.append(concept)
    return tuple(result)


def item_blocks(plan: GenerationPlan, item: PlanItem) -> list[ResourceBlock]:
    """Los recursos del ítem, uno por bloque. Lo ajeno a cada uno: los `covers` de los demás ítems y los de los otros
    bloques del mismo ítem, que son de otros recursos."""
    blocks = split_covers(item.covers, item.quantity)
    texts = {fragment.id: fragment.text for fragment in plan.evidence.fragments}
    backbone = backbone_concepts(plan.items, texts)  # contexto compartido de la unidad, no de un solo recurso
    others = [concept for concept in does_not_cover(plan.items, item.position) if concept_key(concept) not in backbone]
    return [
        ResourceBlock(
            item=item,
            index=index,
            concepts=tuple(block),
            foreign=_unique([*others, *(c for j, other in enumerate(blocks) if j != index for c in other)]),
        )
        for index, block in enumerate(blocks)
    ]


def is_short(resource_type: str, entry: CatalogEntry | None) -> bool:
    """True si el recurso se entrega en un solo párrafo (pregunta detonante, ítem de opción múltiple…)."""
    if resource_type in SHORT_TYPES:
        return True
    hint = entry.length_hint if entry is not None else None
    return hint is not None and hint.max_words <= SHORT_MAX_WORDS


def plan_context(block: ResourceBlock, entry: CatalogEntry | None) -> dict[str, Any]:
    """Lo que el prompt recibe del plan (`context["plan"]`)."""
    return {
        "proposito": block.item.purpose,
        "conceptos": list(block.concepts),
        "noDesarrollar": list(block.foreign),
        "parrafoUnico": is_short(block.item.resource_type, entry),
    }


def catalog_context(entry: CatalogEntry | None) -> dict[str, Any] | None:
    """Lo que el prompt y la verificación reciben del catálogo (CUR-P2): nombre, descripción, verificación y
    extensión. None si el tipo no está en el catálogo."""
    if entry is None:
        return None
    return {
        "nombre": entry.name,
        "descripcion": entry.description,
        "verificacion": entry.verification,
        "extension": entry.length_hint.to_payload() if entry.length_hint else None,
    }


def ordered_fragments(fragments: Sequence[EvidenceFragment], item: PlanItem) -> list[EvidenceFragment]:
    """La evidencia del plan con los fragmentos del ítem primero, en el orden del ítem."""
    by_id = {fragment.chunk_id: fragment for fragment in fragments}
    first = [by_id[fragment_id] for fragment_id in item.fragment_ids if fragment_id in by_id]
    return first + [fragment for fragment in fragments if fragment.chunk_id not in item.fragment_ids]


def plan_summary(plan: GenerationPlan, skip: ResourceBlock) -> list[dict[str, Any]]:
    """Regeneración: el resumen de los demás recursos del plan, sacado de sus ítems (no hay recursos aceptados en el
    pedido de regeneración)."""
    summary = []
    for item in sorted(plan.items, key=lambda i: i.position):
        for block in item_blocks(plan, item):
            if item.position == skip.item.position and block.index == skip.index:
                continue
            summary.append({
                "etapa": item.stage,
                "titulo": item.purpose,
                "resumen": "Conceptos: " + ", ".join(block.concepts),
                "conceptos": list(block.concepts),
            })
    return summary


def _with_instruction(context: dict[str, Any], instruction: str) -> dict[str, Any]:
    request = context["solicitud"]
    return {**context, "solicitud": {**request, "indicaciones": " ".join(filter(None, [request["indicaciones"],
                                                                                         instruction]))}}


def plan_warning(check: PlanCoverage) -> dict[str, Any]:
    """El aviso de solapamiento que acompaña a un recurso de la IA que no respetó del todo su plan."""
    return {
        "kind": "missing_concepts" if check.missing_own else "overlap",
        "reason": check.problem,
        "developedConcepts": list(check.developed),
        "missingOwnConcepts": list(check.own) if check.missing_own else [],
    }


def _follow_plan(
    context: dict[str, Any],
    primary: ResourceGeneratorPort | None,
    fallback: ResourceGeneratorPort | None,
    rejections: list[dict[str, Any]],
) -> StepDraft:
    """Redacta el recurso y comprueba el plan; un recurso que no lo respeta se pide otra vez con la indicación del
    problema. Si vuelve a fallar solo el plan, el recurso de la IA se entrega con su aviso (`avisoPlan`); el de reglas
    se rechaza con `kind: plan` (research R5)."""
    own, foreign = context["plan"]["conceptos"], context["plan"]["noDesarrollar"]
    drafted, generator, warning = draft_resources(context, primary, fallback, rejections)
    if not drafted:
        return StepDraft(generator=generator, warning=warning)
    check = check_plan_coverage(drafted[0], own, foreign)
    if check.accepted:
        return StepDraft(kept=drafted[:1], generator=generator, warning=warning)

    retried, retry_generator, retry_warning = draft_resources(
        _with_instruction(context, check.instruction), generator, None, rejections
    )
    best = drafted[0]
    if retried:
        best, check = retried[0], check_plan_coverage(retried[0], own, foreign)
        if check.accepted:
            return StepDraft(kept=retried[:1], generator=retry_generator or generator, warning=warning)
    if generator is not None and getattr(generator, "uses_ai", False):
        # Pasó el anclaje y la estructura: se entrega con el aviso, sin reemplazarlo por un recurso de reglas.
        return StepDraft(kept=[{**best, "avisoPlan": plan_warning(check)}], generator=generator, warning=warning)
    rejections.append({"title": check.title, "reason": check.problem, "kind": "plan"})

    if fallback is None or generator is fallback or generator is None:
        return StepDraft(generator=retry_generator or generator, warning=retry_warning or warning)
    rescued = normalize_generated_resources(fallback.generate(context), context, rejections)
    if rescued and check_plan_coverage(rescued[0], own, foreign).accepted:
        return StepDraft(kept=rescued[:1], generator=fallback,
                         warning=PLAN_FALLBACK_WARNING.format(name=generator.description))
    if rescued:
        last = check_plan_coverage(rescued[0], own, foreign)
        rejections.append({"title": last.title, "reason": last.problem, "kind": "plan"})
    return StepDraft(generator=fallback, warning=PLAN_FALLBACK_WARNING.format(name=generator.description))


def draft_planned_resource(
    context: dict[str, Any],
    accepted: list[dict[str, Any]],
    primary: ResourceGeneratorPort | None,
    fallback: ResourceGeneratorPort | None,
    rejections: list[dict[str, Any]],
) -> StepDraft:
    """Un recurso de un bloque del plan, con la comprobación del plan y el control de repetición de GEN-01."""
    draft = _follow_plan(context, primary, fallback, rejections)
    kept, repeated = filter_repeated(draft.kept, accepted)
    if not repeated or draft.generator is None:
        return StepDraft(kept=kept, repeated=repeated, generator=draft.generator, warning=draft.warning)
    foreign = ", ".join(f"«{concept}»" for concept in context["plan"]["noDesarrollar"])
    instruction = NO_REPEAT_INSTRUCTION + (f" No repitas estos conceptos de otros recursos: {foreign}." if foreign else "")
    retried = _follow_plan(_with_instruction(context, instruction), primary, fallback, rejections)
    kept, repeated = filter_repeated(retried.kept, accepted)
    generator = retried.generator or draft.generator
    warning = retried.warning if retried.generator is not None else draft.warning
    return StepDraft(kept=kept, repeated=repeated, generator=generator, warning=warning)
