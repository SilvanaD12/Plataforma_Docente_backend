"""Recorrido real por HTTP: curso con sumilla y resultados, material procesado y generación con evidencia (RAG)."""

from __future__ import annotations

import json

import httpx

CREDENTIALS = {"email": "docente@5e.demo", "password": "Demo5E!2026"}

MATERIAL = (
    "Unidad 1: Protocolos de transporte\n\n"
    "El protocolo TCP es orientado a la conexión: establece la conexión con un saludo de tres vías y garantiza una entrega confiable. "
    "El protocolo UDP no establece conexión ni confirma la entrega; por eso es más rápido y se usa en videollamadas.\n\n"
    "El protocolo IP se encarga del direccionamiento y del enrutamiento de los paquetes. "
    "El enrutador es el dispositivo que decide por qué camino viaja cada paquete hasta llegar a su destino. "
    "La encapsulación es el proceso por el cual cada capa agrega su propio encabezado a los datos."
).encode()


def test_real_material_is_processed_and_generates_cited_resources(server: str):
    with httpx.Client(base_url=server, timeout=30) as api:
        h = {"Authorization": "Bearer " + api.post("/api/v1/sessions", json=CREDENTIALS).json()["token"]}
        assert api.get("/api/v1/generator").json()["usesAi"] is False
        course = api.post(
            "/api/v1/courses",
            headers=h,
            json={
                "code": "RED-E2E",
                "name": "Redes",
                "term": "2026-II",
                "summary": "Curso de redes de computadoras.",
                "learningGoal": "Explica cómo se comunican los equipos.",
                "units": [{"title": "Protocolos de transporte", "outcomes": [{"text": "Distingue TCP y UDP"}]}],
            },
        )
        assert course.status_code == 201, course.text
        unit = course.json()["units"][0]
        assert course.json()["summary"] == "Curso de redes de computadoras." and unit["outcomes"][0]["code"] == "RA1.1"

        context = {
            "unitId": unit["id"],
            "outcomeIds": [unit["outcomes"][0]["id"]],
            "documentType": "Separata o apuntes de clase",
            "suggestedStage": None,
            "usePermission": True,
        }
        uploaded = api.post(
            "/api/v1/documents",
            headers=h,
            files={"file": ("protocolos.txt", MATERIAL)},
            data={"context": json.dumps(context)},
        )
        assert uploaded.status_code == 201 and uploaded.json()["status"] == "registrado"
        processed = api.post(f"/api/v1/documents/{uploaded.json()['id']}/process", headers=h)
        assert processed.status_code == 200, processed.text
        assert processed.json()["status"] == "procesado" and processed.json()["fragmentCount"] >= 1
        chunks = api.get(f"/api/v1/documents/{uploaded.json()['id']}/chunks", headers=h).json()
        assert chunks[0]["location"] == "sección 1" and "protocolo TCP" in " ".join(f["text"] for f in chunks)

        request_body = {
            "unitId": unit["id"],
            "outcomeId": None,
            "stage": "evaluate",
            "resourceType": "item_opcion_multiple",
            "quantity": 2,
            "difficulty": "intermedia",
            "optionCount": 4,
            "topK": 8,
            "evidenceThreshold": 0.6,
            "instructions": "",
            "audience": "Tercer ciclo",
            "competency": "Pensamiento crítico",
            "modalities": ["Textual"],
        }
        response = api.post("/api/v1/generations", headers=h, json=request_body)
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["mode"] == "rag" and data["generator"]["usesAi"] is False
        ids = {f["id"] for f in data["fragments"]}
        # Lo recuperado incluye todo lo citado (la evaluación con Ragas lo usa como contexto).
        retrieved = {f["id"] for f in data["retrievedChunks"]}
        assert ids and ids <= retrieved and all(f["text"] for f in data["retrievedChunks"])
        for resource in data["resources"]:
            assert resource["source"] == "rag" and resource["status"] == "pendiente"
            assert all(set(c["fragmentIds"]) <= ids for c in resource["citations"])
            assert len(resource["options"]) == 4 and sum(o["isCorrect"] for o in resource["options"]) == 1
            # HU-016: cada afirmación se contrastó con la evidencia; el generador por reglas cita frases del material.
            # HU-019: cada distractor trae su justificación y el error conceptual que representa.
            assert all(o["feedback"] and o["misconception"] for o in resource["options"] if not o["isCorrect"])
            grounding = resource["grounding"]
            assert grounding["checkedClaims"] == len(resource["citations"]) == grounding["supportedClaims"]
        assert data["grounding"]["hallucinationRate"] == 0.0 and data["grounding"]["rejectedResources"] == []
        assert data["distractorReliability"]["evaluatedDistractors"] == 3 * len(data["resources"])
        assert api.get(f"/api/v1/generations/{data['request']['id']}", headers=h).json()["mode"] == "rag"

        explanation = api.post(
            "/api/v1/generations",
            headers=h,
            json={**request_body, "stage": "explain", "resourceType": "explicacion", "quantity": 1},
        )
        assert explanation.status_code == 200 and explanation.json()["resources"][0]["options"] is None

        assert api.delete(f"/api/v1/documents/{uploaded.json()['id']}", headers=h).status_code == 204
        without_material = api.post("/api/v1/generations", headers=h, json=request_body)
        assert without_material.status_code == 400 and without_material.json()["error"]["code"] == "NO_PROCESSED_MATERIAL"


