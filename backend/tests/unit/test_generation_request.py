"""GEN-01 (T002 y T003): estados, transiciones, hash del pedido y clave de idempotencia. Solo dominio."""

from __future__ import annotations

from dataclasses import replace

import pytest

from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_request import (
    GenerationMode,
    GenerationParameters,
    GenerationRequest,
    GenerationStep,
    InvalidTransitionError,
    RegenerationTarget,
    RequestStatus,
    StepStatus,
    final_status,
    interrupt,
    payload_hash,
    validate_idempotency_key,
)
from platform5e.domain.generation.sequence import plan_steps

NOW = "2026-11-10T12:00:00+00:00"


def make_steps(*statuses: StepStatus) -> tuple[GenerationStep, ...]:
    if not statuses:
        return ()
    types = ["pregunta_detonante", "explicacion", "item_opcion_multiple"][: len(statuses)]
    planned = plan_steps("sequence", types, 1)
    return tuple(replace(GenerationStep.from_plan(p), status=s) for p, s in zip(planned, statuses))


def make_request(steps: tuple[GenerationStep, ...], status: RequestStatus = RequestStatus.RUNNING) -> GenerationRequest:
    parameters = GenerationParameters(resource_types=tuple(step.resource_type for step in steps))
    return GenerationRequest(
        id="gen-req-1",
        teacher_id="docente-a",
        unit_id="u1",
        mode=GenerationMode.SEQUENCE,
        idempotency_key="clave-estable-1",
        payload_hash=payload_hash(GenerationMode.SEQUENCE, "u1", parameters),
        parameters=parameters,
        created_at=NOW,
        steps=steps,
        status=status,
    )


def test_steps_start_pending_from_the_plan():
    step = GenerationStep.from_plan(plan_steps("individual", ["glosario"], 2)[0])
    assert (step.position, step.stage, step.resource_type, step.agent) == (0, "explain", "glosario", "Agente de Explicar")
    assert step.status == StepStatus.PENDING and not step.is_final
    assert make_request((step,), RequestStatus.QUEUED).status == "queued"


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ((StepStatus.SUCCEEDED, StepStatus.SUCCEEDED), RequestStatus.SUCCEEDED),
        ((StepStatus.SUCCEEDED, StepStatus.REJECTED), RequestStatus.PARTIALLY_SUCCEEDED),  # GEN-C3
        ((StepStatus.FAILED, StepStatus.SUCCEEDED, StepStatus.REJECTED), RequestStatus.PARTIALLY_SUCCEEDED),
        ((StepStatus.REJECTED, StepStatus.FAILED), RequestStatus.FAILED),  # GEN-C6
        ((), RequestStatus.FAILED),
    ],
)
def test_the_final_status_depends_on_the_succeeded_steps(statuses, expected):
    assert final_status(make_steps(*statuses)) == expected


def test_the_final_status_needs_every_step_finished():
    with pytest.raises(InvalidTransitionError):
        final_status(make_steps(StepStatus.SUCCEEDED, StepStatus.RUNNING))
    with pytest.raises(InvalidTransitionError):
        final_status(make_steps(StepStatus.PENDING))


def test_interrupting_keeps_finished_steps_and_marks_the_rest():
    request = make_request(make_steps(StepStatus.SUCCEEDED, StepStatus.RUNNING, StepStatus.PENDING))
    interrupted = interrupt(request, NOW)

    assert interrupted.status == RequestStatus.INTERRUPTED and interrupted.finished_at == NOW
    assert interrupted.failure.code == GenerationErrorCode.REQUEST_INTERRUPTED
    assert [s.status for s in interrupted.steps] == [StepStatus.SUCCEEDED, StepStatus.INTERRUPTED, StepStatus.INTERRUPTED]
    assert interrupted.steps[0] == request.steps[0]  # GEN-C4: lo ya generado se conserva
    assert interrupted.steps[1].error == interrupted.failure
    assert request.status == RequestStatus.RUNNING  # función pura: el original no cambia


@pytest.mark.parametrize(
    "status",
    [RequestStatus.SUCCEEDED, RequestStatus.PARTIALLY_SUCCEEDED, RequestStatus.FAILED, RequestStatus.INTERRUPTED],
)
def test_a_final_request_is_not_modified(status):
    request = make_request(make_steps(StepStatus.SUCCEEDED), status)
    assert request.is_final and interrupt(request, NOW) is request


def unit_hash(parameters: GenerationParameters, regeneration: RegenerationTarget | None = None) -> str:
    """Hash de un pedido de secuencia en la unidad u1, para comparar solo los parámetros."""
    return payload_hash(GenerationMode.SEQUENCE, "u1", parameters, regeneration)


