"""Datos guardados en Neon antes del contrato en inglés: se leen con las claves nuevas, sin migrar la base."""

from __future__ import annotations

from platform5e.infrastructure.persistence.repositories.sqlalchemy_account_repository import (
    adapt_legacy_course,
    adapt_legacy_document,
)
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_repository import (
    adapt_legacy_generation,
)


def test_old_course_keys_are_read_as_summary_and_learning_goal():
    course = adapt_legacy_course({"id": "c1", "code": "RED-301", "sumilla": "Redes.", "logro": "Explica redes."})
    assert course == {"id": "c1", "code": "RED-301", "summary": "Redes.", "learningGoal": "Explica redes."}
    assert adapt_legacy_course({"summary": "Ya nuevo"}) == {"summary": "Ya nuevo"}


def test_old_document_origin_and_generator_keys_are_translated():
    document = adapt_legacy_document(
        {"id": "d1", "origin": {"fuente": "Wikipedia", "url": "https://es.wikipedia.org/wiki/TCP", "licencia": "CC BY-SA 4.0", "tema": "TCP"}}
    )
    assert document["origin"] == {
        "source": "Wikipedia", "url": "https://es.wikipedia.org/wiki/TCP", "license": "CC BY-SA 4.0", "topic": "TCP"
    }
    assert adapt_legacy_document({"id": "d2", "origin": None}) == {"id": "d2", "origin": None}
    generation = adapt_legacy_generation({"mode": "rag", "generator": {"descripcion": "Gemini", "usaIA": True, "fallback": False}})
    assert generation["generator"] == {"description": "Gemini", "usesAi": True, "fallback": False}


# --------------------------------------------------------------------------- REV-01 · recursos sin verificación (REV-R11)

import copy  # noqa: E402

import pytest  # noqa: E402

from platform5e.application.services.review.legacy_verification import upgrade_resource_verification  # noqa: E402
from platform5e.domain.generation.grounding import DEFAULT_THRESHOLD  # noqa: E402
from platform5e.domain.review.export_eligibility import export_ineligibility  # noqa: E402

# La afirmación tiene 5 de sus 7 palabras útiles en el fragmento (≈0,71): pasa con 0,6 y no con 0,8.
CLAIM = "El protocolo TCP confirma la entrega ordenada de paquetes cifrados."
EVIDENCE = "El protocolo TCP confirma la entrega ordenada de los datos al receptor."


class StoredResources:
    def __init__(self, *resources: dict) -> None:
        self.by_id = {r["id"]: copy.deepcopy(r) for r in resources}
        self.saves: list[tuple[int, bool]] = []

    def save_resource_if_version(self, teacher_id, unit_id, resource, expected_version, increment=True) -> bool:
        self.saves.append((expected_version, increment))
        if self.by_id[resource["id"]].get("version", 1) != expected_version:
            return False
        self.by_id[resource["id"]] = copy.deepcopy(resource)
        return True


def old_resource(**overrides) -> dict:
    """Un recurso guardado antes de REV-01: sin `verification`, sin `version` y con la copia sin fecha de recuperación."""
    return {
        "id": "old-1", "unitId": "u1", "status": "aprobado", "decidedAt": "2026-10-01T10:00:00", "body": "Texto.",
        "citations": [{"claim": CLAIM, "fragmentIds": ["f1"]}],
        "evidence": [{"id": "f1", "text": EVIDENCE, "location": "página 1", "documentId": "d1", "documentName": "redes.pdf"}],
        **overrides,
    }


def test_a_copy_without_retrieval_dates_is_valid_and_the_date_is_recorded_as_unknown():
    """REV-R11: la falta de fecha de recuperación no invalida la copia; se registra como desconocida (`null`)."""
    repo = StoredResources(old_resource())
    upgraded = upgrade_resource_verification(repo, "ana", "u1", old_resource())
    assert upgraded["verification"]["status"] == "current" and upgraded["status"] == "aprobado"
    assert [fragment["retrievedAt"] for fragment in upgraded["evidence"]] == [None]
    assert repo.by_id["old-1"]["evidence"][0]["retrievedAt"] is None


def test_an_existing_retrieval_date_is_kept():
    resource = old_resource()
    resource["evidence"][0]["retrievedAt"] = "2026-09-30T12:00:00+00:00"
    upgraded = upgrade_resource_verification(StoredResources(resource), "ana", "u1", resource)
    assert upgraded["evidence"][0]["retrievedAt"] == "2026-09-30T12:00:00+00:00"


@pytest.mark.parametrize(
    ("stored", "threshold", "status", "review_status"),
    [
        pytest.param({}, DEFAULT_THRESHOLD, "current", "aprobado", id="sin-umbral-guardado-usa-el-general"),
        pytest.param({"params": {"evidenceThreshold": 0.8}}, 0.8, "insufficient", "pendiente", id="umbral-del-pedido"),
        pytest.param({"grounding": {"threshold": 0.8}}, 0.8, "insufficient", "pendiente", id="umbral-de-la-generacion"),
    ],
)
def test_the_stored_threshold_is_used_or_the_general_one(stored, threshold, status, review_status):
    """REV-R11: se verifica con el `evidenceThreshold` guardado si existe, o con `DEFAULT_THRESHOLD`."""
    resource = old_resource(**stored)
    upgraded = upgrade_resource_verification(StoredResources(resource), "ana", "u1", resource)
    assert upgraded["verification"]["evidenceThreshold"] == threshold
    assert upgraded["verification"]["status"] == status and upgraded["status"] == review_status


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda r: r.update(evidence=[]), id="sin-copia"),
        pytest.param(lambda r: r["evidence"][0].update(text=""), id="fragmento-sin-texto"),
        pytest.param(lambda r: r.update(citations=[{"claim": CLAIM, "fragmentIds": ["f9"]}]), id="fragmento-que-falta"),
    ],
)
def test_without_a_complete_copy_it_is_pending_cannot_be_retried_and_is_not_exported(change):
    """REV-R11: sin copia, o con un fragmento referenciado sin texto, queda pendiente y su única salida es regenerar."""
    resource = old_resource()
    change(resource)
    upgraded = upgrade_resource_verification(StoredResources(resource), "ana", "u1", resource)
    assert upgraded["verification"]["status"] == "pending" and upgraded["verification"]["retryAvailable"] is False
    assert upgraded["status"] == "pendiente" and upgraded["decidedAt"] is None
    assert export_ineligibility(upgraded) == "not_approved"


def test_the_update_keeps_the_version_and_happens_only_once():
    """D7: la actualización no cambia el contenido, así que no incrementa la versión; un recurso ya verificado no se toca."""
    repo = StoredResources(old_resource())
    upgraded = upgrade_resource_verification(repo, "ana", "u1", old_resource())
    assert upgraded["version"] == 1 and repo.saves == [(1, False)]
    assert upgrade_resource_verification(repo, "ana", "u1", upgraded) is upgraded
    assert repo.saves == [(1, False)]
