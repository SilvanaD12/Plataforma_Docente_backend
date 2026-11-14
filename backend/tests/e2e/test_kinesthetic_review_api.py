"""T059 (REV-01) por HTTP: la actividad kinestésica en Revisión.

Materiales, tiempo estimado y espacio no se contrastan con el material, pero entran en la huella (GEN-01, research
R11). Editar cualquiera de los tres en una actividad aprobada la devuelve a revisión (`reviewReset`), y quitarle pasos
respaldados la deja insuficiente con su motivo.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from tests.e2e.generation_flow import generate

CORPUS = Path(__file__).resolve().parents[2] / "evaluation" / "corpus" / "protocols.txt"
ACCOUNT = {"name": "Docente T059", "email": "t059@correo.pe", "password": "clave-segura-1"}


def _approved_activity(api: httpx.Client) -> tuple[dict[str, str], str, dict]:
    h = {"Authorization": "Bearer " + api.post("/api/v1/accounts", json=ACCOUNT).json()["token"]}
    unit = api.post("/api/v1/courses", headers=h, json={
        "code": "T059", "name": "Redes", "term": "2026-II",
        "units": [{"title": "Protocolos", "outcomes": [{"text": "Distingue TCP y UDP"}]}],
    }).json()["units"][0]
    context = {"unitId": unit["id"], "outcomeIds": [unit["outcomes"][0]["id"]],
               "documentType": "Separata o apuntes de clase", "usePermission": True}
    document = api.post("/api/v1/documents", headers=h, files={"file": ("protocols.txt", CORPUS.read_bytes())},
                        data={"context": json.dumps(context)}).json()
    assert api.post(f"/api/v1/documents/{document['id']}/process", headers=h).status_code == 200
    generated, [activity] = generate(api, h, unit["id"], "actividad_kinestesica", quantity=1,
                                     modalities=["Kinestésico"])
    assert generated["status"] == "succeeded", generated
    assert activity["type"] == "actividad_kinestesica" and activity["verification"]["status"] == "current"
    return h, unit["id"], activity


def _save(api: httpx.Client, h: dict, unit_id: str, resource: dict, **changes) -> httpx.Response:
    body = {"expectedVersion": resource["version"], "title": resource["title"], "body": resource["body"],
            "status": resource["status"], "discardReason": None, "edited": True,
            "structure": resource["structure"], **changes}
    return api.put(f"/api/v1/units/{unit_id}/resources/{resource['id']}", headers=h, json=body)


def test_editing_materials_time_or_space_sends_an_approved_activity_back_to_review(server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        h, unit_id, activity = _approved_activity(api)
        for field, value in [("materials", ["Pelotas de colores"]), ("estimatedMinutes", 45), ("space", "Patio")]:
            approved = _save(api, h, unit_id, activity, status="aprobado")
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "aprobado"
            edited = _save(api, h, unit_id, approved.json(), status="aprobado",
                           structure={**approved.json()["structure"], field: value})
            assert edited.status_code == 200, edited.text
            result = edited.json()
            assert result["status"] == "pendiente" and result["reviewReset"] is True, field
            assert result["structure"][field] == value
            assert result["verification"]["status"] == "current", field  # no se contrastan con el material
            activity = result


def test_an_edited_activity_without_three_supported_steps_is_insufficient(server: str):
    with httpx.Client(base_url=server, timeout=60) as api:
        h, unit_id, activity = _approved_activity(api)
        steps = activity["structure"]["guidedSteps"]
        invented = {"title": "Historia de ARPANET", "fragmentIds": steps[0]["fragmentIds"], "question": "",
                    "instruction": "Investiguen quién diseñó ARPANET en 1969 y en qué universidades se instaló."}
        edited = _save(api, h, unit_id, activity,
                       structure={**activity["structure"], "guidedSteps": [steps[0], steps[1], invented]})
        assert edited.status_code == 200, edited.text
        verification = edited.json()["verification"]
        assert verification["status"] == "insufficient" and "al menos 3 pasos" in verification["reason"]
        assert edited.json()["approvalBlockers"]
