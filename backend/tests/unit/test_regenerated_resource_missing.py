"""PR #17 (revisión de Silvana), cambio defensivo en Revisión: si Generación responde `succeeded` pero el recurso nuevo
ya no existe (el docente lo borró entre la respuesta y el descarte), el original no se descarta. Se registra `failed`
con REGENERATED_RESOURCE_NOT_FOUND y se libera la reserva, como cualquier otro fallo. Dobles locales, sin IA."""

from __future__ import annotations

from platform5e.application.ports.outbound.resource_regeneration_port import RegenerationStatus
from tests.unit.test_background_regeneration import build


def test_a_succeeded_answer_whose_new_resource_no_longer_exists_keeps_the_original():
    service, resources, generation = build()
    service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    assert resources.claims["viejo"] == 3
    generation.statuses["gen-req-1"] = RegenerationStatus("gen-req-1", "succeeded", ("borrado",), None)

    status = service.get_regeneration_status("ana", "u1", "viejo")

    assert status["status"] == "failed" and status["code"] == "REGENERATED_RESOURCE_NOT_FOUND"
    assert status["reason"] == "El recurso regenerado ya no existe. Pide la regeneración otra vez."
    assert status["previousDiscarded"] is False and status["newResourceIds"] == []
    old = resources.by_id["viejo"]
    assert (old["status"], old["version"]) == ("pendiente", 3)
    assert old["regeneration"]["status"] == "failed"
    assert resources.claims.get("viejo") is None  # reserva liberada: se puede pedir otra vez

    # Se puede pedir de nuevo desde la misma versión.
    again = service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    assert again["status"] == "running" and len(generation.requests) == 2


def test_only_the_new_resources_that_still_exist_are_recorded():
    service, resources, generation = build()
    service.regenerate_resource("ana", "u1", "viejo", expected_version=3)
    kept = generation.finish("gen-req-1")
    generation.statuses["gen-req-1"] = RegenerationStatus("gen-req-1", "succeeded", ("borrado", kept), None)

    status = service.get_regeneration_status("ana", "u1", "viejo")

    assert status["status"] == "succeeded" and status["newResourceIds"] == [kept]
    assert status["previousDiscarded"] is True
    assert resources.by_id["viejo"]["status"] == "descartado"
    assert resources.by_id["viejo"]["regeneration"]["newResourceIds"] == [kept]
