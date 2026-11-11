"""REV-01 · D10 confirmada por Yan (2026-11-09): la regeneración puede quedar en segundo plano.

El adaptador de Generación (T029 de Yan) devuelve `pending` o `running` con el id del pedido cuando no termina dentro de
su tiempo límite, y `get_regeneration` traduce después el estado del pedido. Revisión trata `pending` y `running` como
«en curso» (sin marcar fallo ni liberar la reserva) y, al consultar el estado, hace el descarte condicional cuando ve
`succeeded` o registra el motivo cuando ve `failed`.
"""

from __future__ import annotations

from typing import Any

import pytest

from platform5e.application.ports.outbound.resource_regeneration_port import RegenerationStatus
from platform5e.application.services.review.resource_review_service import ResourceReviewService
from platform5e.domain.accounts.teacher_account import AccountConfigurationError
from platform5e.domain.review.errors import RegenerationFailedError
from tests.unit.test_resource_regeneration import Resources, Teachers, explanation


class BackgroundGeneration:
    """Doble del adaptador de Yan: el pedido queda en curso y termina cuando la prueba lo indica."""

    def __init__(self, resources: Resources, first_status: str = "pending") -> None:
        self.resources, self.first_status = resources, first_status
        self.requests: list[dict[str, Any]] = []
        self.statuses: dict[str, RegenerationStatus] = {}

    def request_regeneration(self, teacher_id, resource_id, resource_version, params) -> RegenerationStatus:
        request_id = f"gen-req-{len(self.requests) + 1}"
        self.requests.append({"teacher_id": teacher_id, "version": resource_version, "params": params})
        self.statuses[request_id] = RegenerationStatus(request_id, self.first_status)  # type: ignore[arg-type]
        return self.statuses[request_id]

    def get_regeneration(self, teacher_id, request_id) -> RegenerationStatus | None:
        return self.statuses.get(request_id) if teacher_id == "ana" else None

    def finish(self, request_id: str, unit_id: str = "u1") -> str:
        """Como Generación: guarda el recurso nuevo (con regeneratedFrom) y marca el pedido como terminado."""
        new_id = f"nuevo-{request_id}"
        new = {k: v for k, v in explanation(new_id).items() if k != "version"}
        self.resources.save_resources("ana", unit_id, [{**new, "regeneratedFrom": {"resourceId": "viejo", "version": 3}}])
        self.statuses[request_id] = RegenerationStatus(request_id, "succeeded", (new_id,), None)
        return new_id

    def fail(self, request_id: str, reason: str, code: str | None) -> None:
        self.statuses[request_id] = RegenerationStatus(request_id, "failed", (), reason, code)


def build(first_status: str = "pending"):
    resources = Resources(explanation("viejo"))
    generation = BackgroundGeneration(resources, first_status)
    return ResourceReviewService(Teachers(), resources, generation), resources, generation


@pytest.mark.parametrize("first_status", ["pending", "running"])
def test_a_request_still_in_progress_is_not_a_failure(first_status):
    service, resources, generation = build(first_status)
    result = service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    assert result == {"previousResourceId": "viejo", "previousDiscarded": False, "newResourceIds": [], "status": "running"}
    old = resources.by_id["viejo"]
    assert old["status"] == "pendiente" and old["version"] == 3
    assert old["regeneration"]["status"] == "running" and old["regeneration"]["requestId"] == "gen-req-1"
    assert resources.claims["viejo"] == 3


def test_while_it_runs_asking_again_does_not_create_another_request():
    service, _, generation = build()
    service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    again = service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    assert again["status"] == "running" and len(generation.requests) == 1


def test_the_status_says_running_until_generation_finishes():
    service, _, _ = build()
    service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    assert service.get_regeneration_status("ana", "u1", "viejo") == {
        "previousResourceId": "viejo", "previousDiscarded": False, "newResourceIds": [], "status": "running",
        "reason": None, "code": None,
    }


