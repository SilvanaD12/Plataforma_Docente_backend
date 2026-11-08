"""
Cuentas de docente, borrado de cursos y revisión persistida con dobles de prueba (test doubles).
"""

from typing import Any
import pytest

from platform5e.application.ports.outbound.resource_repository_port import ResourceReviewRepositoryPort
from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort
from platform5e.application.services.accounts.account_service import AccountService
from platform5e.application.services.review.resource_review_service import (
    ResourceReviewService,
    validate_approval_blockers,
)
from platform5e.domain.accounts.teacher_account import AccountConfigurationError

DEFAULT_EMAIL: str = "docente@5e.demo"
DEFAULT_PASSWORD: str = "Demo5E!2026"


class MockTeacherRepository(TeacherRepositoryPort):
    """Repositorio falso en memoria para pruebas de configuración y cuentas."""

    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, tuple[str, float]] = {}
        self.courses_db: dict[str, list[dict[str, Any]]] = {}
        self.documents_db: dict[str, list[dict[str, Any]]] = {}
        self.deleted_courses: list[tuple[str, str, list[str]]] = []
        self.initialized_catalogs: dict[str, bool] = {}

    def init_catalog(self, teacher_id: str) -> None:
        self.initialized_catalogs[teacher_id] = True

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        return self.users.get(email)

    def create_user(self, user_data: dict[str, Any]) -> None:
        self.users[user_data["email"]] = user_data

    def save_session(self, fingerprint: str, teacher_id: str, expires_at: float) -> None:
        self.sessions[fingerprint] = (teacher_id, expires_at)

    def get_session(self, fingerprint: str) -> tuple[str, float] | None:
        return self.sessions.get(fingerprint)

    def delete_session(self, fingerprint: str) -> None:
        self.sessions.pop(fingerprint, None)

    def get_courses(self, teacher_id: str) -> list[dict[str, Any]]:
        return self.courses_db.get(teacher_id, [])

    def save_course(self, teacher_id: str, course_data: dict[str, Any]) -> None:
        courses = self.courses_db.setdefault(teacher_id, [])
        for idx, item in enumerate(courses):
            if item["id"] == course_data["id"]:
                courses[idx] = course_data
                return
        courses.append(course_data)

    def delete_course(self, teacher_id: str, course_id: str, unit_ids: list[str]) -> None:
        courses = self.courses_db.get(teacher_id, [])
        self.courses_db[teacher_id] = [c for c in courses if c["id"] != course_id]
        self.deleted_courses.append((teacher_id, course_id, unit_ids))

    def get_documents(self, teacher_id: str) -> list[dict[str, Any]]:
        return self.documents_db.get(teacher_id, [])

    def save_document(self, teacher_id: str, metadata: dict[str, Any], content: bytes) -> None:
        self.documents_db.setdefault(teacher_id, []).append(metadata)

    def get_document(self, teacher_id: str, document_id: str) -> tuple[dict[str, Any], bytes] | None:
        return None

    def delete_document(self, teacher_id: str, document_id: str) -> None:
        docs = self.documents_db.get(teacher_id, [])
        self.documents_db[teacher_id] = [d for d in docs if d["id"] != document_id]

    def get_history(self, teacher_id: str) -> list[dict[str, Any]]:
        return []

    def get_generation_owner(self, generation_id: str) -> str | None:
        return None


@pytest.fixture(scope="module")
def base_account_service() -> AccountService:
    return AccountService(
        MockTeacherRepository(),
        seed_email=DEFAULT_EMAIL,
        seed_password=DEFAULT_PASSWORD,
        seed_demo_catalog=False,
    )


@pytest.fixture
def account_service(base_account_service: AccountService) -> AccountService:
    base_account_service.repository = MockTeacherRepository()
    return base_account_service


def get_error_info(func, *args) -> tuple[str, int]:
    with pytest.raises(AccountConfigurationError) as err:
        func(*args)
    return err.value.code, err.value.status_code


def test_register_opens_a_session_and_allows_signing_in_again(account_service: AccountService):
    session = account_service.register_account("  Ana   Pérez ", " Ana@Correo.pe ", "clave-segura")
    assert session["email"] == "ana@correo.pe" and session["name"] == "Ana Pérez" and session["token"]
    saved_user = account_service.repository.get_user_by_email("ana@correo.pe")
    assert "clave-segura" not in str(saved_user) and len(saved_user["sal"]) == 32
    assert account_service.authenticate_token("Bearer " + session["token"]) == "ana@correo.pe"
    assert account_service.login("ANA@correo.pe", "clave-segura")["name"] == "Ana Pérez"
    assert account_service.get_profile("ana@correo.pe") == {"email": "ana@correo.pe", "name": "Ana Pérez"}
    assert get_error_info(account_service.login, "ana@correo.pe", "otra-clave") == ("INVALID_CREDENTIALS", 401)


