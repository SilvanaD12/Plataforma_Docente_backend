"""GEN-01 (T024 y T026): contrato HTTP del pedido de generación de punta a punta, con el servidor real.

Casos GEN-C1, GEN-C4, GEN-C5, GEN-C6 y GEN-C8, y V10 (aislamiento entre dos docentes).
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text

from tests.e2e.test_sequence_api import _unit_with_material, _wait_until_final

TEACHER_A = {"name": "Rosa Quispe", "email": "rosa.quispe@correo.pe", "password": "clave-segura-3"}
TEACHER_B = {"name": "Mario Salas", "email": "mario.salas@correo.pe", "password": "clave-segura-4"}
ITEM_REQUEST = {"mode": "individual", "resourceTypes": ["item_opcion_multiple"], "quantity": 1, "optionCount": 4}


def _session(api: httpx.Client, account: dict) -> dict[str, str]:
    return {"Authorization": "Bearer " + api.post("/api/v1/accounts", json=account).json()["token"]}


def _start(api: httpx.Client, headers: dict[str, str], body: dict, key: str | None = None) -> httpx.Response:
    return api.post(
        "/api/v1/generation-requests", headers={**headers, "Idempotency-Key": key or str(uuid4())}, json=body
    )


def _unit_resources(api: httpx.Client, headers: dict[str, str], unit_id: str) -> list[dict]:
    return api.get(f"/api/v1/units/{unit_id}/resources", headers=headers).json()


def test_an_individual_request_is_created_and_finishes(server: str):
    """GEN-C1: el recurso pasa a revisión y el pedido termina con el estado que informa el servidor."""
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        response = _start(api, headers, {**ITEM_REQUEST, "unitId": unit["id"]})

        assert response.status_code == 202, response.text
        accepted = response.json()
        assert response.headers["Location"] == f"/api/v1/generation-requests/{accepted['id']}"
        assert accepted["status"] in {"queued", "running", "succeeded"} and accepted["mode"] == "individual"
        assert [s["stage"] for s in accepted["steps"]] == ["evaluate"]

        finished = _wait_until_final(api, headers, accepted["id"])
        [step] = finished["steps"]
        assert finished["status"] == "succeeded" and step["status"] == "succeeded"
        assert step["generator"]["fallback"] is False and step["startedAt"] and step["finishedAt"]
        assert [r["id"] for r in step["resources"]] == step["resourceIds"]
        [resource] = [r for r in _unit_resources(api, headers, unit["id"]) if r["id"] in step["resourceIds"]]
        assert resource["requestId"] == finished["id"] and resource["status"] == "pendiente"


def _stored_resource(database_url: str, resource_id: str) -> tuple[dict, int]:
    """El recurso tal como quedó en la base, sin pasar por Revisión."""
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            data, version = connection.execute(
                text("SELECT datos, version FROM ep002_recursos WHERE id = :id"), {"id": resource_id}
            ).one()
    finally:
        engine.dispose()
    return (json.loads(data) if isinstance(data, str) else data), version


def test_review_reads_and_edits_a_generated_resource_without_verifying_it_again(server: str, e2e_database_url: str):
    """GEN-C8 con REV-01: el recurso llega con `version = 1` y su verificación; Revisión lo muestra vigente con el
    resultado que guardó Generación y acepta el primer guardado con `expectedVersion = 1`."""
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        body = {"mode": "individual", "resourceTypes": ["pregunta_detonante"], "unitId": unit["id"]}
        finished = _wait_until_final(api, headers, _start(api, headers, body).json()["id"])
        [step] = finished["steps"]
        [summary] = step["resources"]
        assert finished["status"] == "succeeded" and summary["verificationStatus"] == "current"

        stored, stored_version = _stored_resource(e2e_database_url, summary["id"])
        verification = stored["verification"]
        assert stored_version == stored["version"] == 1
        assert verification["status"] == "current" and verification["verifiedVersion"] == 1
        assert stored["evidence"] and all(item["retrievedAt"] for item in stored["evidence"])

        # Lectura de Revisión: el mismo resultado (misma hora de comprobación) y la fila sin cambios.
        [read] = [r for r in _unit_resources(api, headers, unit["id"]) if r["id"] == summary["id"]]
        assert read["version"] == 1 and read["verification"] == verification
        assert _stored_resource(e2e_database_url, summary["id"]) == (stored, 1)

        # Primer guardado con expectedVersion = 1: cambiar el título no cambia la huella, así que no se verifica de
        # nuevo y se conserva el resultado de Generación.
        url = f"/api/v1/units/{unit['id']}/resources/{summary['id']}"
        edit = {"expectedVersion": 1, "title": "Título revisado", "body": read["body"], "status": "pendiente",
                "edited": True, "discardReason": None}
        saved = api.put(url, headers=headers, json=edit)
        assert saved.status_code == 200, saved.text
        assert saved.json()["version"] == 2 and saved.json()["title"] == "Título revisado"
        assert saved.json()["verification"] == verification

        stale = api.put(url, headers=headers, json=edit)
        assert stale.status_code == 409 and stale.json()["error"]["code"] == "VERSION_CONFLICT"


def test_the_same_key_returns_the_same_request_and_other_content_conflicts(server: str):
    """GEN-C4 y GEN-C5: reenviar no duplica recursos; la clave con otro contenido responde 409."""
    with httpx.Client(base_url=server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        body, key = {**ITEM_REQUEST, "unitId": unit["id"]}, str(uuid4())

        first = _start(api, headers, body, key)
        assert first.status_code == 202, first.text
        _wait_until_final(api, headers, first.json()["id"])
        resources_before = len(_unit_resources(api, headers, unit["id"]))

        again = _start(api, headers, body, key)
        assert again.status_code == 200 and again.json()["id"] == first.json()["id"]
        assert "Location" not in again.headers
        assert len(_unit_resources(api, headers, unit["id"])) == resources_before

        conflict = _start(api, headers, {**body, "quantity": 2}, key)
        assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
        other_mode = _start(api, headers, {**body, "mode": "sequence"}, key)
        assert other_mode.status_code == 409


def test_the_idempotency_key_is_required_and_validated(server: str):
    with httpx.Client(base_url=server, timeout=30) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        body = {**ITEM_REQUEST, "unitId": unit["id"]}

        missing = api.post("/api/v1/generation-requests", headers=headers, json=body)
        assert missing.status_code == 400 and missing.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
        malformed = _start(api, headers, body, key="clave con espacios")
        assert malformed.status_code == 422 and malformed.json()["error"]["code"] == "INVALID_PARAMETERS"
        assert api.post("/api/v1/generation-requests", json=body).status_code == 401


def test_another_teacher_cannot_see_the_request_or_use_the_unit(server: str):
    """GEN-C5 y V10: la consulta ajena y la unidad ajena responden igual que si no existieran."""
    with httpx.Client(base_url=server, timeout=60) as api:
        owner = _session(api, TEACHER_A)
        unit = _unit_with_material(api, owner)
        request_id = _start(api, owner, {**ITEM_REQUEST, "unitId": unit["id"]}).json()["id"]
        _wait_until_final(api, owner, request_id)

        intruder = _session(api, TEACHER_B)
        foreign = api.get(f"/api/v1/generation-requests/{request_id}", headers=intruder)
        missing = api.get("/api/v1/generation-requests/gen-req-no-existe", headers=intruder)
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json() and foreign.json()["error"]["code"] == "GENERATION_REQUEST_NOT_FOUND"

        foreign_unit = _start(api, intruder, {**ITEM_REQUEST, "unitId": unit["id"]})
        missing_unit = _start(api, intruder, {**ITEM_REQUEST, "unitId": "unidad-que-no-existe"})
        assert foreign_unit.status_code == missing_unit.status_code == 404
        assert foreign_unit.json() == missing_unit.json() and foreign_unit.json()["error"]["code"] == "UNIT_NOT_FOUND"
        listed = api.get("/api/v1/generation-requests", headers=intruder, params={"unitId": unit["id"]})
        assert listed.status_code == 404


def test_a_unit_without_processed_material_is_rejected_without_creating_a_request(server: str):
    """GEN-C6."""
    with httpx.Client(base_url=server, timeout=30) as api:
        headers = _session(api, TEACHER_A)
        course = api.post(
            "/api/v1/courses",
            headers=headers,
            json={"code": "BD-101", "name": "Bases de datos", "term": "2026-II", "units": [{"title": "SQL"}]},
        ).json()
        unit_id = course["units"][0]["id"]

        response = _start(api, headers, {**ITEM_REQUEST, "unitId": unit_id})
        assert response.status_code == 400 and response.json()["error"]["code"] == "NO_PROCESSED_MATERIAL"
        assert api.get("/api/v1/generation-requests", headers=headers, params={"unitId": unit_id}).json() == []


# HU-024 (T056 parcial, sin actividad kinestésica): modalidad del pedido. Caso GEN-C10.
MODALITY_SEQUENCES = {
    "Textual": ["pregunta_detonante", "glosario"],
    "Gamificado": ["ordenar_pasos", "item_opcion_multiple"],
    "Multimedia": ["diagrama_proceso", "infografia"],
}


def test_the_catalog_reports_the_modalities_of_each_type(server: str):
    with httpx.Client(base_url=server, timeout=30) as api:
        catalog = {entry["id"]: entry["modalities"] for entry in api.get("/api/v1/resource-types").json()}
    assert catalog["item_opcion_multiple"] == ["Textual", "Gamificado"]
    assert catalog["exploracion_guiada"] == catalog["caso_aplicado"] == ["Textual"]
    assert all(catalog.values())


@pytest.mark.parametrize("modality", list(MODALITY_SEQUENCES))
def test_one_request_per_modality_saves_it_in_the_request_and_its_resources(server: str, modality: str):
    with httpx.Client(base_url=server, timeout=90) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        body = {"mode": "sequence", "unitId": unit["id"], "resourceTypes": MODALITY_SEQUENCES[modality],
                "modalities": [modality]}
        accepted = _start(api, headers, body)
        assert accepted.status_code == 202, accepted.text
        assert accepted.json()["parameters"]["modalities"] == [modality]

        finished = _wait_until_final(api, headers, accepted.json()["id"])
        assert finished["status"] == "succeeded", finished
        delivered = {resource_id for step in finished["steps"] for resource_id in step["resourceIds"]}
        resources = [r for r in _unit_resources(api, headers, unit["id"]) if r["id"] in delivered]
        assert resources and all(r["params"]["modality"] == modality for r in resources)
        assert all("modalities" not in r["params"] for r in resources)


def test_a_type_outside_the_modality_is_rejected_without_saving_a_request(server: str):
    with httpx.Client(base_url=server, timeout=30) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        for modality, types in [("Textual", ["glosario", "imagen_ilustrativa"]), ("Kinestésico", ["glosario"])]:
            body = {"mode": "sequence", "unitId": unit["id"], "resourceTypes": types, "modalities": [modality]}
            response = _start(api, headers, body)
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == "RESOURCE_TYPE_NOT_IN_MODALITY"
        listed = api.get("/api/v1/generation-requests", headers=headers, params={"unitId": unit["id"]})
        assert listed.status_code == 200 and listed.json() == []


def test_a_request_without_modalities_is_not_filtered_and_returns_an_empty_list(server: str):
    with httpx.Client(base_url=server, timeout=90) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        body = {"mode": "sequence", "unitId": unit["id"], "resourceTypes": ["pregunta_detonante", "diagrama_proceso"]}  # Textual y Multimedia
        accepted = _start(api, headers, body)
        assert accepted.status_code == 202, accepted.text

        finished = _wait_until_final(api, headers, accepted.json()["id"])
        assert finished["status"] == "succeeded" and finished["parameters"]["modalities"] == []
        delivered = {resource_id for step in finished["steps"] for resource_id in step["resourceIds"]}
        resources = [r for r in _unit_resources(api, headers, unit["id"]) if r["id"] in delivered]
        assert resources and all("modality" not in r["params"] for r in resources)


@pytest.fixture
def single_worker_server(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> Iterator[str]:
    """Servidor con un solo hilo de generación: los pedidos siguientes esperan en cola y cuentan como activos."""
    monkeypatch.setenv("GENERATION_MAX_WORKERS", "1")
    yield request.getfixturevalue("server")


def test_a_third_active_request_gets_429_with_retry_after(single_worker_server: str):
    """Research R4: dos pedidos activos por docente. Se envían seguidos; con un solo hilo, los primeros siguen activos."""
    with httpx.Client(base_url=single_worker_server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        all_types = [
            "pregunta_detonante", "sondeo_diagnostico", "guia_exploracion", "caso_indagacion",
            "explicacion", "glosario", "ejercicio_aplicacion", "item_opcion_multiple",
        ]
        big = {"mode": "sequence", "unitId": unit["id"], "resourceTypes": all_types, "quantity": 5}

        responses = [_start(api, headers, big) for _ in range(4)]
        codes = [r.status_code for r in responses]
        assert codes[:2] == [202, 202], [r.text for r in responses]
        limited = [r for r in responses if r.status_code == 429]
        assert limited, f"Ningún pedido llegó al límite: {codes}"
        assert limited[0].json()["error"]["code"] == "TOO_MANY_ACTIVE_REQUESTS"
        assert int(limited[0].headers["Retry-After"]) > 0

        for accepted in responses:
            if accepted.status_code == 202:
                _wait_until_final(api, headers, accepted.json()["id"], timeout=120)


def test_two_simultaneous_requests_with_one_active_get_exactly_one_429(single_worker_server: str):
    """Corrección 2 del PR #14: con un pedido activo, dos envíos simultáneos con claves distintas no dejan tres
    pedidos activos: exactamente uno recibe 429 TOO_MANY_ACTIVE_REQUESTS."""
    with httpx.Client(base_url=single_worker_server, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        all_types = [
            "pregunta_detonante", "sondeo_diagnostico", "guia_exploracion", "caso_indagacion",
            "explicacion", "glosario", "ejercicio_aplicacion", "item_opcion_multiple",
        ]
        big = {"mode": "sequence", "unitId": unit["id"], "resourceTypes": all_types, "quantity": 5}
        first = _start(api, headers, big)
        assert first.status_code == 202, first.text

        barrier = threading.Barrier(2)
        responses: list[httpx.Response] = []

        def submit() -> None:
            with httpx.Client(base_url=single_worker_server, timeout=60) as own:
                barrier.wait()
                responses.append(_start(own, headers, big))

        threads = [threading.Thread(target=submit) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        assert sorted(r.status_code for r in responses) == [202, 429], [r.text for r in responses]
        [limited] = [r for r in responses if r.status_code == 429]
        assert limited.json()["error"]["code"] == "TOO_MANY_ACTIVE_REQUESTS" and int(limited.headers["Retry-After"]) > 0
        active = api.get(
            "/api/v1/generation-requests", headers=headers, params={"unitId": unit["id"], "active": "true"}
        ).json()
        assert len(active) <= 2

        for accepted in [first, *responses]:
            if accepted.status_code == 202:
                _wait_until_final(api, headers, accepted.json()["id"], timeout=120)


@pytest.fixture
def server_without_embeddings(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> Iterator[str]:
    """Servidor sin embeddings: la búsqueda de Material solo puede usar BM25."""
    monkeypatch.setenv("EMBEDDINGS_ENABLED", "false")
    yield request.getfixturevalue("server")


def test_without_embeddings_the_request_reports_the_bm25_fallback_apart_from_the_generator(
    server_without_embeddings: str,
):
    """T032 (GEN-C9): con EMBEDDINGS_ENABLED=false el pedido informa `retrievalMode = bm25_fallback`, y
    `steps[].generator.fallback` sigue en false porque redactó el generador principal: solo refleja el respaldo de
    redacción, no el de búsqueda."""
    with httpx.Client(base_url=server_without_embeddings, timeout=60) as api:
        headers = _session(api, TEACHER_A)
        unit = _unit_with_material(api, headers)
        body = {"mode": "sequence", "unitId": unit["id"], "resourceTypes": ["pregunta_detonante", "explicacion"]}
        response = _start(api, headers, body)
        assert response.status_code == 202, response.text

        finished = _wait_until_final(api, headers, response.json()["id"])
        assert finished["status"] == "succeeded", finished
        assert finished["retrievalMode"] == "bm25_fallback"
        assert len(finished["steps"]) == 2
        for step in finished["steps"]:
            assert step["status"] == "succeeded"
            assert step["generator"]["fallback"] is False
            assert step["generator"]["description"]



# T030 (GEN-C7): regeneración desde Revisión con el adaptador de Generación (T029).


def _generated_explanation(api: httpx.Client, headers: dict[str, str]) -> tuple[dict, dict]:
    """Unidad con material y una explicación creada por un pedido de generación (con `params` guardados)."""
    unit = _unit_with_material(api, headers)
    body = {"mode": "individual", "unitId": unit["id"], "resourceTypes": ["explicacion"]}
    finished = _wait_until_final(api, headers, _start(api, headers, body).json()["id"])
    assert finished["status"] == "succeeded", finished
    [resource_id] = finished["steps"][0]["resourceIds"]
    [resource] = [r for r in _unit_resources(api, headers, unit["id"]) if r["id"] == resource_id]
    assert resource["version"] == 1 and resource["params"]["resourceType"] == "explicacion"
    return unit, resource


def _regeneration_requests(api: httpx.Client, headers: dict[str, str], unit_id: str) -> list[dict]:
    listed = api.get("/api/v1/generation-requests", headers=headers, params={"unitId": unit_id, "limit": 50})
    assert listed.status_code == 200, listed.text
    return [request for request in listed.json() if request["mode"] == "regeneration"]


def _regeneration_finished(api: httpx.Client, headers: dict[str, str], url: str, timeout: float = 30) -> dict:
    """Consulta GET …/regeneration hasta que deje de estar `running`."""
    limit = time.monotonic() + timeout
    while True:
        response = api.get(f"{url}/regeneration", headers=headers)
        assert response.status_code == 200, response.text
        if response.json()["status"] != "running":
            return response.json()
        assert time.monotonic() < limit, "la regeneración sigue en curso"
        time.sleep(0.2)


def test_regenerating_from_review_discards_the_previous_and_repeating_does_not_duplicate(server: str):
    """Éxito: el anterior queda descartado y el nuevo trae `regeneratedFrom` y `verification`. Repetir la misma
    versión no crea otro pedido ni recursos."""
    with httpx.Client(base_url=server, timeout=90) as api:
        headers = _session(api, TEACHER_A)
        unit, previous = _generated_explanation(api, headers)
        url = f"/api/v1/units/{unit['id']}/resources/{previous['id']}"

        regenerated = api.post(f"{url}/regenerations", headers=headers, json={"expectedVersion": 1})
        assert regenerated.status_code == 200, regenerated.text
        body = regenerated.json()
        assert body["status"] == "succeeded" and body["previousDiscarded"] is True
        [new_id] = body["newResourceIds"]

        by_id = {r["id"]: r for r in _unit_resources(api, headers, unit["id"])}
        assert by_id[previous["id"]]["status"] == "descartado"
        assert by_id[previous["id"]]["discardReason"] == "regenerado"
        new = by_id[new_id]
        assert new["regeneratedFrom"] == {"resourceId": previous["id"], "version": 1}
        assert new["verification"]["status"] == "current" and new["version"] == 1 and new["status"] == "pendiente"
        [request] = _regeneration_requests(api, headers, unit["id"])
        assert request["status"] == "succeeded"
        assert api.get(f"{url}/regeneration", headers=headers).json() == {**body, "reason": None, "code": None}

        again = api.post(f"{url}/regenerations", headers=headers, json={"expectedVersion": 1})
        assert again.status_code == 200 and again.json() == body
        assert len(_regeneration_requests(api, headers, unit["id"])) == 1
        assert len(_unit_resources(api, headers, unit["id"])) == len(by_id)


def test_a_failed_regeneration_leaves_the_previous_resource_untouched(server: str):
    """Sin material procesado, Generación rechaza el pedido: el anterior queda igual y no se crea ningún pedido."""
    with httpx.Client(base_url=server, timeout=90) as api:
        headers = _session(api, TEACHER_A)
        unit, previous = _generated_explanation(api, headers)
        for document in api.get("/api/v1/documents", headers=headers).json():
            assert api.delete(f"/api/v1/documents/{document['id']}", headers=headers).status_code == 204

        url = f"/api/v1/units/{unit['id']}/resources/{previous['id']}"
        failed = api.post(f"{url}/regenerations", headers=headers, json={"expectedVersion": 1})
        assert failed.status_code == 409 and failed.json()["error"]["code"] == "NO_PROCESSED_MATERIAL"

        [after] = [r for r in _unit_resources(api, headers, unit["id"]) if r["id"] == previous["id"]]
        assert (after["status"], after["version"], after["body"]) == ("pendiente", 1, previous["body"])
        assert after["verification"] == previous["verification"]
        assert len(_unit_resources(api, headers, unit["id"])) == 1
        assert _regeneration_requests(api, headers, unit["id"]) == []
        status = api.get(f"{url}/regeneration", headers=headers).json()
        assert status["status"] == "failed" and status["code"] == "NO_PROCESSED_MATERIAL"


@pytest.fixture
def no_wait_server(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> Iterator[str]:
    """Servidor en el que la regeneración no espera el pedido: la primera respuesta es `running`."""
    monkeypatch.setenv("GENERATION_REGENERATION_WAIT_SECONDS", "0")
    yield request.getfixturevalue("server")


def test_with_a_short_wait_the_first_answer_is_running_and_the_query_reaches_succeeded(no_wait_server: str):
    with httpx.Client(base_url=no_wait_server, timeout=90) as api:
        headers = _session(api, TEACHER_A)
        unit, previous = _generated_explanation(api, headers)
        url = f"/api/v1/units/{unit['id']}/resources/{previous['id']}"

        first = api.post(f"{url}/regenerations", headers=headers, json={"expectedVersion": 1})
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "running" and first.json()["previousDiscarded"] is False

        finished = _regeneration_finished(api, headers, url)
        assert finished["status"] == "succeeded" and finished["previousDiscarded"] is True
        [new_id] = finished["newResourceIds"]
        by_id = {r["id"]: r for r in _unit_resources(api, headers, unit["id"])}
        assert by_id[previous["id"]]["status"] == "descartado"
        assert by_id[new_id]["regeneratedFrom"] == {"resourceId": previous["id"], "version": 1}


def test_editing_the_resource_while_it_regenerates_keeps_both(no_wait_server: str):
    with httpx.Client(base_url=no_wait_server, timeout=90) as api:
        headers = _session(api, TEACHER_A)
        unit, previous = _generated_explanation(api, headers)
        url = f"/api/v1/units/{unit['id']}/resources/{previous['id']}"

        assert api.post(f"{url}/regenerations", headers=headers, json={"expectedVersion": 1}).json()["status"] == "running"
        edit = {"expectedVersion": 1, "title": "Explicación revisada", "body": previous["body"], "status": "pendiente",
                "edited": True, "discardReason": None}
        saved = api.put(url, headers=headers, json=edit)
        assert saved.status_code == 200, saved.text
        assert saved.json()["version"] == 2

        finished = _regeneration_finished(api, headers, url)
        assert finished["status"] == "succeeded" and finished["previousDiscarded"] is False
        [new_id] = finished["newResourceIds"]
        by_id = {r["id"]: r for r in _unit_resources(api, headers, unit["id"])}
        assert by_id[previous["id"]]["status"] == "pendiente" and by_id[previous["id"]]["title"] == "Explicación revisada"
        assert by_id[new_id]["status"] == "pendiente"


@pytest.fixture
def uncited_flag(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Archivo que, mientras existe, hace que el generador del servidor no cite el material."""
    flag = tmp_path / "no-citar"
    monkeypatch.setenv("E2E_APP_FACTORY", "tests.e2e.uncited_generator_app:create_application")
    monkeypatch.setenv("E2E_UNCITED_FLAG", str(flag))
    return flag