def test_when_generation_finishes_the_status_discards_the_previous_resource():
    """REV-C12: el descarte condicional lo hace Revisión al ver `succeeded`; Generación nunca toca el anterior."""
    service, resources, generation = build()
    service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    new_id = generation.finish("gen-req-1")
    status = service.get_regeneration_status("ana", "u1", "viejo")
    assert status["status"] == "succeeded" and status["previousDiscarded"] is True and status["newResourceIds"] == [new_id]
    old = resources.by_id["viejo"]
    assert old["status"] == "descartado" and old["discardReason"] == "regenerado"
    assert resources.by_id[new_id]["regeneratedFrom"] == {"resourceId": "viejo", "version": 3}
    # Consultar otra vez devuelve lo mismo sin descartar de nuevo.
    assert service.get_regeneration_status("ana", "u1", "viejo")["status"] == "succeeded"
    assert resources.by_id["viejo"]["version"] == 4


def test_if_the_teacher_edits_while_it_runs_both_stay_in_review():
    service, resources, generation = build()
    service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    edited = {**resources.by_id["viejo"], "body": "Texto editado mientras se regeneraba."}
    assert resources.save_resource_if_version("ana", "u1", edited, 3)
    generation.finish("gen-req-1")
    status = service.get_regeneration_status("ana", "u1", "viejo")
    assert status["status"] == "succeeded" and status["previousDiscarded"] is False
    old = resources.by_id["viejo"]
    assert old["status"] == "pendiente" and old["body"] == "Texto editado mientras se regeneraba."


def test_when_generation_fails_the_status_gives_the_reason_and_the_teacher_can_ask_again():
    """REV-C13: el anterior queda como estaba; la reserva se libera para poder pedirla otra vez."""
    service, resources, generation = build()
    service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    generation.fail("gen-req-1", "Procesa primero un documento de la unidad.", "NO_PROCESSED_MATERIAL")
    status = service.get_regeneration_status("ana", "u1", "viejo")
    assert status == {
        "previousResourceId": "viejo", "previousDiscarded": False, "newResourceIds": [], "status": "failed",
        "reason": "Procesa primero un documento de la unidad.", "code": "NO_PROCESSED_MATERIAL",
    }
    assert resources.by_id["viejo"]["status"] == "pendiente" and "viejo" not in resources.claims
    service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    assert len(generation.requests) == 2


def test_a_request_that_generation_no_longer_knows_is_a_failure():
    service, resources, generation = build()
    service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    generation.statuses.clear()
    status = service.get_regeneration_status("ana", "u1", "viejo")
    assert status["status"] == "failed" and status["reason"] and "viejo" not in resources.claims


def test_without_a_regeneration_request_the_status_is_not_found():
    service, _, _ = build()
    with pytest.raises(AccountConfigurationError) as error:
        service.get_regeneration_status("ana", "u1", "viejo")
    assert error.value.code == "REGENERATION_NOT_FOUND" and error.value.status_code == 404


def test_another_teacher_cannot_read_the_status():
    service, _, _ = build()
    service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    with pytest.raises(AccountConfigurationError) as error:
        service.get_regeneration_status("beto", "u1", "viejo")
    assert error.value.status_code == 404


def test_two_overlapping_status_queries_keep_the_discarded_result():
    """Revisión de Silvana (PR #13): si dos consultas del mismo pedido se solapan, la segunda no sobrescribe
    `previousDiscarded: true` con `false`; una vez terminado, todas devuelven el resultado guardado."""
    service, resources, generation = build()
    service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    new_id = generation.finish("gen-req-1")
    inner: list[dict[str, Any]] = []
    overlapped = False
    original = generation.get_regeneration

    def overlapping(teacher_id, request_id):
        nonlocal overlapped
        state = original(teacher_id, request_id)
        if not overlapped:  # la primera consulta ve `succeeded`; antes de que siga, otra consulta termina el pedido
            overlapped = True
            inner.append(service.get_regeneration_status("ana", "u1", "viejo"))
        return state

    generation.get_regeneration = overlapping
    outer = service.get_regeneration_status("ana", "u1", "viejo")
    assert inner[0]["previousDiscarded"] is True and inner[0]["newResourceIds"] == [new_id]
    assert outer["status"] == "succeeded" and outer["previousDiscarded"] is True
    assert resources.by_id["viejo"]["regeneration"]["previousDiscarded"] is True
    assert service.get_regeneration_status("ana", "u1", "viejo")["previousDiscarded"] is True
    assert resources.by_id["viejo"]["status"] == "descartado" and resources.by_id["viejo"]["version"] == 4


