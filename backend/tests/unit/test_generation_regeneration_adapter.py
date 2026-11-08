"""REV-01 · Adaptador síncrono del puerto de regeneración (decisión provisional D10).

Pide a Generación un recurso nuevo con los parámetros guardados del anterior, por el mismo caso de uso que usa la ruta
de generación, y devuelve directamente `succeeded` o `failed`. No modifica ningún archivo de Generación.
"""

from __future__ import annotations

from typing import Any

from platform5e.domain.generation.errors import GenerationError
from platform5e.infrastructure.generation.generation_regeneration_adapter import GenerationRegenerationAdapter

PARAMS = {"unitId": "u1", "resourceType": "explicacion", "stage": "explain", "outcomeId": "ra1", "difficulty": "avanzada",
          "optionCount": 4, "instructions": "Usa ejemplos de videollamadas", "audience": "", "competency": "",
          "modalities": ["Textual"], "topK": 8, "evidenceThreshold": 0.7}


class FakeGenerationService:
    def __init__(self, result: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self.result, self.error = result, error
        self.requests: list[tuple[dict[str, Any], str | None]] = []

    def generate(self, request_data: dict[str, Any], teacher_id: str | None = None) -> dict[str, Any]:
        self.requests.append((request_data, teacher_id))
        if self.error:
            raise self.error
        return self.result or {}


def test_it_asks_generation_for_one_resource_with_the_stored_parameters():
    generation = FakeGenerationService({"resources": [{"id": "rec-nuevo"}]})
    status = GenerationRegenerationAdapter(generation).request_regeneration("ana", "rec-viejo", 3, PARAMS)
    assert status.status == "succeeded" and status.new_resource_ids == ("rec-nuevo",) and status.reason is None
    [(request, teacher)] = generation.requests
    assert teacher == "ana"
    assert request["quantity"] == 1 and request["resourceTypes"] is None
    assert {k: request[k] for k in PARAMS} == PARAMS


def test_a_generation_error_becomes_a_failed_status_with_its_reason():
    generation = FakeGenerationService(error=GenerationError("NO_PROCESSED_MATERIAL", "Procesa primero un documento de la unidad."))
    status = GenerationRegenerationAdapter(generation).request_regeneration("ana", "rec-viejo", 3, PARAMS)
    assert status.status == "failed" and status.new_resource_ids == ()
    assert status.reason == "Procesa primero un documento de la unidad."


def test_no_new_resources_is_a_failure():
    generation = FakeGenerationService({"resources": [], "notice": "Ningún recurso tuvo respaldo suficiente."})
    status = GenerationRegenerationAdapter(generation).request_regeneration("ana", "rec-viejo", 3, PARAMS)
    assert status.status == "failed" and "Ningún recurso tuvo respaldo suficiente." in status.reason


def test_missing_stored_parameters_are_a_failure_without_calling_generation():
    generation = FakeGenerationService({"resources": [{"id": "x"}]})
    status = GenerationRegenerationAdapter(generation).request_regeneration("ana", "rec-viejo", 3, {"unitId": "u1"})
    assert status.status == "failed" and "parámetros" in status.reason
    assert generation.requests == []


def test_an_unexpected_error_is_a_failure_with_a_general_reason():
    generation = FakeGenerationService(error=RuntimeError("timeout del proveedor"))
    status = GenerationRegenerationAdapter(generation).request_regeneration("ana", "rec-viejo", 3, PARAMS)
    assert status.status == "failed" and status.reason


def test_the_status_of_a_request_can_be_read_again():
    adapter = GenerationRegenerationAdapter(FakeGenerationService({"resources": [{"id": "rec-nuevo"}]}))
    status = adapter.request_regeneration("ana", "rec-viejo", 3, PARAMS)
    assert adapter.get_regeneration("ana", status.request_id) == status
    assert adapter.get_regeneration("beto", status.request_id) is None
