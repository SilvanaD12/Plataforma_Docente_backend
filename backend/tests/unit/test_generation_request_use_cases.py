"""GEN-01 (T015 y T017): inicio y consulta del pedido de generación. Casos GEN-C4, GEN-C5 y GEN-C6."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from platform5e.application.ports.outbound.generation_request_repository_port import IdempotencyKeyTaken
from platform5e.application.use_cases.generation.get_generation_request import (
    GetGenerationRequest,
    ResourceSummary,
)
from platform5e.application.use_cases.generation.start_generation_request import (
    StartGenerationCommand,
    StartGenerationRequest,
)
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_request import (
    GenerationMode,
    GenerationParameters,
    RequestStatus,
    StepStatus,
)
from tests.support.generation_fakes import (
    FakeEvidence,
    FakeMembership,
    FakeReviewRepository,
    FakeRunner,
    sqlite_repository,
)

KEY = "3f6c2a1e-8b4d-4d7a-9a51-0c2f8e1b7d10"


def command(
    *types: str,
    key: str | None = KEY,
    mode: GenerationMode = GenerationMode.SEQUENCE,
    teacher_id: str = "docente-a",
    unit_id: str = "u1",
    **parameters: Any,
) -> StartGenerationCommand:
    return StartGenerationCommand(
        teacher_id=teacher_id,
        unit_id=unit_id,
        mode=mode,
        idempotency_key=key,
        parameters=GenerationParameters(resource_types=types or ("pregunta_detonante",), **parameters),
    )


@pytest.fixture
def parts(tmp_path):
    repository = sqlite_repository(tmp_path)
    membership, evidence, runner = FakeMembership(), FakeEvidence(), FakeRunner()
    start = StartGenerationRequest(membership, evidence, repository, runner, clock=lambda: "2026-11-10T12:00:00+00:00")
    return start, repository, membership, evidence, runner


def error_code(action) -> str:
    with pytest.raises(GenerationError) as error:
        action()
    assert error.value.message
    return error.value.code


# T015 · Inicio


def test_a_new_request_is_saved_in_class_order_and_queued(parts):
    start, repository, _, _, runner = parts
    result = start.execute(command("item_opcion_multiple", "pregunta_detonante", "pregunta_detonante"))

    assert result.created and runner.submitted == [result.request.id]
    request = repository.get("docente-a", result.request.id)
    assert request.status == RequestStatus.QUEUED and request.mode == GenerationMode.SEQUENCE
    assert request.parameters.resource_types == ("pregunta_detonante", "item_opcion_multiple")
    assert [(s.position, s.stage, s.status) for s in request.steps] == [
        (0, "engage", StepStatus.PENDING),
        (1, "evaluate", StepStatus.PENDING),
    ]


def test_the_same_key_and_content_returns_the_existing_request(parts):
    """GEN-C4: reenviar no duplica; los campos omitidos con su valor por defecto no cuentan como otro contenido."""
    start, repository, _, _, runner = parts
    first = start.execute(command("glosario", mode=GenerationMode.INDIVIDUAL))
    again = start.execute(command("glosario", mode=GenerationMode.INDIVIDUAL, quantity=1, difficulty="intermedia"))

    assert not again.created and again.request.id == first.request.id
    assert runner.submitted == [first.request.id]
    assert len(repository.list_by_unit("docente-a", "u1", active_only=False, limit=10)) == 1


def test_the_same_key_with_other_content_is_a_conflict(parts):
    """GEN-C5."""
    start, *_ = parts
    start.execute(command("glosario", mode=GenerationMode.INDIVIDUAL))
    assert error_code(lambda: start.execute(command("glosario", mode=GenerationMode.INDIVIDUAL, quantity=2))) == (
        GenerationErrorCode.IDEMPOTENCY_KEY_REUSED
    )


def test_the_same_key_and_parameters_in_another_unit_is_a_conflict(parts):
    """GEN-C5: la unidad forma parte del contenido del pedido."""
    start, _, membership, _, runner = parts
    membership.units[("docente-a", "u2")] = replace(membership.units[("docente-a", "u1")], unit_id="u2")
    start.execute(command("glosario", mode=GenerationMode.INDIVIDUAL))
    assert error_code(lambda: start.execute(command("glosario", mode=GenerationMode.INDIVIDUAL, unit_id="u2"))) == (
        GenerationErrorCode.IDEMPOTENCY_KEY_REUSED
    )
    assert len(runner.submitted) == 1


def test_the_same_key_and_parameters_in_another_mode_is_a_conflict(parts):
    """GEN-C5: un tipo en modo individual y el mismo tipo como secuencia son pedidos distintos."""
    start, _, _, _, runner = parts
    start.execute(command("glosario", mode=GenerationMode.INDIVIDUAL))
    assert error_code(lambda: start.execute(command("glosario", mode=GenerationMode.SEQUENCE))) == (
        GenerationErrorCode.IDEMPOTENCY_KEY_REUSED
    )
    assert len(runner.submitted) == 1


def test_an_accepted_request_is_returned_even_if_the_unit_lost_its_material(parts):
    """GEN-C4: reenviar la clave de un pedido aceptado lo devuelve sin volver a aplicar las reglas de inicio."""
    start, _, membership, evidence, runner = parts
    first = start.execute(command("glosario", mode=GenerationMode.INDIVIDUAL, outcome_id="ra-1"))
    evidence.material = False  # el docente borró el documento después de pedir
    again = start.execute(command("glosario", mode=GenerationMode.INDIVIDUAL, outcome_id="ra-1"))
    assert not again.created and again.request.id == first.request.id
    assert runner.submitted == [first.request.id]

    # La pertenencia sí se comprueba antes: si la unidad ya no es del docente, no se revela el pedido.
    membership.units.clear()
    assert error_code(
        lambda: start.execute(command("glosario", mode=GenerationMode.INDIVIDUAL, outcome_id="ra-1"))
    ) == GenerationErrorCode.UNIT_NOT_FOUND


def test_two_teachers_can_use_the_same_key(parts):
    start, _, membership, _, runner = parts
    membership.units[("docente-b", "u7")] = replace(membership.units[("docente-a", "u1")], unit_id="u7")
    first = start.execute(command("glosario", mode=GenerationMode.INDIVIDUAL))
    second = start.execute(command("glosario", mode=GenerationMode.INDIVIDUAL, teacher_id="docente-b", unit_id="u7"))
    assert first.created and second.created and first.request.id != second.request.id


def test_rules_are_checked_in_order_and_nothing_is_created_on_error(parts):
    start, repository, _, evidence, runner = parts
    assert error_code(lambda: start.execute(command(key=None))) == GenerationErrorCode.IDEMPOTENCY_KEY_REQUIRED
    assert error_code(lambda: start.execute(command(key="corta"))) == GenerationErrorCode.INVALID_PARAMETERS
    # Una unidad ajena y una inexistente dan la misma respuesta.
    assert error_code(lambda: start.execute(command(unit_id="u9"))) == GenerationErrorCode.UNIT_NOT_FOUND
    assert error_code(lambda: start.execute(command(teacher_id="docente-b"))) == GenerationErrorCode.UNIT_NOT_FOUND
    assert error_code(lambda: start.execute(command(outcome_id="ra-ajeno"))) == GenerationErrorCode.INVALID_OUTCOME
    assert error_code(
        lambda: start.execute(command("glosario", "explicacion", mode=GenerationMode.INDIVIDUAL))
    ) == GenerationErrorCode.INVALID_SEQUENCE
    evidence.material = False
    assert error_code(lambda: start.execute(command())) == GenerationErrorCode.NO_PROCESSED_MATERIAL  # GEN-C6

    assert repository.list_by_unit("docente-a", "u1", active_only=False, limit=10) == []
    assert runner.submitted == []


def test_no_more_than_two_active_requests_per_teacher(parts):
    start, repository, *_ = parts
    first = start.execute(command(key="clave-pedido-1"))
    start.execute(command(key="clave-pedido-2"))
    assert error_code(lambda: start.execute(command(key="clave-pedido-3"))) == (
        GenerationErrorCode.TOO_MANY_ACTIVE_REQUESTS
    )
    # Repetir una clave existente no cuenta como pedido nuevo, y al terminar uno se libera el cupo.
    assert not start.execute(command(key="clave-pedido-1")).created
    repository.finish(first.request.id, RequestStatus.SUCCEEDED, None)
    assert start.execute(command(key="clave-pedido-3")).created


def test_a_lost_race_returns_the_winner_request(parts):
    """Si otro envío con la misma clave se guardó entre la búsqueda y la inserción, se responde con ese pedido."""
    start, repository, *_ = parts
    winner = start.execute(command(key="clave-carrera")).request

    class RacingRepository:
        def __getattr__(self, name: str):
            return getattr(repository, name)

        def find_by_key(self, teacher_id: str, key: str):
            return None  # todavía no lo veía

        def create_within_limit(self, request, max_active):
            raise IdempotencyKeyTaken(winner)

    racing = StartGenerationRequest(FakeMembership(), FakeEvidence(), RacingRepository(), FakeRunner())
    result = racing.execute(command(key="clave-carrera"))
    assert not result.created and result.request.id == winner.id
    with pytest.raises(GenerationError) as conflict:
        racing.execute(command(key="clave-carrera", quantity=3))
    assert conflict.value.code == GenerationErrorCode.IDEMPOTENCY_KEY_REUSED


# T017 · Consulta


def test_get_shows_each_step_with_a_short_view_of_its_resources(parts):
    start, repository, membership, *_ = parts
    request = start.execute(command("pregunta_detonante", "explicacion")).request
    review = FakeReviewRepository()
    review.save_resources(
        "docente-a",
        "u1",
        [
            {"id": "rec-1", "title": "Video en vivo", "verification": {"status": "current"}},
            {"id": "rec-2", "title": "Sin comprobar", "verification": {"status": "pending"}},
            # Editado en Revisión hasta quedar sin respaldo: se muestra el estado real. Sin verificación: pendiente.
            {"id": "rec-3", "title": "Editado", "verification": {"status": "insufficient"}},
            {"id": "rec-4", "title": "Sin verificación"},
        ],
    )
    engage = replace(
        request.steps[0], status=StepStatus.SUCCEEDED, resource_ids=("rec-1", "rec-2", "rec-3", "rec-4", "rec-borrado")
    )
    repository.update_step(request.id, engage)

    view = GetGenerationRequest(repository, membership, review).get("docente-a", request.id)
    assert view.request.id == request.id
    assert view.resources_by_step == {
        0: (
            ResourceSummary("rec-1", "Video en vivo", "current"),
            ResourceSummary("rec-2", "Sin comprobar", "pending"),
            ResourceSummary("rec-3", "Editado", "insufficient"),
            ResourceSummary("rec-4", "Sin verificación", "pending"),
        ),
        1: (),
    }


def test_a_foreign_or_missing_request_is_not_found(parts):
    """GEN-C5: la consulta ajena se rechaza igual que una inexistente."""
    start, repository, membership, *_ = parts
    request = start.execute(command()).request
    get = GetGenerationRequest(repository, membership, FakeReviewRepository())
    for teacher_id, request_id in (("docente-b", request.id), ("docente-a", "gen-req-no-existe")):
        assert error_code(lambda: get.get(teacher_id, request_id)) == GenerationErrorCode.GENERATION_REQUEST_NOT_FOUND


def test_list_requires_the_unit_and_bounds_the_limit(parts):
    start, repository, membership, *_ = parts
    first = start.execute(command(key="clave-lista-1")).request
    second = start.execute(command(key="clave-lista-2")).request
    repository.finish(first.id, RequestStatus.SUCCEEDED, None)
    get = GetGenerationRequest(repository, membership, FakeReviewRepository())

    assert {r.id for r in get.list("docente-a", "u1")} == {first.id, second.id}
    assert [r.id for r in get.list("docente-a", "u1", active_only=True)] == [second.id]
    assert len(get.list("docente-a", "u1", limit=0)) == 1  # el mínimo es 1
    assert error_code(lambda: get.list("docente-b", "u1")) == GenerationErrorCode.UNIT_NOT_FOUND