def test_a_regeneration_that_failed_after_starting_can_be_asked_again_from_the_same_version(
    uncited_flag, request: pytest.FixtureRequest
):
    """El primer intento se crea y falla (el generador no cita el material). Desde la misma versión, el segundo
    intento usa la clave `-r2`, termina bien y descarta el anterior."""
    server = request.getfixturevalue("server")
    with httpx.Client(base_url=server, timeout=90) as api:
        headers = _session(api, TEACHER_A)
        unit, previous = _generated_explanation(api, headers)
        url = f"/api/v1/units/{unit['id']}/resources/{previous['id']}"

        uncited_flag.touch()
        failed = api.post(f"{url}/regenerations", headers=headers, json={"expectedVersion": 1})
        assert failed.status_code == 409, failed.text
        assert failed.json()["error"]["code"] == "INSUFFICIENT_EVIDENCE"
        [first_attempt] = _regeneration_requests(api, headers, unit["id"])
        assert first_attempt["status"] == "failed"  # el pedido se creó y falló al ejecutarse
        [unchanged] = [r for r in _unit_resources(api, headers, unit["id"]) if r["id"] == previous["id"]]
        assert (unchanged["status"], unchanged["version"]) == ("pendiente", 1)

        uncited_flag.unlink()
        retried = api.post(f"{url}/regenerations", headers=headers, json={"expectedVersion": 1})
        assert retried.status_code == 200, retried.text
        body = retried.json()
        assert body["status"] == "succeeded" and body["previousDiscarded"] is True
        [new_id] = body["newResourceIds"]

        attempts = {r["id"]: r["status"] for r in _regeneration_requests(api, headers, unit["id"])}
        assert len(attempts) == 2 and attempts[first_attempt["id"]] == "failed"
        assert sorted(attempts.values()) == ["failed", "succeeded"]
        by_id = {r["id"]: r for r in _unit_resources(api, headers, unit["id"])}
        assert by_id[previous["id"]]["status"] == "descartado"
        assert by_id[new_id]["regeneratedFrom"] == {"resourceId": previous["id"], "version": 1}
        assert api.get(f"{url}/regeneration", headers=headers).json()["status"] == "succeeded"