def test_the_payload_hash_ignores_omitted_defaults_and_repeated_types():
    explicit = GenerationParameters(
        resource_types=("glosario", "explicacion", "glosario"),
        quantity=1,
        difficulty="intermedia",
        option_count=4,
        top_k=10,
        evidence_threshold=0.6,
        modalities=("Textual",),
    )
    assert unit_hash(explicit) == unit_hash(GenerationParameters(resource_types=("glosario", "explicacion")))
    assert len(unit_hash(explicit)) == 64


def test_the_payload_hash_changes_with_the_content():
    base = GenerationParameters(resource_types=("glosario",))
    assert unit_hash(base) != unit_hash(replace(base, quantity=2))  # GEN-C5: otra cantidad es otro pedido
    assert unit_hash(base) != unit_hash(GenerationParameters(resource_types=("explicacion",)))
    # El orden recibido de los tipos forma parte del pedido.
    assert unit_hash(GenerationParameters(resource_types=("glosario", "explicacion"))) != unit_hash(
        GenerationParameters(resource_types=("explicacion", "glosario"))
    )
    first = RegenerationTarget("rec-1", 1)
    assert unit_hash(base, first) != unit_hash(base)
    assert unit_hash(base, first) != unit_hash(base, RegenerationTarget("rec-1", 2))
    assert unit_hash(base, first) == unit_hash(base, RegenerationTarget("rec-1", 1))


def test_the_payload_hash_includes_the_mode_and_the_unit():
    """GEN-C5: la misma clave con los mismos parámetros en otra unidad o en otro modo es otro pedido."""
    base = GenerationParameters(resource_types=("glosario",))
    reference = payload_hash(GenerationMode.SEQUENCE, "u1", base)
    assert payload_hash("sequence", "u1", base) == reference  # el modo puede llegar como texto
    assert payload_hash(GenerationMode.SEQUENCE, "u2", base) != reference
    assert payload_hash(GenerationMode.INDIVIDUAL, "u1", base) != reference
    assert payload_hash(GenerationMode.REGENERATION, "u1", base) != reference


@pytest.mark.parametrize(
    "key", ["3f6c2a1e-8b4d-4d7a-9a51-0c2f8e1b7d10", "regen-rec-api-1-v2", "abcd_123", "a" * 128]
)
def test_valid_idempotency_keys_are_accepted(key):
    assert validate_idempotency_key(key) == key


@pytest.mark.parametrize(
    ("key", "code"),
    [
        (None, GenerationErrorCode.IDEMPOTENCY_KEY_REQUIRED),
        ("", GenerationErrorCode.IDEMPOTENCY_KEY_REQUIRED),
        ("   ", GenerationErrorCode.IDEMPOTENCY_KEY_REQUIRED),
        ("corta", GenerationErrorCode.INVALID_PARAMETERS),
        ("a" * 129, GenerationErrorCode.INVALID_PARAMETERS),
        ("clave con espacios", GenerationErrorCode.INVALID_PARAMETERS),
        ("clave/con/barras", GenerationErrorCode.INVALID_PARAMETERS),
        ("clave-estable-1\n", GenerationErrorCode.INVALID_PARAMETERS),
    ],
)
def test_invalid_idempotency_keys_are_rejected(key, code):
    with pytest.raises(GenerationError) as error:
        validate_idempotency_key(key)
    assert error.value.code == code
    assert error.value.message  # mensaje en español para el docente


def test_error_codes_are_plain_strings():
    assert GenerationErrorCode.IDEMPOTENCY_KEY_REUSED == "IDEMPOTENCY_KEY_REUSED"
    assert {code.value for code in GenerationErrorCode} >= {
        "IDEMPOTENCY_KEY_REQUIRED",
        "IDEMPOTENCY_KEY_REUSED",
        "INVALID_SEQUENCE",
        "GENERATION_REQUEST_NOT_FOUND",
        "UNIT_NOT_FOUND",
        "TOO_MANY_ACTIVE_REQUESTS",
        "DEADLINE_EXCEEDED",
        "EVIDENCE_UNAVAILABLE",
        "REGENERATION_PARAMETERS_MISSING",
        "REGENERATION_TARGET_INVALID",
        "REGENERATION_ATTEMPTS_EXHAUSTED",
    }
    # Solo Revisión responde REGENERATION_UNAVAILABLE (su 503); Generación ya no lo usa.
    assert "REGENERATION_UNAVAILABLE" not in {code.value for code in GenerationErrorCode}
