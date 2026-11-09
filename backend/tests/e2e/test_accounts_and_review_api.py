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
            "expectedVersion": resource["version"],
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


UNSUPPORTED_BODY = (
    "Los satélites geoestacionarios orbitan sobre el ecuador terrestre a gran altura.\n\n"
    "Las órbitas bajas permiten fotografías satelitales de alta resolución."
)


def _unit_with_an_explanation(api: httpx.Client, email: str) -> tuple[dict, dict, dict, dict]:
    """Cuenta, curso, material procesado y una explicación generada por reglas, lista para revisar."""
    token = api.post("/api/v1/accounts", json={**ACCOUNT, "email": email}).json()["token"]
    h = {"Authorization": "Bearer " + token}
    course = api.post(
        "/api/v1/courses",
        headers=h,
        json={"code": "REV-01", "name": "Redes", "term": "2026-II",
              "units": [{"title": "Protocolos", "outcomes": [{"text": "Distingue TCP y UDP"}]}]},
    ).json()
    unit = course["units"][0]
    context = {"unitId": unit["id"], "outcomeIds": [unit["outcomes"][0]["id"]],
               "documentType": "Separata o apuntes de clase", "usePermission": True}
    document = api.post(
        "/api/v1/documents", headers=h, files={"file": ("protocolos.txt", MATERIAL)}, data={"context": json.dumps(context)}
    ).json()
    assert api.post(f"/api/v1/documents/{document['id']}/process", headers=h).status_code == 200
    generated = api.post(
        "/api/v1/generations",
        headers=h,
        json={"unitId": unit["id"], "stage": "explain", "resourceType": "explicacion", "quantity": 1, "evidenceThreshold": 0.6},
    )
    assert generated.status_code == 200, generated.text
    resource = api.get(f"/api/v1/units/{unit['id']}/resources", headers=h).json()[0]
    return h, unit, document, resource


def _edit(resource: dict, version: int, **changes) -> dict:
    return {"title": resource["title"], "body": resource["body"], "status": "pendiente", "edited": True,
            "expectedVersion": version, **changes}


def test_saves_check_the_version_and_the_stored_evidence(server: str):
    """REV-C1, C6 y C14 por HTTP: versión de partida, verificación al guardar y copia histórica intacta."""
    with httpx.Client(base_url=server, timeout=30) as api:
        h, unit, document, resource = _unit_with_an_explanation(api, "rev01@correo.pe")
        url = f"/api/v1/units/{unit['id']}/resources/{resource['id']}"
        assert resource["version"] == 1

        # Primera pestaña: un cambio de título guarda la versión 2 y deja una verificación vigente.
        first = api.put(url, headers=h, json=_edit(resource, 1, title="Protocolos de transporte"))
        assert first.status_code == 200, first.text
        assert first.json()["version"] == 2 and first.json()["verification"]["status"] == "current"

        # Segunda pestaña, todavía en la versión 1: conflicto, y la versión vigente no cambia (REV-C14).
        stale = api.put(url, headers=h, json=_edit(resource, 1, body=UNSUPPORTED_BODY))
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "VERSION_CONFLICT"
        current = api.get(f"/api/v1/units/{unit['id']}/resources", headers=h).json()[0]
        assert current["version"] == 2 and current["body"] == resource["body"]
        assert current["verification"] == first.json()["verification"]

        # Un cuerpo que el material no respalda queda con verificación insuficiente y su motivo (REV-C1).
        edited = api.put(url, headers=h, json=_edit(resource, 2, body=UNSUPPORTED_BODY))
        assert edited.status_code == 200, edited.text
        verification = edited.json()["verification"]
        assert verification["status"] == "insufficient" and verification["reason"]
        assert edited.json()["version"] == 3

        # Reprocesar el material crea fragmentos nuevos, pero la copia histórica y la verificación no cambian (REV-C6).
        before = api.get(f"/api/v1/units/{unit['id']}/resources", headers=h).json()[0]
        assert api.post(f"/api/v1/documents/{document['id']}/process", headers=h).status_code == 200
        new_chunk_ids = {c["id"] for c in api.get(f"/api/v1/documents/{document['id']}/chunks", headers=h).json()}
        after = api.get(f"/api/v1/units/{unit['id']}/resources", headers=h).json()[0]
        assert not new_chunk_ids & {e["id"] for e in after["evidence"]}
        assert after["evidence"] == before["evidence"]
        assert after["verification"] == before["verification"] and after["version"] == before["version"]

        # Otra cuenta no puede guardar en la unidad ajena.
        other = {"Authorization": "Bearer " + api.post("/api/v1/accounts", json={**ACCOUNT, "email": "otra@correo.pe"}).json()["token"]}
        assert api.put(url, headers=other, json=_edit(resource, 3)).status_code == 404



