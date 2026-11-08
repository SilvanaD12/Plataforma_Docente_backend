"""GEN-01 (T022): ejecución en segundo plano de un pedido con generadores falsos.

Usa el repositorio real de pedidos sobre un SQLite temporal y puertos falsos para Cuentas, Material y Revisión.
Casos GEN-C2, GEN-C3 y GEN-C6.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import pytest

from platform5e.application.ports.outbound.evidence_provider_port import EvidenceUnavailable
from platform5e.application.use_cases.generation.run_generation_request import RunGenerationRequest, _Heartbeat
from platform5e.application.use_cases.generation.start_generation_request import (
    StartGenerationCommand,
    StartGenerationRequest,
)
from platform5e.domain.generation.generation_request import (
    GenerationMode,
    GenerationParameters,
    RequestStatus,
    StepStatus,
)
from platform5e.application.services.generation.step_drafting import NO_REPEAT_INSTRUCTION
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
        assert "verification" not in resource  # TODO(T026)
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
    """Ajuste conocido (provisional hasta T026): la copia incluye los fragmentos de la estructura."""
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
