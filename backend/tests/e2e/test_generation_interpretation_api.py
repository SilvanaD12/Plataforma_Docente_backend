import httpx


def test_interprets_a_message_without_creating_a_request(server: str):
    base_path = "/api/v1/generation-requests"

    with httpx.Client(base_url=server, timeout=30, trust_env=False) as api:
        account = api.post(
            "/api/v1/accounts",
            json={
                "name": "Docente de prueba",
                "email": "docente-hu038@example.com",
                "password": "clave-segura-hu038",
            },
        )
        assert account.status_code == 201, account.text
        headers = {"Authorization": f"Bearer {account.json()['token']}"}

        course = api.post(
            "/api/v1/courses",
            headers=headers,
            json={
                "code": "HU038",
                "name": "Redes",
                "term": "2026-II",
                "units": [{"title": "TCP/IP"}],
            },
        )
        assert course.status_code == 201, course.text
        unit_id = course.json()["units"][0]["id"]

        response = api.post(
            f"{base_path}/interpret",
            headers=headers,
            json={"unitId": unit_id, "message": "Para TCP/IP, quiero dos glosarios"},
        )
        assert response.status_code == 200, response.text
        assert response.json() == {
            "draft": {
                "unitId": unit_id,
                "mode": "individual",
                "resourceTypes": ["glosario"],
                "quantity": 2,
            },
            "stages": [{"resourceType": "glosario", "stage": "explain"}],
            "issues": [],
        }

        requests = api.get(base_path, headers=headers, params={"unitId": unit_id})
        assert requests.status_code == 200, requests.text
        assert requests.json() == []

        print("HTTP 200: Glosario, cantidad 2, etapa Explicar.")
        print("Pedidos creados: 0.")

        other_account = api.post(
            "/api/v1/accounts",
            json={
                "name": "Otro docente",
                "email": "otro-docente-hu038@example.com",
                "password": "clave-segura-otro-hu038",
            },
        )
        assert other_account.status_code == 201, other_account.text
        other_headers = {"Authorization": f"Bearer {other_account.json()['token']}"}

        foreign_unit = api.post(
            f"{base_path}/interpret",
            headers=other_headers,
            json={"unitId": unit_id, "message": "Quiero un glosario"},
        )
        missing_unit = api.post(
            f"{base_path}/interpret",
            headers=other_headers,
            json={"unitId": "unidad-inexistente-hu038", "message": "Quiero un glosario"},
        )
        assert foreign_unit.status_code == 404, foreign_unit.text
        assert missing_unit.status_code == 404, missing_unit.text
        assert foreign_unit.json() == missing_unit.json()
        assert foreign_unit.json()["error"]["code"] == "UNIT_NOT_FOUND"
        print("HTTP 404 UNIT_NOT_FOUND: misma respuesta para unidad ajena e inexistente.")

        blank_message = api.post(
            f"{base_path}/interpret",
            headers=headers,
            json={"unitId": unit_id, "message": "   "},
        )
        assert blank_message.status_code == 422, blank_message.text
        assert blank_message.json()["error"]["code"] == "INVALID_PARAMETERS"
        print("HTTP 422 INVALID_PARAMETERS: mensaje en blanco rechazado.")