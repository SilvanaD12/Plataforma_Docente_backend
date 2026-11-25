"""QA-17: cuerpos y configuración del locustfile (backend/performance/locust/payloads.py), sin Locust ni red."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PAYLOADS = Path(__file__).resolve().parents[2] / "performance" / "locust" / "payloads.py"


@pytest.fixture(scope="module")
def payloads():
    spec = importlib.util.spec_from_file_location("locust_payloads", PAYLOADS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # las dataclasses buscan su módulo en sys.modules
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    yield module
    sys.modules.pop(spec.name, None)


def test_the_default_profile_waits_one_to_three_seconds_with_the_default_weights(payloads):
    settings = payloads.load_settings({})
    assert (settings.profile, settings.wait_min, settings.wait_max) == ("steady", 1.0, 3.0)
    assert (settings.weight_courses, settings.weight_search, settings.weight_generation) == (3, 3, 1)
    assert settings.health_weight == 0 and settings.resource_types == ("explicacion",)
    assert settings.corpus.name == "protocols.txt" and settings.corpus.exists()


def test_the_burst_profile_has_no_wait_and_a_health_user(payloads):
    settings = payloads.load_settings({"LOCUST_PROFILE": "burst"})
    assert (settings.wait_min, settings.wait_max, settings.health_weight) == (0.0, 0.0, 1)


def test_settings_come_from_the_environment_and_bad_values_keep_the_defaults(payloads):
    settings = payloads.load_settings({
        "LOCUST_PROFILE": "otro", "LOCUST_WAIT_MIN": "2", "LOCUST_WAIT_MAX": "1", "LOCUST_WEIGHT_SEARCH": "0",
        "LOCUST_WEIGHT_GENERATION": "mucho", "LOCUST_RESOURCE_TYPES": "pregunta_detonante, explicacion",
        "LOCUST_POLL_SECONDS": "-1",
    })
    assert settings.profile == "steady" and (settings.wait_min, settings.wait_max) == (2.0, 2.0)
    assert settings.weight_search == 0 and settings.weight_generation == 1
    assert settings.resource_types == ("pregunta_detonante", "explicacion") and settings.poll_seconds == 1.0


def test_every_virtual_user_gets_its_own_email(payloads):
    emails = {payloads.unique_email("correo.pe") for _ in range(50)}
    assert len(emails) == 50 and all(e.startswith("locust.") and e.endswith("@correo.pe") for e in emails)


def test_the_bodies_follow_collect_samples(payloads):
    course = payloads.course_body()
    assert course["units"] == [{"title": "Protocolos de transporte",
                                "outcomes": [{"text": "Distingue TCP, UDP e IP según su función"}]}]
    unit = {"id": "u1", "outcomes": [{"id": "ra-1"}]}
    assert json.loads(payloads.document_context(unit)) == {
        "unitId": "u1", "outcomeIds": ["ra-1"], "documentType": "Separata o apuntes de clase",
        "suggestedStage": None, "usePermission": True,
    }
    # T021: el pedido parte de un plan aprobado, con un recurso por tipo como el cuerpo anterior.
    assert payloads.plan_body("u1", ("explicacion",)) == {
        "unitId": "u1", "resourceTypes": [{"type": "explicacion", "quantity": 1}],
    }
    assert [t["type"] for t in payloads.plan_body("u1", ("pregunta_detonante", "explicacion"))["resourceTypes"]] == [
        "pregunta_detonante", "explicacion"]
    assert payloads.planned_generation_body({"id": "gen-plan-1", "version": 1, "status": "approved"}) == {
        "planId": "gen-plan-1", "planVersion": 1}
    assert payloads.search_params("protocolo TCP", "u1") == {"query": "protocolo TCP", "unitId": "u1", "topK": 8}


def test_retry_after_and_error_codes(payloads):
    assert payloads.retry_after_seconds({"Retry-After": "7"}) == 7.0
    assert payloads.retry_after_seconds({}) == 5.0 and payloads.retry_after_seconds({"Retry-After": "x"}) == 5.0
    assert payloads.error_code({"error": {"code": "TOO_MANY_ACTIVE_REQUESTS"}}) == payloads.TOO_MANY_ACTIVE_REQUESTS
    assert payloads.error_code([]) is None and payloads.error_code(None) is None
