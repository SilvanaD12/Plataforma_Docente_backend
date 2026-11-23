"""GEN-P1 (T010) por HTTP: el plan de generación como recurso propio (specs/006-plan-de-generacion).

Servidor real con el planificador por reglas. Cubre los escenarios V1, V2, V4, V5 y V8 de quickstart.md. «Usado» lo
deja GEN-P2 al generar; aquí se escribe en la base para probar `PLAN_ALREADY_USED`.
"""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text

from tests.e2e.test_generation_requests_api import TEACHER_A, TEACHER_B, _session
from tests.e2e.test_sequence_api import _unit_with_material

PLANS = "/api/v1/generation-plans"
BODY = {
    "instructions": "Diferencias entre TCP y UDP",
    "resourceTypes": [{"type": "item_opcion_multiple", "quantity": 1}, {"type": "pregunta_detonante"},
                      {"type": "explicacion", "quantity": 1}],
}


def _create(api: httpx.Client, headers: dict, unit_id: str, key: str | None = None, **changes) -> httpx.Response:
    return api.post(PLANS, headers={**headers, "Idempotency-Key": key or f"plan-{uuid4().hex}"},
                    json={**BODY, "unitId": unit_id, **changes})


def _editable(item: dict, **changes) -> dict:
    fields = {k: item[k] for k in ("resourceType", "quantity", "purpose", "covers", "fragmentIds")}
    return {**fields, **changes}


def _no_5e(response: httpx.Response) -> None:
    assert "5E" not in response.text, response.text


