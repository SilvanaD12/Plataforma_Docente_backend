"""HU-024 (T050 a T053): modalidad del pedido como grupo de tipos de recurso. Caso GEN-C10 y research R11."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.application.services.generation.step_drafting import saved_parameters
from platform5e.application.use_cases.catalog.list_resource_types import ListResourceTypesUseCase
from platform5e.application.use_cases.generation import start_generation_request
from platform5e.application.use_cases.generation.run_generation_request import RunGenerationRequest
from platform5e.application.use_cases.generation.start_generation_request import StartGenerationCommand
from platform5e.application.use_cases.generation.start_regeneration import parameters_from_saved
from platform5e.domain.generation.errors import GenerationErrorCode
from platform5e.domain.generation.generation_request import (
    GenerationMode,
    GenerationParameters,
    RequestStatus,
    payload_hash,
)
from platform5e.domain.generation.resource_catalog import RESOURCE_TYPES
from platform5e.domain.generation.resource_formats import (
    MODALITIES,
    MODALITY_TYPES,
    modalities_of,
    types_outside_modality,
)
from platform5e.infrastructure.adapters.review_verification_adapter import ReviewVerificationAdapter
from platform5e.infrastructure.http.routers.generation_requests import status_payload
from platform5e.infrastructure.http.schemas.catalog import ResourceTypeResponse
from platform5e.infrastructure.http.schemas.generation_requests import (
    GenerationRequestStatus,
    StartGenerationRequest as StartBody,
)
from tests.unit.test_generation_request_use_cases import KEY, command, error_code, parts  # noqa: F401 (fixture)
from tests.unit.test_start_regeneration import Setup

# Tipo que agregará T054. Hasta entonces Kinestésico no tiene tipos.
FUTURE_KINESTHETIC_TYPE = "actividad_kinestesica"


# T051 · Catálogo


def test_the_four_modalities_group_the_types_of_the_data_model():
    assert MODALITIES == ("Textual", "Gamificado", "Multimedia", "Kinestésico")
    assert MODALITY_TYPES["Textual"] == {
        "pregunta_detonante", "sondeo_diagnostico", "guia_exploracion", "caso_indagacion", "exploracion_guiada",
        "explicacion", "glosario", "ejercicio_aplicacion", "caso_aplicado", "item_opcion_multiple",
    }
    assert MODALITY_TYPES["Gamificado"] == {
        "reto_prediccion", "emparejamiento", "ordenar_pasos", "verdadero_falso", "completar_espacios",
        "item_opcion_multiple",
    }
    assert MODALITY_TYPES["Multimedia"] == {
        "imagen_ilustrativa", "audio_detonante", "podcast_resumen", "diagrama_proceso", "mapa_conceptual", "infografia",
    }
    assert MODALITY_TYPES["Kinestésico"] == frozenset()  # T054 agrega actividad_kinestesica


def test_every_catalog_type_belongs_to_at_least_one_modality():
    catalog = {entry.id for entry in RESOURCE_TYPES}
    grouped = set().union(*MODALITY_TYPES.values())
    assert grouped <= catalog | {FUTURE_KINESTHETIC_TYPE}
    assert [type_id for type_id in catalog if not modalities_of(type_id)] == []
    assert modalities_of("item_opcion_multiple") == ["Textual", "Gamificado"]
    assert modalities_of("exploracion_guiada") == modalities_of("caso_aplicado") == ["Textual"]
    assert modalities_of("imagen_ilustrativa") == ["Multimedia"]


def test_the_catalog_reports_the_modalities_of_each_type():
    entries = ListResourceTypesUseCase().execute()
    assert len(entries) == len(RESOURCE_TYPES)
    by_id = {entry["id"]: entry for entry in entries}
    assert by_id["item_opcion_multiple"]["modalities"] == ["Textual", "Gamificado"]
    assert by_id["caso_aplicado"]["modalities"] == ["Textual"]
    response = ResourceTypeResponse.model_validate(by_id["podcast_resumen"]).model_dump(mode="json", by_alias=True)
    assert response["modalities"] == ["Multimedia"]


def test_types_outside_a_modality_keep_the_received_order():
    assert types_outside_modality("Gamificado", ["glosario", "item_opcion_multiple", "explicacion"]) == [
        "glosario",
        "explicacion",
    ]
    assert types_outside_modality("Textual", ["glosario", "caso_aplicado"]) == []
    assert types_outside_modality("Kinestésico", ["exploracion_guiada"]) == ["exploracion_guiada"]


# T050 · Contrato


def _body(**fields: Any) -> dict[str, Any]:
    return {"mode": "individual", "unitId": "u1", "resourceTypes": ["glosario"], **fields}


def test_the_body_accepts_one_of_the_four_modalities_without_a_server_default():
    assert StartBody.model_validate(_body()).to_parameters().modality is None
    assert StartBody.model_validate(_body(modalities=[])).to_parameters().modality is None
    for modality in MODALITIES:
        assert StartBody.model_validate(_body(modalities=[modality])).to_parameters().modality == modality
    assert "default" not in StartBody.model_json_schema(by_alias=True)["properties"]["modalities"]


@pytest.mark.parametrize("modalities", [["Visual"], ["Textual", "Gamificado"], ["textual"], "Textual"])
def test_the_body_rejects_unknown_values_and_more_than_one_modality(modalities):
    with pytest.raises(ValidationError):
        StartBody.model_validate(_body(modalities=modalities))


def test_the_parameters_keep_the_modality_and_it_changes_the_hash():
    without = GenerationParameters(resource_types=("glosario",))
    textual = GenerationParameters(resource_types=("glosario",), modality="Textual")
    assert without.modality is None
    assert without.to_payload()["modality"] is None and "modalities" not in without.to_payload()
    assert textual.to_payload()["modality"] == "Textual"
    # Sin valor por defecto en el servidor: omitirla y enviar «Textual» son pedidos distintos (research R2 y R11).
    assert payload_hash("sequence", "u1", without) != payload_hash("sequence", "u1", textual)


def test_the_status_view_returns_modalities_as_a_list_of_zero_or_one(parts):
    start = parts[0]
    with_modality = start.execute(command("item_opcion_multiple", modality="Gamificado")).request
    without = start.execute(command("glosario", key="otra-clave-123")).request

    chosen = status_payload(with_modality)["parameters"]
    assert chosen["modalities"] == ["Gamificado"] and "modality" not in chosen
    assert status_payload(without)["parameters"]["modalities"] == []
    GenerationRequestStatus.model_validate(status_payload(with_modality))  # cumple el contrato


# T052 · Validación al iniciar


def test_a_type_outside_the_modality_is_rejected_and_nothing_is_created(parts):
    start, repository, _, _, runner = parts
    code = error_code(lambda: start.execute(command("glosario", "reto_prediccion", modality="Textual")))
    assert code == GenerationErrorCode.RESOURCE_TYPE_NOT_IN_MODALITY
    assert repository.find_by_key("docente-a", KEY) is None and runner.submitted == []


def test_the_rejection_names_the_types_that_do_not_belong(parts):
    start = parts[0]
    with pytest.raises(start_generation_request.GenerationError) as rejected:
        start.execute(command("glosario", "item_opcion_multiple", modality="Gamificado"))
    assert "Glosario" in rejected.value.message and "Gamificado" in rejected.value.message
    assert "opción múltiple" not in rejected.value.message


@pytest.mark.parametrize("resource_type", ["exploracion_guiada", "imagen_ilustrativa", "ordenar_pasos"])
def test_kinesthetic_has_no_types_until_t054(parts, resource_type):
    start, repository = parts[0], parts[1]
    code = error_code(lambda: start.execute(command(resource_type, modality="Kinestésico")))
    assert code == GenerationErrorCode.RESOURCE_TYPE_NOT_IN_MODALITY
    assert repository.find_by_key("docente-a", KEY) is None


def test_a_compatible_request_saves_its_modality(parts):
    start, repository = parts[0], parts[1]
    created = start.execute(command("imagen_ilustrativa", "podcast_resumen", modality="Multimedia")).request
    assert repository.get("docente-a", created.id).parameters.modality == "Multimedia"


def test_without_a_modality_the_types_are_not_filtered(parts):
    start, repository = parts[0], parts[1]
    created = start.execute(command("glosario", "imagen_ilustrativa", "reto_prediccion")).request
    saved = repository.get("docente-a", created.id).parameters
    assert saved.modality is None and len(saved.resource_types) == 3


def test_resending_an_accepted_request_returns_it_without_validating_again(parts, monkeypatch):
    start = parts[0]
    first = start.execute(command("glosario", modality="Textual"))
    # Si la regla cambiara después de aceptar el pedido, reenviar la misma clave lo sigue devolviendo.
    monkeypatch.setattr(start_generation_request, "types_outside_modality", lambda modality, types: list(types))
    again = start.execute(command("glosario", modality="Textual"))
    assert not again.created and again.request.id == first.request.id


def test_the_other_rules_run_before_the_modality_after_the_key_lookup(parts):
    start = parts[0]
    first = start.execute(command("glosario"))
    # La misma clave con otra modalidad es otro contenido: conflicto, aunque el tipo no pertenezca a ella.
    code = error_code(lambda: start.execute(command("glosario", modality="Gamificado")))
    assert code == GenerationErrorCode.IDEMPOTENCY_KEY_REUSED and first.created


def test_requests_saved_before_hu024_are_read_without_a_modality(parts, tmp_path):
    start, repository = parts[0], parts[1]
    created = start.execute(command("glosario")).request
    engine = create_engine(f"sqlite:///{tmp_path / 'generation.db'}")
    try:
        with engine.begin() as connection:
            stored = connection.execute(
                text("SELECT parameters FROM gen_generation_requests WHERE id = :id"), {"id": created.id}
            ).scalar_one()
            legacy = stored if isinstance(stored, str) else __import__("json").dumps(stored)
            legacy = legacy.replace('"modality": null', '"modalities": ["Textual"]')
            assert '"modalities": ["Textual"]' in legacy and '"modality"' not in legacy
            connection.execute(
                text("UPDATE gen_generation_requests SET parameters = :p WHERE id = :id"),
                {"p": legacy, "id": created.id},
            )
    finally:
        engine.dispose()
    assert repository.get("docente-a", created.id).parameters.modality is None


# T053 · Parámetros de cada recurso y regeneración


def test_the_resource_params_keep_the_modality_only_when_chosen():
    base = {"resourceType": "glosario", "stage": "explain", "modality": None}
    assert "modality" not in saved_parameters(base) and "modalities" not in saved_parameters(base)
    assert saved_parameters({**base, "modality": "Textual"})["modality"] == "Textual"


def test_regeneration_reads_the_saved_modality_and_old_params_without_one():
    assert parameters_from_saved({"resourceType": "glosario", "modality": "Textual"}).modality == "Textual"
    assert parameters_from_saved({"resourceType": "glosario", "modalities": ["Textual"]}).modality is None
    assert parameters_from_saved({"resourceType": "glosario", "modality": "Visual"}).modality is None
    assert parameters_from_saved({"resourceType": "glosario", "modality": ["Textual"]}).modality is None


@pytest.fixture
def setup(tmp_path) -> Setup:
    return Setup(tmp_path)


def _run_rules(setup: Setup, request_id: str):
    RunGenerationRequest(
        setup.repository,
        setup.membership,
        setup.evidence,
        setup.review,
        ReviewVerificationAdapter(),
        RuleBasedGenerator(),
        heartbeat_seconds=0,
    ).execute(request_id)
    return setup.repository.get("docente-a", request_id)


@pytest.mark.parametrize(("modality", "resource_type"), [("Gamificado", "item_opcion_multiple"), (None, "explicacion")])
def test_each_new_resource_stores_the_chosen_modality_in_its_params(setup, modality, resource_type):
    start = setup.use_case._start_generation
    request = start.execute(
        StartGenerationCommand(
            "docente-a", "u1", GenerationMode.INDIVIDUAL, KEY,
            GenerationParameters(resource_types=(resource_type,), modality=modality),
        )
    ).request
    finished = _run_rules(setup, request.id)

    resources = setup.review.all()
    assert finished.status == RequestStatus.SUCCEEDED and resources
    for resource in resources:
        assert "modalities" not in resource["params"]
        assert resource["params"].get("modality") == modality
        assert ("modality" in resource["params"]) == (modality is not None)


@pytest.mark.parametrize(("resource_type", "stage"), [("imagen_ilustrativa", "explore"), ("audio_detonante", "engage")])
def test_old_image_and_audio_saved_with_textual_are_regenerated(setup, resource_type, stage):
    """Prueba obligatoria de R11: los recursos anteriores guardaron `modalities: ["Textual"]` aunque no son textuales.
    La regeneración no comprueba la modalidad y el recurso nuevo no la hereda."""
    old_params = {
        "resourceType": resource_type, "stage": stage, "outcomeId": None, "difficulty": "intermedia",
        "optionCount": 4, "instructions": "", "audience": "", "competency": "", "modalities": ["Textual"],
        "topK": 10, "evidenceThreshold": 0.6,
    }
    started = setup.regenerate(resource_id=f"rec-{resource_type}", version=1, params=old_params)
    assert started.created and started.request.parameters.modality is None

    finished = _run_rules(setup, started.request.id)
    [resource] = setup.review.all()
    assert finished.status == RequestStatus.SUCCEEDED
    assert resource["type"] == resource_type and resource["regeneratedFrom"]["resourceId"] == f"rec-{resource_type}"
    assert "modality" not in resource["params"] and "modalities" not in resource["params"]


def test_regeneration_keeps_the_saved_modality_without_checking_it(setup):
    # Un recurso nuevo con una modalidad que hoy no incluye su tipo (por ejemplo, si cambia MODALITY_TYPES).
    params = {"resourceType": "imagen_ilustrativa", "stage": "explore", "modality": "Textual"}
    started = setup.regenerate(resource_id="rec-img", version=1, params=params)
    assert started.created and started.request.parameters.modality == "Textual"
    _run_rules(setup, started.request.id)
    [resource] = setup.review.all()
    assert resource["params"]["modality"] == "Textual"
