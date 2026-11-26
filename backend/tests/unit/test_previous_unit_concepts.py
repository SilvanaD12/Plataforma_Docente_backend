"""PLAN-C16 (spec 006, T030, research R11): el plan recibe los conceptos de las unidades anteriores del curso.

Cambio I del «Plan de cambios v2» de Juan: una unidad no vuelve a explicar lo que ya trataron las anteriores. Mismo
patrón que CUR-P3 (puerto, adaptador y contexto congelado en el plan). Repositorio real sobre SQLite temporal; cursos,
evidencia y modelo son dobles. Sin red ni proveedores.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from unittest.mock import Mock

from platform5e.application.ports.outbound.evidence_provider_port import EvidenceFragment
from platform5e.application.ports.outbound.unit_membership_port import OutcomeRef
from platform5e.application.services.generation.plan_drafting import (
    GenerationPlanner,
    RuleBasedPlanner,
    build_plan_prompt,
    plan_response_schema,
)
from platform5e.application.services.generation.planned_drafting import (
    PREVIOUS_UNIT_KIND,
    item_blocks,
    previous_only,
    previous_unit_warning,
)
from platform5e.application.services.generation.prompt_drafting import build_prompt_instructions
from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.application.use_cases.generation.create_generation_plan import (
    MAX_PREVIOUS_UNIT_CONCEPTS,
    CreateGenerationPlan,
)
from platform5e.domain.generation.generation_plan import (
    GenerationPlan,
    PlanItem,
    PlanStatus,
    PreviousUnitConcepts,
    SessionContext,
    approve_plan,
    mark_plan_used,
)
from platform5e.domain.generation.generation_request import StepStatus
from platform5e.domain.generation.topic_coverage import concept_key
from platform5e.infrastructure.adapters.course_previous_unit_concepts_adapter import (
    MAX_CONCEPTS_PER_UNIT,
    CoursePreviousUnitConceptsAdapter,
)
from platform5e.infrastructure.adapters.plan_context_adapters import (
    NoPreviousUnitConceptsAdapter,
    NoReferentsAdapter,
    NoSessionTypologyAdapter,
)
from platform5e.infrastructure.http.schemas.generation_plans import SessionContext as SessionContextSchema
from platform5e.infrastructure.http.schemas.resources import PlanWarning
from tests.support.generation_fakes import UNIT, FakeEvidence, FakeMembership, FakeReviewRepository
from tests.unit.test_generation_plan_use_cases import CATALOG, clock, command, inputs
from tests.unit.test_generation_plan_use_cases import repository as repository  # noqa: F401 (fixture)
from tests.unit.test_plan_drafting import Recorder, gemini
from tests.unit.test_planned_generation import (
    EXPLANATION,
    Capturing,
    develops_udp,
    plan_evidence,
    planned,
    runner,
    starter,
    store_plan,
)
from tests.unit.test_planned_generation import engine as engine  # noqa: F401 (fixture)
from tests.unit.test_planned_generation import plans as plans  # noqa: F401 (fixture)
from tests.unit.test_planned_generation import requests as requests  # noqa: F401 (fixture)

TEACHER = "docente-a"
OTHER = "docente-b"
U1_TEXTS = [
    "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable.",
    "El protocolo UDP no establece conexión y es más rápido.",
    "La entrega confiable de TCP usa números de secuencia y acuses de recibo.",
]
U2_TEXTS = [
    "El control de congestión de TCP reduce la ventana de envío cuando se pierden segmentos.",
    "La ventana deslizante permite enviar varios segmentos antes de recibir acuses de recibo.",
    "El protocolo TCP retransmite los segmentos perdidos tras un tiempo de espera.",
    "El arranque lento duplica la ventana de congestión en cada ida y vuelta.",
]
REQUESTED = inputs(("explicacion", 2), ("pregunta_detonante", 1), instructions="TCP")
CONGESTION = OutcomeRef("ra-2", "RA2.1", "Explica el control de congestión de TCP")
UNIT_1 = UNIT
UNIT_2 = replace(UNIT, unit_id="u2", unit_number=2, unit_title="Control de congestión", outcomes=(CONGESTION,))
COURSE = {"id": "c1", "units": [{"id": "u1", "number": 1, "title": "Protocolos de transporte"},
                                {"id": "u2", "number": 2, "title": "Control de congestión"},
                                {"id": "u3", "number": 3, "title": "Aplicaciones"}]}


def fragments(texts: list[str], prefix: str) -> tuple[EvidenceFragment, ...]:
    return tuple(EvidenceFragment(f"{prefix}{n}", f"doc-{prefix}", f"{prefix}.pdf", f"p. {n}", text, 0.9, None, None)
                 for n, text in enumerate(texts, 1))


def courses(by_teacher: dict[str, list[dict[str, Any]]] | None = None) -> Mock:
    port = Mock()
    tables = by_teacher if by_teacher is not None else {TEACHER: [COURSE]}
    port.get_courses.side_effect = lambda teacher_id: tables.get(teacher_id, [])
    return port


def creator(repository, texts, adapter=None, teacher=TEACHER, unit=UNIT_1) -> CreateGenerationPlan:
    return CreateGenerationPlan(
        membership=FakeMembership({(teacher, unit.unit_id): unit}), evidence=FakeEvidence(fragments(texts, unit.unit_id)),
        referents=NoReferentsAdapter(), typologies=NoSessionTypologyAdapter(), catalog=CATALOG,
        planner=GenerationPlanner(None, {e.id: e for e in CATALOG.entries()}), repository=repository, clock=clock,
        previous_units=adapter if adapter is not None else CoursePreviousUnitConceptsAdapter(courses(), repository),
    )


def settle(repository, plan: GenerationPlan, used: bool = False) -> GenerationPlan:
    """Aprueba el plan (y lo marca usado, si se pide) en el repositorio."""
    approved = approve_plan(plan, plan.version, [], clock())
    assert repository.save_if_version(approved, plan.version)
    if not used:
        return approved
    done = mark_plan_used(approved, approved.version, "gen-req-1", clock())
    assert repository.save_if_version(done, approved.version)
    return done


def unit_1_plan(repository, teacher=TEACHER, key="clave-u1-0001", status="approved") -> GenerationPlan:
    plan = creator(repository, U1_TEXTS, teacher=teacher).execute(
        command(key, REQUESTED, "u1", teacher)).view.plan
    if status == "draft":
        return plan
    return settle(repository, plan, used=status == "used")


def keys(concepts) -> set[str]:
    return {concept_key(concept) for concept in concepts}


def covers(plan: GenerationPlan) -> list[str]:
    return [concept for item in plan.items for concept in item.covers]


# El plan de la unidad 2


def test_without_previous_units_the_unit_2_plan_repeats_unit_1_concepts(repository):
    """Lo que pasaba antes del cambio: el material de la unidad 2 vuelve a nombrar TCP y los acuses de recibo."""
    unit_1 = unit_1_plan(repository)
    plan = creator(repository, U2_TEXTS, NoPreviousUnitConceptsAdapter(), unit=UNIT_2).execute(
        command("clave-u2-0001", REQUESTED, "u2")).view.plan
    assert keys(covers(plan)) & keys(covers(unit_1)) == {"tcp", "acuses recibo"}
    assert plan.session_context.previous_unit_concepts == ()


def test_the_unit_2_plan_excludes_unit_1_concepts_and_shows_them_read_only(repository):
    unit_1 = unit_1_plan(repository)
    assert covers(unit_1) == ["entrega confiable", "números de secuencia", "TCP", "acuses de recibo"]
    result = creator(repository, U2_TEXTS, unit=UNIT_2).execute(command("clave-u2-0001", REQUESTED, "u2"))
    plan = result.view.plan
    assert plan.session_context.previous_unit_concepts == (
        PreviousUnitConcepts(1, "Protocolos de transporte", tuple(covers(unit_1))),)
    assert keys(covers(plan)).isdisjoint(keys(covers(unit_1)))
    assert covers(plan)[0] == "control de congestión"
    assert result.view.problems == ()  # el plan sigue siendo válido
    # Congelado en el plan guardado y en el contrato del API (de solo lectura).
    stored = repository.get(TEACHER, plan.id)
    assert stored.session_context == plan.session_context
    payload = plan.session_context.to_payload()
    assert payload["previousUnitConcepts"] == [{"unitNumber": 1, "unitTitle": "Protocolos de transporte",
                                                "concepts": covers(unit_1)}]
    assert SessionContextSchema.model_validate(payload).previous_unit_concepts[0].unit_number == 1


def test_terms_of_the_chosen_outcome_are_still_allowed(repository):
    unit_1_plan(repository)
    chosen = replace(REQUESTED, outcome_id="ra-2")
    plan = creator(repository, U2_TEXTS, unit=UNIT_2).execute(command("clave-u2-0002", chosen, "u2")).view.plan
    assert "TCP" in covers(plan) and "acuses de recibo" not in covers(plan)
    # TCP es del plan, no de la unidad anterior: no se avisa si un recurso lo desarrolla.
    assert previous_only(plan) == ("entrega confiable", "números de secuencia", "acuses de recibo")


def test_the_first_unit_is_unchanged(repository):
    unit_1_plan(repository, OTHER, "clave-ajena-0001")  # lo de otro docente no cuenta
    with_port = creator(repository, U1_TEXTS).execute(command("clave-u1-0002", REQUESTED, "u1")).view.plan
    without = creator(repository, U1_TEXTS, NoPreviousUnitConceptsAdapter()).execute(
        command("clave-u1-0003", REQUESTED, "u1")).view.plan
    assert with_port.session_context.previous_unit_concepts == ()
    assert with_port.items == without.items


def test_another_teachers_plans_never_reach_my_plan(repository):
    """Aislamiento: el otro docente tiene sus propias unidades u1 y u2 con planes aprobados."""
    adapter = CoursePreviousUnitConceptsAdapter(courses({TEACHER: [COURSE], OTHER: [COURSE]}), repository)
    unit_1_plan(repository, OTHER, "clave-ajena-0001")
    plan = creator(repository, U2_TEXTS, adapter, unit=UNIT_2).execute(command("clave-u2-0003", REQUESTED, "u2")).view.plan
    assert plan.session_context.previous_unit_concepts == ()
    assert adapter.previous_unit_concepts(OTHER, "u2")[0].concepts[:2] == ("entrega confiable", "números de secuencia")
    assert adapter.previous_unit_concepts(TEACHER, "u2") == ()


def test_a_failing_port_creates_the_plan_without_previous_concepts(repository):
    class Broken:
        def previous_unit_concepts(self, teacher_id, unit_id, limit=30):
            raise RuntimeError("Cursos no responde")

    plan = creator(repository, U2_TEXTS, Broken(), unit=UNIT_2).execute(command("clave-u2-0004", REQUESTED, "u2")).view.plan
    assert plan.session_context.previous_unit_concepts == () and plan.items


def test_the_use_case_caps_what_an_adapter_returns(repository):
    class Many:
        def previous_unit_concepts(self, teacher_id, unit_id, limit=30):
            return tuple(PreviousUnitConcepts(n, f"Unidad {n}", tuple(f"concepto {n} {i}" for i in range(12)))
                         for n in range(1, 5))

    plan = creator(repository, U2_TEXTS, Many(), unit=UNIT_2).execute(command("clave-u2-0005", REQUESTED, "u2")).view.plan
    assert len(plan.session_context.previous_concepts) == MAX_PREVIOUS_UNIT_CONCEPTS


# El adaptador


def test_the_adapter_takes_the_latest_approved_or_used_plan_of_each_earlier_unit(repository):
    adapter = CoursePreviousUnitConceptsAdapter(courses(), repository)
    unit_1_plan(repository, status="draft")
    assert adapter.previous_unit_concepts(TEACHER, "u2") == ()  # un borrador no cuenta
    unit_1_plan(repository, key="clave-u1-0002", status="used")
    newer = creator(repository, ["El protocolo UDP no establece conexión y usa datagramas de tamaño fijo."]).execute(
        command("clave-u1-0003", inputs(("explicacion", 1), instructions="UDP"), "u1")).view.plan
    settle(repository, newer)
    [unit] = adapter.previous_unit_concepts(TEACHER, "u2")
    assert unit.concepts == tuple(covers(newer))  # el último por `updatedAt`
    # La unidad 3 recibe las unidades 1 y 2; una unidad posterior nunca cuenta para una anterior.
    plan_2 = creator(repository, U2_TEXTS, unit=UNIT_2).execute(command("clave-u2-0001", REQUESTED, "u2")).view.plan
    settle(repository, plan_2)
    assert [u.unit_number for u in adapter.previous_unit_concepts(TEACHER, "u3")] == [1, 2]
    assert [u.unit_number for u in adapter.previous_unit_concepts(TEACHER, "u2")] == [1]
    assert adapter.previous_unit_concepts(TEACHER, "u1") == ()
    assert adapter.previous_unit_concepts(TEACHER, "otra") == ()
    assert adapter.previous_unit_concepts(TEACHER, "u3", limit=0) == ()


def test_the_adapter_caps_per_unit_and_in_total_nearest_unit_first_without_repeating(repository):
    units = [{"id": f"u{n}", "title": f"Unidad {n}"} for n in range(1, 6)]  # sin `number`: cuenta la posición
    adapter = CoursePreviousUnitConceptsAdapter(courses({TEACHER: [{"id": "c1", "units": units}]}), repository)
    plan = unit_1_plan(repository)
    for n in range(1, 5):
        concepts = tuple(f"tema {n} parte {i}" for i in range(15)) + ("TCP",)
        item = PlanItem(1, "explain", "explicacion", 1, "Explicar", concepts, ("u11",))
        repository.create(replace(plan, id=f"gen-plan-u{n}", idempotency_key=f"clave-u{n}", unit_id=f"u{n}",
                                  items=(item,), status=PlanStatus.APPROVED))
    result = adapter.previous_unit_concepts(TEACHER, "u5")
    assert [u.unit_number for u in result] == [2, 3, 4]  # la unidad 1 ya no entra en el tope de 30
    assert [len(u.concepts) for u in result] == [6, MAX_CONCEPTS_PER_UNIT, MAX_CONCEPTS_PER_UNIT]
    assert sum("TCP" in u.concepts for u in result) == 0  # «TCP» es el 16.º de cada unidad: queda fuera del tope
    assert result[-1].unit_title == "Unidad 4"


def test_a_concept_of_a_nearer_unit_is_not_repeated_for_an_older_one(repository):
    adapter = CoursePreviousUnitConceptsAdapter(courses(), repository)
    unit_1 = unit_1_plan(repository)
    item = PlanItem(1, "explain", "explicacion", 1, "Explicar", ("acuses de recibo", "ventana deslizante"), ("u11",))
    repository.create(replace(unit_1, id="gen-plan-u2", idempotency_key="clave-u2", unit_id="u2", items=(item,)))
    first, second = adapter.previous_unit_concepts(TEACHER, "u3")
    assert second.concepts == ("acuses de recibo", "ventana deslizante")
    assert first.concepts == ("entrega confiable", "números de secuencia", "TCP")


# Planificadores


def test_the_rule_planner_uses_previous_concepts_only_when_nothing_else_is_left():
    planner = RuleBasedPlanner({e.id: e for e in CATALOG.entries()})
    evidence = creator_evidence(U1_TEXTS)
    every = ("entrega confiable", "números de secuencia", "TCP", "acuses de recibo")
    one = inputs(("explicacion", 1), instructions="TCP")
    [item] = planner.draft(one, evidence, previous=every[:3])
    assert item.covers == ("acuses de recibo",)
    # Válvula: si todos son de unidades anteriores, el plan usa lo mínimo para no quedar inválido.
    everything = RuleBasedPlanner._candidates("TCP", U1_TEXTS, [], minimum=99)
    [item] = planner.draft(inputs(("explicacion", 2), instructions="TCP"), evidence, previous=everything)
    assert len(item.covers) == 2 and set(item.covers) <= set(everything)


def creator_evidence(texts):
    return plan_evidence(fragments(texts, "u1"))


def test_the_gemini_plan_prompt_lists_them_and_the_schema_does_not_change():
    context = SessionContext(previous_unit_concepts=(
        PreviousUnitConcepts(1, "Protocolos de transporte", ("entrega confiable", "TCP")),))
    with_previous = build_plan_prompt(REQUESTED, creator_evidence(U2_TEXTS), {e.id: e for e in CATALOG.entries()},
                                      session_context=context)
    without = build_plan_prompt(REQUESTED, creator_evidence(U2_TEXTS), {e.id: e for e in CATALOG.entries()})
    assert ("YA TRATADOS EN UNIDADES ANTERIORES (refiérete a ellos, no los vuelvas a explicar ni los pongas como "
            "conceptos de los ítems, salvo los del resultado elegido): Unidad 1 (Protocolos de transporte): "
            "entrega confiable, TCP") in with_previous.user
    assert "UNIDADES ANTERIORES" not in without.user
    assert with_previous.schema == without.schema == plan_response_schema(REQUESTED)


def test_the_gemini_planner_receives_them_and_its_rules_fallback_too():
    recorder = Recorder({"error": {"code": 500, "message": "interno"}})
    context = SessionContext(previous_unit_concepts=(PreviousUnitConcepts(1, "U1", ("TCP", "acuses de recibo")),))
    planner = GenerationPlanner(gemini(recorder), {e.id: e for e in CATALOG.entries()})
    items, generator = planner.draft(inputs(("explicacion", 1), instructions="TCP"), creator_evidence(U2_TEXTS),
                                     session_context=context)
    assert "YA TRATADOS EN UNIDADES ANTERIORES" in json.dumps(recorder.bodies[0], ensure_ascii=False)
    assert "acuses de recibo" in json.dumps(recorder.bodies[0], ensure_ascii=False) and generator["fallback"] is True
    assert keys(c for i in items for c in i.covers).isdisjoint({"tcp", "acuses recibo"})


# Generación desde el plan: prompt del recurso y aviso


class Unsaved:
    """Repositorio que devuelve el plan sin guardarlo, para armarlo con `store_plan` y agregarle el contexto."""

    @staticmethod
    def create(plan: GenerationPlan) -> GenerationPlan:
        return plan


def store_with_previous(plans, *items, previous=("protocolo UDP",)) -> GenerationPlan:
    """Un plan aprobado con los conceptos de una unidad anterior congelados, como lo deja `CreateGenerationPlan`."""
    context = SessionContext(previous_unit_concepts=(PreviousUnitConcepts(1, "Unidad anterior", previous),))
    return plans.create(replace(store_plan(Unsaved, *items), session_context=context))


def run(requests, plans, model, *items, previous=("protocolo UDP",)):
    store_with_previous(plans, *items, previous=previous)
    request = starter(requests, plans).execute_planned(planned()).request
    review = FakeReviewRepository()
    runner(requests, plans, review, model).execute(request.id)
    return requests.get(TEACHER, request.id), review.all()


def test_a_resource_that_explains_a_previous_unit_concept_is_delivered_with_a_warning(requests, plans):
    model = Capturing(develops_udp)
    explanation = replace(EXPLANATION, quantity=1, covers=("control de flujo",))
    done, resources = run(requests, plans, model, explanation)
    [step] = done.steps
    [resource] = resources
    reason = ("«TCP frente a UDP»: vuelve a explicar «protocolo UDP», que ya se trató en una unidad anterior. Revisa "
              "si basta con mencionarlo.")
    assert step.status == StepStatus.SUCCEEDED and step.rejections == ()
    assert resource["planWarning"] == {"kind": PREVIOUS_UNIT_KIND, "reason": reason,
                                       "developedConcepts": ["protocolo UDP"], "missingOwnConcepts": []}
    assert step.plan_warnings == ({"title": "TCP frente a UDP", "reason": reason, "resourceId": resource["id"]},)
    assert PlanWarning.model_validate(resource["planWarning"]).kind == "previous_unit"
    assert len(model.contexts) == 1  # no es un rechazo ni se pide otra vez
    [context] = model.contexts
    assert context["plan"]["unidadesAnteriores"] == ["protocolo UDP"]
    _, user = build_prompt_instructions(context)
    assert ("Ya se trataron en unidades anteriores: «protocolo UDP»; refiérete a ellos si hace falta, sin volver a "
            "explicarlos.") in user


def test_a_resource_that_only_mentions_it_has_no_warning(requests, plans):
    done, resources = run(requests, plans, Capturing(), replace(EXPLANATION, quantity=1, covers=("control de flujo",)))
    [resource] = resources
    assert "planWarning" not in resource and done.steps[0].plan_warnings == ()


def test_without_previous_units_the_plan_context_is_unchanged(requests, plans):
    model = Capturing()
    run(requests, plans, model, replace(EXPLANATION, quantity=1, covers=("control de flujo",)), previous=())
    assert "unidadesAnteriores" not in model.contexts[0]["plan"]


def test_a_previous_concept_assigned_by_the_plan_is_not_previous_for_its_blocks(plans):
    plan = store_with_previous(plans, replace(EXPLANATION, covers=("control de flujo", "protocolo UDP")),
                               previous=("protocolo UDP", "datagramas"))
    blocks = item_blocks(plan, plan.items[0])
    assert {block.previous for block in blocks} == {("datagramas",)}


def test_the_warning_uses_the_foreign_concept_rule():
    defined = {"titulo": "UDP", "contenido": "El protocolo UDP es un protocolo sin conexión.", "alternativas": []}
    named = {"titulo": "TCP", "contenido": "TCP es más lento que el protocolo UDP.", "alternativas": []}
    inside_own = {"titulo": "UDP rápido", "contenido": "El protocolo UDP rápido no establece conexión. El protocolo "
                  "UDP rápido pierde algunos datagramas.", "alternativas": []}
    assert previous_unit_warning(defined, [], ["protocolo UDP"])["developedConcepts"] == ["protocolo UDP"]
    assert previous_unit_warning(named, [], ["protocolo UDP"]) is None  # nombrarlo una vez no cuenta
    assert previous_unit_warning(inside_own, ["protocolo UDP rápido"], ["protocolo UDP"]) is None
    assert previous_unit_warning(inside_own, [], ["protocolo UDP"]) is not None
    assert previous_unit_warning(defined, [], []) is None


def test_a_rules_resource_gets_the_warning_too_and_is_not_rejected(requests, plans):
    """El camino por reglas tampoco rechaza: «emisor» (de una unidad anterior) está en las dos oraciones citadas."""
    explanation = replace(EXPLANATION, quantity=1, covers=("control de flujo",), fragment_ids=("f1", "f6"))
    done, resources = run(requests, plans, RuleBasedGenerator(), explanation, previous=("emisor",))
    [step] = done.steps
    [resource] = resources
    assert step.status == StepStatus.SUCCEEDED and step.rejections == ()
    assert resource["planWarning"]["kind"] == PREVIOUS_UNIT_KIND
    assert resource["planWarning"]["developedConcepts"] == ["emisor"]