def test_create_returns_a_draft_plan_and_the_same_key_returns_it_again(server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        created = _create(api, headers, unit["id"], key="plan-clave-001")
        again = _create(api, headers, unit["id"], key="plan-clave-001")
        reused = _create(api, headers, unit["id"], key="plan-clave-001", audience="Otro público")
        listed = api.get(PLANS, headers=headers, params={"unitId": unit["id"]})
        read = api.get(f"{PLANS}/{created.json()['id']}", headers=headers)

    assert created.status_code == 201, created.text
    plan = created.json()
    assert (plan["status"], plan["version"], plan["origin"], plan["unitId"]) == ("draft", 1, "teacher", unit["id"])
    assert plan["generator"] == {"description": "Planificador por reglas (sin IA)", "usesAi": False,
                                 "fallback": False, "fallbackReason": None}
    assert [i["resourceType"] for i in plan["items"]] == ["pregunta_detonante", "explicacion", "item_opcion_multiple"]
    evidence_ids = {f["id"] for f in plan["evidence"]["fragments"]}
    for item in plan["items"]:
        assert item["covers"] and set(item["fragmentIds"]) <= evidence_ids and item["fragmentIds"]
        others = [c for other in plan["items"] if other is not item for c in other["covers"]]
        assert item["doesNotCover"] == others
    assert plan["referents"] == [] and plan["sessionContext"] == {"previousTypologies": []}
    assert plan["validation"] == {"valid": True, "problems": []} and plan["warnings"] == []
    assert plan["inputs"]["resourceTypes"][1] == {"type": "pregunta_detonante", "quantity": None}
    _no_5e(created)

    assert again.status_code == 200 and again.json()["id"] == plan["id"]
    assert reused.status_code == 409 and reused.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert listed.status_code == 200 and [p["id"] for p in listed.json()] == [plan["id"]]
    assert read.status_code == 200 and read.json() == plan


def test_a_plan_of_another_teacher_is_not_found(server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        owner = _session(api, TEACHER_A)
        unit = _unit_with_material(api, owner)
        plan = _create(api, owner, unit["id"]).json()
        other = _session(api, TEACHER_B)
        url = f"{PLANS}/{plan['id']}"
        answers = [
            api.get(url, headers=other),
            api.put(url, headers=other, json={"expectedVersion": 1, "items": []}),
            api.post(f"{url}/approve", headers=other, json={"expectedVersion": 1}),
            api.get(f"{PLANS}/gen-plan-no-existe", headers=owner),
        ]
        foreign_unit = api.get(PLANS, headers=other, params={"unitId": unit["id"]})
        foreign_create = _create(api, other, unit["id"])

    assert all(r.status_code == 404 and r.json()["error"]["code"] == "PLAN_NOT_FOUND" for r in answers)
    assert len({json.dumps(r.json()) for r in answers}) == 1  # ajeno e inexistente responden igual
    assert foreign_unit.status_code == 404 and foreign_create.status_code == 404
    assert foreign_create.json()["error"]["code"] == "UNIT_NOT_FOUND"


def test_editing_saves_an_invalid_draft_and_approving_needs_a_valid_plan_and_the_current_version(server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        plan = _create(api, headers, unit["id"]).json()
        url = f"{PLANS}/{plan['id']}"
        first, second, third = plan["items"]

        # V4 (a): mover un concepto de un ítem a otro.
        moved = api.put(url, headers=headers, json={"expectedVersion": 1, "items": [
            _editable(first, covers=first["covers"] + [second["covers"][0]]),
            _editable(second, covers=second["covers"][1:] or ["Otro concepto"]),
            _editable(third),
        ]})
        # V4 (b): un concepto repetido y un ítem sin fragmentos: se guarda igual.
        broken = api.put(url, headers=headers, json={"expectedVersion": 2, "items": [
            _editable(first, covers=["Concepto compartido"], quantity=1),
            _editable(second, covers=["concepto  compartido"], fragmentIds=[], quantity=1),
            _editable(third),
        ]})
        stale = api.put(url, headers=headers, json={"expectedVersion": 1, "items": [_editable(first)]})
        old_approve = api.post(f"{url}/approve", headers=headers, json={"expectedVersion": 1})
        invalid_approve = api.post(f"{url}/approve", headers=headers, json={"expectedVersion": 3})
        fixed = api.put(url, headers=headers, json={"expectedVersion": 3, "items": [_editable(i) for i in plan["items"]]})
        approved = api.post(f"{url}/approve", headers=headers, json={"expectedVersion": 4})
        approved_again = api.post(f"{url}/approve", headers=headers, json={"expectedVersion": 4})
        back_to_draft = api.put(url, headers=headers, json={"expectedVersion": 4,
                                                            "items": [_editable(i) for i in plan["items"]]})

    assert moved.status_code == 200 and moved.json()["version"] == 2 and moved.json()["status"] == "draft"
    assert second["covers"][0] in moved.json()["items"][0]["covers"]
    assert second["covers"][0] in moved.json()["items"][1]["doesNotCover"]

    assert broken.status_code == 200 and broken.json()["version"] == 3
    validation = broken.json()["validation"]
    assert validation["valid"] is False
    assert {(p["code"], p["itemPosition"]) for p in validation["problems"]} == {
        ("CONCEPT_OWNED_TWICE", 2), ("ITEM_WITHOUT_EVIDENCE", 2),
    }
    _no_5e(broken)

    for conflict in (stale, old_approve):
        assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "PLAN_VERSION_CONFLICT"
    assert invalid_approve.status_code == 422 and invalid_approve.json()["error"]["code"] == "PLAN_INVALID"
    assert {d["code"] for d in invalid_approve.json()["error"]["details"]} == {
        "CONCEPT_OWNED_TWICE", "ITEM_WITHOUT_EVIDENCE",
    }
    _no_5e(invalid_approve)

    assert fixed.status_code == 200 and fixed.json()["validation"]["valid"] is True
    assert approved.status_code == 200 and approved.json()["status"] == "approved" and approved.json()["approvedAt"]
    assert approved_again.status_code == 200 and approved_again.json() == approved.json()
    assert back_to_draft.json()["status"] == "draft" and back_to_draft.json()["version"] == 5


def test_a_used_plan_cannot_be_edited_or_approved(server: str, e2e_database_url: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        plan = _create(api, headers, unit["id"]).json()
        url = f"{PLANS}/{plan['id']}"
        assert api.post(f"{url}/approve", headers=headers, json={"expectedVersion": 1}).status_code == 200

        # GEN-P2 marca el plan como usado al generar; aquí se escribe directamente en la base.
        engine = create_engine(e2e_database_url)
        with engine.begin() as connection:
            connection.execute(text("UPDATE gen_generation_plans SET status = 'used', used_by_request_id = 'gen-req-x' "
                                    "WHERE id = :id"), {"id": plan["id"]})
        engine.dispose()

        edit = api.put(url, headers=headers, json={"expectedVersion": 1,
                                                   "items": [_editable(i) for i in plan["items"]]})
        approve = api.post(f"{url}/approve", headers=headers, json={"expectedVersion": 1})
        read = api.get(url, headers=headers)

    for answer in (edit, approve):
        assert answer.status_code == 409 and answer.json()["error"]["code"] == "PLAN_ALREADY_USED"
    assert read.json()["status"] == "used" and read.json()["usedByRequestId"] == "gen-req-x"


def test_a_topic_the_material_does_not_cover_creates_no_plan(server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        answer = _create(api, headers, unit["id"],
                         instructions="¿Cómo se estructuran las tablas y llaves primarias en un modelo relacional?")
        listed = api.get(PLANS, headers=headers, params={"unitId": unit["id"]})

    assert answer.status_code == 422 and answer.json()["error"]["code"] == "INSUFFICIENT_EVIDENCE"
    assert "llaves primarias, modelo relacional" in answer.json()["error"]["message"]
    assert listed.json() == []
    _no_5e(answer)


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"resourceTypes": [{"type": "tipo_inexistente"}]}, "INVALID_PARAMETERS"),
        ({"resourceTypes": [{"type": "glosario"}, {"type": "glosario"}]}, "INVALID_PARAMETERS"),
        ({"modality": "Textual", "resourceTypes": [{"type": "imagen_ilustrativa"}]}, "RESOURCE_TYPE_NOT_IN_MODALITY"),
        ({"resourceTypes": [{"type": "glosario", "quantity": 6}]}, "INVALID_PARAMETERS"),
    ],
    ids=["tipo-inexistente", "tipo-repetido", "fuera-de-modalidad", "cantidad"],
)
def test_invalid_inputs_create_no_plan(server: str, changes, code):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        answer = _create(api, headers, unit["id"], **changes)
    assert answer.status_code == 422 and answer.json()["error"]["code"] == code, answer.text
    _no_5e(answer)


def test_the_idempotency_key_is_required(server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        answer = api.post(PLANS, headers=headers, json={**BODY, "unitId": unit["id"]})
    assert answer.status_code == 400 and answer.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


def test_deleting_the_course_deletes_its_plans(server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        plan = _create(api, headers, unit["id"]).json()
        [course] = [c for c in api.get("/api/v1/courses", headers=headers).json()
                    if unit["id"] in {u["id"] for u in c["units"]}]
        deleted = api.delete(f"/api/v1/courses/{course['id']}", headers=headers)
        read = api.get(f"{PLANS}/{plan['id']}", headers=headers)
    assert deleted.status_code in (200, 204), deleted.text
    assert read.status_code == 404 and read.json()["error"]["code"] == "PLAN_NOT_FOUND"
