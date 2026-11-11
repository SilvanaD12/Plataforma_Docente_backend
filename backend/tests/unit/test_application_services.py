"""
Pruebas unitarias de la capa de aplicación con puertos falsos en memoria.

No usan base de datos ni HTTP: cada servicio recibe un repositorio falso que cumple su
puerto. Así se comprueba la regla de negocio aislada de los adaptadores (arquitectura
hexagonal, EN-004).
"""

from __future__ import annotations

from copy import deepcopy
import io
import time
from typing import Any
import zipfile

import pytest

from platform5e.application.ports.outbound.generation_repository_port import GenerationRepositoryPort
from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort
from platform5e.application.services.accounts.account_service import AccountService
from platform5e.application.use_cases.generation.get_legacy_generation import GetLegacyGeneration
from platform5e.domain.accounts.teacher_account import AccountConfigurationError
from platform5e.domain.generation.errors import GenerationError


# --------------------------------------------------------------------------- historial de la generación síncrona

class LegacyGenerationRepository(GenerationRepositoryPort):
    """Repositorio reducido (T046 parcial): solo el catálogo de demostración y las generaciones guardadas."""

    def __init__(self, saved: dict[str, dict[str, Any]] | None = None) -> None:
        self.saved = saved or {}

    def get_demo_catalog(self) -> dict[str, Any]:
        return {"units": []}

    def get_by_id(self, generation_id: str) -> dict[str, Any] | None:
        return self.saved.get(generation_id)


def test_a_saved_generation_is_returned_as_it_was_answered():
    stored = {"request": {"id": "sol-1"}, "mode": "rag", "resources": [{"id": "r1"}]}
    assert GetLegacyGeneration(LegacyGenerationRepository({"sol-1": stored})).get("sol-1") is stored


def test_get_missing_generation():
    with pytest.raises(GenerationError) as err:
        GetLegacyGeneration(LegacyGenerationRepository()).get("sol-no-existe")
    assert err.value.code == "GENERATION_NOT_FOUND"


# --------------------------------------------------------------------------- configuración (EP-002)

class MockAccountRepository(TeacherRepositoryPort):
    def __init__(self) -> None:
        self.sessions: dict[str, tuple[str, float]] = {}
        self.catalogs: dict[str, list[dict[str, Any]]] = {}
        self.docs: dict[tuple[str, str], tuple[dict[str, Any], bytes]] = {}
        self.owners: dict[str, str] = {}
        self.users: dict[str, dict[str, Any]] = {}
        self.deleted_entries: list[tuple[str, str, list[str]]] = []

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        return self.users.get(email)

    def create_user(self, user_data: dict[str, Any]) -> None:
        self.users[user_data["email"]] = user_data

    def delete_course(self, teacher_id: str, course_id: str, unit_ids: list[str]) -> None:
        self.catalogs[teacher_id] = [c for c in self.catalogs.get(teacher_id, []) if c["id"] != course_id]
        self.deleted_entries.append((teacher_id, course_id, unit_ids))

    def init_catalog(self, teacher_id: str) -> None:
        self.catalogs.setdefault(
            teacher_id,
            [
                {
                    "id": "curso-1",
                    "code": "ED-201",
                    "name": "Estructuras de datos",
                    "term": "2026-II",
                    "units": [
                        {
                            "id": "unidad-1",
                            "courseId": "curso-1",
                            "number": 1,
                            "title": "Pilas",
                            "outcomes": [{"id": "ra-1"}],
                        }
                    ],
                }
            ],
        )

    def save_session(self, fingerprint: str, teacher_id: str, expires_at: float) -> None:
        self.sessions[fingerprint] = (teacher_id, expires_at)

    def get_session(self, fingerprint: str) -> tuple[str, float] | None:
        return self.sessions.get(fingerprint)

    def delete_session(self, fingerprint: str) -> None:
        self.sessions.pop(fingerprint, None)

    def get_courses(self, teacher_id: str) -> list[dict[str, Any]]:
        return deepcopy(self.catalogs.get(teacher_id, []))

    def save_course(self, teacher_id: str, course_data: dict[str, Any]) -> None:
        courses = [c for c in self.catalogs.get(teacher_id, []) if c["id"] != course_data["id"]]
        self.catalogs[teacher_id] = courses + [course_data]

    def get_documents(self, teacher_id: str) -> list[dict[str, Any]]:
        return [metadata for (owner, _), (metadata, _) in self.docs.items() if owner == teacher_id]

    def save_document(self, teacher_id: str, metadata: dict[str, Any], content: bytes) -> None:
        self.docs[(teacher_id, metadata["id"])] = (metadata, content)

    def get_document(self, teacher_id: str, document_id: str) -> tuple[dict[str, Any], bytes] | None:
        return self.docs.get((teacher_id, document_id))

    def delete_document(self, teacher_id: str, document_id: str) -> None:
        self.docs.pop((teacher_id, document_id), None)

    def get_history(self, teacher_id: str) -> list[dict[str, Any]]:
        return []

    def get_generation_owner(self, generation_id: str) -> str | None:
        return self.owners.get(generation_id)


