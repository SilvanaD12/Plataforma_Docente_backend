"""
Pruebas de límites de configuración docente, aislamiento de credenciales y consultas.
"""

from __future__ import annotations

import pytest

from platform5e.application.services.accounts.account_service import AccountService
from platform5e.domain.accounts.teacher_account import AccountConfigurationError
from tests.unit.test_application_services import MockAccountRepository


def test_injected_credentials_without_reading_the_environment(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_TEACHER_EMAIL", "ignorado@example.com")
    service = AccountService(MockAccountRepository(), " Docente@example.com ", " clave con espacios ")
    assert service.login("docente@example.com", " clave con espacios ")["email"] == "docente@example.com"
    with pytest.raises(AccountConfigurationError):
        service.login("docente@5e.demo", "Demo5E!2026")


def test_documents_and_history_queries_go_through_the_service():
    repo = MockAccountRepository()
    service = AccountService(repo, "docente@example.com", "clave")
    service.login("docente@example.com", "clave")
    assert service.list_courses("docente@example.com")[0]["id"] == "curso-1"
    repo.save_document("docente@example.com", {"id": "doc-1"}, b"original")
    assert service.list_documents("docente@example.com") == [{"id": "doc-1"}]
    assert service.get_document("docente@example.com", "doc-1") == ({"id": "doc-1"}, b"original")
    with pytest.raises(AccountConfigurationError) as err:
        service.get_document("otro@example.com", "doc-1")
    assert err.value.status_code == 404
    repo.get_history = lambda email: [{"createdAt": "2026-10-01"}, {"createdAt": "2026-10-09"}]
    assert service.list_generation_requests("docente@example.com")[0]["createdAt"] == "2026-10-09"
    service.delete_document("docente@example.com", "doc-1")
    assert service.list_documents("docente@example.com") == []
    with pytest.raises(AccountConfigurationError):
        service.delete_document("docente@example.com", "doc-1")

def test_settings_use_english_names_and_still_read_the_previous_spanish_ones():
    from platform5e.infrastructure.settings import read_flag, read_setting

    assert read_setting("LLM_API_KEY", "", {"LLM_API_KEY": "nueva", "IA_API_KEY": "vieja"}) == "nueva"
    assert read_setting("LLM_API_KEY", "", {"IA_API_KEY": "vieja"}) == "vieja"
    assert read_setting("LLM_MODEL", "por-defecto", {}) == "por-defecto"
    assert read_flag("TOPIC_SEARCH_ENABLED", True, {"BUSQUEDA_POR_TEMA": "false"}) is False
    assert read_flag("DEMO_CATALOG", False, {"DEMO_CATALOG": "TRUE"}) is True
