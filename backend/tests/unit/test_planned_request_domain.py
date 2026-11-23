"""GEN-P2 (T011): reglas puras del pedido que parte de un plan (specs/006-plan-de-generacion, research R2 y R5).

Un paso por ítem, el modo que sale del plan, el hash del pedido con el plan y el detalle de la evidencia vencida.
"""

from __future__ import annotations

import pytest

from platform5e.domain.generation.errors import GenerationErrorCode
from platform5e.domain.generation.generation_plan import PlanEvidence, PlanFragment, PlanItem
from platform5e.domain.generation.generation_request import (
    GenerationMode,
    GenerationParameters,
    PlanReference,
    RegenerationTarget,
    payload_hash,
)
from platform5e.domain.generation.planned_request import (
    PlanEvidenceStale,
    plan_mode,
    plan_parameters_quantity,
    planned_steps,
    stale_documents,
)


def item(position: int, resource_type: str, stage: str, quantity: int = 1, fragments=("f1",)) -> PlanItem:
    return PlanItem(position, stage, resource_type, quantity, "Propósito", tuple(f"c{position}-{n}" for n in
                    range(quantity)), tuple(fragments))


def fragment(fragment_id: str, document_id: str, document_name: str) -> PlanFragment:
    return PlanFragment(fragment_id, document_id, document_name, "p. 1", "texto", 0.5, None, None)


def test_one_step_per_item_in_plan_order_with_its_stage_agent_and_item_position():
    items = (item(1, "pregunta_detonante", "engage"), item(2, "explicacion", "explain", 2),
             item(3, "explicacion", "explain"))
    steps = planned_steps(items)
    assert [(s.position, s.stage, s.resource_type, s.plan_item_position) for s in steps] == [
        (0, "engage", "pregunta_detonante", 1), (1, "explain", "explicacion", 2), (2, "explain", "explicacion", 3)]
    assert [s.agent for s in steps] == ["Agente de Enganchar", "Agente de Explicar", "Agente de Explicar"]


@pytest.mark.parametrize(
    ("items", "mode"),
    [
        ((item(1, "explicacion", "explain"),), GenerationMode.INDIVIDUAL),
        ((item(1, "explicacion", "explain", 2),), GenerationMode.SEQUENCE),
        ((item(1, "pregunta_detonante", "engage"), item(2, "explicacion", "explain")), GenerationMode.SEQUENCE),
    ],
)
def test_the_mode_comes_from_the_plan(items, mode):
    assert plan_mode(items) == mode


def test_the_stored_quantity_is_the_largest_item_quantity():
    assert plan_parameters_quantity((item(1, "explicacion", "explain", 2), item(2, "glosario", "explain", 3))) == 3


def test_the_payload_hash_changes_with_the_plan_and_its_version():
    parameters = GenerationParameters(resource_types=("explicacion",))
    without = payload_hash(GenerationMode.INDIVIDUAL, "u1", parameters)
    first = payload_hash(GenerationMode.INDIVIDUAL, "u1", parameters, plan=PlanReference("gen-plan-1", 1))
    second = payload_hash(GenerationMode.INDIVIDUAL, "u1", parameters, plan=PlanReference("gen-plan-1", 2))
    other = payload_hash(GenerationMode.INDIVIDUAL, "u1", parameters, plan=PlanReference("gen-plan-2", 1))
    assert len({without, first, second, other}) == 4
    assert first == payload_hash(GenerationMode.INDIVIDUAL, "u1", parameters, plan=PlanReference("gen-plan-1", 1))


def test_the_regeneration_target_keeps_the_plan_block_only_when_it_has_one():
    assert RegenerationTarget("rec-1", 2).to_payload() == {"resourceId": "rec-1", "resourceVersion": 2}
    assert RegenerationTarget("rec-1", 2, plan_block=1).to_payload() == {
        "resourceId": "rec-1", "resourceVersion": 2, "planBlock": 1}


def test_stale_documents_group_the_missing_fragments_by_document_in_evidence_order():
    evidence = PlanEvidence("hybrid", "2026-11-22T10:00:00+00:00", (
        fragment("f1", "doc-1", "tcp.pdf"), fragment("f2", "doc-2", "udp.txt"), fragment("f3", "doc-1", "tcp.pdf"),
        fragment("f4", "doc-3", "ip.pptx")))
    details = stale_documents(evidence, ["f3", "f1", "f2", "f4"], existing={"f2", "f4"})
    assert details == [{"documentId": "doc-1", "documentName": "tcp.pdf", "missingFragmentIds": ["f1", "f3"]}]
    assert stale_documents(evidence, ["f2"], existing={"f2"}) == []


def test_the_stale_error_carries_the_details_and_its_code():
    details = [{"documentId": "doc-1", "documentName": "tcp.pdf", "missingFragmentIds": ["f1"]}]
    error = PlanEvidenceStale(details)
    assert error.code == GenerationErrorCode.PLAN_EVIDENCE_STALE and error.details == details
    assert "plan nuevo" in error.message and "5E" not in error.message