def _late_answer_after_a_retry(service, generation, late: RegenerationStatus) -> dict[str, Any]:
    """Revisión de Silvana en el PR #17 de Yan: una consulta lee el primer intento (`gen-req-1`, en curso) y espera a
    Generación. Mientras espera, ese intento falla, se libera la reserva y el docente pide otra vez la regeneración
    desde la misma versión (`gen-req-2`). Después llega la respuesta tardía del primer intento."""
    service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    original = generation.get_regeneration
    waiting = True

    def late_answer(teacher_id, request_id):
        nonlocal waiting
        if not waiting:
            return original(teacher_id, request_id)
        waiting = False
        generation.fail("gen-req-1", "Generación no respondió a tiempo.", None)
        assert service.get_regeneration_status("ana", "u1", "viejo")["status"] == "failed"
        assert service.regenerate_resource("ana", "u1", "viejo", expected_version=3)["status"] == "running"
        return late

    generation.get_regeneration = late_answer
    return service.get_regeneration_status("ana", "u1", "viejo")


@pytest.mark.parametrize("late_status", ["failed", "succeeded"])
def test_a_late_answer_of_an_old_attempt_leaves_the_new_attempt_intact(late_status):
    service, resources, generation = build()
    new_ids = ("nuevo-tardio",) if late_status == "succeeded" else ()
    late = RegenerationStatus("gen-req-1", late_status, new_ids, "Respuesta tardía.", None)  # type: ignore[arg-type]
    answer = _late_answer_after_a_retry(service, generation, late)

    old = resources.by_id["viejo"]
    assert old["regeneration"]["requestId"] == "gen-req-2" and old["regeneration"]["status"] == "running"
    assert resources.claims["viejo"] == 3, "la respuesta vieja liberó la reserva del intento nuevo"
    assert old["status"] == "pendiente" and old["version"] == 3, "la respuesta vieja descartó el recurso"
    assert answer["status"] == "running"
    assert len(generation.requests) == 2


def test_a_running_write_does_not_overwrite_the_same_attempt_once_it_failed():
    """Revisión de Silvana en el PR #17 de Yan: una consulta lee el intento en curso y, antes de escribir su
    `running`, otra consulta del mismo intento guarda `failed` y libera la reserva. La primera no debe pisar `failed`:
    si lo hiciera, el recurso quedaría «en curso» sin reserva y el pedido siguiente no crearía uno nuevo."""
    service, resources, generation = build()
    service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    original = resources.save_resource_if_attempt
    inner: list[dict[str, Any]] = []

    def racing(teacher_id, unit_id, resource, expected_version, attempt_id, increment=False):
        if not inner and resource["regeneration"]["status"] == "running":
            # Entre la lectura y la escritura de la primera consulta, el intento falla y otra consulta lo registra.
            generation.fail("gen-req-1", "Generación no respondió a tiempo.", None)
            inner.append(service.get_regeneration_status("ana", "u1", "viejo"))
        return original(teacher_id, unit_id, resource, expected_version, attempt_id, increment)

    resources.save_resource_if_attempt = racing
    answer = service.get_regeneration_status("ana", "u1", "viejo")

    assert inner[0]["status"] == "failed"
    assert resources.by_id["viejo"]["regeneration"]["status"] == "failed", "la escritura vieja pisó `failed`"
    assert answer["status"] == "failed"
    assert "viejo" not in resources.claims
    assert service.regenerate_resource("ana", "u1", "viejo", expected_version=3)["status"] == "running"
    assert len(generation.requests) == 2, "el pedido siguiente respondió «en curso» sin crear uno nuevo"


def test_a_post_whose_regenerated_resource_no_longer_exists_is_a_state_conflict():
    """Cierre de REV-01: si Generación termina dentro del POST pero ningún recurso nuevo sigue en Revisión (d1c7faf),
    el error es 409 REGENERATED_RESOURCE_NOT_FOUND, como los rechazos por el estado del material. El 422 queda para
    los parámetros guardados del recurso, como dice la ficha."""
    service, resources, _ = build(first_status="succeeded")
    with pytest.raises(RegenerationFailedError) as error:
        service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    assert error.value.code == "REGENERATED_RESOURCE_NOT_FOUND" and error.value.status_code == 409
    old = resources.by_id["viejo"]
    assert (old["status"], old["version"]) == ("pendiente", 3) and "viejo" not in resources.claims
