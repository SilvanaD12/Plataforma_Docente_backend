"""GEN-P1 (T001 a T003): dominio del plan de generación (specs/006-plan-de-generacion/data-model.md).

Estados y versión, validación con sus 10 códigos, `doesNotCover` calculado con los `covers` de los demás ítems y
reparto de los conceptos de un ítem en tantos bloques como su cantidad.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_plan import (
    GenerationPlan,
    PlanEvidence,
    PlanFragment,
    PlanInputs,
    PlanInvalid,
    PlanItem,
    PlanStatus,
    RequestedType,
    SessionContext,
    approve_plan,
    edit_plan,
    mark_plan_used,
    order_items,
)
from platform5e.domain.generation.plan_validation import does_not_cover, split_covers, validate_plan
from platform5e.domain.generation.resource_catalog import RESOURCE_TYPES
from platform5e.domain.generation.topic_coverage import concept_key

KNOWN = {entry.id: entry.stage for entry in RESOURCE_TYPES}
NOW = "2026-11-22T10:00:00.000000+00:00"
LATER = "2026-11-22T10:05:00.000000+00:00"


def fragment(fragment_id: str) -> PlanFragment:
    return PlanFragment(fragment_id, "doc-1", "protocolos.txt", "p. 1", f"Texto {fragment_id}", 0.9, None, None)


def item(position: int, resource_type: str, covers: list[str], fragment_ids: list[str] | None = None,
         quantity: int = 1, purpose: str = "Para practicar") -> PlanItem:
    return PlanItem(position, KNOWN.get(resource_type, "explain"), resource_type, quantity, purpose, tuple(covers),
                    tuple(fragment_ids if fragment_ids is not None else ["f1"]))


def plan(*items: PlanItem, status: PlanStatus = PlanStatus.DRAFT, version: int = 1,
         modality: str | None = None) -> GenerationPlan:
    inputs = PlanInputs(instructions="TCP y UDP", audience="", competency="", outcome_id=None, modality=modality,
                        resource_types=tuple(RequestedType(i.resource_type, i.quantity) for i in items),
                        difficulty="intermedia", option_count=4, evidence_threshold=0.6, top_k=12)
    return GenerationPlan(
        id="gen-plan-1", teacher_id="docente-a", unit_id="u1", idempotency_key="clave-plan-1", payload_hash="h",
        version=version, status=status, origin="teacher", inputs=inputs,
        evidence=PlanEvidence("bm25_fallback", NOW, (fragment("f1"), fragment("f2"))),
        referents=(), session_context=SessionContext(()), items=tuple(items), warnings=(),
        generator={"description": "Planificador por reglas (sin IA)", "usesAi": False, "fallback": False,
                   "fallbackReason": None},
        used_by_request_id=None, created_at=NOW, updated_at=NOW, approved_at=None, used_at=None,
    )


def codes(problems) -> list[str]:
    return [p.code for p in problems]


VALID = plan(item(1, "pregunta_detonante", ["velocidad de UDP"]),
             item(2, "explicacion", ["Control de flujo en TCP", "retransmisión de segmentos"], ["f1", "f2"]))


# Validación (T002)


def test_a_valid_plan_has_no_problems():
    assert validate_plan(VALID, KNOWN) == []


@pytest.mark.parametrize(
    ("bad", "code", "position"),
    [
        (plan(), "PLAN_EMPTY", None),
        (plan(item(1, "explicacion", ["Control de flujo"], [])), "ITEM_WITHOUT_EVIDENCE", 1),
        (plan(item(1, "explicacion", ["Control de flujo"], ["f9"])), "FRAGMENT_NOT_IN_EVIDENCE", 1),
        (plan(item(1, "explicacion", ["Control de flujo"]), item(2, "glosario", ["control  de flújo"])),
         "CONCEPT_OWNED_TWICE", 2),
        (plan(item(1, "explicacion", ["Control de flujo"], quantity=2)), "NOT_ENOUGH_CONCEPTS", 1),
        (plan(item(1, "tipo_que_no_existe", ["Control de flujo"])), "TYPE_NOT_IN_CATALOG", 1),
        (plan(item(1, "imagen_ilustrativa", ["Control de flujo"]), modality="Textual"),
         "RESOURCE_TYPE_NOT_IN_MODALITY", 1),
        (plan(item(1, "explicacion", ["a", "b", "c", "d", "e", "f"], quantity=6)), "QUANTITY_OUT_OF_RANGE", 1),
        (plan(item(1, "explicacion", ["Control de flujo"], purpose="  ")), "PURPOSE_REQUIRED", 1),
    ],
)
def test_each_rule_reports_its_code_and_item(bad, code, position):
    problems = validate_plan(bad, KNOWN)
    assert code in codes(problems)
    [problem] = [p for p in problems if p.code == code]
    assert problem.item_position == position and problem.message and "5E" not in problem.message


def test_more_than_eight_distinct_types_is_too_many():
    types = [entry.id for entry in RESOURCE_TYPES][:9]
    assert len(set(types)) == 9
    many = plan(*[item(n, t, [f"Concepto {n}"]) for n, t in enumerate(types, 1)])
    assert "TOO_MANY_TYPES" in codes(validate_plan(many, KNOWN))


def test_concepts_are_compared_without_case_accents_spaces_or_stopwords():
    assert concept_key("Control  de Flújo") == concept_key("control flujo") == "control flujo"
    assert concept_key("el modelo OSI") == "modelo osi"


# doesNotCover y reparto (T002, T003)


def test_does_not_cover_is_the_covers_of_the_other_items_in_order():
    items = (item(1, "pregunta_detonante", ["A", "B"]), item(2, "explicacion", ["C"]), item(3, "glosario", ["D"]))
    assert does_not_cover(items, 1) == ["C", "D"]
    assert does_not_cover(items, 2) == ["A", "B", "D"]
    edited = (items[0], replace(items[1], covers=("C", "E")), items[2])
    assert does_not_cover(edited, 3) == ["A", "B", "C", "E"]  # cambia al editar otro ítem


def test_covers_split_into_consecutive_blocks_first_ones_larger():
    assert split_covers(["a", "b", "c", "d", "e"], 2) == [["a", "b", "c"], ["d", "e"]]
    assert split_covers(["a", "b", "c"], 3) == [["a"], ["b"], ["c"]]
    assert split_covers(["a", "b"], 1) == [["a", "b"]]
    with pytest.raises(ValueError):
        split_covers(["a"], 2)


def test_items_are_ordered_by_stage_and_renumbered():
    ordered = order_items([item(9, "item_opcion_multiple", ["x"]), item(4, "pregunta_detonante", ["y"]),
                           item(7, "explicacion", ["z"])])
    assert [(i.position, i.resource_type) for i in ordered] == [
        (1, "pregunta_detonante"), (2, "explicacion"), (3, "item_opcion_multiple"),
    ]


# Estados y versión (T001)


def test_editing_bumps_the_version_and_goes_back_to_draft_even_from_approved():
    approved = plan(*VALID.items, status=PlanStatus.APPROVED, version=3)
    edited = edit_plan(approved, 3, VALID.items[:1], LATER)
    assert (edited.status, edited.version, edited.updated_at, len(edited.items)) == (PlanStatus.DRAFT, 4, LATER, 1)


def test_an_invalid_draft_is_saved_anyway():
    invalid_items = (item(1, "explicacion", ["A"], []),)
    edited = edit_plan(VALID, 1, invalid_items, LATER)
    assert edited.version == 2 and validate_plan(edited, KNOWN)  # se guarda con sus problemas


def test_approving_needs_the_current_version_and_a_valid_plan():
    approved = approve_plan(VALID, 1, validate_plan(VALID, KNOWN), LATER)
    assert (approved.status, approved.version, approved.approved_at) == (PlanStatus.APPROVED, 1, LATER)
    assert approve_plan(approved, 1, [], "otra hora") is approved  # ya aprobado con esa versión: sin cambios

    with pytest.raises(GenerationError) as conflict:
        approve_plan(VALID, 2, [], LATER)
    assert conflict.value.code == GenerationErrorCode.PLAN_VERSION_CONFLICT

    broken = plan(item(1, "explicacion", ["control de flujo"], []))
    with pytest.raises(PlanInvalid) as invalid:
        approve_plan(broken, 1, validate_plan(broken, KNOWN), LATER)
    assert invalid.value.code == GenerationErrorCode.PLAN_INVALID
    assert codes(invalid.value.problems) == ["ITEM_WITHOUT_EVIDENCE"]


def test_a_used_plan_cannot_be_edited_or_approved():
    used = mark_plan_used(approve_plan(VALID, 1, [], LATER), 1, "gen-req-1", LATER)
    assert (used.status, used.used_by_request_id, used.used_at) == (PlanStatus.USED, "gen-req-1", LATER)
    for action in (lambda: edit_plan(used, 1, VALID.items, LATER), lambda: approve_plan(used, 1, [], LATER)):
        with pytest.raises(GenerationError) as error:
            action()
        assert error.value.code == GenerationErrorCode.PLAN_ALREADY_USED


def test_only_an_approved_plan_with_its_version_can_be_used():
    for draft_or_stale, version in ((VALID, 1), (approve_plan(VALID, 1, [], LATER), 2)):
        with pytest.raises(GenerationError):
            mark_plan_used(draft_or_stale, version, "gen-req-1", LATER)
