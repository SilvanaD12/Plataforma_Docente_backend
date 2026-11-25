"""GEN-P2 por HTTP: el pedido de generación parte del plan aprobado (specs/006-plan-de-generacion, quickstart V6, V7
y V12). Servidor real con el planificador y el generador por reglas: sin proveedores de IA.
"""

from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from tests.e2e.generation_flow import wait_until_final
from tests.e2e.test_generation_requests_api import TEACHER_A, _session
from tests.e2e.test_sequence_api import _unit_with_material

PLANS = "/api/v1/generation-plans"
REQUESTS = "/api/v1/generation-requests"
PLAN_BODY = {
    "instructions": "Diferencias entre TCP y UDP",
    "resourceTypes": [{"type": "pregunta_detonante", "quantity": 1}, {"type": "explicacion", "quantity": 2}],
}


def _approved_plan(api: httpx.Client, headers: dict, unit_id: str) -> dict:
    created = api.post(PLANS, headers={**headers, "Idempotency-Key": f"plan-{uuid4().hex}"},
                       json={**PLAN_BODY, "unitId": unit_id})
    assert created.status_code == 201, created.text
    plan = created.json()
    assert plan["validation"]["valid"], plan["validation"]
    approved = api.post(f"{PLANS}/{plan['id']}/approve", headers=headers, json={"expectedVersion": plan["version"]})
    assert approved.status_code == 200, approved.text
    return approved.json()


def _generate(api: httpx.Client, headers: dict, body: dict, key: str | None = None) -> httpx.Response:
    return api.post(REQUESTS, headers={**headers, "Idempotency-Key": key or f"gen-{uuid4().hex}"}, json=body)


