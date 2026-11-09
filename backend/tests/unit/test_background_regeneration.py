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
