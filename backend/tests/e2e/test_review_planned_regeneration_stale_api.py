"""T014 · Prueba E2E de regeneración desde Revisión con plan cuya evidencia cambió (V12).

Servidor real con LLM_PROVIDER=rules:
1. Crea una unidad con dos documentos procesados.
2. Crea y aprueba un plan de generación.
3. Genera los recursos del plan.
4. Con documentos intactos, regenera un recurso del plan ya usado: responde 200 (sin PLAN_ALREADY_USED) y
   el plan conserva su status ('used'), version y usedByRequestId.
5. Borra un documento del que dependen fragmentos del ítem del plan, conservando el otro documento procesado.
6. Pide la regeneración desde Revisión: responde 409 PLAN_EVIDENCE_STALE con el details de StaleDocument
   (documentId, documentName, missingFragmentIds).
7. El recurso previo en Revisión conserva su versión, estado y contenido intactos.
8. El plan no se modifica.
"""

from __future__ import annotations

import json
from uuid import uuid4

import httpx

from tests.e2e.generation_flow import wait_until_final
from tests.e2e.test_generation_requests_api import TEACHER_A, _session
from tests.e2e.test_sequence_api import _unit_with_material

PLANS = "/api/v1/generation-plans"
REQUESTS = "/api/v1/generation-requests"
PLAN_BODY = {
    "instructions": "Diferencias entre TCP y UDP",
    "resourceTypes": [{"type": "pregunta_detonante", "quantity": 1}, {"type": "explicacion", "quantity": 2}],
}


def _unit_with_two_documents(api: httpx.Client, headers: dict[str, str]) -> tuple[dict, dict, dict]:
    unit = _unit_with_material(api, headers)
    context = {
        "unitId": unit["id"],
        "outcomeIds": [unit["outcomes"][0]["id"]],
        "documentType": "Separata o apuntes de clase",
        "suggestedStage": None,
        "usePermission": True,
    }
    doc2 = api.post(
        "/api/v1/documents",
        headers=headers,
        files={"file": ("redes_avanzadas.txt", "UDP no garantiza la entrega ni el orden de llegada.")},
        data={"context": json.dumps(context)},
    ).json()
    assert api.post(f"/api/v1/documents/{doc2['id']}/process", headers=headers).json()["status"] == "procesado"
    docs = [d for d in api.get("/api/v1/documents", headers=headers).json() if d["unitId"] == unit["id"]]
    doc1 = next(d for d in docs if d["id"] != doc2["id"])
    return unit, doc1, doc2


