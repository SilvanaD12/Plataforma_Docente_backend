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


def test_duplication_report_cross_unit_with_include_course(server):
    """REV-P4: reporte entre unidades del mismo curso con ?includeCourse=true."""
    with httpx.Client(base_url=server, timeout=60) as api:
        token_a = api.post(
            "/api/v1/accounts",
            json={"name": "Docente Curso", "email": "docente_cross_dup@correo.pe", "password": "clave-segura-1"},
        ).json()["token"]
        headers_a = {"Authorization": f"Bearer {token_a}"}

        course = api.post(
            "/api/v1/courses",
            headers=headers_a,
            json={
                "code": "CROSS-101",
                "name": "Redes entre unidades",
                "term": "2026-II",
                "units": [
                    {"title": "Unidad 1: Capa de transporte", "outcomes": [{"text": "Distingue TCP y UDP"}]},
                    {"title": "Unidad 2: Redes avanzadas", "outcomes": [{"text": "Analiza TCP y UDP"}]},
                ],
            },
        ).json()
        unit_1, unit_2 = course["units"][0], course["units"][1]

        for unit in (unit_1, unit_2):
            ctx = {
                "unitId": unit["id"],
                "outcomeIds": [unit["outcomes"][0]["id"]],
                "documentType": "Separata o apuntes de clase",
                "usePermission": True,
            }
            doc = api.post(
                "/api/v1/documents",
                headers=headers_a,
                files={"file": ("redes.txt", MATERIAL)},
                data={"context": json.dumps(ctx)},
            ).json()
            api.post(f"/api/v1/documents/{doc['id']}/process", headers=headers_a)

        _, [r1_a] = generate(api, headers_a, unit_1["id"], "explicacion", quantity=1, modalities=["Textual"])
        _, [r1_b] = generate(api, headers_a, unit_1["id"], "explicacion", quantity=1, modalities=["Textual"])
        _, [r2_a] = generate(api, headers_a, unit_2["id"], "explicacion", quantity=1, modalities=["Textual"])

        # Ajustar textos casi equivalentes mediante PUT para asegurar similitud alta reproducible
        for unit_obj, res_obj, body_text in (
            (
                unit_1,
                r1_a,
                "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable de datos.",
            ),
            (
                unit_1,
                r1_b,
                "El protocolo TCP es orientado a la conexión y garantiza la entrega confiable de los datos.",
            ),
            (
                unit_2,
                r2_a,
                "TCP es un protocolo orientado a la conexión que garantiza una entrega confiable de datos.",
            ),
        ):
            put_resp = api.put(
                f"/api/v1/units/{unit_obj['id']}/resources/{res_obj['id']}",
                headers=headers_a,
                json={
                    "expectedVersion": res_obj["version"],
                    "title": "Protocolo TCP",
                    "body": body_text,
                    "status": "pendiente",
                    "edited": True,
                },
            )
            assert put_resp.status_code == 200, put_resp.text

        # Sin includeCourse: solo compara dentro de la unidad actual y no incluye campos crossUnit
        without_course = api.get(
            f"/api/v1/units/{unit_1['id']}/duplication-report", headers=headers_a
        ).json()
        assert without_course["comparedPairs"] == 1
        assert len(without_course["flaggedPairs"]) == 1
        assert {
            without_course["flaggedPairs"][0]["resourceIdA"],
            without_course["flaggedPairs"][0]["resourceIdB"],
        } == {r1_a["id"], r1_b["id"]}
        assert "crossUnit" not in without_course["flaggedPairs"][0]
        assert "unitIdB" not in without_course["flaggedPairs"][0]
        assert "unitTitleB" not in without_course["flaggedPairs"][0]

        # Con includeCourse=true: incluye pares de la unidad y entre unidades con unitTitleB correcto
        with_course = api.get(
            f"/api/v1/units/{unit_1['id']}/duplication-report?includeCourse=true",
            headers=headers_a,
        ).json()
        assert with_course["comparedPairs"] == 3  # 1 interno en u1 + (2 * 1) cruzados u1-u2
        cross_pairs = [p for p in with_course["flaggedPairs"] if p.get("crossUnit") is True]
        same_pairs = [p for p in with_course["flaggedPairs"] if p.get("crossUnit") is False]
        assert len(cross_pairs) == 2
        assert len(same_pairs) == 1
        assert same_pairs[0]["unitIdB"] is None
        assert same_pairs[0]["unitTitleB"] is None
        for pair in cross_pairs:
            assert pair["resourceIdB"] == r2_a["id"]
            assert pair["unitIdB"] == unit_2["id"]
            assert pair["unitTitleB"] == "Unidad 2: Redes avanzadas"
            assert pair["score"] >= 0.70

        # Docente B no puede consultar el reporte de una unidad ajena -> 404
        token_b = api.post(
            "/api/v1/accounts",
            json={"name": "Docente Ajeno", "email": "docente_b_cross_dup@correo.pe", "password": "clave-segura-2"},
        ).json()["token"]
        headers_b = {"Authorization": f"Bearer {token_b}"}
        forbidden = api.get(
            f"/api/v1/units/{unit_1['id']}/duplication-report?includeCourse=true",
            headers=headers_b,
        )
        assert forbidden.status_code == 404
        assert forbidden.json()["error"]["code"] == "UNIT_NOT_FOUND"