SEED_EMAIL: str = "docente@5e.demo"
SEED_PASSWORD: str = "Demo5E!2026"


@pytest.fixture(scope="module")
def base_account_service() -> AccountService:
    return AccountService(MockAccountRepository(), SEED_EMAIL, SEED_PASSWORD)


@pytest.fixture
def account_service(base_account_service: AccountService) -> AccountService:
    base_account_service.repository = MockAccountRepository()
    return base_account_service


def _get_bearer_header(service: AccountService) -> str:
    return "Bearer " + service.login(SEED_EMAIL, SEED_PASSWORD)["token"]


def _make_doc_context(**overrides) -> dict[str, Any]:
    base = {
        "unitId": "unidad-1",
        "usePermission": True,
        "documentType": "Guía de práctica",
        "outcomeIds": ["ra-1"],
    }
    return {**base, **overrides}


def _get_account_error_code(func, *args) -> str:
    with pytest.raises(AccountConfigurationError) as err:
        func(*args)
    return err.value.code


def test_login_authenticates_and_logs_out(account_service: AccountService):
    authorization = _get_bearer_header(account_service)
    assert account_service.authenticate_token(authorization) == SEED_EMAIL
    account_service.logout(authorization)
    assert _get_account_error_code(account_service.authenticate_token, authorization) == "SESSION_EXPIRED"


def test_invalid_credentials_and_sessions(account_service: AccountService):
    assert _get_account_error_code(account_service.login, SEED_EMAIL, "otra") == "INVALID_CREDENTIALS"
    assert _get_account_error_code(account_service.login, "otro@5e.demo", SEED_PASSWORD) == "INVALID_CREDENTIALS"
    assert _get_account_error_code(account_service.authenticate_token, None) == "SESSION_REQUIRED"
    assert _get_account_error_code(account_service.authenticate_token, "Token abc") == "SESSION_REQUIRED"

    authorization = _get_bearer_header(account_service)
    fingerprint = next(iter(account_service.repository.sessions))
    account_service.repository.sessions[fingerprint] = (SEED_EMAIL, time.time() - 1)
    assert _get_account_error_code(account_service.authenticate_token, authorization) == "SESSION_EXPIRED"


def test_unit_only_from_the_teachers_courses(account_service: AccountService):
    account_service.login(SEED_EMAIL, SEED_PASSWORD)
    assert account_service.get_unit(SEED_EMAIL, "unidad-1")["title"] == "Pilas"
    assert _get_account_error_code(account_service.get_unit, SEED_EMAIL, "unidad-ajena") == "UNIT_NOT_FOUND"


def test_create_and_edit_course(account_service: AccountService):
    account_service.login(SEED_EMAIL, SEED_PASSWORD)
    new_course = account_service.save_course(
        SEED_EMAIL,
        {
            "code": " ed-301 ",
            "name": "Grafos",
            "term": "2026-II",
            "units": [{"title": "Recorridos"}],
        },
    )
    assert new_course["code"] == "ED-301" and new_course["units"][0]["number"] == 1
    unit = new_course["units"][0]
    edited_course = account_service.save_course(
        SEED_EMAIL,
        {
            "code": "ED-301",
            "name": "Grafos II",
            "term": "2026-II",
            "units": [{"id": unit["id"], "title": "BFS y DFS"}, {"title": "Caminos"}],
        },
        new_course["id"],
    )
    assert [u["number"] for u in edited_course["units"]] == [1, 2]
    assert edited_course["units"][0]["id"] == unit["id"]


