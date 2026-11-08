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