def test_material_routes_validate_session_and_data(server: str):
    with httpx.Client(base_url=server, timeout=30) as api:
        assert api.post("/api/v1/documents/x/process").status_code == 401
        h = {"Authorization": "Bearer " + api.post("/api/v1/sessions", json=CREDENTIALS).json()["token"]}
        assert (
            api.post("/api/v1/documents/no-existe/process", headers=h).json()["error"]["code"]
            == "DOCUMENT_NOT_FOUND"
        )
        assert api.post("/api/v1/documents/from-topic", headers=h, json={"unitId": "u1", "topic": "ab"}).status_code == 422
        disabled_search = api.post("/api/v1/documents/from-topic", headers=h, json={"unitId": "u2", "topic": "redes"})
        assert disabled_search.status_code == 503 and disabled_search.json()["error"]["code"] == "TOPIC_SEARCH_UNAVAILABLE"

def test_secure_404_on_unauthorized_unit_access(server: str):
    """Valida el 404 seguro (MAT-C2) al intentar operar sobre unidades ajenas o inexistentes."""
    with httpx.Client(base_url=server, timeout=30) as api:
        h = {"Authorization": "Bearer " + api.post("/api/v1/sessions", json=CREDENTIALS).json()["token"]}
        
        # Intentar procesar o subir material a una unidad que no existe o no pertenece al scope
        response = api.post(
            "/api/v1/documents",
            headers=h,
            files={"file": ("invalido.txt", b"Contenido de prueba")},
            data={"context": json.dumps({
                "unitId": "unidad-inexistente-999",
                "outcomeIds": [],
                "documentType": "Separata o apuntes de clase",
                "usePermission": True
            })},
        )
        # El sistema debe denegar el acceso de forma segura con un 404 o 422 de membresía
        assert response.status_code in (404, 422)
        error_data = response.json()
        assert "error" in error_data