def test_catalog_rules(account_service: AccountService):
    account_service.login(SEED_EMAIL, SEED_PASSWORD)
    data = {"code": "ED-201", "name": "Copia", "term": "2026-II", "units": []}
    assert _get_account_error_code(account_service.save_course, SEED_EMAIL, data) == "DUPLICATE_CODE"
    assert (
        _get_account_error_code(account_service.save_course, SEED_EMAIL, {**data, "code": "X-1"}, "curso-no-existe")
        == "COURSE_NOT_FOUND"
    )
    without_units = {"code": "ED-201", "name": "Estructuras", "term": "2026-II", "units": []}
    assert _get_account_error_code(account_service.save_course, SEED_EMAIL, without_units, "curso-1") == "INVALID_UNITS"


def test_registers_valid_material(account_service: AccountService):
    account_service.login(SEED_EMAIL, SEED_PASSWORD)
    doc = account_service.register_document(SEED_EMAIL, "separata.pdf", b"%PDF-1.7 contenido", _make_doc_context())
    assert doc["kind"] == "pdf" and doc["status"] == "registrado" and doc["source"] == "backend"

    pptx_buffer = io.BytesIO()
    with zipfile.ZipFile(pptx_buffer, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("ppt/presentation.xml", "<p/>")

    assert (
        account_service.register_document(SEED_EMAIL, "clase.pptx", pptx_buffer.getvalue(), _make_doc_context())["kind"]
        == "pptx"
    )
    assert (
        account_service.register_document(SEED_EMAIL, "notas.txt", "Pilas y colas".encode(), _make_doc_context())["kind"]
        == "txt"
    )
    assert (
        _get_account_error_code(
            account_service.register_document, SEED_EMAIL, "SEPARATA.pdf", b"%PDF-1.7", _make_doc_context()
        )
        == "DUPLICATE_DOCUMENT"
    )


def test_rejects_invalid_material(account_service: AccountService):
    account_service.login(SEED_EMAIL, SEED_PASSWORD)
    test_cases = [
        ("a.pdf", b"%PDF-1", _make_doc_context(usePermission=False), "PERMISSION_REQUIRED"),
        ("a.pdf", b"%PDF-1", _make_doc_context(documentType="Otro"), "INVALID_TYPE"),
        ("a.pdf", b"%PDF-1", _make_doc_context(outcomeIds=["ra-ajeno"]), "INVALID_OUTCOME"),
        ("a.pdf", b"%PDF-1", _make_doc_context(outcomeIds=[]), "INVALID_OUTCOME"),
        ("../a.pdf", b"%PDF-1", _make_doc_context(), "INVALID_NAME"),
        ("a.docx", b"datos", _make_doc_context(), "INVALID_FORMAT"),
        ("a.pdf", b"", _make_doc_context(), "INVALID_SIZE"),
        ("a.pdf", b"no es pdf", _make_doc_context(), "INVALID_FORMAT"),
        ("a.pptx", b"no es zip", _make_doc_context(), "INVALID_FORMAT"),
        ("a.txt", b"\xff\xfe\x00", _make_doc_context(), "INVALID_FORMAT"),
    ]
    for filename, content, context, error_code in test_cases:
        assert (
            _get_account_error_code(account_service.register_document, SEED_EMAIL, filename, content, context)
            == error_code
        ), filename


def test_another_teachers_generation_is_not_exposed(account_service: AccountService):
    authorization = _get_bearer_header(account_service)
    account_service.repository.owners["sol-1"] = "otro@5e.demo"
    assert (
        _get_account_error_code(account_service.verify_generation_ownership, "sol-1", authorization)
        == "GENERATION_NOT_FOUND"
    )
    account_service.repository.owners["sol-2"] = SEED_EMAIL
    assert account_service.verify_generation_ownership("sol-2", authorization) is None
    assert account_service.verify_generation_ownership("sol-sin-dueño", None) is None