# PR #17 (revisión de Silvana): el id del pedido no se pierde y no se descarta el original si el nuevo ya no existe.


@pytest.fixture
def flaky_lookup_flag(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Archivo que, mientras existe, hace fallar una vez la consulta de un pedido de generación en el servidor."""
    flag = tmp_path / "falla-una-consulta"
    monkeypatch.setenv("E2E_APP_FACTORY", "tests.e2e.flaky_request_lookup_app:create_application")
    monkeypatch.setenv("E2E_FLAKY_LOOKUP_FLAG", str(flag))
    return flag


def test_a_temporary_failure_on_the_first_query_keeps_the_request_and_the_status_reaches_succeeded(
    flaky_lookup_flag, request: pytest.FixtureRequest
):
    server = request.getfixturevalue("server")
    with httpx.Client(base_url=server, timeout=90) as api:
        headers = _session(api, TEACHER_A)
        unit, previous = _generated_explanation(api, headers)
        url = f"/api/v1/units/{unit['id']}/resources/{previous['id']}"

        flaky_lookup_flag.touch()  # la primera consulta del pedido, dentro de la espera del adaptador, falla
        first = api.post(f"{url}/regenerations", headers=headers, json={"expectedVersion": 1})
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "running"
        assert not flaky_lookup_flag.exists()

        finished = _regeneration_finished(api, headers, url)
        assert finished["status"] == "succeeded" and finished["previousDiscarded"] is True
        [new_id] = finished["newResourceIds"]
        by_id = {r["id"]: r for r in _unit_resources(api, headers, unit["id"])}
        assert by_id[previous["id"]]["status"] == "descartado"
        assert by_id[new_id]["regeneratedFrom"] == {"resourceId": previous["id"], "version": 1}
        assert len(_regeneration_requests(api, headers, unit["id"])) == 1


def _regeneration_keys(database_url: str, unit_id: str) -> list[str]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return sorted(
                connection.execute(
                    text("SELECT idempotency_key FROM gen_generation_requests WHERE unit_id = :unit AND mode = 'regeneration'"),
                    {"unit": unit_id},
                ).scalars()
            )
    finally:
        engine.dispose()


def test_if_the_new_resource_is_deleted_before_the_query_the_original_is_kept_and_can_be_regenerated_again(
    no_wait_server: str, e2e_database_url: str
):
    with httpx.Client(base_url=no_wait_server, timeout=90) as api:
        headers = _session(api, TEACHER_A)
        unit, previous = _generated_explanation(api, headers)
        url = f"/api/v1/units/{unit['id']}/resources/{previous['id']}"

        assert api.post(f"{url}/regenerations", headers=headers, json={"expectedVersion": 1}).json()["status"] == "running"
        [attempt] = _regeneration_requests(api, headers, unit["id"])
        assert _wait_until_final(api, headers, attempt["id"])["status"] == "succeeded"
        [new] = [r for r in _unit_resources(api, headers, unit["id"]) if r.get("regeneratedFrom")]
        assert api.delete(f"/api/v1/units/{unit['id']}/resources/{new['id']}", headers=headers).status_code == 204

        status = api.get(f"{url}/regeneration", headers=headers).json()
        assert status["status"] == "failed" and status["code"] == "REGENERATED_RESOURCE_NOT_FOUND"
        assert status["previousDiscarded"] is False
        [original] = [r for r in _unit_resources(api, headers, unit["id"]) if r["id"] == previous["id"]]
        assert (original["status"], original["version"]) == ("pendiente", 1)

        again = api.post(f"{url}/regenerations", headers=headers, json={"expectedVersion": 1})
        assert again.status_code == 200 and again.json()["status"] == "running"
        assert _regeneration_keys(e2e_database_url, unit["id"]) == [
            f"regen-{previous['id']}-v1", f"regen-{previous['id']}-v1-r2",
        ]