def test_register_validates_the_data(account_service: AccountService):
    account_service.register_account("Ana", "ana@correo.pe", "clave-segura")
    assert get_error_info(account_service.register_account, "Otra", "ana@correo.pe", "clave-segura") == ("ACCOUNT_EXISTS", 409)
    assert get_error_info(account_service.register_account, "Otra", DEFAULT_EMAIL, "clave-segura") == ("ACCOUNT_EXISTS", 409)
    assert get_error_info(account_service.register_account, "A", "b@correo.pe", "clave-segura")[0] == "INVALID_NAME"
    assert get_error_info(account_service.register_account, "Beto", "sin-arroba", "clave-segura")[0] == "INVALID_EMAIL"
    assert get_error_info(account_service.register_account, "Beto", "b@correo.pe", "corta")[0] == "WEAK_PASSWORD"


def test_bootstrap_account_works_without_sample_course(account_service: AccountService):
    session = account_service.login(DEFAULT_EMAIL, DEFAULT_PASSWORD)
    assert session["name"] == "Docente" and account_service.repository.initialized_catalogs == {}
    assert account_service.get_profile(DEFAULT_EMAIL)["name"] == "Docente"


def test_deleting_a_course_includes_its_units(account_service: AccountService):
    course = account_service.save_course(
        "ana@correo.pe",
        {
            "code": "red-301",
            "name": "Redes",
            "term": "2026-II",
            "units": [{"title": "Protocolos"}, {"title": "Subredes"}],
        },
    )
    account_service.delete_course("ana@correo.pe", course["id"])
    assert account_service.list_courses("ana@correo.pe") == []
    assert account_service.repository.deleted_courses == [
        ("ana@correo.pe", course["id"], [u["id"] for u in course["units"]])
    ]
    assert get_error_info(account_service.delete_course, "ana@correo.pe", course["id"]) == ("COURSE_NOT_FOUND", 404)


# --------------------------------------------------------------------------- revisión

class MockTeacherConfigRepository(TeacherRepositoryPort):
    def get_courses(self, teacher_id: str) -> list[dict[str, Any]]:
        return [{"id": "c1", "units": [{"id": "u1"}, {"id": "u2"}]}] if teacher_id == "ana" else []

    def init_catalog(self, teacher_id: str) -> None: ...
    def get_user_by_email(self, email: str) -> dict[str, Any] | None: return None
    def create_user(self, user_data: dict[str, Any]) -> None: ...
    def save_session(self, fingerprint: str, teacher_id: str, expires_at: float) -> None: ...
    def get_session(self, fingerprint: str) -> tuple[str, float] | None: return None
    def delete_session(self, fingerprint: str) -> None: ...
    def save_course(self, teacher_id: str, course_data: dict[str, Any]) -> None: ...
    def delete_course(self, teacher_id: str, course_id: str, unit_ids: list[str]) -> None: ...
    def get_documents(self, teacher_id: str) -> list[dict[str, Any]]: return []
    def save_document(self, teacher_id: str, metadata: dict[str, Any], content: bytes) -> None: ...
    def get_document(self, teacher_id: str, document_id: str) -> tuple[dict[str, Any], bytes] | None: return None
    def delete_document(self, teacher_id: str, document_id: str) -> None: ...
    def get_history(self, teacher_id: str) -> list[dict[str, Any]]: return []
    def get_generation_owner(self, generation_id: str) -> str | None: return None


