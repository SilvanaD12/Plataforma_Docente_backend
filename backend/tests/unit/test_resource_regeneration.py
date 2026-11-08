"""REV-01 · Regenerar un recurso desde Revisión sin perder el anterior (REV-R10 · REV-C12, C13).

Decisión provisional D10 (sin confirmación de Generación): el pedido es síncrono, Revisión registra la versión del
recurso al pedirlo y descarta el anterior con el motivo «regenerado» solo si sigue en esa versión.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from platform5e.application.ports.outbound.resource_regeneration_port import RegenerationStatus
from platform5e.application.services.review.resource_review_service import ResourceReviewService
from platform5e.domain.accounts.teacher_account import AccountConfigurationError

EVIDENCE = "El protocolo TCP confirma la entrega de los datos al receptor."
PARAMS = {"resourceType": "explicacion", "stage": "explain", "outcomeId": "ra1", "difficulty": "intermedia",
          "optionCount": 4, "instructions": "", "audience": "", "competency": "", "modalities": ["Textual"],
          "topK": 10, "evidenceThreshold": 0.6}


def explanation(resource_id: str, **overrides: Any) -> dict[str, Any]:
    return {
        "id": resource_id, "unitId": "u1", "type": "explicacion", "format": "text", "title": "TCP",
        "body": "El protocolo TCP confirma la entrega de los datos.", "options": None, "structure": None,
        "citations": [{"claim": "El protocolo TCP confirma la entrega de los datos.", "fragmentIds": ["f1"]}],
        "evidence": [{"id": "f1", "text": EVIDENCE, "location": "p. 1", "documentId": "d1", "documentName": "redes.pdf"}],
        "status": "pendiente", "edited": False, "discardReason": None, "createdAt": "2026-11-08T10:00:00+00:00",
        "decidedAt": None, "params": dict(PARAMS), "version": 3, **overrides,
    }


class Teachers:
    def get_courses(self, teacher_id: str) -> list[dict[str, Any]]:
        return [{"id": "c1", "units": [{"id": "u1"}]}] if teacher_id == "ana" else []


class Resources:
    """Recursos guardados, con el guardado condicional por versión."""

    def __init__(self, *resources: dict[str, Any]) -> None:
        self.by_id = {r["id"]: copy.deepcopy(r) for r in resources}

    def get_resource_by_id(self, teacher_id: str, resource_id: str) -> dict[str, Any] | None:
        return copy.deepcopy(self.by_id.get(resource_id)) if teacher_id == "ana" else None

    def get_resources_by_unit(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        return [copy.deepcopy(r) for r in self.by_id.values() if r["unitId"] == unit_id] if teacher_id == "ana" else []

    def save_resources(self, teacher_id: str, unit_id: str, resources: list[dict[str, Any]]) -> None:
        for resource in resources:
            self.by_id[resource["id"]] = {**copy.deepcopy(resource), "version": resource.get("version", 1)}

    def save_resource_if_version(self, teacher_id, unit_id, resource, expected_version, increment=True) -> bool:
        current = self.by_id.get(resource["id"])
        if current is None or current.get("version", 1) != expected_version:
            return False
        self.by_id[resource["id"]] = {**copy.deepcopy(resource), "version": expected_version + 1 if increment else expected_version}
        return True


class FakeGeneration:
    """Doble del puerto de regeneración: «genera» recursos nuevos guardándolos, como lo hace Generación."""

    def __init__(self, resources: Resources, outcome: str = "succeeded", during=None) -> None:
        self.resources, self.outcome, self.during = resources, outcome, during
        self.calls: list[dict[str, Any]] = []

    def request_regeneration(self, teacher_id, resource_id, resource_version, params) -> RegenerationStatus:
        self.calls.append({"teacher_id": teacher_id, "resource_id": resource_id, "version": resource_version, "params": params})
        if self.during:
            self.during()
        request_id = f"req-{len(self.calls)}"
        if self.outcome == "failed":
            return RegenerationStatus(request_id, "failed", (), "No hay material procesado en la unidad.")
        new_id = f"nuevo-{len(self.calls)}"
        self.resources.save_resources(teacher_id, params["unitId"], [{k: v for k, v in explanation(new_id).items() if k != "version"}])
        return RegenerationStatus(request_id, "succeeded", (new_id,), None)

    def get_regeneration(self, teacher_id, request_id) -> RegenerationStatus:
        raise AssertionError("el adaptador síncrono no se consulta")


def build(outcome: str = "succeeded", during=None, resource: dict[str, Any] | None = None):
    resources = Resources(resource or explanation("viejo"))
    generation = FakeGeneration(resources, outcome, during)
    return ResourceReviewService(Teachers(), resources, generation), resources, generation


def test_a_successful_regeneration_discards_the_previous_resource_when_it_is_still_at_the_registered_version():
    """REV-C12: el nuevo queda para revisión y el anterior pasa a Descartados con el motivo «regenerado»."""
    service, resources, generation = build()
    result = service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    assert result == {"previousResourceId": "viejo", "previousDiscarded": True, "newResourceIds": ["nuevo-1"], "status": "succeeded"}

    old = resources.by_id["viejo"]
    assert old["status"] == "descartado" and old["discardReason"] == "regenerado" and old["decidedAt"]
    new = resources.by_id["nuevo-1"]
    assert new["status"] == "pendiente" and new["regeneratedFrom"] == {"resourceId": "viejo", "version": 3}
    assert generation.calls[0]["params"] == {**PARAMS, "unitId": "u1"} and generation.calls[0]["version"] == 3


def test_the_new_resource_is_verified_when_it_is_read_like_any_resource_without_verification():
    service, resources, _ = build()
    service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    new = next(r for r in service.list_resources("ana", "u1") if r["id"] == "nuevo-1")
    assert new["verification"]["status"] == "current" and new["version"] == 1


def test_if_the_teacher_edits_the_previous_resource_meanwhile_both_stay_in_review():
    """REV-C12: si el docente lo editó mientras tanto, el anterior no se descarta y los dos quedan en Revisión."""
    holder: dict[str, Any] = {}

    def teacher_edits() -> None:
        edited = {**holder["resources"].by_id["viejo"], "body": "Texto editado en otra pestaña."}
        assert holder["resources"].save_resource_if_version("ana", "u1", edited, 3)

    service, resources, _ = build(during=teacher_edits)
    holder["resources"] = resources
    result = service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    assert result["previousDiscarded"] is False and result["newResourceIds"] == ["nuevo-1"]
    old = resources.by_id["viejo"]
    assert old["status"] == "pendiente" and old["body"] == "Texto editado en otra pestaña." and old["version"] == 4
    assert resources.by_id["nuevo-1"]["status"] == "pendiente"


def test_a_failed_regeneration_leaves_the_previous_resource_unchanged_and_gives_the_reason():
    """REV-C13: el recurso anterior queda como estaba y se informa el motivo."""
    service, resources, _ = build(outcome="failed")
    before = copy.deepcopy(resources.by_id["viejo"])
    with pytest.raises(AccountConfigurationError) as error:
        service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    assert error.value.code == "REGENERATION_FAILED" and error.value.status_code == 502
    assert error.value.message == "No hay material procesado en la unidad."
    old = resources.by_id["viejo"]
    assert {k: old[k] for k in ("status", "body", "version", "discardReason")} == {
        k: before[k] for k in ("status", "body", "version", "discardReason")
    }
    assert [r for r in resources.by_id if r.startswith("nuevo")] == []


def test_asking_twice_from_the_same_version_does_not_duplicate_resources():
    """Pedir la regeneración dos veces con la misma versión devuelve el mismo resultado sin generar otra vez."""
    service, resources, generation = build()
    first = service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    second = service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    assert second == first and len(generation.calls) == 1
    assert [r for r in resources.by_id if r.startswith("nuevo")] == ["nuevo-1"]


def test_after_a_failure_the_teacher_can_ask_again():
    service, resources, generation = build(outcome="failed")
    for _ in range(2):
        with pytest.raises(AccountConfigurationError):
            service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    assert len(generation.calls) == 2


def test_an_outdated_version_is_a_conflict_and_nothing_is_generated():
    service, resources, generation = build()
    with pytest.raises(AccountConfigurationError) as error:
        service.regenerate_resource("ana", "u1", "viejo", expected_version=2)
    assert error.value.code == "VERSION_CONFLICT" and generation.calls == []


def test_another_teacher_gets_404_and_nothing_is_generated():
    service, _, generation = build()
    with pytest.raises(AccountConfigurationError) as error:
        service.regenerate_resource("beto", "u1", "viejo", expected_version=3)
    assert error.value.status_code == 404 and generation.calls == []


def test_without_a_regeneration_port_the_service_says_it_is_not_available():
    resources = Resources(explanation("viejo"))
    service = ResourceReviewService(Teachers(), resources)
    with pytest.raises(AccountConfigurationError) as error:
        service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    assert error.value.code == "REGENERATION_UNAVAILABLE" and error.value.status_code == 503
