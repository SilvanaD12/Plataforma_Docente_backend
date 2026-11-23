"""
GEN-P2: reglas puras del pedido de generación que parte de un plan aprobado
(specs/006-plan-de-generacion, research R2 y R5; data-model, «Evidencia vigente»).

- Un paso por ítem del plan, en el orden del plan, con la etapa del ítem y el agente de esa etapa.
- El modo sale del plan: `individual` si tiene un solo ítem con cantidad 1; `sequence` en los demás casos.
- Antes de generar o regenerar, cada fragmento citado debe seguir existiendo en la unidad; si no, el pedido se
  rechaza con `PLAN_EVIDENCE_STALE` y el detalle por documento (`StaleDocument`).

Solo reglas puras: no conoce HTTP, la base de datos ni los otros módulos.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_plan import PlanEvidence, PlanItem
from platform5e.domain.generation.generation_request import GenerationMode, GenerationStep
from platform5e.domain.generation.sequence import STAGE_AGENTS

STALE_MESSAGE: str = (
    "El material del plan cambió: se borró o se volvió a procesar un documento que cita. Crea un plan nuevo."
)
PLAN_REQUIRED_MESSAGE: str = "Planifica los recursos antes de generarlos: crea y aprueba un plan."


class PlanEvidenceStale(GenerationError):
    """Algún fragmento del plan ya no existe en la unidad. `details` es la lista de `StaleDocument`."""

    def __init__(self, details: list[dict[str, Any]]) -> None:
        super().__init__(GenerationErrorCode.PLAN_EVIDENCE_STALE, STALE_MESSAGE)
        self.details: list[dict[str, Any]] = details


def planned_steps(items: Sequence[PlanItem]) -> tuple[GenerationStep, ...]:
    """Los pasos pendientes del pedido: uno por ítem, en el orden del plan (ya ordenado por etapa)."""
    return tuple(
        GenerationStep(
            position=index,
            stage=item.stage,
            resource_type=item.resource_type,
            agent=STAGE_AGENTS.get(item.stage, item.stage),
            plan_item_position=item.position,
        )
        for index, item in enumerate(sorted(items, key=lambda i: i.position))
    )


def plan_mode(items: Sequence[PlanItem]) -> GenerationMode:
    """`individual` con un solo ítem de cantidad 1; `sequence` en los demás casos (research R2)."""
    if len(items) == 1 and items[0].quantity == 1:
        return GenerationMode.INDIVIDUAL
    return GenerationMode.SEQUENCE


def plan_parameters_quantity(items: Sequence[PlanItem]) -> int:
    """La cantidad que se guarda en los parámetros del pedido: la mayor de los ítems (cada paso usa la de su ítem)."""
    return max((item.quantity for item in items), default=1)


def plan_fragment_ids(items: Iterable[PlanItem]) -> list[str]:
    """Los fragmentos que citan los ítems, sin repetir y en el orden de los ítems."""
    return list(dict.fromkeys(fragment_id for item in items for fragment_id in item.fragment_ids))


def stale_documents(
    evidence: PlanEvidence, fragment_ids: Iterable[str], existing: set[str]
) -> list[dict[str, Any]]:
    """Los documentos con fragmentos que ya no existen, en el orden de la evidencia del plan. El nombre sale de la
    copia congelada, así se conoce aunque el documento se haya borrado. Lista vacía si no falta ninguno."""
    missing = {fragment_id for fragment_id in fragment_ids if fragment_id not in existing}
    documents: dict[str, dict[str, Any]] = {}
    for fragment in evidence.fragments:
        if fragment.id not in missing:
            continue
        document = documents.setdefault(
            fragment.document_id,
            {"documentId": fragment.document_id, "documentName": fragment.document_name, "missingFragmentIds": []},
        )
        document["missingFragmentIds"].append(fragment.id)
    return list(documents.values())
