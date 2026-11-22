"""GEN-P1 (T008, T009): casos de uso del plan con dobles de los puertos (specs/006-plan-de-generacion, PLAN-C1 a C7).

El repositorio es el real sobre un SQLite temporal; la evidencia, la pertenencia, los referentes y las tipologías son
dobles. El planificador es el de reglas: sin red.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import create_engine

from platform5e.application.ports.outbound.evidence_provider_port import EvidenceUnavailable, NoProcessedMaterial
from platform5e.application.services.generation.plan_drafting import GenerationPlanner
from platform5e.application.use_cases.generation.approve_generation_plan import ApproveGenerationPlan
from platform5e.application.use_cases.generation.create_generation_plan import (
    CreateGenerationPlan,
    CreatePlanCommand,
)
from platform5e.application.use_cases.generation.get_generation_plan import GetGenerationPlan
from platform5e.application.use_cases.generation.update_generation_plan import (
    EditedItem,
    UpdateGenerationPlan,
)
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_plan import (
    PlanInputs,
    PlanInvalid,
    PlanStatus,
    PreviousTypology,
    Referent,
    RequestedType,
)
from platform5e.infrastructure.adapters.plan_context_adapters import NoReferentsAdapter, NoSessionTypologyAdapter
from platform5e.infrastructure.adapters.resource_catalog_adapter import StaticResourceCatalogAdapter
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_plan_repository import (
    SQLAlchemyGenerationPlanRepository,
)
from tests.support.generation_fakes import FakeEvidence, FakeMembership

CATALOG = StaticResourceCatalogAdapter()
TIMES = iter(f"2026-11-22T10:{minute:02d}:00.000000+00:00" for minute in range(60))


def clock() -> str:
    return next(TIMES)


def inputs(*requested: tuple[str, int | None], instructions: str = "Diferencias entre TCP y UDP",
           **changes) -> PlanInputs:
    base = PlanInputs(instructions=instructions, audience="", competency="", outcome_id=None, modality=None,
                      resource_types=tuple(RequestedType(t, q) for t, q in requested))
    return replace(base, **changes)


REQUESTED = inputs(("explicacion", 1), ("pregunta_detonante", 1))


class Referents:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple] = []

    def referents_for(self, teacher_id, unit_id, topic, fragments):
        self.calls.append((teacher_id, unit_id, topic, tuple(f.id for f in fragments)))
        if self.error:
            raise self.error
        return (Referent("Andrew Tanenbaum", "Autor de Redes de computadoras", ("f1",)),)


class Typologies:
    def __init__(self, *previous: tuple[str, ...]) -> None:
        self.previous = previous

    def previous_typologies(self, teacher_id, unit_id, limit=3):
        return tuple(PreviousTypology(f"Sesión {n}", "2026-11-20T10:00:00+00:00", types)
                     for n, types in enumerate(self.previous, 1))[:limit]

    def record_typology(self, *args) -> None: ...


@pytest.fixture
def repository(tmp_path) -> SQLAlchemyGenerationPlanRepository:
    return SQLAlchemyGenerationPlanRepository(create_engine(f"sqlite:///{tmp_path / 'plans.db'}"))


def creator(repository, evidence=None, referents=None, typologies=None, membership=None) -> CreateGenerationPlan:
    return CreateGenerationPlan(
        membership=membership or FakeMembership(), evidence=evidence or FakeEvidence(),
        referents=referents or NoReferentsAdapter(), typologies=typologies or NoSessionTypologyAdapter(),
        catalog=CATALOG, planner=GenerationPlanner(None, {e.id: e for e in CATALOG.entries()}),
        repository=repository, clock=clock,
    )


def command(key: str = "clave-plan-0001", plan_inputs: PlanInputs = REQUESTED, unit_id: str = "u1",
            teacher_id: str = "docente-a") -> CreatePlanCommand:
    return CreatePlanCommand(teacher_id=teacher_id, unit_id=unit_id, idempotency_key=key, inputs=plan_inputs)


def code_of(action) -> str:
    with pytest.raises(GenerationError) as error:
        action()
    return error.value.code


# Crear (T008)


def test_creating_freezes_the_evidence_and_returns_a_draft_in_stage_order(repository):
    evidence = FakeEvidence()
    result = creator(repository, evidence).execute(command())
    plan = result.view.plan
    assert result.created and plan.status == PlanStatus.DRAFT and plan.version == 1 and plan.origin == "teacher"
    assert [i.resource_type for i in plan.items] == ["pregunta_detonante", "explicacion"]
    assert [f.id for f in plan.evidence.fragments] == ["f1", "f2"] and plan.evidence.retrieved_at
    assert result.view.problems == ()
    [query] = evidence.queries  # una sola recuperación
    assert query.limit == 12 and "Diferencias entre TCP y UDP" in query.query and "Protocolos de transporte" in query.query
    assert repository.get("docente-a", plan.id) == plan


def test_the_same_key_returns_the_plan_and_another_body_is_a_conflict(repository):
    use_case = creator(repository)
    first = use_case.execute(command())
    again = use_case.execute(command())
    assert not again.created and again.view.plan == first.view.plan
    other = inputs(("explicacion", 1), ("pregunta_detonante", 1), audience="Otro público")
    assert code_of(lambda: use_case.execute(command(plan_inputs=other))) == GenerationErrorCode.IDEMPOTENCY_KEY_REUSED


@pytest.mark.parametrize(
    ("plan_inputs", "code"),
    [
        (inputs(("tipo_inexistente", 1)), GenerationErrorCode.INVALID_PARAMETERS),
        (inputs(("glosario", 1), ("glosario", 2)), GenerationErrorCode.INVALID_PARAMETERS),
        (inputs(("glosario", 6)), GenerationErrorCode.INVALID_PARAMETERS),
        (inputs(), GenerationErrorCode.INVALID_PARAMETERS),
        (inputs(("imagen_ilustrativa", 1), modality="Textual"), GenerationErrorCode.RESOURCE_TYPE_NOT_IN_MODALITY),
        (inputs(("glosario", 1), outcome_id="ra-de-otra-unidad"), GenerationErrorCode.INVALID_OUTCOME),
    ],
    ids=["tipo-inexistente", "tipo-repetido", "cantidad", "sin-tipos", "modalidad", "resultado"],
)
def test_invalid_inputs_create_nothing(repository, plan_inputs, code):
    assert code_of(lambda: creator(repository).execute(command(plan_inputs=plan_inputs))) == code
    assert repository.list_for_unit("docente-a", "u1") == []


def test_foreign_unit_missing_key_and_missing_material(repository):
    assert code_of(lambda: creator(repository).execute(command(teacher_id="docente-b"))) == (
        GenerationErrorCode.UNIT_NOT_FOUND)
    assert code_of(lambda: creator(repository).execute(command(key=None))) == (
        GenerationErrorCode.IDEMPOTENCY_KEY_REQUIRED)
    with pytest.raises(NoProcessedMaterial):
        creator(repository, FakeEvidence(material=False)).execute(command())
    with pytest.raises(EvidenceUnavailable):
        creator(repository, FakeEvidence(error=EvidenceUnavailable())).execute(command())


def test_a_topic_outside_the_material_is_insufficient_evidence(repository):
    off_topic = inputs(("glosario", 1), instructions="Tablas y llaves primarias en un modelo relacional")
    with pytest.raises(GenerationError) as error:
        creator(repository).execute(command(plan_inputs=off_topic))
    assert error.value.code == GenerationErrorCode.INSUFFICIENT_EVIDENCE
    assert "llaves primarias" in error.value.message and "5E" not in error.value.message
    assert repository.list_for_unit("docente-a", "u1") == []


def test_referents_and_previous_typologies_come_from_their_ports(repository):
    referents = Referents()
    typologies = Typologies(("explicacion", "pregunta_detonante"), ("glosario",))
    plan = creator(repository, referents=referents, typologies=typologies).execute(command()).view.plan
    assert [r.name for r in plan.referents] == ["Andrew Tanenbaum"]
    assert referents.calls == [("docente-a", "u1", "Diferencias entre TCP y UDP", ("f1", "f2"))]
    assert [t.resource_types for t in plan.session_context.previous_typologies] == [
        ("explicacion", "pregunta_detonante"), ("glosario",)]
    assert plan.warnings == ("SAME_TYPOLOGY_AS_LAST_SESSION",)


def test_another_typology_gives_no_warning_and_a_failing_port_gives_empty_context(repository):
    plan = creator(repository, typologies=Typologies(("glosario",), ("explicacion", "pregunta_detonante"))).execute(
        command()).view.plan
    assert plan.warnings == ()  # solo cuenta la última sesión

    failing = creator(repository, referents=Referents(RuntimeError("Material no responde"))).execute(
        command(key="clave-plan-0002")).view.plan
    assert failing.referents == ()


# Leer, listar, editar y aprobar (T009)


def test_another_teachers_plan_is_not_found_like_a_missing_one(repository):
    plan = creator(repository).execute(command()).view.plan
    reader = GetGenerationPlan(repository, FakeMembership(), CATALOG)
    assert reader.get("docente-a", plan.id).plan == plan
    for teacher, plan_id in (("docente-b", plan.id), ("docente-a", "gen-plan-no-existe")):
        assert code_of(lambda: reader.get(teacher, plan_id)) == GenerationErrorCode.PLAN_NOT_FOUND
    assert [v.plan.id for v in reader.list("docente-a", "u1")] == [plan.id]
    assert reader.list("docente-a", "u1", status=PlanStatus.APPROVED) == []
    assert code_of(lambda: reader.list("docente-b", "u1")) == GenerationErrorCode.UNIT_NOT_FOUND


def edited(plan, **changes) -> list[EditedItem]:
    items = [EditedItem(i.resource_type, i.quantity, i.purpose, i.covers, i.fragment_ids) for i in plan.items]
    return [replace(items[0], **changes), *items[1:]]


def test_editing_saves_even_an_invalid_draft_and_checks_the_version(repository):
    plan = creator(repository).execute(command()).view.plan
    updater = UpdateGenerationPlan(repository, CATALOG, clock=clock)

    view = updater.execute("docente-a", plan.id, 1, edited(plan, fragment_ids=()))
    assert view.plan.version == 2 and view.plan.status == PlanStatus.DRAFT
    assert [p.code for p in view.problems] == ["ITEM_WITHOUT_EVIDENCE"]
    assert repository.get("docente-a", plan.id).version == 2

    assert code_of(lambda: updater.execute("docente-a", plan.id, 1, edited(plan))) == (
        GenerationErrorCode.PLAN_VERSION_CONFLICT)
    assert code_of(lambda: updater.execute("docente-a", plan.id, 2, edited(plan, resource_type="no_existe"))) == (
        GenerationErrorCode.INVALID_PARAMETERS)
    assert code_of(lambda: updater.execute("docente-b", plan.id, 2, edited(plan))) == (
        GenerationErrorCode.PLAN_NOT_FOUND)


def test_the_stage_comes_from_the_catalog_and_items_are_reordered(repository):
    plan = creator(repository).execute(command()).view.plan
    reversed_items = list(reversed(edited(plan)))
    view = UpdateGenerationPlan(repository, CATALOG, clock=clock).execute("docente-a", plan.id, 1, reversed_items)
    assert [(i.position, i.stage, i.resource_type) for i in view.plan.items] == [
        (1, "engage", "pregunta_detonante"), (2, "explain", "explicacion")]


def test_approving_needs_a_valid_plan_and_the_current_version(repository):
    plan = creator(repository).execute(command()).view.plan
    updater = UpdateGenerationPlan(repository, CATALOG, clock=clock)
    approver = ApproveGenerationPlan(repository, CATALOG, clock=clock)

    updater.execute("docente-a", plan.id, 1, edited(plan, covers=plan.items[1].covers))  # concepto repetido
    with pytest.raises(PlanInvalid) as invalid:
        approver.execute("docente-a", plan.id, 2)
    assert {p.code for p in invalid.value.problems} == {"CONCEPT_OWNED_TWICE"}
    assert code_of(lambda: approver.execute("docente-a", plan.id, 1)) == GenerationErrorCode.PLAN_VERSION_CONFLICT

    updater.execute("docente-a", plan.id, 2, edited(plan))
    approved = approver.execute("docente-a", plan.id, 3).plan
    assert (approved.status, approved.version) == (PlanStatus.APPROVED, 3) and approved.approved_at
    assert approver.execute("docente-a", plan.id, 3).plan == approved  # aprobar otra vez no cambia nada
    assert repository.get("docente-a", plan.id) == approved


def test_a_used_plan_cannot_be_edited_or_approved(repository):
    plan = creator(repository).execute(command()).view.plan
    approved = ApproveGenerationPlan(repository, CATALOG, clock=clock).execute("docente-a", plan.id, 1).plan
    repository.save_if_version(replace(approved, status=PlanStatus.USED, used_by_request_id="gen-req-1"), 1)
    assert code_of(lambda: UpdateGenerationPlan(repository, CATALOG, clock=clock).execute(
        "docente-a", plan.id, 1, edited(plan))) == GenerationErrorCode.PLAN_ALREADY_USED
    assert code_of(lambda: ApproveGenerationPlan(repository, CATALOG, clock=clock).execute(
        "docente-a", plan.id, 1)) == GenerationErrorCode.PLAN_ALREADY_USED


def test_a_concurrent_save_with_the_same_version_loses(repository):
    """Dos `PUT` con la misma versión: el repositorio guarda uno y el otro recibe PLAN_VERSION_CONFLICT."""
    plan = creator(repository).execute(command()).view.plan

    class RacingRepository:
        """Otra pestaña guarda justo entre la lectura y la escritura de esta."""

        def __init__(self, inner) -> None:
            self.inner = inner

        def get(self, teacher_id, plan_id):
            current = self.inner.get(teacher_id, plan_id)
            if current.version == 1:
                self.inner.save_if_version(replace(current, version=2), 1)
            return current

        def save_if_version(self, *args):
            return self.inner.save_if_version(*args)

    racing = UpdateGenerationPlan(RacingRepository(repository), CATALOG, clock=clock)
    assert code_of(lambda: racing.execute("docente-a", plan.id, 1, edited(plan))) == (
        GenerationErrorCode.PLAN_VERSION_CONFLICT)