def test_approving_from_an_outdated_version_is_a_version_conflict(server: str):
    """REV-C14 por HTTP: aprobar desde la versión 1 cuando existe la 2 es VERSION_CONFLICT, no APPROVAL_BLOCKED."""
    with httpx.Client(base_url=server, timeout=30) as api:
        h, unit, document, resource = _unit_with_an_explanation(api, "rev01-aprobar@correo.pe")
        url = f"/api/v1/units/{unit['id']}/resources/{resource['id']}"
        assert api.put(url, headers=h, json=_edit(resource, 1, title="Otra pestaña")).status_code == 200

        stale = api.put(url, headers=h, json=_edit(resource, 1, body=UNSUPPORTED_BODY, status="aprobado"))
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "VERSION_CONFLICT", stale.text
        current = api.get(f"/api/v1/units/{unit['id']}/resources", headers=h).json()[0]
        assert current["version"] == 2 and current["status"] == "pendiente" and current["body"] == resource["body"]

def test_approval_needs_a_current_verification_and_retry_only_applies_to_pending(server: str):
    """REV-C3 y REV-C11 por HTTP: bloqueo con motivo, verificación al leer y reintento solo para pendientes."""
    with httpx.Client(base_url=server, timeout=30) as api:
        h, unit, _, resource = _unit_with_an_explanation(api, "rev01-c@correo.pe")
        url = f"/api/v1/units/{unit['id']}/resources/{resource['id']}"

        # Al leerla, la explicación recién generada queda verificada contra su copia, sin cambiar de versión (D7).
        assert resource["verification"]["status"] == "current" and resource["version"] == 1
        assert resource["approvalBlockers"] == []

        # Una edición sin respaldo bloquea la aprobación con el motivo de la verificación (REV-C3).
        blocked = api.put(url, headers=h, json={**_edit(resource, 1, body=UNSUPPORTED_BODY), "status": "aprobado"})
        assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "APPROVAL_BLOCKED"
        assert "respaldo" in blocked.json()["error"]["message"].lower()
        saved = api.put(url, headers=h, json=_edit(resource, 1, body=UNSUPPORTED_BODY))
        assert saved.status_code == 200 and saved.json()["verification"]["status"] == "insufficient"
        assert saved.json()["approvalBlockers"]

        # «Reintentar comprobación» solo aplica a una comprobación pendiente: aquí es insuficiente.
        retry = api.post(url + "/verification", headers=h, json={"expectedVersion": 2})
        assert retry.status_code == 409 and retry.json()["error"]["code"] == "VERIFICATION_NOT_PENDING"

        # Corregir el texto vuelve a dejarla vigente y se puede aprobar.
        fixed = api.put(url, headers=h, json={**_edit(resource, 2), "status": "aprobado"})
        assert fixed.status_code == 200, fixed.text
        assert fixed.json()["status"] == "aprobado" and fixed.json()["verification"]["status"] == "current"

        # Otra cuenta no puede reintentar en la unidad ajena.
        other = {"Authorization": "Bearer " + api.post("/api/v1/accounts", json={**ACCOUNT, "email": "otra-c@correo.pe"}).json()["token"]}
        assert api.post(url + "/verification", headers=other, json={"expectedVersion": 3}).status_code == 404