def test_an_approved_plan_generates_one_resource_per_block_and_becomes_used(server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        plan = _approved_plan(api, headers, unit["id"])
        body = {"planId": plan["id"], "planVersion": plan["version"]}
        started = _generate(api, headers, body, key="gen-desde-plan-01")
        again = _generate(api, headers, body, key="gen-desde-plan-01")
        reused = _generate(api, headers, body)
        final = wait_until_final(api, headers, started.json()["id"])
        stored_plan = api.get(f"{PLANS}/{plan['id']}", headers=headers).json()
        resources = {r["id"]: r for r in api.get(f"/api/v1/units/{unit['id']}/resources", headers=headers).json()}

    assert started.status_code == 202, started.text
    request = started.json()
    assert (request["planId"], request["planVersion"], request["mode"]) == (plan["id"], plan["version"], "sequence")
    assert [(s["resourceType"], s["planItemPosition"]) for s in request["steps"]] == [
        (item["resourceType"], item["position"]) for item in plan["items"]]
    assert again.status_code == 200 and again.json()["id"] == request["id"]
    assert reused.status_code == 409 and reused.json()["error"]["code"] == "PLAN_ALREADY_USED"
    assert stored_plan["status"] == "used" and stored_plan["usedByRequestId"] == request["id"]

    assert final["status"] == "succeeded", final
    assert all(step["planWarnings"] == [] for step in final["steps"])  # con reglas no hay avisos: se rechaza
    quantities = {item["position"]: item["quantity"] for item in plan["items"]}
    for step in final["steps"]:
        assert len(step["resourceIds"]) == quantities[step["planItemPosition"]], step
        blocks = [resources[rid]["params"]["planBlock"] for rid in step["resourceIds"]]
        assert blocks == list(range(quantities[step["planItemPosition"]]))
        for rid in step["resourceIds"]:
            params = resources[rid]["params"]
            assert (params["planId"], params["planItemPosition"]) == (plan["id"], step["planItemPosition"])
    plan_fragments = {f["id"] for f in plan["evidence"]["fragments"]}
    cited = {fid for rid in resources for c in resources[rid]["citations"] for fid in c["fragmentIds"]}
    assert cited <= plan_fragments


def test_a_draft_or_outdated_plan_is_rejected(server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        draft = api.post(PLANS, headers={**headers, "Idempotency-Key": f"plan-{uuid4().hex}"},
                         json={**PLAN_BODY, "unitId": unit["id"]}).json()
        not_approved = _generate(api, headers, {"planId": draft["id"], "planVersion": 1})
        outdated = _generate(api, headers, {"planId": draft["id"], "planVersion": 7})
        missing = _generate(api, headers, {"planId": "gen-plan-no-existe", "planVersion": 1})
        listed = api.get(REQUESTS, headers=headers, params={"unitId": unit["id"]})

    assert not_approved.status_code == 422 and not_approved.json()["error"]["code"] == "PLAN_NOT_APPROVED"
    assert outdated.status_code == 409 and outdated.json()["error"]["code"] == "PLAN_VERSION_CONFLICT"
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "PLAN_NOT_FOUND"
    assert listed.json() == []


def test_stale_evidence_answers_409_with_each_document_and_keeps_the_plan_approved(server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        plan = _approved_plan(api, headers, unit["id"])
        [document] = [d for d in api.get("/api/v1/documents", headers=headers).json() if d["unitId"] == unit["id"]]
        # Volver a procesar el documento da ids nuevos a sus fragmentos: los del plan dejan de existir.
        assert api.post(f"/api/v1/documents/{document['id']}/process", headers=headers).status_code == 200
        stale = _generate(api, headers, {"planId": plan["id"], "planVersion": plan["version"]})
        after = api.get(f"{PLANS}/{plan['id']}", headers=headers).json()
        listed = api.get(REQUESTS, headers=headers, params={"unitId": unit["id"]})

    assert stale.status_code == 409, stale.text
    error = stale.json()["error"]
    cited = sorted({fid for item in plan["items"] for fid in item["fragmentIds"]})
    assert error["code"] == "PLAN_EVIDENCE_STALE" and "5E" not in error["message"]
    assert error["details"] == [{"documentId": document["id"], "documentName": document["fileName"],
                                 "missingFragmentIds": [f["id"] for f in plan["evidence"]["fragments"]
                                                        if f["id"] in cited]}]
    assert after["status"] == "approved" and listed.json() == []


@pytest.mark.usefixtures("legacy_body")  # T021: el cuerpo anterior solo con GENERATION_REQUIRE_PLAN=false
def test_the_previous_body_generates_from_an_implicit_plan(server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        started = _generate(api, headers, {"mode": "sequence", "unitId": unit["id"], "quantity": 1,
                                           "resourceTypes": ["explicacion", "pregunta_detonante"],
                                           "instructions": "Diferencias entre TCP y UDP"})
        final = wait_until_final(api, headers, started.json()["id"])
        [plan] = api.get(PLANS, headers=headers, params={"unitId": unit["id"]}).json()

    assert started.status_code == 202, started.text
    assert plan["origin"] == "implicit" and plan["status"] == "used"
    assert started.json()["planId"] == plan["id"] and plan["usedByRequestId"] == started.json()["id"]
    assert [s["planItemPosition"] for s in final["steps"]] == [item["position"] for item in plan["items"]]
    assert final["status"] == "succeeded", final


@pytest.fixture
def plan_required(monkeypatch):
    """El servidor de la prueba arranca con GENERATION_REQUIRE_PLAN=true (se pide antes que `server`)."""
    monkeypatch.setenv("GENERATION_REQUIRE_PLAN", "true")


def test_with_require_plan_the_previous_body_is_rejected_and_a_plan_still_works(plan_required, server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        old = _generate(api, headers, {"mode": "individual", "unitId": unit["id"],
                                       "resourceTypes": ["explicacion"]})
        plan = _approved_plan(api, headers, unit["id"])
        planned = _generate(api, headers, {"planId": plan["id"], "planVersion": plan["version"]})

    assert old.status_code == 422 and old.json()["error"]["code"] == "PLAN_REQUIRED"
    assert "5E" not in old.json()["error"]["message"]
    assert planned.status_code == 202, planned.text


def test_review_regenerates_a_planned_resource_from_its_item_without_writing_the_plan(server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        plan = _approved_plan(api, headers, unit["id"])
        started = _generate(api, headers, {"planId": plan["id"], "planVersion": plan["version"]})
        final = wait_until_final(api, headers, started.json()["id"])
        used = api.get(f"{PLANS}/{plan['id']}", headers=headers).json()
        resource_id = final["steps"][-1]["resourceIds"][-1]
        resource = next(r for r in api.get(f"/api/v1/units/{unit['id']}/resources", headers=headers).json()
                        if r["id"] == resource_id)
        regenerated = api.post(f"/api/v1/units/{unit['id']}/resources/{resource_id}/regenerations",
                               headers=headers, json={"expectedVersion": resource["version"]})
        after = api.get(f"{PLANS}/{plan['id']}", headers=headers).json()
        requests = api.get(REQUESTS, headers=headers, params={"unitId": unit["id"]}).json()
        regeneration = next(r for r in requests if r["mode"] == "regeneration")
        detail = wait_until_final(api, headers, regeneration["id"])

    assert regenerated.status_code == 200, regenerated.text
    assert regenerated.json()["status"] in ("succeeded", "running"), regenerated.json()
    assert after == used  # regenerar no escribe el plan: ni estado, ni versión, ni usedByRequestId
    assert detail["planId"] == plan["id"] and detail["status"] == "succeeded", detail
    assert detail["regeneration"]["planBlock"] == resource["params"]["planBlock"]
    assert [s["planItemPosition"] for s in detail["steps"]] == [resource["params"]["planItemPosition"]]


@pytest.fixture
def implicit_plan_off(monkeypatch):
    """Servidor con GENERATION_IMPLICIT_PLAN=false: solo para medir la línea base de P4 (se pide antes que `server`)."""
    monkeypatch.setenv("GENERATION_IMPLICIT_PLAN", "false")


@pytest.mark.usefixtures("legacy_body")
def test_with_the_implicit_plan_off_the_previous_body_has_no_plan(implicit_plan_off, server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        started = _generate(api, headers, {"mode": "sequence", "unitId": unit["id"], "quantity": 1,
                                           "resourceTypes": ["explicacion", "pregunta_detonante"],
                                           "instructions": "Diferencias entre TCP y UDP"})
        final = wait_until_final(api, headers, started.json()["id"])
        plans = api.get(PLANS, headers=headers, params={"unitId": unit["id"]}).json()
        resources = api.get(f"/api/v1/units/{unit['id']}/resources", headers=headers).json()
        planned = _generate(api, headers, {"planId": _approved_plan(api, headers, unit["id"])["id"], "planVersion": 1})

    assert started.status_code == 202 and started.json()["planId"] is None and plans == []
    assert final["status"] == "succeeded" and all(s["planItemPosition"] is None for s in final["steps"])
    assert resources and all("planId" not in r["params"] for r in resources)
    assert planned.status_code == 202  # un plan aprobado sigue funcionando


def test_require_plan_wins_over_the_implicit_plan_switch(implicit_plan_off, plan_required, server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        old = _generate(api, headers, {"mode": "individual", "unitId": unit["id"], "resourceTypes": ["explicacion"]})

    assert old.status_code == 422 and old.json()["error"]["code"] == "PLAN_REQUIRED"

def test_cur_p2_catalog_type_generates_from_an_approved_plan(server: str):
    resource_type = "resumen_ideas_clave"
    with httpx.Client(base_url=server, timeout=60) as api:
        response = api.get("/api/v1/resource-types")
        assert response.status_code == 200, response.text
        [entry] = [item for item in response.json() if item["id"] == resource_type]
        assert (entry["stage"], entry["format"], entry["modalities"]) == (
            "explain", "text", ["Textual"],
        )

        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        created = api.post(
            PLANS,
            headers={**headers, "Idempotency-Key": f"plan-{uuid4().hex}"},
            json={
                "unitId": unit["id"],
                "instructions": "Diferencias entre TCP y UDP",
                "modality": "Textual",
                "resourceTypes": [{"type": resource_type, "quantity": 1}],
            },
        )
        assert created.status_code == 201, created.text
        plan = created.json()
        assert plan["validation"]["valid"], plan["validation"]
        assert [item["resourceType"] for item in plan["items"]] == [resource_type]

        approved = api.post(
            f"{PLANS}/{plan['id']}/approve",
            headers=headers,
            json={"expectedVersion": plan["version"]},
        )
        assert approved.status_code == 200, approved.text
        started = _generate(
            api, headers, {"planId": plan["id"], "planVersion": approved.json()["version"]},
        )
        assert started.status_code == 202, started.text
        final = wait_until_final(api, headers, started.json()["id"])
        assert final["status"] == "succeeded", final
        [step] = final["steps"]
        [resource_id] = step["resourceIds"]

        saved = api.get(f"/api/v1/units/{unit['id']}/resources", headers=headers)
        assert saved.status_code == 200, saved.text
        [resource] = [item for item in saved.json() if item["id"] == resource_id]
        assert (resource["type"], resource["format"]) == (resource_type, "text")
        assert resource["citations"], resource


# T021 · GENERATION_REQUIRE_PLAN=true por defecto (sin variable en el servidor de la prueba)


def test_by_default_the_previous_body_is_rejected_with_plan_required(server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        old = _generate(api, headers, {"mode": "sequence", "unitId": unit["id"],
                                       "resourceTypes": ["pregunta_detonante", "explicacion"]})
        requests = api.get(REQUESTS, headers=headers, params={"unitId": unit["id"]}).json()
        plans = api.get(PLANS, headers=headers, params={"unitId": unit["id"]})

    assert old.status_code == 422 and old.json()["error"]["code"] == "PLAN_REQUIRED"
    assert "5E" not in old.json()["error"]["message"]
    assert requests == []  # ni pedido ni plan implícito
    assert plans.status_code == 200 and plans.json() == []


def test_by_default_a_resource_from_a_plan_can_still_be_regenerated_from_review(server: str):
    """La regeneración no es un pedido nuevo del docente: rehace un recurso con sus datos guardados y, si nació de un
    plan, con el ítem de ese plan (sin escribirlo). No necesita un plan aprobado nuevo."""
    with httpx.Client(base_url=server, timeout=90) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        plan = _approved_plan(api, headers, unit["id"])
        started = _generate(api, headers, {"planId": plan["id"], "planVersion": plan["version"]})
        final = wait_until_final(api, headers, started.json()["id"])
        resources = {r["id"]: r for r in api.get(f"/api/v1/units/{unit['id']}/resources", headers=headers).json()}
        previous = resources[final["steps"][-1]["resourceIds"][0]]
        url = f"/api/v1/units/{unit['id']}/resources/{previous['id']}"
        regenerated = api.post(f"{url}/regenerations", headers=headers, json={"expectedVersion": previous["version"]})
        after = {r["id"]: r for r in api.get(f"/api/v1/units/{unit['id']}/resources", headers=headers).json()}

    assert final["status"] == "succeeded", final
    assert regenerated.status_code == 200, regenerated.text
    body = regenerated.json()
    assert body["status"] == "succeeded" and body["previousDiscarded"] is True
    [new_id] = body["newResourceIds"]
    assert after[new_id]["regeneratedFrom"] == {"resourceId": previous["id"], "version": previous["version"]}
    assert after[new_id]["params"]["planId"] == plan["id"]  # el ítem del plan, leído sin escribirlo