def _approved_plan(api: httpx.Client, headers: dict, unit_id: str) -> dict:
    created = api.post(
        PLANS,
        headers={**headers, "Idempotency-Key": f"plan-{uuid4().hex}"},
        json={**PLAN_BODY, "unitId": unit_id},
    )
    assert created.status_code == 201, created.text
    plan = created.json()
    assert plan["validation"]["valid"], plan["validation"]
    approved = api.post(
        f"{PLANS}/{plan['id']}/approve", headers=headers, json={"expectedVersion": plan["version"]}
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def _generate(api: httpx.Client, headers: dict, body: dict) -> httpx.Response:
    return api.post(REQUESTS, headers={**headers, "Idempotency-Key": f"gen-{uuid4().hex}"}, json=body)


def test_review_regeneration_with_stale_plan_evidence_answers_409_and_keeps_resource_and_plan(server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit, doc1, doc2 = _unit_with_two_documents(api, headers)
        plan = _approved_plan(api, headers, unit["id"])

        # Genera los recursos desde el plan
        started = _generate(api, headers, {"planId": plan["id"], "planVersion": plan["version"]})
        assert started.status_code == 202, started.text
        final = wait_until_final(api, headers, started.json()["id"])
        assert final["status"] == "succeeded", final

        used_plan = api.get(f"{PLANS}/{plan['id']}", headers=headers).json()
        assert used_plan["status"] == "used"
        assert used_plan["usedByRequestId"] == started.json()["id"]

        resources_initial = {
            r["id"]: r for r in api.get(f"/api/v1/units/{unit['id']}/resources", headers=headers).json()
        }

        # 1. Con documentos intactos, regenerar un recurso de un plan 'used' funciona (sin PLAN_ALREADY_USED)
        resource_intact_id = final["steps"][0]["resourceIds"][0]
        resource_intact = resources_initial[resource_intact_id]
        regen_ok = api.post(
            f"/api/v1/units/{unit['id']}/resources/{resource_intact_id}/regenerations",
            headers=headers,
            json={"expectedVersion": resource_intact["version"]},
        )
        assert regen_ok.status_code == 200, regen_ok.text
        assert regen_ok.json()["status"] in ("succeeded", "running"), regen_ok.json()

        # El plan conserva su status ('used'), su version y su usedByRequestId intactos
        plan_after_regen_ok = api.get(f"{PLANS}/{plan['id']}", headers=headers).json()
        assert plan_after_regen_ok["status"] == used_plan["status"] == "used"
        assert plan_after_regen_ok["version"] == used_plan["version"]
        assert plan_after_regen_ok["usedByRequestId"] == used_plan["usedByRequestId"]

        # Identificar qué documento cita el ítem del segundo recurso
        resource_stale_id = final["steps"][1]["resourceIds"][0]
        resource_stale_before = resources_initial[resource_stale_id]
        item_pos = resource_stale_before["params"]["planItemPosition"]
        plan_item = next(item for item in plan["items"] if item["position"] == item_pos)
        item_fragments = set(plan_item["fragmentIds"])
        doc_cited_id = next(
            f["documentId"] for f in plan["evidence"]["fragments"] if f["id"] in item_fragments
        )

        # 2. Borrar el documento que cita este ítem (la unidad conserva el otro documento procesado)
        del_resp = api.delete(f"/api/v1/documents/{doc_cited_id}", headers=headers)
        assert del_resp.status_code == 204, del_resp.text

        # 3. Pide la regeneración desde Revisión del recurso cuyo ítem cita fragmentos del documento borrado
        stale_response = api.post(
            f"/api/v1/units/{unit['id']}/resources/{resource_stale_id}/regenerations",
            headers=headers,
            json={"expectedVersion": resource_stale_before["version"]},
        )

        assert stale_response.status_code == 409, stale_response.text
        error = stale_response.json()["error"]
        assert error["code"] == "PLAN_EVIDENCE_STALE"
        assert "5E" not in error["message"]

        # Comprueba que details cumple el esquema StaleDocument (documentId, documentName, missingFragmentIds)
        details = error["details"]
        assert isinstance(details, list) and len(details) >= 1
        matched_doc = next((d for d in details if d["documentId"] == doc_cited_id), None)
        assert matched_doc is not None, f"Documento borrado {doc_cited_id} no figura en details: {details}"
        assert matched_doc["documentName"]
        assert isinstance(matched_doc["missingFragmentIds"], list)
        assert len(matched_doc["missingFragmentIds"]) >= 1

        # 4. El recurso anterior queda exactamente igual (misma versión, contenido y estado)
        resources_after = {
            r["id"]: r for r in api.get(f"/api/v1/units/{unit['id']}/resources", headers=headers).json()
        }
        resource_stale_after = resources_after[resource_stale_id]
        assert resource_stale_after["version"] == resource_stale_before["version"]
        assert resource_stale_after["body"] == resource_stale_before["body"]
        assert resource_stale_after["status"] == resource_stale_before["status"]
        assert resource_stale_after["title"] == resource_stale_before["title"]

        # 5. El plan no cambia su estado ni versión
        plan_after_stale = api.get(f"{PLANS}/{plan['id']}", headers=headers).json()
        assert plan_after_stale["status"] == "used"
        assert plan_after_stale["version"] == used_plan["version"]
        assert plan_after_stale["usedByRequestId"] == used_plan["usedByRequestId"]
