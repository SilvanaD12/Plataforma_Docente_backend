"""Recorrido por HTTP de una cuenta nueva: curso, material, generación, revisión guardada, descargas y borrado."""

from __future__ import annotations

import json

import httpx

MATERIAL = (
    "Unidad 1: Protocolos de transporte\n\n"
    "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable de los datos. "
    "El protocolo UDP no establece conexión ni confirma la entrega; por eso es más rápido.\n\n"
    "El protocolo IP se encarga del direccionamiento y del enrutamiento de los paquetes. "
    "El enrutador es el dispositivo que decide el camino de cada paquete hasta su destino. "
    "La encapsulación es el proceso por el cual cada capa agrega su propio encabezado a los datos."
).encode()
ACCOUNT = {"name": "Ana Pérez", "email": "ana.perez@correo.pe", "password": "clave-segura-1"}


def test_new_account_reviews_downloads_and_deletes_its_course(server: str):
    with httpx.Client(base_url=server, timeout=30) as api:
        created = api.post("/api/v1/accounts", json=ACCOUNT)
        assert created.status_code == 201 and created.json()["name"] == "Ana Pérez"
        h = {"Authorization": "Bearer " + created.json()["token"]}
        assert api.post("/api/v1/accounts", json=ACCOUNT).status_code == 409
        assert (
            api.post("/api/v1/accounts", json={**ACCOUNT, "email": "otra@correo.pe", "password": "corta"}).status_code
            == 422
        )
        assert api.get("/api/v1/sessions/current", headers=h).json() == {
            "email": "ana.perez@correo.pe",
            "name": "Ana Pérez",
        }
        assert api.get("/api/v1/courses", headers=h).json() == []
        assert (
            api.post(
                "/api/v1/sessions",
                json={"email": "ANA.PEREZ@correo.pe", "password": "clave-segura-1"},
            ).status_code
            == 200
        )

        course = api.post(
            "/api/v1/courses",
            headers=h,
            json={
                "code": "RED-301",
                "name": "Redes",
                "term": "2026-II",
                "units": [{"title": "Protocolos", "outcomes": [{"text": "Distingue TCP y UDP"}]}],
            },
        ).json()
        unit = course["units"][0]
        context = {
            "unitId": unit["id"],
            "outcomeIds": [unit["outcomes"][0]["id"]],
            "documentType": "Separata o apuntes de clase",
            "suggestedStage": None,
            "usePermission": True,
        }
        document = api.post(
            "/api/v1/documents",
            headers=h,
            files={"file": ("protocolos.txt", MATERIAL)},
            data={"context": json.dumps(context)},
        ).json()
        assert (
            api.post(f"/api/v1/documents/{document['id']}/process", headers=h).json()["status"]
            == "procesado"
        )

        request_body = {
            "unitId": unit["id"],
            "outcomeId": None,
            "stage": "evaluate",
            "resourceType": "item_opcion_multiple",
            "quantity": 1,
            "difficulty": "intermedia",
            "optionCount": 4,
            "topK": 8,
            "evidenceThreshold": 0.6,
            "instructions": "",
            "audience": "",
            "competency": "",
            "modalities": ["Textual"],
        }
        generated = api.post("/api/v1/generations", headers=h, json=request_body).json()
        assert generated["generator"]["fallback"] is False

        base = f"/api/v1/units/{unit['id']}"
        resources = api.get(base + "/resources", headers=h).json()
        assert [r["id"] for r in resources] == [generated["resources"][0]["id"]]
        resource = resources[0]
        assert resource["evidence"] and resource["evidence"][0]["documentName"] == "protocolos.txt"
        assert resource["params"]["resourceType"] == "item_opcion_multiple" and resource["generatorKind"] == "respaldo"

        review = {
            "title": resource["title"],
            "body": resource["body"],
            "status": "aprobado",
            "discardReason": None,
            "edited": False,
            "options": [
                {
                    "id": o["id"],
                    "text": o["text"],
                    "feedback": o["feedback"],
                    "decision": "pendiente",
                    "discardReason": None,
                    "edited": False,
                }
                for o in resource["options"]
            ],
        }
        blocked = api.put(f"{base}/resources/{resource['id']}", headers=h, json=review)
        assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "APPROVAL_BLOCKED"
        for o in review["options"]:
            o["decision"] = "aceptado"
        approved = api.put(f"{base}/resources/{resource['id']}", headers=h, json=review)
        assert approved.status_code == 200 and approved.json()["status"] == "aprobado"
        assert api.get(base + "/resources", headers=h).json()[0]["status"] == "aprobado"
        assert api.get("/api/v1/review-summary", headers=h).json() == [
            {"courseId": course["id"], "unitId": unit["id"], "approved": 1, "pending": 0}
        ]

        other = {
            "Authorization": "Bearer "
            + api.post("/api/v1/accounts", json={**ACCOUNT, "email": "beto@correo.pe"}).json()["token"]
        }
        assert api.get(base + "/resources", headers=other).status_code == 404
        assert api.get(base + "/resources").status_code == 401

        download = api.post(
            base + "/downloads",
            headers=h,
            json={"format": "moodle_xml", "fileName": "red-301-unidad-1-moodle.xml", "resourceCount": 1},
        )
        assert download.status_code == 201
        assert [d["fileName"] for d in api.get(base + "/downloads", headers=h).json()] == [
            "red-301-unidad-1-moodle.xml"
        ]
        assert (
            api.post(
                base + "/downloads",
                headers=h,
                json={"format": "pdf", "fileName": "x.pdf", "resourceCount": 1},
            ).status_code
            == 422
        )
        assert api.delete(base + "/downloads", headers=h).status_code == 204
        assert api.get(base + "/downloads", headers=h).json() == []

        assert api.delete(f"{base}/resources/{resource['id']}", headers=h).status_code == 204
        assert api.get(base + "/resources", headers=h).json() == []

        assert api.delete(f"/api/v1/courses/{course['id']}", headers=h).status_code == 204
        assert api.get("/api/v1/documents", headers=h).json() == []
        assert api.get(base + "/resources", headers=h).status_code == 404
        assert api.delete(f"/api/v1/courses/{course['id']}", headers=h).status_code == 404