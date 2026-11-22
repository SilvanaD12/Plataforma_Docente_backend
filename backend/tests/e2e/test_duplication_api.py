"""REV-P3 · Pruebas e2e de la API de reporte de duplicidad (REV-R15)."""

from collections.abc import Iterator
import json

import httpx
import pytest

from tests.e2e.generation_flow import generate

MATERIAL = (
    "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable. "
    "El protocolo UDP no confirma la entrega; por eso es más rápido e introduce menos retardo."
).encode()


def test_duplication_report_endpoint_authorization_and_isolation(server):
    with httpx.Client(base_url=server, timeout=60) as api:
        # 1. 401 Unauthorized sin token
        unauth_response = api.get("/api/v1/units/unidad-inexistente/duplication-report")
        assert unauth_response.status_code == 401

        # 2. Crear docente A y unidad
        token_a = api.post(
            "/api/v1/accounts",
            json={"name": "Docente A", "email": "docente_a_dup@correo.pe", "password": "clave-segura-1"},
        ).json()["token"]
        headers_a = {"Authorization": f"Bearer {token_a}"}

        course_a = api.post(
            "/api/v1/courses",
            headers=headers_a,
            json={
                "code": "DUP-101",
                "name": "Duplicados",
                "term": "2026-II",
                "units": [{"title": "Unidad 1", "outcomes": [{"text": "Distingue protocolos"}]}],
            },
        ).json()
        unit_a = course_a["units"][0]
        unit_id = unit_a["id"]

        # 3. 200 Reporte vacío (sin recursos aún)
        report_resp = api.get(f"/api/v1/units/{unit_id}/duplication-report", headers=headers_a)
        assert report_resp.status_code == 200
        report = report_resp.json()
        assert report["threshold"] == 0.70
        assert report["comparedPairs"] == 0
        assert report["flaggedPairs"] == []
        assert report["duplicatePairRate"] == 0.0

        # 4. Generar material y 2 recursos
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

        _, [r1] = generate(
            api, headers_a, unit_id, "item_opcion_multiple", quantity=1, optionCount=4, modalities=["Textual"]
        )
        _, [r2] = generate(
            api, headers_a, unit_id, "explicacion", quantity=1, modalities=["Textual"]
        )
        resources = [r1, r2]
        assert len(resources) >= 2

        # 5. Consultar reporte tras generar recursos
        report_after = api.get(f"/api/v1/units/{unit_id}/duplication-report", headers=headers_a).json()
        assert report_after["comparedPairs"] >= 1
        assert "duplicatePairRate" in report_after
        assert isinstance(report_after["flaggedPairs"], list)

        # 6. Crear docente B e intentar acceder a la unidad de A -> 404 UNIT_NOT_FOUND
        token_b = api.post(
            "/api/v1/accounts",
            json={"name": "Docente B", "email": "docente_b_dup@correo.pe", "password": "clave-segura-2"},
        ).json()["token"]
        headers_b = {"Authorization": f"Bearer {token_b}"}

        forbidden_resp = api.get(f"/api/v1/units/{unit_id}/duplication-report", headers=headers_b)
        assert forbidden_resp.status_code == 404
        assert forbidden_resp.json()["error"]["code"] == "UNIT_NOT_FOUND"


@pytest.fixture
def custom_threshold_server(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> Iterator[str]:
    """B4: Servidor con variable de entorno REVIEW_DUPLICATE_THRESHOLD=0.9."""
    monkeypatch.setenv("REVIEW_DUPLICATE_THRESHOLD", "0.9")
    yield request.getfixturevalue("server")


def test_duplication_report_configurable_threshold(custom_threshold_server: str):
    """B4: Comprueba que la variable REVIEW_DUPLICATE_THRESHOLD es respetada por la aplicación."""
    with httpx.Client(base_url=custom_threshold_server, timeout=60) as api:
        token = api.post(
            "/api/v1/accounts",
            json={"name": "Docente Umbral", "email": "docente_umbral@correo.pe", "password": "clave-segura-1"},
        ).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        course = api.post(
            "/api/v1/courses",
            headers=headers,
            json={
                "code": "THR-101",
                "name": "Umbral",
                "term": "2026-II",
                "units": [{"title": "Unidad 1", "outcomes": [{"text": "Distingue protocolos"}]}],
            },
        ).json()
        unit_id = course["units"][0]["id"]

        report = api.get(f"/api/v1/units/{unit_id}/duplication-report", headers=headers).json()
        assert report["threshold"] == 0.9
