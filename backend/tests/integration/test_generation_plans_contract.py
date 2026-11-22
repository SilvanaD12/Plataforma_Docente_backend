"""GEN-P1 (T010): las rutas del plan exportadas a docs/api/openapi.json siguen el contrato de
specs/006-plan-de-generacion/contracts/generation-plans.openapi.yaml.

Compara las rutas (con los parámetros de ruta normalizados), los métodos, los `operationId`, los estados documentados
y, para cada esquema del contrato que la API publica con el mismo nombre, sus propiedades y campos obligatorios. La
ruta de GEN-P2 (`POST /generation-requests` con plan) queda fuera: llega en el siguiente PR.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = yaml.safe_load((ROOT / "specs/006-plan-de-generacion/contracts/generation-plans.openapi.yaml").read_text())
SPEC = json.loads((ROOT / "docs/api/openapi.json").read_text())
PREFIX = CONTRACT["servers"][0]["url"]  # /api/v1
METHODS = {"get", "post", "put", "patch", "delete"}
# FastAPI documenta 422 en toda ruta con parámetros (validación del cuerpo, la consulta o la ruta).
FRAMEWORK_STATUSES = {"422"}
SCHEMAS = ["CreateGenerationPlan", "RequestedType", "EditablePlanItem", "UpdateGenerationPlan", "PlanItem",
           "PlanInputs", "PlanFragment", "PlanEvidence", "Referent", "PreviousTypology", "PlanProblem",
           "PlanGenerator", "GenerationPlan"]


def _normalized(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{id}", path)


def _plan_operations(paths: dict, prefix: str = "") -> dict[tuple[str, str], dict]:
    return {
        (method, _normalized(prefix + path)): operation
        for path, item in paths.items()
        if "/generation-plans" in path
        for method, operation in item.items()
        if method in METHODS
    }


CONTRACT_OPERATIONS = _plan_operations(CONTRACT["paths"], PREFIX)
API_OPERATIONS = _plan_operations(SPEC["paths"])


def test_the_api_publishes_exactly_the_plan_routes_of_the_contract():
    assert set(API_OPERATIONS) == set(CONTRACT_OPERATIONS) and len(CONTRACT_OPERATIONS) == 5


@pytest.mark.parametrize("route", sorted(CONTRACT_OPERATIONS), ids=lambda r: f"{r[0]} {r[1]}")
def test_each_route_keeps_its_operation_id_tag_and_statuses(route):
    contract, api = CONTRACT_OPERATIONS[route], API_OPERATIONS[route]
    assert api["operationId"] == contract["operationId"]
    assert api["tags"] == contract["tags"] == ["generation-plans"]
    expected = set(contract["responses"])
    assert expected <= set(api["responses"])
    assert set(api["responses"]) - expected <= FRAMEWORK_STATUSES


def test_plan_creation_takes_the_idempotency_key_header_and_documents_retry_after():
    create = API_OPERATIONS[("post", "/api/v1/generation-plans")]
    [key] = [p for p in create["parameters"] if p["name"] == "Idempotency-Key"]
    assert key["in"] == "header" and "^[A-Za-z0-9_-]{8,128}$" in json.dumps(key["schema"])
    assert "Retry-After" in create["responses"]["429"]["headers"]
    listing = API_OPERATIONS[("get", "/api/v1/generation-plans")]
    names = {p["name"]: p for p in listing["parameters"]}
    assert {"unitId", "status", "limit"} <= set(names) and names["unitId"]["required"] is True


@pytest.mark.parametrize("name", SCHEMAS)
def test_each_schema_has_the_properties_and_required_fields_of_the_contract(name):
    contract = CONTRACT["components"]["schemas"][name]
    api = SPEC["components"]["schemas"][name]
    assert set(api["properties"]) == set(contract["properties"])
    assert set(api.get("required", [])) == set(contract.get("required", []))
    if contract.get("additionalProperties") is False:
        assert api.get("additionalProperties") is False  # los cuerpos rechazan campos desconocidos


def test_problem_codes_match_the_contract():
    problem = SPEC["components"]["schemas"]["PlanProblem"]["properties"]["code"]
    assert set(problem["enum"]) == set(CONTRACT["components"]["schemas"]["PlanProblem"]["properties"]["code"]["enum"])