def test_search_evidence_isolation_and_t007_strict(server: str):
    """Valida aislamiento estricto entre dos docentes (con y sin unit_id) y MAT-C2 / T007."""
    with httpx.Client(base_url=server, timeout=30) as api:
        # 1. Crear docente A y su curso/unidad con resultado de aprendizaje
        reg_a = api.post(
            "/api/v1/accounts",
            json={"name": "Docente A", "email": "docente_a@test.pe", "password": "Password123!"},
        )
        assert reg_a.status_code == 201
        h_a = {"Authorization": f"Bearer {reg_a.json()['token']}"}

        course_a = api.post(
            "/api/v1/courses",
            headers=h_a,
            json={
                "code": "CUR-A",
                "name": "Curso A",
                "term": "2026-II",
                "summary": "Resumen curso A",
                "learningGoal": "Objetivo curso A",
                "units": [{"title": "Unidad A", "outcomes": [{"text": "Resultado A"}]}],
            },
        ).json()
        unit_a_id = course_a["units"][0]["id"]
        outcome_a_id = course_a["units"][0]["outcomes"][0]["id"]

        # 2. Crear docente B y su curso/unidad con resultado de aprendizaje
        reg_b = api.post(
            "/api/v1/accounts",
            json={"name": "Docente B", "email": "docente_b@test.pe", "password": "Password123!"},
        )
        assert reg_b.status_code == 201
        h_b = {"Authorization": f"Bearer {reg_b.json()['token']}"}

        course_b = api.post(
            "/api/v1/courses",
            headers=h_b,
            json={
                "code": "CUR-B",
                "name": "Curso B",
                "term": "2026-II",
                "summary": "Resumen curso B",
                "learningGoal": "Objetivo curso B",
                "units": [{"title": "Unidad B", "outcomes": [{"text": "Resultado B"}]}],
            },
        ).json()
        unit_b_id = course_b["units"][0]["id"]
        outcome_b_id = course_b["units"][0]["outcomes"][0]["id"]

        # 3. Subir y procesar material para Docente A
        doc_a_payload = {
            "unitId": unit_a_id,
            "outcomeIds": [outcome_a_id],
            "documentType": "Separata o apuntes de clase",
            "suggestedStage": None,
            "usePermission": True,
        }
        res_doc_a = api.post(
            "/api/v1/documents",
            headers=h_a,
            files={"file": ("protocolo_a.txt", b"Texto exclusivo del docente A sobre arquitectura de software TCP/IP")},
            data={"context": json.dumps(doc_a_payload)},
        )
        assert res_doc_a.status_code == 201, res_doc_a.text
        doc_a_id = res_doc_a.json()["id"]
        assert api.post(f"/api/v1/documents/{doc_a_id}/process", headers=h_a).status_code == 200

        # 4. Subir y procesar material para Docente B
        doc_b_payload = {
            "unitId": unit_b_id,
            "outcomeIds": [outcome_b_id],
            "documentType": "Separata o apuntes de clase",
            "suggestedStage": None,
            "usePermission": True,
        }
        res_doc_b = api.post(
            "/api/v1/documents",
            headers=h_b,
            files={"file": ("protocolo_b.txt", b"Texto exclusivo del docente B sobre redes avanzadas UDP")},
            data={"context": json.dumps(doc_b_payload)},
        )
        assert res_doc_b.status_code == 201, res_doc_b.text
        doc_b_id = res_doc_b.json()["id"]
        assert api.post(f"/api/v1/documents/{doc_b_id}/process", headers=h_b).status_code == 200

        # 5. Búsqueda con y sin unit_id para Docente A (aislamiento estricto)
        res_a_unit = api.get("/api/v1/documents/search", headers=h_a, params={"query": "docente", "unit_id": unit_a_id})
        assert res_a_unit.status_code == 200
        items_a_unit = res_a_unit.json()
        assert len(items_a_unit) > 0
        assert all("docente A" in item["text"] for item in items_a_unit)
        assert not any("docente B" in item["text"] for item in items_a_unit)

        res_a_no_unit = api.get("/api/v1/documents/search", headers=h_a, params={"query": "docente"})
        assert res_a_no_unit.status_code == 200
        items_a_no_unit = res_a_no_unit.json()
        assert len(items_a_no_unit) > 0
        assert all("docente A" in item["text"] for item in items_a_no_unit)
        assert not any("docente B" in item["text"] for item in items_a_no_unit)

        # 6. T007 / MAT-C2 estricto: unidad ajena real vs. unidad inexistente devuelven el mismo 404 y cuerpo
        payload_ajena = {
            "unitId": unit_b_id,
            "outcomeIds": [outcome_b_id],
            "documentType": "Separata o apuntes de clase",
            "suggestedStage": None,
            "usePermission": True,
        }
        res_ajena = api.post(
            "/api/v1/documents",
            headers=h_a,
            files={"file": ("invalido.txt", b"Contenido de prueba")},
            data={"context": json.dumps(payload_ajena)},
        )

        payload_inexistente = {
            "unitId": "unidad-no-existe-999",
            "outcomeIds": [outcome_a_id],
            "documentType": "Separata o apuntes de clase",
            "suggestedStage": None,
            "usePermission": True,
        }
        res_inexistente = api.post(
            "/api/v1/documents",
            headers=h_a,
            files={"file": ("invalido.txt", b"Contenido de prueba")},
            data={"context": json.dumps(payload_inexistente)},
        )

        assert res_ajena.status_code == 404
        assert res_inexistente.status_code == 404
        assert res_ajena.json() == res_inexistente.json()

        # Verificar que ninguno de los dos intentos guardó material
        docs_a = api.get("/api/v1/documents", headers=h_a).json()
        assert len(docs_a) == 1
        assert docs_a[0]["fileName"] == "protocolo_a.txt"