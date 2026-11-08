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