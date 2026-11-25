"""GEN-P2 (T011 a T015): generación desde el plan aprobado (specs/006-plan-de-generacion, research R2, R5 y R6).

Repositorios reales sobre un SQLite temporal; pertenencia, evidencia, Revisión y el ejecutor son dobles. Los
generadores son el de reglas y modelos falsos: ninguna llamada a un proveedor real.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import create_engine

from platform5e.application.ports.outbound.evidence_provider_port import EvidenceFragment
from platform5e.application.ports.outbound.resource_catalog_port import CatalogEntry
from platform5e.application.services.generation.plan_drafting import GenerationPlanner
from platform5e.application.services.generation.prompt_drafting import build_prompt_instructions
from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.application.use_cases.generation.create_generation_plan import CreateGenerationPlan
from platform5e.application.use_cases.generation.run_generation_request import RunGenerationRequest
from platform5e.application.use_cases.generation.start_generation_request import (
    StartGenerationCommand,
    StartGenerationRequest,
    StartPlannedGenerationCommand,
)
from platform5e.application.use_cases.generation.start_regeneration import (
    StartRegeneration,
    StartRegenerationCommand,
)
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_plan import (
    GenerationPlan,
    PlanEvidence,
    PlanFragment,
    PlanInputs,
    PlanItem,
    PlanStatus,
    RequestedType,
    SessionContext,
)
from platform5e.domain.generation.generation_request import (
    GenerationMode,
    GenerationParameters,
    RequestStatus,
    StepStatus,
)
from platform5e.domain.generation.planned_request import PlanEvidenceStale
from platform5e.domain.generation.text_types import LengthHint
from platform5e.infrastructure.adapters.plan_context_adapters import NoReferentsAdapter, NoSessionTypologyAdapter
from platform5e.infrastructure.adapters.resource_catalog_adapter import StaticResourceCatalogAdapter
from platform5e.infrastructure.adapters.review_verification_adapter import ReviewVerificationAdapter
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_plan_repository import (
    SQLAlchemyGenerationPlanRepository,
)
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_request_repository import (
    SQLAlchemyGenerationRequestRepository,
)
from tests.support.generation_fakes import FakeEvidence, FakeMembership, FakeReviewRepository, FakeRunner

TEACHER = "docente-a"
TEXTS = {
    "f1": "El control de flujo de TCP evita que el emisor sature al receptor con demasiados segmentos.",
    "f2": "La retransmisión de TCP reenvía los segmentos que no recibieron confirmación del receptor.",
    "f3": "El protocolo UDP no establece conexión y por eso es más rápido que TCP en las llamadas de voz.",
    "f4": "El protocolo UDP se usa en la transmisión de video porque tolera la pérdida de algunos datagramas.",
    "f5": "El saludo de tres vías de TCP establece la conexión antes de enviar los datos al receptor.",
    "f6": "Con el control de flujo, el receptor anuncia su ventana para que el emisor ajuste el envío de segmentos.",
}
DOCUMENTS = {"f1": "doc-1", "f2": "doc-1", "f3": "doc-2", "f4": "doc-2", "f5": "doc-1", "f6": "doc-1"}
NAMES = {"doc-1": "tcp.pdf", "doc-2": "udp.txt"}
FRAGMENTS = tuple(
    EvidenceFragment(fid, DOCUMENTS[fid], NAMES[DOCUMENTS[fid]], f"p. {n}", text, 1 - n / 10, None, None)
    for n, (fid, text) in enumerate(TEXTS.items(), 1)
)
CATALOG = StaticResourceCatalogAdapter()
TRIGGER = PlanItem(1, "engage", "pregunta_detonante", 1, "Despertar la curiosidad por UDP", ("protocolo UDP",),
                   ("f3", "f4"))
EXPLANATION = PlanItem(2, "explain", "explicacion", 2, "Explicar la entrega confiable de TCP",
                       ("control de flujo", "retransmisión"), ("f1", "f2", "f6"))


class Catalog:
    """El catálogo actual más tipos de texto nuevos de prueba (CUR-P2 los deja inactivos hasta cablearlos)."""

    def __init__(self, *extra: CatalogEntry) -> None:
        self.extra = extra

    def entries(self):
        entries = {entry.id: entry for entry in CATALOG.entries()}
        entries.update((entry.id, entry) for entry in self.extra)
        return tuple(entries.values())


STORY = CatalogEntry("historia_corta", "Historia corta", "engage", "text",
                     "Narra una situación breve y pide identificar el concepto.", ("Textual",),
                     length_hint=LengthHint(40, 120), verification="framed")
SUMMARY = CatalogEntry("resumen_ideas_clave", "Resumen de ideas clave", "explain", "text",
                       "Resume las ideas centrales del tema con sus fuentes.", ("Textual",),
                       length_hint=LengthHint(120, 300), verification="strict")
QUOTE = CatalogEntry("frase_celebre_comentada", "Frase célebre comentada", "engage", "text",
                     "Presenta una cita textual del material y pide interpretarla.", ("Textual",),
                     length_hint=LengthHint(30, 90), verification="strict")


@pytest.fixture
def engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path / 'gen-p2.db'}", connect_args={"check_same_thread": False})


@pytest.fixture
def plans(engine):
    return SQLAlchemyGenerationPlanRepository(engine)


@pytest.fixture
def requests(engine):
    return SQLAlchemyGenerationRequestRepository(engine)


def plan_evidence(fragments=FRAGMENTS) -> PlanEvidence:
    return PlanEvidence("hybrid", "2026-11-22T10:00:00.000000+00:00", tuple(
        PlanFragment(f.chunk_id, f.document_id, f.document_name, f.location, f.text, f.relevance, None, None)
        for f in fragments))


def store_plan(plans, *items: PlanItem, status=PlanStatus.APPROVED, plan_id="gen-plan-1", version=1,
               fragments=FRAGMENTS) -> GenerationPlan:
    plan = GenerationPlan(
        id=plan_id, teacher_id=TEACHER, unit_id="u1", idempotency_key=f"clave-{plan_id}", payload_hash="hash",
        version=version, status=status, origin="teacher",
        inputs=PlanInputs("Confiabilidad de TCP frente a UDP", "", "", None, None,
                          tuple(RequestedType(i.resource_type, i.quantity) for i in items)),
        evidence=plan_evidence(fragments), referents=(), session_context=SessionContext(), items=tuple(items), warnings=(),
        generator={"description": "Planificador por reglas (sin IA)", "usesAi": False, "fallback": False,
                   "fallbackReason": None},
        used_by_request_id=None, created_at="2026-11-22T10:00:00.000000+00:00",
        updated_at="2026-11-22T10:00:00.000000+00:00",
        approved_at="2026-11-22T10:01:00.000000+00:00" if status == PlanStatus.APPROVED else None,
    )
    return plans.create(plan)


def starter(requests, plans, evidence=None, implicit=None, require_plan=False) -> StartGenerationRequest:
    return StartGenerationRequest(
        FakeMembership(), evidence or FakeEvidence(FRAGMENTS), requests, FakeRunner(),
        plans=plans, implicit_plans=implicit, require_plan=require_plan,
    )


def planned(plan_id="gen-plan-1", version=1, key="clave-pedido-0001") -> StartPlannedGenerationCommand:
    return StartPlannedGenerationCommand(TEACHER, plan_id, version, key)


def runner(requests, plans, review, primary, fallback=None, evidence=None, catalog=CATALOG) -> RunGenerationRequest:
    return RunGenerationRequest(
        requests, FakeMembership(), evidence or FakeEvidence(FRAGMENTS), review, ReviewVerificationAdapter(),
        primary, fallback, heartbeat_seconds=0, plans=plans, catalog=catalog,
    )


def code_of(action) -> str:
    with pytest.raises(GenerationError) as error:
        action()
    return error.value.code


class Capturing:
    """Generador que registra cada contexto y redacta con reglas (o con `answer` si se indica)."""

    description = "Gemini falso"
    uses_ai = True

    def __init__(self, answer=None) -> None:
        self.contexts: list[dict[str, Any]] = []
        self.answer = answer

    def generate(self, context: dict[str, Any]) -> dict[str, Any]:
        self.contexts.append(context)
        if self.answer is not None:
            result = self.answer(context)
            if result is not None:
                return result
        return RuleBasedGenerator().generate(context)


def tag(context: dict[str, Any], fragment_id: str) -> str:
    return next(f["etiqueta"] for f in context["fragmentos"] if f["id"] == fragment_id)


# T011 · Iniciar el pedido desde el plan


def test_an_approved_plan_starts_a_request_with_one_step_per_item_and_becomes_used(requests, plans):
    store_plan(plans, TRIGGER, EXPLANATION)
    start = starter(requests, plans)
    result = start.execute_planned(planned())
    request = result.request
    assert result.created and request.mode == GenerationMode.SEQUENCE
    assert (request.plan.plan_id, request.plan.plan_version) == ("gen-plan-1", 1)
    assert [(s.position, s.resource_type, s.plan_item_position) for s in request.steps] == [
        (0, "pregunta_detonante", 1), (1, "explicacion", 2)]
    assert request.parameters.resource_types == ("pregunta_detonante", "explicacion")
    assert request.parameters.instructions == "Confiabilidad de TCP frente a UDP"
    stored = plans.get(TEACHER, "gen-plan-1")
    assert stored.status == PlanStatus.USED and stored.used_by_request_id == request.id and stored.used_at
    assert stored.version == 1
    assert requests.get(TEACHER, request.id).plan == request.plan
    assert start._runner.submitted == [request.id]


class Sessions:
    """Doble de CUR-P3: registra cada tipología usada; con `error`, falla como un Cursos caído."""

    def __init__(self, error: Exception | None = None) -> None:
        self.recorded: list[tuple] = []
        self.error = error

    def previous_typologies(self, teacher_id, unit_id, limit=3):
        return ()

    def record_typology(self, teacher_id, unit_id, plan_id, resource_types, used_at):
        if self.error:
            raise self.error
        self.recorded.append((teacher_id, unit_id, plan_id, tuple(resource_types), used_at))


def test_using_the_plan_records_its_typology_once_and_a_failing_courses_does_not_block(requests, plans):
    store_plan(plans, TRIGGER, EXPLANATION)
    sessions = Sessions()
    start = StartGenerationRequest(FakeMembership(), FakeEvidence(FRAGMENTS), requests, FakeRunner(), plans=plans,
                                   typologies=sessions)
    request = start.execute_planned(planned()).request
    start.execute_planned(planned())  # el mismo envío no registra otra sesión
    used = plans.get(TEACHER, "gen-plan-1")
    assert sessions.recorded == [(TEACHER, "u1", "gen-plan-1", ("pregunta_detonante", "explicacion"), used.used_at)]
    assert request.plan.plan_id == "gen-plan-1"

    store_plan(plans, TRIGGER, plan_id="gen-plan-2")
    failing = StartGenerationRequest(FakeMembership(), FakeEvidence(FRAGMENTS), requests, FakeRunner(), plans=plans,
                                     typologies=Sessions(RuntimeError("Cursos no responde")))
    assert failing.execute_planned(planned("gen-plan-2", key="clave-pedido-0009")).created


def test_the_same_key_and_plan_returns_the_request_even_after_the_plan_is_used(requests, plans):
    store_plan(plans, EXPLANATION)
    start = starter(requests, plans)
    first = start.execute_planned(planned())
    again = start.execute_planned(planned())
    assert again.created is False and again.request.id == first.request.id
    assert first.request.mode == GenerationMode.SEQUENCE  # un ítem con cantidad 2
    assert code_of(lambda: start.execute_planned(planned(key="clave-pedido-0002"))) == "PLAN_ALREADY_USED"


def test_a_single_item_with_quantity_one_is_an_individual_request(requests, plans):
    store_plan(plans, TRIGGER)
    assert starter(requests, plans).execute_planned(planned()).request.mode == GenerationMode.INDIVIDUAL


def test_a_draft_plan_another_version_or_a_missing_plan_are_rejected(requests, plans):
    store_plan(plans, TRIGGER, status=PlanStatus.DRAFT)
    store_plan(plans, TRIGGER, plan_id="gen-plan-2", version=3)
    start = starter(requests, plans)
    assert code_of(lambda: start.execute_planned(planned())) == "PLAN_NOT_APPROVED"
    assert code_of(lambda: start.execute_planned(planned("gen-plan-2", 2))) == "PLAN_VERSION_CONFLICT"
    assert code_of(lambda: start.execute_planned(planned("gen-plan-x"))) == "PLAN_NOT_FOUND"
    assert code_of(lambda: start.execute_planned(
        StartPlannedGenerationCommand("otro-docente", "gen-plan-2", 3, "clave-pedido-0003"))) == "PLAN_NOT_FOUND"
    assert requests.list_by_unit(TEACHER, "u1", False, 10) == []


def test_stale_evidence_rejects_the_request_with_the_missing_documents_and_keeps_the_plan(requests, plans):
    store_plan(plans, TRIGGER, EXPLANATION)
    evidence = FakeEvidence(FRAGMENTS, existing={"f2", "f4", "f6"})
    with pytest.raises(PlanEvidenceStale) as stale:
        starter(requests, plans, evidence).execute_planned(planned())
    assert stale.value.code == GenerationErrorCode.PLAN_EVIDENCE_STALE
    assert stale.value.details == [  # en el orden de la evidencia del plan
        {"documentId": "doc-1", "documentName": "tcp.pdf", "missingFragmentIds": ["f1"]},
        {"documentId": "doc-2", "documentName": "udp.txt", "missingFragmentIds": ["f3"]},
    ]
    assert evidence.existence_checks == [("f3", "f4", "f1", "f2", "f6")]
    assert plans.get(TEACHER, "gen-plan-1").status == PlanStatus.APPROVED
    assert requests.list_by_unit(TEACHER, "u1", False, 10) == []


def test_the_plan_is_claimed_atomically_with_the_request(requests, plans, engine):
    store_plan(plans, TRIGGER)
    # Otro envío ya usó el plan entre la lectura y el alta: este pedido no se guarda.
    approved = plans.get(TEACHER, "gen-plan-1")
    used = replace(approved, status=PlanStatus.USED, used_by_request_id="otro-pedido", used_at=approved.updated_at)
    assert plans.save_if_version(used, 1)

    class StalePlans:
        """La primera lectura llega antes que el otro envío; las siguientes ven el plan ya usado."""

        reads = 0

        def get(self, teacher_id, plan_id):
            self.reads += 1
            return approved if self.reads == 1 else plans.get(teacher_id, plan_id)

    start = StartGenerationRequest(FakeMembership(), FakeEvidence(FRAGMENTS), requests, FakeRunner(), plans=StalePlans())
    assert code_of(lambda: start.execute_planned(planned())) == "PLAN_ALREADY_USED"
    assert requests.list_by_unit(TEACHER, "u1", False, 10) == []


def test_when_the_active_limit_is_reached_the_plan_stays_approved(requests, plans):
    store_plan(plans, TRIGGER)
    legacy = StartGenerationRequest(FakeMembership(), FakeEvidence(FRAGMENTS), requests, FakeRunner())
    for n in range(2):
        legacy.execute(StartGenerationCommand(TEACHER, "u1", GenerationMode.INDIVIDUAL, f"clave-activa-{n:04d}",
                                              GenerationParameters(resource_types=("explicacion",))))
    assert code_of(lambda: starter(requests, plans).execute_planned(planned())) == "TOO_MANY_ACTIVE_REQUESTS"
    assert plans.get(TEACHER, "gen-plan-1").status == PlanStatus.APPROVED


# T011 · Cuerpo anterior: plan implícito y GENERATION_REQUIRE_PLAN


def implicit_creator(plans, evidence) -> CreateGenerationPlan:
    return CreateGenerationPlan(
        FakeMembership(), evidence, NoReferentsAdapter(), NoSessionTypologyAdapter(), CATALOG,
        GenerationPlanner(None, {e.id: e for e in CATALOG.entries()}), plans,
    )


def old_body(key="clave-antigua-0001") -> StartGenerationCommand:
    return StartGenerationCommand(TEACHER, "u1", GenerationMode.SEQUENCE, key, GenerationParameters(
        resource_types=("explicacion", "pregunta_detonante"), instructions="Control de flujo y retransmisión en TCP"))


def test_the_previous_body_creates_an_implicit_approved_plan_and_generates_from_it(requests, plans):
    evidence = FakeEvidence(FRAGMENTS)
    start = starter(requests, plans, evidence, implicit=implicit_creator(plans, evidence))
    result = start.execute(old_body())
    request = result.request
    [plan] = plans.list_for_unit(TEACHER, "u1")
    assert result.created and plan.origin == "implicit" and plan.status == PlanStatus.USED
    assert plan.used_by_request_id == request.id and request.plan.plan_id == plan.id
    assert [s.plan_item_position for s in request.steps] == [item.position for item in plan.items]
    assert [s.resource_type for s in request.steps] == ["pregunta_detonante", "explicacion"]
    # El mismo envío devuelve el mismo pedido y no crea otro plan.
    again = start.execute(old_body())
    assert again.created is False and again.request.id == request.id
    assert len(plans.list_for_unit(TEACHER, "u1")) == 1


def test_with_require_plan_the_previous_body_is_rejected_but_regeneration_is_not(requests, plans):
    start = starter(requests, plans, require_plan=True)
    assert code_of(lambda: start.execute(old_body())) == "PLAN_REQUIRED"
    assert requests.list_by_unit(TEACHER, "u1", False, 10) == []
    regeneration = StartRegeneration(start).execute(StartRegenerationCommand(
        TEACHER, "u1", "rec-antiguo", 1, {"resourceType": "explicacion", "unitId": "u1"}))
    assert regeneration.created and regeneration.request.plan is None


# GENERATION_IMPLICIT_PLAN=false: solo para medir la línea base de P4 en el mismo servidor (plan.md)


def test_settings_for_the_implicit_plan_and_the_required_plan():
    from platform5e.infrastructure.settings import generation_implicit_plan, generation_require_plan

    # T021: el plan es obligatorio por defecto; el plan implícito sigue siendo solo un interruptor de medición.
    assert generation_implicit_plan({}) is True and generation_require_plan({}) is True
    assert generation_implicit_plan({"GENERATION_IMPLICIT_PLAN": "false"}) is False
    assert generation_require_plan({"GENERATION_REQUIRE_PLAN": "false"}) is False
    assert generation_require_plan({"GENERATION_REQUIRE_PLAN": "otro"}) is True  # un valor no válido deja el defecto


def test_without_the_implicit_plan_the_previous_body_is_drafted_as_before_the_plan(requests, plans):
    evidence = FakeEvidence(FRAGMENTS)
    start = starter(requests, plans, evidence, implicit=None)  # GENERATION_IMPLICIT_PLAN=false
    request = start.execute(old_body()).request
    assert request.plan is None and plans.list_for_unit(TEACHER, "u1") == []
    assert [(s.resource_type, s.plan_item_position) for s in request.steps] == [
        ("pregunta_detonante", None), ("explicacion", None)]

    model = Capturing()
    review = FakeReviewRepository()
    runner(requests, plans, review, model, evidence=evidence).execute(request.id)
    done = requests.get(TEACHER, request.id)
    assert len(evidence.queries) == 1  # busca en el material como antes, sin la evidencia de un plan
    assert all("plan" not in context for context in model.contexts)
    assert all("conceptos" not in item for context in model.contexts for item in context["secuenciaPrevia"])
    system, user = build_prompt_instructions(model.contexts[0])
    assert "devuelve menos recursos" in system and "PLAN DE ESTE RECURSO" not in user
    assert all("planId" not in r["params"] for r in review.all())
    assert all(r["kind"] != "plan" for s in done.steps for r in s.rejections)


@pytest.mark.parametrize("implicit", [False, True], ids=["sin-plan-implicito", "con-plan-implicito"])
def test_require_plan_takes_precedence_over_the_implicit_plan_switch(requests, plans, implicit):
    evidence = FakeEvidence(FRAGMENTS)
    creator = implicit_creator(plans, evidence) if implicit else None
    start = starter(requests, plans, evidence, implicit=creator, require_plan=True)
    assert code_of(lambda: start.execute(old_body())) == "PLAN_REQUIRED"
    assert requests.list_by_unit(TEACHER, "u1", False, 10) == [] and plans.list_for_unit(TEACHER, "u1") == []


# T012 · Un recurso por bloque, con la evidencia del plan


def run_plan(requests, plans, primary, *items, fallback=None, catalog=CATALOG, evidence=None):
    fragments = evidence.fragments if evidence is not None else FRAGMENTS
    store_plan(plans, *items, fragments=fragments)
    evidence = evidence or FakeEvidence(FRAGMENTS)
    request = starter(requests, plans, evidence).execute_planned(planned()).request
    review = FakeReviewRepository()
    runner(requests, plans, review, primary, fallback, evidence, catalog).execute(request.id)
    return requests.get(TEACHER, request.id), review.all(), evidence


def test_each_block_of_an_item_gives_one_resource_from_the_plan_evidence(requests, plans):
    done, resources, evidence = run_plan(requests, plans, RuleBasedGenerator(), TRIGGER, EXPLANATION)
    assert done.status == RequestStatus.SUCCEEDED, [s.rejections for s in done.steps]
    trigger_step, explanation_step = done.steps
    assert len(trigger_step.resource_ids) == 1 and len(explanation_step.resource_ids) == 2
    assert evidence.queries == []  # no hay una búsqueda nueva
    assert [e["chunkId"] for e in done.evidence] == list(TEXTS)
    by_id = {r["id"]: r for r in resources}
    blocks = [by_id[rid]["params"] for rid in explanation_step.resource_ids]
    assert [(p["planId"], p["planItemPosition"], p["planBlock"]) for p in blocks] == [
        ("gen-plan-1", 2, 0), ("gen-plan-1", 2, 1)]
    first, second = (by_id[rid] for rid in explanation_step.resource_ids)
    assert "control de flujo" in first["body"].lower() and "retransmisión" not in first["body"].lower()
    assert "retransmisión" in second["body"].lower()
    cited = {fid for r in resources for c in r["citations"] for fid in c["fragmentIds"]}
    assert cited <= set(TEXTS)


def test_each_prompt_has_its_block_purpose_foreign_concepts_and_what_was_covered_before(requests, plans):
    model = Capturing()
    run_plan(requests, plans, model, TRIGGER, EXPLANATION)
    trigger, first, second = model.contexts
    assert trigger["plan"] == {
        "proposito": "Despertar la curiosidad por UDP", "conceptos": ["protocolo UDP"],
        "noDesarrollar": ["control de flujo", "retransmisión"], "parrafoUnico": True}
    assert first["plan"]["conceptos"] == ["control de flujo"]
    assert first["plan"]["noDesarrollar"] == ["protocolo UDP", "retransmisión"]
    assert second["plan"]["conceptos"] == ["retransmisión"]
    assert [f["id"] for f in first["fragmentos"]][:3] == ["f1", "f2", "f6"]  # los del ítem primero
    assert first["solicitud"]["cantidad"] == 1
    assert [p["conceptos"] for p in second["secuenciaPrevia"]] == [["protocolo UDP"], ["control de flujo"]]
    system, user = build_prompt_instructions(first)
    assert "devuelve menos recursos" not in system
    assert "Desarrolla completos estos conceptos: «control de flujo»." in user
    assert "«protocolo UDP», «retransmisión»" in user and "puedes nombrarlos, pero no explicarlos" in user
    assert "Explicar la entrega confiable de TCP" in user and "5E" not in user
    _, trigger_user = build_prompt_instructions(trigger)
    assert "no los nombres" in trigger_user


# T013 · Comprobación del plan y rechazo `kind: plan`


def develops_udp(context: dict[str, Any]) -> dict[str, Any] | None:
    """Modelo falso que, en la explicación, desarrolla «protocolo UDP», que es de la pregunta detonante."""
    if context["solicitud"]["tipo"] != "explicacion":
        return None
    paragraphs = [TEXTS["f1"], TEXTS["f3"], TEXTS["f4"]]
    return {"recursos": [{
        "titulo": "TCP frente a UDP", "contenido": "\n\n".join(paragraphs), "alternativas": [],
        "citas": [{"afirmacion": text, "fragmentos": [tag(context, fid)]}
                  for text, fid in zip(paragraphs, ("f1", "f3", "f4"))],
    }]}


def test_an_ai_resource_that_only_fails_the_plan_check_is_delivered_with_a_plan_warning(requests, plans):
    """Política tras P4 (research R5): si después del reintento solo falla la comprobación del plan (el anclaje y la
    estructura pasaron), el recurso de la IA se entrega con un aviso de solapamiento y no se reemplaza con reglas."""
    model = Capturing(develops_udp)
    explanation = replace(EXPLANATION, quantity=1, covers=("control de flujo",))
    done, resources, _ = run_plan(requests, plans, model, TRIGGER, explanation, fallback=RuleBasedGenerator())
    step = done.steps[1]
    reason = "«TCP frente a UDP»: desarrolla «protocolo UDP», que el plan asigna a otro recurso."
    assert step.status == StepStatus.SUCCEEDED and len(step.resource_ids) == 1 and step.rejections == ()
    assert step.generator["usesAi"] is True and step.generator["fallback"] is False
    [resource] = [r for r in resources if r["id"] == step.resource_ids[0]]
    assert resource["title"] == "TCP frente a UDP" and resource["generatorKind"] == "ia"
    assert resource["planWarning"] == {"kind": "overlap", "reason": reason, "developedConcepts": ["protocolo UDP"],
                                       "missingOwnConcepts": []}
    assert step.plan_warnings == ({"title": "TCP frente a UDP", "reason": reason, "resourceId": resource["id"]},)
    calls = [c for c in model.contexts if c["solicitud"]["tipo"] == "explicacion"]
    assert len(calls) == 2  # el primer intento y un reintento con la indicación del problema
    assert "no respetó el plan" in calls[1]["solicitud"]["indicaciones"]
    assert "Desarrolla solo estos conceptos: «control de flujo»." in calls[1]["solicitud"]["indicaciones"]


def test_an_ai_resource_without_its_own_concepts_is_delivered_with_a_warning_too(requests, plans):
    def off_topic(context):
        text = TEXTS["f5"]
        return {"recursos": [{"titulo": "El saludo", "contenido": text, "alternativas": [],
                              "citas": [{"afirmacion": text, "fragmentos": [tag(context, "f5")]}]}]}

    done, resources, _ = run_plan(requests, plans, Capturing(off_topic), replace(EXPLANATION, quantity=1,
                                                                                    covers=("control de flujo",)))
    [step] = done.steps
    [resource] = resources
    assert step.rejections == () and resource["planWarning"]["missingOwnConcepts"] == ["control de flujo"]
    assert "no desarrolla ninguno de sus conceptos del plan («control de flujo»)" in step.plan_warnings[0]["reason"]


class RulesThatIgnoreThePlan:
    """Un generador sin IA cuyo recurso desarrolla un concepto de otro ítem (el camino por reglas)."""

    description, uses_ai = "Generador por reglas (sin IA)", False

    def generate(self, context):
        return develops_udp(context) or RuleBasedGenerator().generate(context)


def test_on_the_rule_based_path_a_plan_failure_is_still_a_plan_rejection(requests, plans):
    explanation = replace(EXPLANATION, quantity=1, covers=("control de flujo",))
    done, resources, _ = run_plan(requests, plans, RulesThatIgnoreThePlan(), TRIGGER, explanation)
    step = done.steps[1]
    assert step.status == StepStatus.REJECTED and step.resource_ids == () and step.plan_warnings == ()
    assert step.rejections == ({
        "title": "TCP frente a UDP", "kind": "plan",
        "reason": "«TCP frente a UDP»: desarrolla «protocolo UDP», que el plan asigna a otro recurso."},)
    assert all("planWarning" not in r for r in resources)


def test_an_ai_resource_that_fails_grounding_still_goes_to_the_rule_based_fallback(requests, plans):
    def invented(context):
        text = "Los satélites geoestacionarios regulan el control de flujo desde la órbita sobre el ecuador."
        return {"recursos": [{"titulo": "Inventado", "contenido": text, "alternativas": [],
                              "citas": [{"afirmacion": text, "fragmentos": [tag(context, "f1")]}]}]}

    explanation = replace(EXPLANATION, quantity=1, covers=("control de flujo",))
    done, resources, _ = run_plan(requests, plans, Capturing(invented), explanation, fallback=RuleBasedGenerator())
    [step] = done.steps
    assert step.status == StepStatus.SUCCEEDED and step.generator["fallback"] is True
    assert [r["kind"] for r in step.rejections] == ["grounding"] and step.plan_warnings == ()
    assert all("planWarning" not in r for r in resources)


def test_a_resource_that_follows_the_plan_passes_without_a_retry(requests, plans):
    model = Capturing()
    done, _, _ = run_plan(requests, plans, model, TRIGGER, EXPLANATION)
    assert len(model.contexts) == 3 and all(not s.rejections for s in done.steps)


def test_a_failing_model_falls_back_to_rules_with_its_reason(requests, plans):
    class Down:
        description, uses_ai = "Gemini falso", True

        def generate(self, context):
            raise TimeoutError("sin respuesta")

    done, _, _ = run_plan(requests, plans, Down(), TRIGGER, fallback=RuleBasedGenerator())
    [step] = done.steps
    assert step.status == StepStatus.SUCCEEDED and step.generator["fallback"] is True
    assert step.generator["fallbackReason"].startswith("Gemini falso no respondió")


# T014 · Regeneración desde Revisión con el ítem del plan


def regenerate(requests, plans, resource, evidence=None):
    start = starter(requests, plans, evidence or FakeEvidence(FRAGMENTS))
    return StartRegeneration(start).execute(StartRegenerationCommand(
        TEACHER, "u1", resource["id"], resource["version"], {**resource["params"], "unitId": "u1"}))


def test_regeneration_reads_the_item_of_a_used_plan_without_writing_it(requests, plans):
    done, resources, _ = run_plan(requests, plans, RuleBasedGenerator(), TRIGGER, EXPLANATION)
    used = plans.get(TEACHER, "gen-plan-1")
    second = next(r for r in resources if r["params"].get("planBlock") == 1)
    result = regenerate(requests, plans, second)
    request = result.request
    assert result.created and request.mode == GenerationMode.REGENERATION
    assert request.plan.plan_id == "gen-plan-1" and request.regeneration.plan_block == 1
    assert [(s.resource_type, s.plan_item_position) for s in request.steps] == [("explicacion", 2)]
    assert plans.get(TEACHER, "gen-plan-1") == used  # ni estado, ni versión, ni usedByRequestId cambian

    model = Capturing()
    review = FakeReviewRepository()
    runner(requests, plans, review, model).execute(request.id)
    [context] = model.contexts
    assert context["plan"]["conceptos"] == ["retransmisión"]
    assert {"protocolo UDP", "control de flujo"} <= set(context["plan"]["noDesarrollar"])
    assert [p["conceptos"] for p in context["secuenciaPrevia"]] == [["protocolo UDP"], ["control de flujo"]]
    [new] = review.all()
    assert new["regeneratedFrom"] == {"resourceId": second["id"], "version": second["version"]}
    assert (new["params"]["planId"], new["params"]["planItemPosition"], new["params"]["planBlock"]) == (
        "gen-plan-1", 2, 1)


def test_regeneration_with_a_stale_item_fragment_fails_with_its_documents(requests, plans):
    _, resources, _ = run_plan(requests, plans, RuleBasedGenerator(), TRIGGER, EXPLANATION)
    trigger = next(r for r in resources if r["params"]["planItemPosition"] == 1)
    with pytest.raises(PlanEvidenceStale) as stale:
        regenerate(requests, plans, trigger, FakeEvidence(FRAGMENTS, existing={"f1", "f2", "f4", "f5", "f6"}))
    assert stale.value.details == [{"documentId": "doc-2", "documentName": "udp.txt", "missingFragmentIds": ["f3"]}]
    # Otro ítem del mismo plan, con sus fragmentos intactos, sí se regenera.
    explanation = next(r for r in resources if r["params"]["planItemPosition"] == 2)
    assert regenerate(requests, plans, explanation,
                      FakeEvidence(FRAGMENTS, existing={"f1", "f2", "f4", "f5", "f6"})).created


def test_review_receives_the_stale_code_from_the_regeneration_adapter(requests, plans):
    from platform5e.application.use_cases.generation.get_generation_request import GetGenerationRequest
    from platform5e.infrastructure.adapters.generation_regeneration_adapter import GenerationRegenerationAdapter

    _, resources, _ = run_plan(requests, plans, RuleBasedGenerator(), TRIGGER, EXPLANATION)
    trigger = next(r for r in resources if r["params"]["planItemPosition"] == 1)
    start = starter(requests, plans, FakeEvidence(FRAGMENTS, existing={"f1", "f2", "f6"}))
    adapter = GenerationRegenerationAdapter(
        StartRegeneration(start), GetGenerationRequest(requests, FakeMembership(), FakeReviewRepository()),
        wait_seconds=0,
    )
    outcome = adapter.request_regeneration(TEACHER, trigger["id"], trigger["version"], {**trigger["params"],
                                                                                       "unitId": "u1"})
    # Revisión recibe el código; el 409 con `details` depende del contrato de Revisión (REV-01, Juan).
    assert (outcome.status, outcome.code) == ("failed", "PLAN_EVIDENCE_STALE")
    assert "plan nuevo" in outcome.reason


# T015 y CUR-P2 · Tipos de texto nuevos del catálogo, `strict` y `framed`


def catalog_item(entry: CatalogEntry, covers, fragments, position=1) -> PlanItem:
    return PlanItem(position, entry.stage, entry.id, 1, f"Usar {entry.name}", tuple(covers), tuple(fragments))


def test_a_strict_text_type_is_drafted_from_its_description_and_checked_by_paragraph(requests, plans):
    model = Capturing()
    item = catalog_item(SUMMARY, ("control de flujo",), ("f1", "f6"))
    done, [resource], _ = run_plan(requests, plans, model, item, catalog=Catalog(SUMMARY))
    [step] = done.steps
    assert step.status == StepStatus.SUCCEEDED, step.rejections
    assert resource["type"] == "resumen_ideas_clave" and resource["format"] == "text"
    assert resource["grounding"]["checkedParagraphs"] >= 1
    _, user = build_prompt_instructions(model.contexts[0])
    assert "«Resumen de ideas clave». Resume las ideas centrales del tema con sus fuentes." in user
    assert "Extensión: entre 120 y 300 palabras." in user


def test_a_framed_text_type_accepts_scene_setting_and_needs_two_supported_statements(requests, plans):
    model = Capturing()
    item = catalog_item(STORY, ("control de flujo",), ("f1", "f6"))
    done, [resource], _ = run_plan(requests, plans, model, item, catalog=Catalog(STORY))
    assert done.steps[0].status == StepStatus.SUCCEEDED, done.steps[0].rejections
    assert resource["grounding"]["supportedConceptStatements"] >= 2
    assert resource["grounding"]["framingSentences"] >= 1
    assert "Extensión: entre 40 y 120 palabras." in build_prompt_instructions(model.contexts[0])[1]


def test_a_framed_resource_with_one_supported_statement_is_rejected_as_grounding(requests, plans):
    def thin_story(context):
        body = f"Ana prepara la red del laboratorio para la feria escolar del viernes. {TEXTS['f1']}"
        return {"recursos": [{"titulo": "La feria", "contenido": body, "alternativas": [],
                              "citas": [{"afirmacion": TEXTS["f1"], "fragmentos": [tag(context, "f1")]}]}]}

    item = catalog_item(STORY, ("control de flujo",), ("f1", "f6"))
    done, resources, _ = run_plan(requests, plans, Capturing(thin_story), item, catalog=Catalog(STORY))
    [step] = done.steps
    assert resources == [] and step.status == StepStatus.REJECTED
    assert step.rejections[0]["kind"] == "grounding"
    assert step.rejections[0]["reason"] == (
        "«La feria»: solo 1 afirmación sobre los conceptos se apoya en el material; este tipo necesita al menos 2.")


def test_a_strict_type_whose_evidence_lacks_what_it_needs_is_rejected_without_drafting(requests, plans):
    model = Capturing()
    item = catalog_item(QUOTE, ("control de flujo",), ("f1", "f6"))
    done, resources, _ = run_plan(requests, plans, model, item, catalog=Catalog(QUOTE))
    [step] = done.steps
    assert model.contexts == [] and resources == []
    assert step.status == StepStatus.REJECTED
    assert step.rejections == ({"title": "Frase célebre comentada", "kind": "grounding",
                                "reason": "El material no tiene una cita textual para este tema."},)


def test_the_quote_type_is_drafted_when_the_evidence_has_a_literal_quote(requests, plans):
    quote = "Cerf dijo: «el control de flujo es la cortesía entre los equipos de la red»."
    quoted = EvidenceFragment("f7", "doc-1", "tcp.pdf", "p. 7", quote, 0.2, None, None)
    item = catalog_item(QUOTE, ("control de flujo",), ("f7", "f1"))
    done, [resource], _ = run_plan(requests, plans, RuleBasedGenerator(), item, catalog=Catalog(QUOTE),
                                   evidence=FakeEvidence((*FRAGMENTS, quoted)))
    assert done.steps[0].status == StepStatus.SUCCEEDED, done.steps[0].rejections
    assert "«el control de flujo es la cortesía entre los equipos de la red»" in resource["body"]


def test_length_hint_from_the_catalog_reaches_existing_types_too(requests, plans):
    entries = tuple(replace(e, length_hint=LengthHint(60, 90)) if e.id == "pregunta_detonante" else e
                    for e in CATALOG.entries())

    class Hinted:
        def entries(self):
            return entries

    model = Capturing()
    run_plan(requests, plans, model, TRIGGER, catalog=Hinted())
    assert "Extensión: entre 60 y 90 palabras." in build_prompt_instructions(model.contexts[0])[1]
