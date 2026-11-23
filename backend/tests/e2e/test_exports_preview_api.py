"""REV-P2 · Pruebas e2e de la vista previa de exportación SCORM (REV-R14)."""

import json

import httpx

from tests.e2e.generation_flow import generate

MATERIAL = (
    "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable. "
    "El protocolo UDP no confirma la entrega; por eso es más rápido e introduce menos retardo."
).encode()


def test_exports_preview_api_flow_and_no_history_side_effects(server):
    with httpx.Client(base_url=server, timeout=60) as api:
        # 1. 401 Unauthorized sin token
        unauth = api.post("/api/v1/units/unidad-inexistente/exports/preview", json={"format": "scorm_zip"})
        assert unauth.status_code == 401

        # 2. Crear docente A y unidad
        token_a = api.post(
            "/api/v1/accounts",
            json={"name": "Docente SCORM", "email": "docente_scorm_prev@correo.pe", "password": "clave-segura-1"},
        ).json()["token"]
        headers_a = {"Authorization": f"Bearer {token_a}"}

        course_a = api.post(
            "/api/v1/courses",
            headers=headers_a,
            json={
                "code": "SCORM-201",
                "name": "Redes Avanzadas",
                "term": "2026-II",
                "units": [{"title": "Capa de Transporte", "outcomes": [{"text": "Analiza TCP y UDP"}]}],
            },
        ).json()
        unit_a = course_a["units"][0]
        unit_id = unit_a["id"]

        preview_url = f"/api/v1/units/{unit_id}/exports/preview"

        # 3. 422 si formato no es scorm_zip
        invalid_format_resp = api.post(
            preview_url,
            headers=headers_a,
            json={"format": "documento"},
        )
        assert invalid_format_resp.status_code == 422
        assert invalid_format_resp.json()["error"]["code"] == "INVALID_PREVIEW_FORMAT"

        # 4. 422 si no hay recursos aprobados/elegibles
        no_resources_resp = api.post(
            preview_url,
            headers=headers_a,
            json={"format": "scorm_zip"},
        )
        assert no_resources_resp.status_code == 422
        assert no_resources_resp.json()["error"]["code"] == "NO_APPROVED_RESOURCES"

        # 5. Generar material y 1 recurso
        context = {
            "unitId": unit_id,
            "outcomeIds": [unit_a["outcomes"][0]["id"]],
            "documentType": "Separata o apuntes de clase",
            "usePermission": True,
        }
        document = api.post(
            "/api/v1/documents",
            headers=headers_a,
            files={"file": ("redes.txt", MATERIAL)},
            data={"context": json.dumps(context)},
        ).json()
        api.post(f"/api/v1/documents/{document['id']}/process", headers=headers_a)

        _, [explanation] = generate(
            api, headers_a, unit_id, "explicacion", quantity=1, modalities=["Textual"]
        )

        # Todavía no está aprobado -> 422
        not_yet_approved = api.post(preview_url, headers=headers_a, json={"format": "scorm_zip"})
        assert not_yet_approved.status_code == 422
        assert not_yet_approved.json()["error"]["code"] == "NO_APPROVED_RESOURCES"

        # Aprobar el recurso
        approved = api.put(
            f"/api/v1/units/{unit_id}/resources/{explanation['id']}",
            headers=headers_a,
            json={
                "title": explanation["title"],
                "body": explanation["body"],
                "status": "aprobado",
                "expectedVersion": explanation["version"],
            },
        )
        assert approved.status_code == 200

        # 6. Vista previa exitosa (200)
        preview_resp = api.post(preview_url, headers=headers_a, json={"format": "scorm_zip"})
        assert preview_resp.status_code == 200
        data = preview_resp.json()
        assert "pages" in data
        assert "excluded" in data
        assert len(data["pages"]) >= 1

        page1 = data["pages"][0]
        assert page1["number"] == 1
        assert page1["title"] == explanation["title"]
        assert "<!doctype html>" in page1["html"]
        assert explanation["title"] in page1["html"]

        # 7. Comprobar que NO se registró ninguna descarga en el historial
        unit_downloads = api.get(f"/api/v1/units/{unit_id}/downloads", headers=headers_a).json()
        assert len(unit_downloads) == 0

        my_downloads = api.get("/api/v1/downloads", headers=headers_a).json()
        assert len(my_downloads) == 0

        # 8. Docente B no puede acceder a la unidad -> 404
        token_b = api.post(
            "/api/v1/accounts",
            json={"name": "Docente B", "email": "docente_b_scorm@correo.pe", "password": "clave-segura-2"},
        ).json()["token"]
        headers_b = {"Authorization": f"Bearer {token_b}"}

        forbidden_resp = api.post(preview_url, headers=headers_b, json={"format": "scorm_zip"})
        assert forbidden_resp.status_code == 404
        assert forbidden_resp.json()["error"]["code"] == "UNIT_NOT_FOUND"