class MockReviewRepository(ResourceReviewRepositoryPort):
    def __init__(self) -> None:
        self.resources: dict[tuple[str, str], dict[str, Any]] = {}
        self.downloads_list: list[tuple[str, str, dict[str, Any]]] = []

    def get_resources_by_unit(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        return [r for (d, _), r in self.resources.items() if d == teacher_id and r["unitId"] == unit_id]

    def get_resource_by_id(self, teacher_id: str, resource_id: str) -> dict[str, Any] | None:
        return self.resources.get((teacher_id, resource_id))

    def save_resources(self, teacher_id: str, unit_id: str, resources: list[dict[str, Any]]) -> None:
        for r in resources:
            self.resources[(teacher_id, r["id"])] = r

    def delete_resource(self, teacher_id: str, resource_id: str) -> None:
        self.resources.pop((teacher_id, resource_id), None)

    def get_downloads(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        return [d for (dd, u, d) in self.downloads_list if dd == teacher_id and u == unit_id]

    def save_download(self, teacher_id: str, unit_id: str, download_record: dict[str, Any]) -> None:
        self.downloads_list.append((teacher_id, unit_id, download_record))

    def delete_downloads(self, teacher_id: str, unit_id: str) -> None:
        self.downloads_list = [x for x in self.downloads_list if not (x[0] == teacher_id and x[1] == unit_id)]


def make_sample_item(rid: str = "r1", **overrides) -> dict[str, Any]:
    options = [
        {"id": f"{rid}:a", "text": "TCP", "isCorrect": True, "feedback": "Correcto.", "decision": "pendiente", "discardReason": None, "edited": False},
        {"id": f"{rid}:b", "text": "UDP", "isCorrect": False, "feedback": "No.", "decision": "pendiente", "discardReason": None, "edited": False},
        {"id": f"{rid}:c", "text": "IP", "isCorrect": False, "feedback": "No.", "decision": "pendiente", "discardReason": None, "edited": False},
        {"id": f"{rid}:d", "text": "DNS", "isCorrect": False, "feedback": "No.", "decision": "pendiente", "discardReason": None, "edited": False},
    ]
    return {
        "id": rid,
        "unitId": "u1",
        "title": "TCP o UDP",
        "body": "¿Cuál confirma la entrega?",
        "options": options,
        "status": "pendiente",
        "edited": False,
        "discardReason": None,
        "createdAt": "2026-10-10T10:00:00",
        "decidedAt": None,
        **overrides,
    }


def make_review_service(*resources) -> tuple[ResourceReviewService, MockReviewRepository]:
    repo = MockReviewRepository()
    repo.save_resources("ana", "u1", list(resources))
    return ResourceReviewService(MockTeacherConfigRepository(), repo), repo


def make_changes_dict(resource: dict[str, Any], decisions: dict[str, str] | None = None, **others) -> dict[str, Any]:
    options = (
        [
            {**o, "decision": (decisions or {}).get(o["id"][-1], o["decision"])}
            for o in resource["options"]
        ]
        if resource["options"]
        else None
    )
    return {
        "title": resource["title"],
        "body": resource["body"],
        "status": "pendiente",
        "discardReason": None,
        "edited": False,
        "options": options,
        **others,
    }


def test_listing_is_sorted_and_only_for_own_units():
    service, _ = make_review_service(make_sample_item("r1"), make_sample_item("r2", createdAt="2026-10-10T11:00:00"))
    assert [r["id"] for r in service.list_resources("ana", "u1")] == ["r2", "r1"]
    with pytest.raises(AccountConfigurationError) as error:
        service.list_resources("otro", "u1")
    assert error.value.status_code == 404


def test_approval_requires_deciding_distractors():
    resource = make_sample_item()
    service, repo = make_review_service(resource)
    with pytest.raises(AccountConfigurationError) as error:
        service.update_resource("ana", "u1", "r1", make_changes_dict(resource, status="aprobado"))
    assert error.value.code == "APPROVAL_BLOCKED" and "pendiente" in error.value.message

    partial = make_changes_dict(resource, {"b": "aceptado", "c": "descartado", "d": "descartado"}, status="aprobado")
    with pytest.raises(AccountConfigurationError) as error:
        service.update_resource("ana", "u1", "r1", partial)
    assert "al menos 2" in error.value.message

    approved = service.update_resource(
        "ana",
        "u1",
        "r1",
        make_changes_dict(resource, {"a": "aceptado", "b": "aceptado", "c": "aceptado", "d": "descartado"}, status="aprobado"),
    )
    assert approved["status"] == "aprobado" and approved["decidedAt"]
    assert approved["options"][0]["decision"] == "pendiente"
    assert repo.get_resource_by_id("ana", "r1")["status"] == "aprobado"

    reverted = service.update_resource("ana", "u1", "r1", make_changes_dict(approved))
    assert reverted["status"] == "pendiente" and reverted["decidedAt"] is None


def test_discard_saves_reason_and_edit():
    resource = make_sample_item()
    service, _ = make_review_service(resource)
    edited = service.update_resource(
        "ana",
        "u1",
        "r1",
        make_changes_dict(resource, title="Nuevo título", edited=True, status="descartado", discardReason="regenerado"),
    )
    assert edited["title"] == "Nuevo título" and edited["edited"] and edited["discardReason"] == "regenerado"

    without_reason = service.update_resource("ana", "u1", "r1", make_changes_dict(edited))
    assert without_reason["discardReason"] is None


@pytest.mark.parametrize(
    "bad_payload,expected_code",
    [
        ({"status": "otro"}, "INVALID_STATUS"),
        ({"discardReason": "inventado"}, "INVALID_REASON"),
        ({"options": []}, "INVALID_OPTIONS"),
        ({"options": None}, "INVALID_OPTIONS"),
    ],
)
def test_update_rejects_invalid_data(bad_payload, expected_code):
    resource = make_sample_item()
    service, _ = make_review_service(resource)
    with pytest.raises(AccountConfigurationError) as error:
        service.update_resource("ana", "u1", "r1", {**make_changes_dict(resource), **bad_payload})
    assert error.value.code == expected_code


def test_invalid_decision_on_an_option():
    resource = make_sample_item()
    service, _ = make_review_service(resource)
    incoming = make_changes_dict(resource)
    incoming["options"][1] = {**incoming["options"][1], "decision": "quizas"}
    with pytest.raises(AccountConfigurationError) as error:
        service.update_resource("ana", "u1", "r1", incoming)
    assert error.value.code == "INVALID_DECISION"


def test_resource_without_options_and_resource_from_another_unit():
    explanation = {**make_sample_item("r9"), "options": None}
    service, _ = make_review_service(explanation)
    approved = service.update_resource("ana", "u1", "r9", make_changes_dict(explanation, status="aprobado"))
    assert approved["status"] == "aprobado" and approved["options"] is None

    with pytest.raises(AccountConfigurationError) as error:
        service.update_resource("ana", "u2", "r9", make_changes_dict(explanation))
    assert error.value.code == "RESOURCE_NOT_FOUND"

    service.delete_resource("ana", "u1", "r9")
    assert service.list_resources("ana", "u1") == []


def test_approval_blockers():
    assert validate_approval_blockers({"body": " ", "options": None}) == ["El contenido no puede estar vacío."]
    without_key = make_sample_item()
    without_key["options"] = [{**o, "isCorrect": False, "decision": "aceptado"} for o in without_key["options"]]
    assert validate_approval_blockers(without_key) == ["La pregunta necesita una respuesta correcta."]


def test_download_history():
    service, _ = make_review_service()
    first = service.register_download(
        "ana", "u1", {"format": "moodle_xml", "fileName": "red-301-unidad-1.xml", "resourceCount": 2}
    )
    service.register_download("ana", "u2", {"format": "documento", "fileName": "otra.html", "resourceCount": 1})
    assert [d["id"] for d in service.get_downloads_history("ana", "u1")] == [first["id"]]

    with pytest.raises(AccountConfigurationError) as error:
        service.register_download("ana", "u1", {"format": "pdf", "fileName": "x.pdf", "resourceCount": 1})
    assert error.value.code == "INVALID_FORMAT"

    service.clear_downloads_history("ana", "u1")
    assert service.get_downloads_history("ana", "u1") == [] and len(service.get_downloads_history("ana", "u2")) == 1


def test_without_bootstrap_account_only_registered_accounts_sign_in():
    service = AccountService(MockTeacherRepository(), "", "", seed_demo_catalog=False)
    assert get_error_info(service.login, "", "") == ("INVALID_CREDENTIALS", 401)
    assert get_error_info(service.login, DEFAULT_EMAIL, DEFAULT_PASSWORD) == ("INVALID_CREDENTIALS", 401)
    service.register_account("Ana", "ana@correo.pe", "clave-segura")
    assert service.login("ana@correo.pe", "clave-segura")["name"] == "Ana"


def test_summary_counts_approved_and_pending_per_unit():
    service, _ = make_review_service(
        make_sample_item("r1"),
        make_sample_item("r2", status="aprobado"),
        make_sample_item("r3", status="descartado"),
    )
    assert service.get_summary("ana") == [
        {"courseId": "c1", "unitId": "u1", "approved": 1, "pending": 1},
        {"courseId": "c1", "unitId": "u2", "approved": 0, "pending": 0},
    ]
    assert service.get_summary("otro") == []