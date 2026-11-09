"""GEN-01 (T028): inicio de la regeneración de un recurso de Revisión, con puertos falsos. Caso GEN-C7.

Todavía no hay puerto de regeneración de Revisión (T029): se prueba el caso de uso directamente.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from platform5e.application.use_cases.generation.run_generation_request import RunGenerationRequest
from platform5e.application.use_cases.generation.start_generation_request import StartGenerationRequest
from platform5e.application.use_cases.generation.start_regeneration import (
    StartRegeneration,
    StartRegenerationCommand,
    parameters_from_saved,
    regeneration_key,
)
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_request import (
    GenerationMode,
    GenerationParameters,
    RegenerationTarget,
    RequestStatus,
)
from platform5e.infrastructure.adapters.review_verification_adapter import ReviewVerificationAdapter
from tests.support.generation_fakes import (
    FRAGMENTS,
    FakeEvidence,
    FakeMembership,
    FakeReviewRepository,
    FakeRunner,
    sqlite_repository,
)
from tests.unit.test_sequence_orchestrator import StageAwareGenerator

# Los `params` que guarda `saved_parameters` en el recurso.
SAVED_PARAMS: dict[str, Any] = {
    "resourceType": "pregunta_detonante",
    "stage": "engage",
    "outcomeId": "ra-1",
    "difficulty": "avanzada",
    "optionCount": 3,
    "instructions": "Usa un ejemplo de videollamadas.",
    "audience": "Primer ciclo",
    "competency": "Pensamiento crítico",
    "modalities": ["Textual", "Visual"],
    "topK": 6,
    "evidenceThreshold": 0.5,
}


class Setup:
    def __init__(self, tmp_path) -> None:
        self.repository = sqlite_repository(tmp_path)
        self.membership = FakeMembership()
        self.evidence = FakeEvidence()
        self.review = FakeReviewRepository()
        self.runner = FakeRunner()
        self.use_case = StartRegeneration(
            StartGenerationRequest(self.membership, self.evidence, self.repository, self.runner)
        )

    def regenerate(self, resource_id: str = "rec-api-1", version: int = 2, params: Any = SAVED_PARAMS):
        return self.use_case.execute(StartRegenerationCommand("docente-a", "u1", resource_id, version, params))

    def run(self, request_id: str, generator=None):
        RunGenerationRequest(
            self.repository,
            self.membership,
            self.evidence,
            self.review,
            ReviewVerificationAdapter(),
            generator or StageAwareGenerator(),
            heartbeat_seconds=0,
        ).execute(request_id)
        return self.repository.get("docente-a", request_id)


@pytest.fixture
def setup(tmp_path) -> Setup:
    return Setup(tmp_path)


def test_a_regeneration_request_has_one_step_with_the_saved_params(setup):
    result = setup.regenerate()
    request = result.request

    assert result.created and setup.runner.submitted == [request.id]
    assert request.mode == GenerationMode.REGENERATION and request.status == RequestStatus.QUEUED
    assert request.idempotency_key == "regen-rec-api-1-v2"
    assert request.regeneration == RegenerationTarget("rec-api-1", 2)
    [step] = request.steps
    assert (step.resource_type, step.stage) == ("pregunta_detonante", "engage")
    assert request.parameters == GenerationParameters(
        resource_types=("pregunta_detonante",),
        quantity=1,
        outcome_id="ra-1",
        difficulty="avanzada",
        option_count=3,
        top_k=6,
        evidence_threshold=0.5,
        instructions="Usa un ejemplo de videollamadas.",
        audience="Primer ciclo",
        competency="Pensamiento crítico",
        modalities=("Textual", "Visual"),
    )


def test_asking_twice_for_the_same_version_returns_the_same_request(setup):
    first = setup.regenerate()
    again = setup.regenerate()
    assert not again.created and again.request.id == first.request.id
    assert setup.runner.submitted == [first.request.id]  # no se encola otra vez ni duplica recursos

    newer = setup.regenerate(version=3)  # el docente editó el recurso: otra versión, otro pedido
    assert newer.created and newer.request.id != first.request.id
    assert newer.request.idempotency_key == regeneration_key("rec-api-1", 3) == "regen-rec-api-1-v3"


def test_the_new_resource_uses_current_evidence_and_records_where_it_came_from(setup):
    """La evidencia es la que el material tiene hoy, no la copia histórica del recurso anterior (GEN-R6)."""
    # El material se reprocesó: los mismos textos llegan con otros fragmentos y otro documento.
    updated = tuple(
        replace(fragment, chunk_id=f"nuevo-{fragment.chunk_id}", document_id="doc2", document_name="apuntes-2026.pdf")
        for fragment in FRAGMENTS
    )
    setup.evidence.fragments = updated
    request = setup.run(setup.regenerate().request.id)

    [resource] = setup.review.all()
    assert request.status == RequestStatus.SUCCEEDED and request.steps[0].resource_ids == (resource["id"],)
    assert resource["regeneratedFrom"] == {"resourceId": "rec-api-1", "version": 2}
    assert resource["id"] != "rec-api-1" and resource["version"] == 1
    assert resource["verification"]["status"] == "current"
    assert resource["evidence"] and {item["documentName"] for item in resource["evidence"]} == {"apuntes-2026.pdf"}
    assert all(item["id"].startswith("nuevo-") for item in resource["evidence"])
    assert resource["params"]["resourceType"] == "pregunta_detonante"
    assert resource["params"]["evidenceThreshold"] == 0.5 == resource["verification"]["evidenceThreshold"]
    assert len(setup.evidence.queries) == 1 and setup.evidence.queries[0].limit == 6


@pytest.mark.parametrize("params", [None, {}, {"stage": "engage"}, {"resourceType": ""}, "pregunta_detonante"])
def test_a_resource_without_params_cannot_be_regenerated(setup, params):
    with pytest.raises(GenerationError) as unavailable:
        setup.regenerate(params=params)
    assert unavailable.value.code == GenerationErrorCode.REGENERATION_UNAVAILABLE
    assert "no se puede regenerar" in unavailable.value.message
    assert setup.runner.submitted == []


@pytest.mark.parametrize(("resource_id", "version"), [("", 1), ("rec api/1", 1), ("rec-api-1", 0), ("rec-api-1", True)])
def test_an_invalid_target_cannot_be_regenerated(setup, resource_id, version):
    with pytest.raises(GenerationError) as unavailable:
        setup.regenerate(resource_id=resource_id, version=version)
    assert unavailable.value.code == GenerationErrorCode.REGENERATION_UNAVAILABLE
    assert setup.runner.submitted == []


def test_the_usual_rules_still_apply(setup):
    setup.membership.units.clear()
    with pytest.raises(GenerationError) as foreign:
        setup.regenerate()
    assert foreign.value.code == GenerationErrorCode.UNIT_NOT_FOUND


def test_missing_or_old_values_take_the_request_defaults():
    defaults = GenerationParameters(resource_types=("explicacion",))
    assert parameters_from_saved({"resourceType": "explicacion"}) == defaults
    old = {"resourceType": "explicacion", "topK": None, "optionCount": "4", "modalities": [], "evidenceThreshold": True}
    assert parameters_from_saved(old) == defaults
