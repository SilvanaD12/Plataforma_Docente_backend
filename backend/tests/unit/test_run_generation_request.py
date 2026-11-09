"""GEN-01 (T022 y T026): ejecución en segundo plano de un pedido con generadores falsos.

Usa el repositorio real de pedidos sobre un SQLite temporal, puertos falsos para Cuentas, Material y Revisión, y el
adaptador real de verificación de Revisión. Casos GEN-C2, GEN-C3, GEN-C6 y GEN-C8.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import text

from platform5e.application.ports.outbound.evidence_provider_port import EvidenceUnavailable
from platform5e.application.use_cases.generation.run_generation_request import RunGenerationRequest, _Heartbeat
from platform5e.application.use_cases.generation.start_generation_request import (
    StartGenerationCommand,
    StartGenerationRequest,
)
from platform5e.domain.generation.grounding import VERIFICATION_RULE_VERSION
from platform5e.domain.generation.generation_request import (
    GenerationMode,
    GenerationParameters,
    RequestStatus,
    StepStatus,
)
from platform5e.application.services.generation.step_drafting import NO_REPEAT_INSTRUCTION
from platform5e.infrastructure.adapters.review_verification_adapter import ReviewVerificationAdapter
from tests.support.generation_fakes import (
    INVENTED_RESOURCE,
    FailingGenerator,
    FakeEvidence,
    FakeMembership,
    FakeReviewRepository,
    FakeRunner,
    sqlite_repository,
)
from tests.unit.test_sequence_orchestrator import DISTINCT_RESOURCES, REPEATED_RESOURCE, StageAwareGenerator


class Setup:
    """Crea pedidos con el caso de uso de inicio y los ejecuta con RunGenerationRequest."""

    def __init__(self, tmp_path) -> None:
        self.repository = sqlite_repository(tmp_path)
        self.membership = FakeMembership()
        self.evidence = FakeEvidence()
        self.review = FakeReviewRepository()
        self.runner = FakeRunner()
        self.keys = iter(f"clave-pedido-{n:04d}" for n in range(1000))

    def start(self, *types: str, mode: GenerationMode = GenerationMode.SEQUENCE, **parameters: Any) -> str:
        command = StartGenerationCommand(
            teacher_id="docente-a",
            unit_id="u1",
            mode=mode,
            idempotency_key=next(self.keys),
            parameters=GenerationParameters(resource_types=types, option_count=3, **parameters),
        )
        return StartGenerationRequest(self.membership, self.evidence, self.repository, self.runner).execute(
            command
        ).request.id

    def run(self, request_id: str, primary, fallback=None, **options: Any):
        use_case = RunGenerationRequest(
            self.repository,
            self.membership,
            self.evidence,
            self.review,
            options.pop("verification", ReviewVerificationAdapter()),
            primary,
            fallback,
            heartbeat_seconds=options.pop("heartbeat_seconds", 0),
            **options,
        )
        use_case.execute(request_id)
        return self.repository.get("docente-a", request_id)


@pytest.fixture
def setup(tmp_path) -> Iterator[Setup]:
    yield Setup(tmp_path)


def test_a_sequence_runs_in_class_order_and_delivers_resources_to_review(setup):
    request_id = setup.start("item_opcion_multiple", "pregunta_detonante", "explicacion")
    generator = StageAwareGenerator()
    request = setup.run(request_id, generator)

    assert request.status == RequestStatus.SUCCEEDED and request.failure is None
    assert [(s.stage, s.agent, s.status) for s in request.steps] == [
        ("engage", "Agente de Enganchar", StepStatus.SUCCEEDED),
        ("explain", "Agente de Explicar", StepStatus.SUCCEEDED),
        ("evaluate", "Agente de Evaluar", StepStatus.SUCCEEDED),
    ]
    assert all(s.started_at and s.finished_at and s.generator["fallback"] is False for s in request.steps)

    saved = setup.review.all()
    assert [r["id"] for r in saved] == [rid for s in request.steps for rid in s.resource_ids]
    for resource, step in zip(saved, request.steps):
        assert resource["requestId"] == request_id and resource["agent"] == step.agent
        assert resource["params"]["resourceType"] == step.resource_type and resource["generatorKind"] == "ia"
        assert resource["evidence"] and all(item["retrievedAt"] for item in resource["evidence"])
        assert resource["version"] == 1 and resource["verification"]["status"] == "current"
        assert resource["verification"]["verifiedVersion"] == 1 and resource["verification"]["ruleVersion"] >= 1
    # Cada agente ve lo que redactaron los anteriores.
    assert [p["titulo"] for p in generator.contexts[2]["secuenciaPrevia"]] == [
        "Video en vivo sin esperas",
        "Entrega confiable con TCP",
    ]


def test_evidence_is_retrieved_once_and_shared_by_every_step(setup):
    request_id = setup.start("pregunta_detonante", "explicacion", "item_opcion_multiple")
    generator = StageAwareGenerator()
    request = setup.run(request_id, generator)

    assert len(setup.evidence.queries) == 1
    query = setup.evidence.queries[0]
    assert (query.teacher_id, query.unit_id, query.limit) == ("docente-a", "u1", 10)
    assert "Protocolos de transporte" in query.query and "Distingue TCP y UDP" in query.query
    assert len({tuple(f["id"] for f in c["fragmentos"]) for c in generator.contexts}) == 1
    assert [f["chunkId"] for f in request.evidence] == ["f1", "f2"]
    assert all(f["retrievedAt"] == request.evidence[0]["retrievedAt"] for f in request.evidence)


def test_a_rejected_step_and_a_valid_one_give_partial_success(setup):
    """GEN-C3: se conserva lo válido y se informa el motivo del rechazo."""
    request_id = setup.start("pregunta_detonante", "explicacion")
    request = setup.run(request_id, StageAwareGenerator({**DISTINCT_RESOURCES, "explicacion": INVENTED_RESOURCE}))

    assert request.status == RequestStatus.PARTIALLY_SUCCEEDED and request.failure is None
    engage, explain = request.steps
    assert engage.status == StepStatus.SUCCEEDED and len(engage.resource_ids) == 1
    assert explain.status == StepStatus.REJECTED and explain.resource_ids == ()
    assert explain.rejections[0]["title"] == "Inventado" and explain.rejections[0]["kind"] == "grounding"
    assert "respaldo" in explain.rejections[0]["reason"]
    assert [r["type"] for r in setup.review.all()] == ["pregunta_detonante"]


def test_when_every_step_fails_the_request_fails_with_a_reason(setup):
    """GEN-C6: el pedido aceptado termina fallido, con su motivo, y sigue consultable."""
    request_id = setup.start("pregunta_detonante", "explicacion")
    request = setup.run(request_id, FailingGenerator())

    assert request.status == RequestStatus.FAILED
    assert all(s.status == StepStatus.FAILED and s.error.code == "GENERATION_FAILED" for s in request.steps)
    assert request.failure.code == "GENERATION_FAILED" and request.failure.message
    assert "sin respuesta del proveedor" not in request.failure.message  # sin detalle técnico
    assert setup.review.all() == []


def test_when_every_step_is_rejected_the_failure_lists_the_reasons(setup):
    request_id = setup.start("pregunta_detonante", "explicacion")
    request = setup.run(
        request_id, StageAwareGenerator({"pregunta_detonante": INVENTED_RESOURCE, "explicacion": INVENTED_RESOURCE})
    )

    assert request.status == RequestStatus.FAILED
    assert [s.status for s in request.steps] == [StepStatus.REJECTED, StepStatus.REJECTED]
    assert request.failure.code == "INSUFFICIENT_EVIDENCE" and "Motivo:" in request.failure.message


def test_if_the_ai_fails_the_rule_based_generator_answers_and_it_is_reported(setup):
    request_id = setup.start("explicacion", mode=GenerationMode.INDIVIDUAL)
    rules = StageAwareGenerator()
    rules.description, rules.uses_ai = "generador por reglas", False
    request = setup.run(request_id, FailingGenerator(), rules)

    [step] = request.steps
    assert request.status == RequestStatus.SUCCEEDED
    assert step.generator == {"description": "generador por reglas", "usesAi": False, "fallback": True}
    assert setup.review.all()[0]["generatorKind"] == "respaldo"


@pytest.mark.parametrize("retrieval_mode", ["hybrid", "bm25_fallback"])
@pytest.mark.parametrize("ai_fails", [False, True], ids=["redacta-ia", "redacta-respaldo"])
def test_the_search_fallback_and_the_drafting_fallback_are_reported_separately(setup, retrieval_mode, ai_fails):
    """T031/T032 (GEN-C9): el pedido guarda el modo de búsqueda; `generator.fallback` solo dice si redactó el respaldo."""
    setup.evidence.retrieval_mode = retrieval_mode
    request_id = setup.start("explicacion", mode=GenerationMode.INDIVIDUAL)
    rules = StageAwareGenerator()
    rules.description, rules.uses_ai = "generador por reglas", False
    request = setup.run(request_id, FailingGenerator() if ai_fails else StageAwareGenerator(), rules)

    [step] = request.steps
    assert request.status == RequestStatus.SUCCEEDED
    assert request.retrieval_mode == retrieval_mode
    assert step.generator["fallback"] is ai_fails


def test_a_repeated_resource_is_asked_again_and_rejected_if_it_still_repeats(setup):
    request_id = setup.start("pregunta_detonante", "explicacion")
    generator = StageAwareGenerator({"pregunta_detonante": REPEATED_RESOURCE, "explicacion": REPEATED_RESOURCE})
    request = setup.run(request_id, generator)

    engage, explain = request.steps
    assert request.status == RequestStatus.PARTIALLY_SUCCEEDED
    assert engage.status == StepStatus.SUCCEEDED and explain.status == StepStatus.REJECTED
    assert explain.rejections[0]["kind"] == "repetition" and "repetía" in explain.rejections[0]["reason"]
    assert sum(NO_REPEAT_INSTRUCTION in c["solicitud"]["indicaciones"] for c in generator.contexts) == 1


def test_steps_after_the_deadline_fail_and_previous_ones_are_kept(setup):
    request_id = setup.start("pregunta_detonante", "explicacion", "item_opcion_multiple")
    ticks = iter([0.0, 1.0, 5.0, 100.0, 100.0])  # inicio, antes de cada paso
    request = setup.run(request_id, StageAwareGenerator(), deadline_seconds=10, monotonic=lambda: next(ticks))

    assert [s.status for s in request.steps] == [StepStatus.SUCCEEDED, StepStatus.SUCCEEDED, StepStatus.FAILED]
    assert request.steps[2].error.code == "DEADLINE_EXCEEDED"
    assert request.status == RequestStatus.PARTIALLY_SUCCEEDED
    assert len(setup.review.all()) == 2


def test_failures_before_drafting_finish_the_request(setup):
    missing_unit = setup.start("explicacion", mode=GenerationMode.INDIVIDUAL)
    setup.membership.units.clear()  # el curso se borró mientras el pedido esperaba
    request = setup.run(missing_unit, StageAwareGenerator())
    assert request.status == RequestStatus.FAILED and request.failure.code == "UNIT_NOT_FOUND"
    assert request.steps[0].status == StepStatus.FAILED

    setup.membership = FakeMembership()
    unavailable = setup.start("glosario", mode=GenerationMode.INDIVIDUAL)
    setup.evidence.error = EvidenceUnavailable()
    request = setup.run(unavailable, StageAwareGenerator())
    assert request.status == RequestStatus.FAILED and request.failure.code == "EVIDENCE_UNAVAILABLE"


def test_a_request_that_is_not_queued_is_not_run(setup):
    request_id = setup.start("explicacion", mode=GenerationMode.INDIVIDUAL)
    setup.repository.finish(request_id, RequestStatus.INTERRUPTED, None)
    generator = StageAwareGenerator()
    request = setup.run(request_id, generator)
    assert request.status == RequestStatus.INTERRUPTED and generator.contexts == []
    assert setup.evidence.queries == []


def test_structure_fragments_are_copied_to_the_resource_evidence(setup):
    """Ajuste conocido: la copia incluye los fragmentos de la estructura, con los ids del puerto de Revisión."""
    request_id = setup.start("exploracion_guiada", mode=GenerationMode.INDIVIDUAL)
    guided = {
        "titulo": "Explora TCP y UDP",
        "contenido": "Sigue los pasos para comparar TCP y UDP.",
        # La única cita usa F1; F2 solo aparece en los pasos guiados.
        "citas": [{"afirmacion": "TCP garantiza una entrega confiable", "fragmentos": ["F1"]}],
        "alternativas": [],
        "estructura": {
            "pasos_guiados": [
                {
                    "titulo": "Conexión en TCP",
                    "consigna": "Lee cómo TCP es orientado a la conexión",
                    "pregunta": "¿Qué garantiza TCP en la entrega?",
                    "fragmentos": ["F1"],
                },
                {
                    "titulo": "Rapidez de UDP",
                    "consigna": "Lee por qué UDP no establece conexión",
                    "pregunta": "¿Por qué UDP es más rápido?",
                    "fragmentos": ["F2"],
                },
                {
                    "titulo": "Compara protocolos",
                    "consigna": "Compara la entrega confiable de TCP con UDP",
                    "pregunta": "¿Cuál protocolo establece conexión?",
                    "fragmentos": ["F2"],
                },
            ]
        },
    }
    request = setup.run(request_id, StageAwareGenerator({"exploracion_guiada": guided}))
    [resource] = setup.review.all()
    assert request.status == RequestStatus.SUCCEEDED
    assert [s["fragmentIds"] for s in resource["structure"]["guidedSteps"]] == [["f1"], ["f2"], ["f2"]]
    assert [item["id"] for item in resource["evidence"]] == ["f1", "f2"]


# T026 · Verificación antes de entregar


class StubVerification(ReviewVerificationAdapter):
    """Verificación real de Revisión, salvo para los tipos indicados: insuficiente o con error."""

    def __init__(self, insufficient: set[str] = frozenset(), failing: set[str] = frozenset(), fingerprint_fails=False):
        self.insufficient, self.failing, self.fingerprint_fails = insufficient, failing, fingerprint_fails

    def verify(self, resource, threshold):
        if resource["type"] in self.failing:
            raise RuntimeError("detalle interno de la verificación")
        result = super().verify(resource, threshold)
        if resource["type"] in self.insufficient:
            return {**result, "status": "insufficient", "reason": "Solo 1 de 4 afirmaciones se apoyan en el material."}
        return result

    def fingerprint(self, resource):
        if self.fingerprint_fails:
            raise RuntimeError("sin huella")
        return super().fingerprint(resource)


def test_every_delivered_resource_has_its_verification_version_and_dated_copy(setup):
    request_id = setup.start("pregunta_detonante", "item_opcion_multiple")
    request = setup.run(request_id, StageAwareGenerator())
    adapter = ReviewVerificationAdapter()

    assert request.status == RequestStatus.SUCCEEDED
    for resource in setup.review.all():
        verification = resource["verification"]
        assert resource["version"] == 1 and "regeneratedFrom" not in resource
        assert set(verification) == {
            "status", "reason", "fingerprint", "verifiedVersion", "evidenceThreshold", "ruleVersion", "checkedAt",
            "retryAvailable", "summary",
        }
        assert (verification["status"], verification["reason"], verification["retryAvailable"]) == (
            "current", None, False
        )
        assert verification["fingerprint"] == adapter.fingerprint(resource)
        assert (verification["verifiedVersion"], verification["ruleVersion"]) == (1, VERIFICATION_RULE_VERSION)
        assert verification["evidenceThreshold"] == 0.6 and verification["summary"]
        # La copia tiene exactamente los fragmentos que Revisión exigirá, fechados al recuperar la evidencia.
        assert [item["id"] for item in resource["evidence"]] == adapter.referenced_fragment_ids(resource)
        assert {item["retrievedAt"] for item in resource["evidence"]} == {request.evidence[0]["retrievedAt"]}


def test_the_threshold_of_the_request_is_the_one_verified(setup):
    request_id = setup.start("pregunta_detonante", mode=GenerationMode.INDIVIDUAL, evidence_threshold=0.4)
    setup.run(request_id, StageAwareGenerator())
    [resource] = setup.review.all()
    assert resource["verification"]["evidenceThreshold"] == 0.4 == resource["params"]["evidenceThreshold"]


def test_an_insufficient_draft_is_rejected_as_grounding_and_not_delivered(setup):
    """GEN-C8: un borrador que la verificación de Revisión deja insuficiente no llega a Revisión."""
    request_id = setup.start("pregunta_detonante", "explicacion")
    generator = StageAwareGenerator()
    request = setup.run(request_id, generator, verification=StubVerification(insufficient={"pregunta_detonante"}))

    engage, explain = request.steps
    assert request.status == RequestStatus.PARTIALLY_SUCCEEDED
    assert engage.status == StepStatus.REJECTED and engage.resource_ids == ()
    assert engage.rejections == (
        {"title": "Video en vivo sin esperas", "reason": "Solo 1 de 4 afirmaciones se apoyan en el material.",
         "kind": "grounding"},
    )
    assert engage.grounding["rejectedResources"][0]["title"] == "Video en vivo sin esperas"
    assert engage.grounding["checkedClaims"] > 0  # sus afirmaciones se cuentan en el informe (I21)
    assert [r["type"] for r in setup.review.all()] == ["explicacion"]
    assert generator.contexts[1]["secuenciaPrevia"] == []  # el siguiente agente no ve el recurso rechazado


def test_if_verification_fails_the_resource_is_delivered_pending_with_the_reason(setup, caplog):
    request_id = setup.start("pregunta_detonante", mode=GenerationMode.INDIVIDUAL)
    with caplog.at_level("ERROR", logger="platform5e.generation.run"):
        request = setup.run(request_id, StageAwareGenerator(), verification=StubVerification(failing={"pregunta_detonante"}))

    [step] = request.steps
    [resource] = setup.review.all()
    verification = resource["verification"]
    assert request.status == RequestStatus.SUCCEEDED and step.resource_ids == (resource["id"],)
    assert verification["status"] == "pending" and "Reintenta la comprobación" in verification["reason"]
    assert "detalle interno" not in verification["reason"] and "detalle interno" in caplog.text
    assert verification["retryAvailable"] is True  # la copia está completa: Revisión ofrece reintentar
    assert verification["fingerprint"] == ReviewVerificationAdapter().fingerprint(resource)
    assert (verification["verifiedVersion"], verification["ruleVersion"]) == (1, VERIFICATION_RULE_VERSION)
    assert verification["evidenceThreshold"] == 0.6 and verification["summary"] == {} and verification["checkedAt"]
    assert resource["version"] == 1


def test_a_resource_is_delivered_pending_even_if_its_fingerprint_also_fails(setup):
    request_id = setup.start("pregunta_detonante", mode=GenerationMode.INDIVIDUAL)
    setup.run(
        request_id,
        StageAwareGenerator(),
        verification=StubVerification(failing={"pregunta_detonante"}, fingerprint_fails=True),
    )
    [resource] = setup.review.all()
    assert resource["verification"]["status"] == "pending" and resource["verification"]["fingerprint"] == ""


# Corrección 1 del PR #14: el pedido o la unidad desaparecen mientras se genera.


def _delete_request(setup: Setup, request_id: str) -> None:
    """Como `delete_course`: se borran los pasos y el pedido."""
    with setup.repository._engine.begin() as connection:  # noqa: SLF001 - simula el borrado del curso
        connection.execute(text("DELETE FROM gen_generation_steps WHERE request_id = :id"), {"id": request_id})
        connection.execute(text("DELETE FROM gen_generation_requests WHERE id = :id"), {"id": request_id})


def test_if_the_request_disappears_while_saving_the_new_resources_are_removed(setup):
    """El curso se borra entre la comprobación y la confirmación del paso: los recursos recién guardados se quitan."""
    request_id = setup.start("pregunta_detonante", "explicacion")
    review = setup.review

    class DeletedWhileSaving:
        def __getattr__(self, name: str):
            return getattr(review, name)

        def save_resources(self, teacher_id, unit_id, resources):
            review.save_resources(teacher_id, unit_id, resources)
            _delete_request(setup, request_id)

    setup.review = DeletedWhileSaving()
    generator = StageAwareGenerator()
    assert setup.run(request_id, generator) is None

    assert review.all() == []
    assert len(generator.contexts) == 1  # no siguió con el segundo paso
    with setup.repository._engine.connect() as connection:  # noqa: SLF001
        assert connection.execute(text("SELECT COUNT(*) FROM gen_generation_steps")).scalar() == 0


def test_if_the_unit_stops_belonging_to_the_teacher_nothing_else_is_saved(setup):
    request_id = setup.start("pregunta_detonante", "explicacion")
    membership = setup.membership

    class UnitRemovedWhileDrafting(StageAwareGenerator):
        def generate(self, context):
            membership.units.clear()  # la unidad se quitó del curso mientras se redactaba
            return super().generate(context)

    generator = UnitRemovedWhileDrafting()
    request = setup.run(request_id, generator)

    assert setup.review.all() == [] and len(generator.contexts) == 1
    assert request.status == RequestStatus.FAILED and request.failure.code == "UNIT_NOT_FOUND"
    assert all(step.status == StepStatus.FAILED and step.resource_ids == () for step in request.steps)


def test_the_heartbeat_beats_while_the_request_runs():
    beats: list[float] = []
    with _Heartbeat(lambda: beats.append(time.monotonic()), 0.01):
        time.sleep(0.08)
    count = len(beats)
    time.sleep(0.05)
    assert count >= 2 and len(beats) == count  # se detiene al salir

    failures = threading.Event()

    def broken() -> None:
        failures.set()
        raise ConnectionError("base caída")

    with _Heartbeat(broken, 0.01):
        assert failures.wait(1)  # un latido fallido no rompe la ejecución


# Orden de escritura de un paso con multimedia (research R3)


class MemoryMedia:
    def __init__(self, log: list[str]) -> None:
        self.saved: dict[str, bytes] = {}
        self.log = log

    def save_media(self, teacher_id, media, content) -> None:
        self.log.append("multimedia")
        self.saved[media["id"]] = content

    def get_media(self, teacher_id, media_id):
        return None

    def delete_media(self, teacher_id, media_id) -> None:
        self.log.append("borra multimedia")
        self.saved.pop(media_id, None)


def _image_setup(setup, log: list[str]):
    from tests.integration.test_course_deleted_while_generating_media import IMAGE_RESOURCE, PausingMediaGenerator

    media = MemoryMedia(log)
    real_update_step, real_save_resources = setup.repository.update_step, setup.review.save_resources

    def update_step(request_id, step):
        log.append(f"paso {step.status.value}")
        return real_update_step(request_id, step)

    def save_resources(teacher_id, unit_id, resources):
        log.append("recursos")
        return real_save_resources(teacher_id, unit_id, resources)

    setup.repository.update_step = update_step
    setup.review.save_resources = save_resources
    generator = StageAwareGenerator({**DISTINCT_RESOURCES, "imagen_ilustrativa": IMAGE_RESOURCE})
    options = {"media_generator": PausingMediaGenerator(pause=False), "media_repository": media}
    return media, generator, options


def test_the_step_saves_media_then_resources_and_confirms_last(setup):
    log: list[str] = []
    request_id = setup.start("imagen_ilustrativa", mode=GenerationMode.INDIVIDUAL)
    media, generator, options = _image_setup(setup, log)

    request = setup.run(request_id, generator, **options)

    assert request.status == RequestStatus.SUCCEEDED
    assert log == ["paso running", "multimedia", "recursos", "paso succeeded"]
    [resource] = setup.review.all()
    assert resource["media"]["status"] == "ready" and resource["media"]["id"] in media.saved


def test_if_saving_the_resources_fails_the_saved_media_is_removed(setup):
    log: list[str] = []
    request_id = setup.start("imagen_ilustrativa", mode=GenerationMode.INDIVIDUAL)
    media, generator, options = _image_setup(setup, log)

    def failing_save(teacher_id, unit_id, resources):
        log.append("recursos")
        raise ConnectionError("base caída")

    setup.review.save_resources = failing_save
    request = setup.run(request_id, generator, **options)

    [step] = request.steps
    assert step.status == StepStatus.FAILED and step.resource_ids == ()
    assert media.saved == {} and setup.review.all() == []
    assert log == ["paso running", "multimedia", "recursos", "borra multimedia", "paso failed"]
