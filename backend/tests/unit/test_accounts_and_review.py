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

    def save_resource_if_version(
        self, teacher_id: str, unit_id: str, resource: dict[str, Any], expected_version: int, increment: bool = True
    ) -> bool:
        current = self.resources.get((teacher_id, resource["id"]))
        if current is None or current.get("version", 1) != expected_version:
            return False
        self.resources[(teacher_id, resource["id"])] = {
            **resource,
            "version": expected_version + 1 if increment else expected_version,
        }
        return True

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
        # REV-01: afirmación y copia histórica que la respalda, como en los recursos de Generación.
        "citations": [{"claim": "El protocolo TCP confirma la entrega de los datos.", "fragmentIds": ["frag-sample"]}],
        "evidence": [{"id": "frag-sample", "text": "El protocolo TCP confirma la entrega de los datos al receptor.",
                      "location": "página 1", "documentId": "d1", "documentName": "redes.pdf"}],
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
        "expectedVersion": resource.get("version", 1),
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
    # REV-01: los registros los crea la exportación (un registro por archivo); el POST manual se retiró.
    service, repo = make_review_service()
    first = {"id": "descarga-1", "unitId": "u1", "format": "moodle_xml", "fileName": "red-301-unidad-1.xml",
             "resourceCount": 2, "createdAt": "2026-11-08T10:00:00+00:00"}
    repo.save_download("ana", "u1", first)
    repo.save_download("ana", "u2", {"id": "descarga-2", "unitId": "u2", "format": "documento", "fileName": "otra.html",
                                     "resourceCount": 1, "createdAt": "2026-11-08T11:00:00+00:00"})
    assert [d["id"] for d in service.get_downloads_history("ana", "u1")] == [first["id"]]

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


# --------------------------------------------------------------------------- REV-01 · guardar con versión y verificar

import copy  # noqa: E402

from platform5e.domain.generation.grounding import VERIFICATION_RULE_VERSION  # noqa: E402
from platform5e.domain.review.content_fingerprint import content_fingerprint  # noqa: E402
from platform5e.domain.review.resource_verification import verify_resource  # noqa: E402

FRAGMENT_TCP = "frag-tcp"
FRAGMENT_UDP = "frag-udp"
EVIDENCE_TCP = (
    "Los dos protocolos principales de esta capa en Internet son TCP y UDP. El protocolo TCP está orientado a la "
    "conexión y garantiza la entrega ordenada de los datos."
)
EVIDENCE_UDP = "UDP tiene menor latencia que TCP porque no espera confirmaciones ni retransmite datos."
UNSUPPORTED_TEXT = "Los satélites geoestacionarios orbitan sobre el ecuador terrestre a gran altura."


def make_verified_explanation(rid: str = "rx", **overrides: Any) -> dict[str, Any]:
    resource = {
        "id": rid,
        "unitId": "u1",
        "type": "explicacion",
        "format": "text",
        "title": "TCP y UDP",
        "body": "Los dos protocolos principales de esta capa en Internet son TCP y UDP.\n\n"
        "UDP tiene menor latencia que TCP porque no espera confirmaciones ni retransmite datos.",
        "bodyHtml": None,
        "structure": None,
        "options": None,
        "citations": [
            {"claim": "Los dos protocolos principales de esta capa en Internet son TCP y UDP.", "fragmentIds": [FRAGMENT_TCP]},
            {"claim": "UDP tiene menor latencia que TCP porque no espera confirmaciones ni retransmite datos.",
             "fragmentIds": [FRAGMENT_UDP]},
        ],
        "evidence": [
            {"id": FRAGMENT_TCP, "text": EVIDENCE_TCP, "location": "sección 1", "documentId": "d1", "documentName": "m.txt"},
            {"id": FRAGMENT_UDP, "text": EVIDENCE_UDP, "location": "sección 1", "documentId": "d1", "documentName": "m.txt"},
        ],
        "grounding": {"threshold": 0.6},
        "status": "pendiente",
        "edited": False,
        "discardReason": None,
        "createdAt": "2026-11-08T10:00:00",
        "decidedAt": None,
        "version": 1,
    }
    resource.update(overrides)
    resource["verification"] = verify_resource(resource, threshold=0.6, rule_version=VERIFICATION_RULE_VERSION)
    return resource


def make_versioned_service(*resources: dict[str, Any]) -> tuple[ResourceReviewService, MockReviewRepository]:
    repo = MockReviewRepository()
    repo.save_resources("ana", "u1", [copy.deepcopy(r) for r in resources])
    return ResourceReviewService(MockTeacherConfigRepository(), repo), repo


def save_changes(resource: dict[str, Any], **others: Any) -> dict[str, Any]:
    return {
        "title": resource["title"],
        "body": resource["body"],
        "status": resource["status"],
        "discardReason": None,
        "edited": False,
        "expectedVersion": resource.get("version", 1),
        **others,
    }


def test_saving_requires_the_version_it_starts_from():
    """REV-R12: cada guardado indica la versión de contenido de la que parte."""
    resource = make_verified_explanation()
    service, _ = make_versioned_service(resource)
    changes = save_changes(resource)
    del changes["expectedVersion"]
    with pytest.raises(AccountConfigurationError) as error:
        service.update_resource("ana", "u1", "rx", changes)
    assert error.value.code == "VERSION_REQUIRED" and error.value.status_code == 422


def test_saving_from_an_outdated_version_is_a_conflict_and_changes_nothing():
    """REV-C14: un guardado que parte de una versión anterior se rechaza sin tocar el recurso ni su verificación."""
    resource = make_verified_explanation(version=4)
    service, repo = make_versioned_service(resource)
    before = copy.deepcopy(repo.get_resource_by_id("ana", "rx"))
    with pytest.raises(AccountConfigurationError) as error:
        service.update_resource("ana", "u1", "rx", save_changes(resource, body=UNSUPPORTED_TEXT, expectedVersion=3))
    assert error.value.code == "VERSION_CONFLICT" and error.value.status_code == 409
    assert repo.get_resource_by_id("ana", "rx") == before


def test_two_saves_from_the_same_version_conflict():
    """REV-C14: dos pestañas parten de la misma versión; la segunda debe recargar."""
    resource = make_verified_explanation()
    service, _ = make_versioned_service(resource)
    first = service.update_resource("ana", "u1", "rx", save_changes(resource, title="Primera pestaña"))
    assert first["version"] == 2
    with pytest.raises(AccountConfigurationError) as error:
        service.update_resource("ana", "u1", "rx", save_changes(resource, title="Segunda pestaña"))
    assert error.value.code == "VERSION_CONFLICT"



def test_approving_from_an_outdated_version_is_a_conflict_before_checking_the_approval():
    """REV-C14: aprobar desde la versión 1 cuando ya existe la 2 responde VERSION_CONFLICT, no APPROVAL_BLOCKED.

    El contenido enviado no tiene respaldo (bloquearía la aprobación), pero la versión se compara antes de evaluarla.
    """
    resource = make_verified_explanation()
    service, repo = make_versioned_service(resource)
    service.update_resource("ana", "u1", "rx", save_changes(resource, title="Primera pestaña"))
    before = copy.deepcopy(repo.get_resource_by_id("ana", "rx"))
    with pytest.raises(AccountConfigurationError) as error:
        service.update_resource(
            "ana", "u1", "rx", save_changes(resource, body=UNSUPPORTED_TEXT, status="aprobado", expectedVersion=1)
        )
    assert error.value.code == "VERSION_CONFLICT" and error.value.status_code == 409
    assert repo.get_resource_by_id("ana", "rx") == before


def test_a_save_that_loses_the_race_after_reading_is_still_a_conflict():
    """REV-C14: si otra pestaña guarda entre la lectura y la escritura, el UPDATE condicional rechaza el guardado."""
    resource = make_verified_explanation()
    service, repo = make_versioned_service(resource)
    stale = copy.deepcopy(repo.get_resource_by_id("ana", "rx"))
    service.update_resource("ana", "u1", "rx", save_changes(resource, title="Otra pestaña"))
    saved = copy.deepcopy(repo.get_resource_by_id("ana", "rx"))
    repo.get_resource_by_id = lambda teacher_id, resource_id: copy.deepcopy(stale)  # la lectura llegó antes
    with pytest.raises(AccountConfigurationError) as error:
        service.update_resource("ana", "u1", "rx", save_changes(resource, title="Esta pestaña"))
    assert error.value.code == "VERSION_CONFLICT"
    assert repo.resources[("ana", "rx")] == saved


def test_save_without_changing_the_fingerprint_keeps_the_verification():
    """REV-C2: un cambio de formato o de título no vuelve a verificar; la versión sí avanza."""
    resource = make_verified_explanation()
    service, repo = make_versioned_service(resource)
    saved = service.update_resource(
        "ana", "u1", "rx",
        save_changes(resource, title="Otro título", bodyHtml="<p><strong>Los dos protocolos</strong>…</p>", edited=True),
    )
    assert saved["verification"] == resource["verification"]  # mismo resultado, sin recalcular
    assert saved["version"] == 2 and saved["reviewReset"] is False
    stored = repo.get_resource_by_id("ana", "rx")
    assert stored["evidence"] == resource["evidence"] and "reviewReset" not in stored



FORMATTED = "<p><strong>Los dos protocolos</strong> principales son TCP y UDP.</p>"
NEW_BODY = "Los dos protocolos principales de esta capa en Internet son TCP y UDP."


@pytest.mark.parametrize(
    "body_html_change",
    [pytest.param({}, id="sin-bodyHtml"), pytest.param({"bodyHtml": FORMATTED}, id="bodyHtml-viejo")],
)
def test_changing_the_body_without_new_formatting_clears_the_stored_html(body_html_change):
    """Revisión de Silvana (PR #6): si cambia el cuerpo y no llega un bodyHtml nuevo, el HTML guardado se borra para
    que la revisión y los exportadores usen el cuerpo nuevo y no el texto anterior."""
    resource = make_verified_explanation(bodyHtml=FORMATTED)
    service, repo = make_versioned_service(resource)
    saved = service.update_resource("ana", "u1", "rx", save_changes(resource, body=NEW_BODY, edited=True, **body_html_change))
    assert saved["bodyHtml"] is None
    assert repo.get_resource_by_id("ana", "rx")["bodyHtml"] is None and repo.get_resource_by_id("ana", "rx")["body"] == NEW_BODY


def test_changing_the_body_with_new_formatting_keeps_the_new_html():
    resource = make_verified_explanation(bodyHtml=FORMATTED)
    service, repo = make_versioned_service(resource)
    new_html = "<p><em>Los dos protocolos</em> principales de esta capa en Internet son TCP y UDP.</p>"
    service.update_resource("ana", "u1", "rx", save_changes(resource, body=NEW_BODY, bodyHtml=new_html, edited=True))
    assert repo.get_resource_by_id("ana", "rx")["bodyHtml"] == new_html


def test_keeping_the_body_keeps_the_stored_html():
    """Un cambio de título sin bodyHtml conserva el formato guardado."""
    resource = make_verified_explanation(bodyHtml=FORMATTED)
    service, repo = make_versioned_service(resource)
    service.update_resource("ana", "u1", "rx", save_changes(resource, title="Otro título", edited=True))
    assert repo.get_resource_by_id("ana", "rx")["bodyHtml"] == FORMATTED


def test_content_change_is_verified_again_against_the_stored_copy():
    """REV-C1: el cambio de una afirmación respaldada se comprueba al guardar y el resultado queda para esa versión."""
    resource = make_verified_explanation()
    service, repo = make_versioned_service(resource)
    saved = service.update_resource(
        "ana", "u1", "rx", save_changes(resource, body=f"{UNSUPPORTED_TEXT}\n\n{UNSUPPORTED_TEXT} Otra vez.")
    )
    verification = saved["verification"]
    assert verification["status"] == "insufficient" and verification["reason"]
    assert verification["fingerprint"] == content_fingerprint(saved) != resource["verification"]["fingerprint"]
    assert verification["verifiedVersion"] == 2 == saved["version"] and verification["evidenceThreshold"] == 0.6
    assert repo.get_resource_by_id("ana", "rx")["verification"] == verification
    assert repo.get_resource_by_id("ana", "rx")["evidence"] == resource["evidence"]  # la copia histórica no cambia


def test_editing_an_approved_resource_sends_it_back_to_review():
    """REV-C1: un recurso aprobado que cambia su contenido respaldado requiere una nueva aprobación manual."""
    resource = make_verified_explanation(status="aprobado", decidedAt="2026-11-08T11:00:00")
    service, repo = make_versioned_service(resource)
    new_body = "Los dos protocolos principales de esta capa en Internet son TCP y UDP."
    saved = service.update_resource("ana", "u1", "rx", save_changes(resource, body=new_body, status="aprobado"))
    assert saved["status"] == "pendiente" and saved["reviewReset"] is True and saved["decidedAt"] is None
    assert saved["verification"]["status"] == "current"
    assert repo.get_resource_by_id("ana", "rx")["status"] == "pendiente"

    approved_again = service.update_resource("ana", "u1", "rx", save_changes(saved, status="aprobado"))
    assert approved_again["status"] == "aprobado" and approved_again["reviewReset"] is False


def test_a_result_for_another_fingerprint_is_recomputed_when_saving():
    """REV-C5: un resultado guardado para otra versión del contenido no se reutiliza."""
    resource = make_verified_explanation()
    resource["verification"] = {**resource["verification"], "fingerprint": "sha256:" + "0" * 64}
    service, _ = make_versioned_service(resource)
    saved = service.update_resource("ana", "u1", "rx", save_changes(resource))
    assert saved["verification"]["fingerprint"] == content_fingerprint(saved)
    assert saved["verification"]["status"] == "current"


def test_resource_without_a_stored_version_starts_at_version_one():
    """Los recursos guardados antes de REV-01 no tienen `version`: cuentan como versión 1."""
    resource = make_verified_explanation()
    del resource["version"]
    service, _ = make_versioned_service(resource)
    saved = service.update_resource("ana", "u1", "rx", save_changes(resource, expectedVersion=1))
    assert saved["version"] == 2


def test_saving_never_touches_the_stored_evidence_copy():
    """REV-C6: la copia histórica no depende del índice del material; reprocesarlo no la cambia."""
    resource = make_verified_explanation()
    service, repo = make_versioned_service(resource)
    service.update_resource("ana", "u1", "rx", save_changes(resource, body=UNSUPPORTED_TEXT))
    assert repo.get_resource_by_id("ana", "rx")["evidence"] == resource["evidence"]


# --------------------------------------------------------------------------- REV-01 · bloque c) bloqueos y reintento

from platform5e.application.services.review import resource_review_service as review_module  # noqa: E402
from platform5e.application.services.review.resource_review_service import (  # noqa: E402
    approval_blockers,
    verification_blockers,
)


def pending_from_generation(resource: dict[str, Any], retry: bool = True) -> dict[str, Any]:
    """Un recurso que Generación entrega sin poder completar la verificación (REV-C11)."""
    return {
        **resource,
        "verification": {
            **resource["verification"],
            "status": "pending",
            "reason": "La comprobación no pudo completarse durante la generación.",
            "retryAvailable": retry,
            "summary": {},
        },
    }


def test_missing_verification_is_not_a_blocker_because_saving_computes_it():
    """Opción A: sin `verification` (p. ej. la respuesta de Generación) no hay bloqueo que mostrar; al guardar, el
    servicio verifica la versión editada antes de evaluar la aprobación."""
    resource = make_verified_explanation()
    del resource["verification"]
    assert verification_blockers(resource) == []


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        pytest.param(lambda r: r["verification"].update(fingerprint="sha256:" + "0" * 64), "otra versión", id="otra-huella"),
        pytest.param(lambda r: r["verification"].update(status="insufficient", reason="Sin respaldo en el material."),
                     "Sin respaldo en el material.", id="insuficiente"),
        pytest.param(lambda r: r["verification"].update(status="pending", reason="No se pudo completar."),
                     "No se pudo completar.", id="pendiente"),
    ],
)
def test_verification_blocks_approval_with_its_reason(change, expected):
    """REV-C3 y REV-C5: sin verificación vigente para el contenido actual no se puede aprobar, y se dice por qué."""
    resource = make_verified_explanation()
    assert verification_blockers(resource) == [] and approval_blockers(resource) == []
    change(resource)
    reasons = verification_blockers(resource)
    assert len(reasons) == 1 and expected in reasons[0]
    assert reasons[0] in approval_blockers(resource)


def test_pedagogical_rules_are_unchanged_and_combined_with_verification():
    """`validate_approval_blockers` conserva sus reglas; `approval_blockers` agrega la de verificación."""
    resource = make_verified_explanation(body=" ")
    assert validate_approval_blockers(resource) == ["El contenido no puede estar vacío."]
    assert approval_blockers(resource)[0] == "El contenido no puede estar vacío."


def test_approval_is_checked_against_the_verification_of_the_edited_version():
    """El bloqueo se evalúa con la verificación de la versión editada, no con la que tenía guardada."""
    resource = make_verified_explanation()
    service, repo = make_versioned_service(resource)
    with pytest.raises(AccountConfigurationError) as error:
        service.update_resource("ana", "u1", "rx", save_changes(resource, body=UNSUPPORTED_TEXT, status="aprobado"))
    assert error.value.code == "APPROVAL_BLOCKED" and "respaldo" in error.value.message.lower()
    assert repo.get_resource_by_id("ana", "rx")["version"] == 1  # el guardado bloqueado no cambia nada

    stale = pending_from_generation(make_verified_explanation())
    service, _ = make_versioned_service(stale)
    fixed = service.update_resource(
        "ana", "u1", "rx", save_changes(stale, body="Los dos protocolos principales de esta capa en Internet son TCP y UDP.",
                                        status="aprobado")
    )
    assert fixed["status"] == "aprobado" and fixed["verification"]["status"] == "current"


def test_resource_delivered_pending_by_generation_cannot_be_approved():
    """REV-C11: un recurso que llega pendiente se trata como uno editado sin verificar."""
    resource = pending_from_generation(make_verified_explanation())
    service, _ = make_versioned_service(resource)
    with pytest.raises(AccountConfigurationError) as error:
        service.update_resource("ana", "u1", "rx", save_changes(resource, status="aprobado"))
    assert error.value.code == "APPROVAL_BLOCKED" and "pendiente" in error.value.message.lower()


def test_retrying_a_pending_check_uses_the_stored_threshold_and_the_current_rule():
    """REV-C3: «Reintentar comprobación» verifica la misma versión con la copia histórica, sin editar."""
    resource = pending_from_generation(make_verified_explanation())
    resource["verification"]["evidenceThreshold"] = 0.55
    resource["verification"]["ruleVersion"] = 0
    service, repo = make_versioned_service(resource)
    checked = service.retry_verification("ana", "u1", "rx", expected_version=1)
    verification = checked["verification"]
    assert verification["status"] == "current" and verification["evidenceThreshold"] == 0.55
    assert verification["ruleVersion"] == VERIFICATION_RULE_VERSION
    assert checked["version"] == 1 and checked["body"] == resource["body"]  # misma versión del contenido
    assert repo.get_resource_by_id("ana", "rx")["verification"] == verification


@pytest.mark.parametrize(
    ("resource", "expected_version", "code"),
    [
        pytest.param(make_verified_explanation(), 1, "VERIFICATION_NOT_PENDING", id="vigente"),
        pytest.param({**pending_from_generation(make_verified_explanation(), retry=False), "evidence": []}, 1,
                     "REGENERATION_REQUIRED", id="copia-incompleta"),
        pytest.param(pending_from_generation(make_verified_explanation()), 7, "VERSION_CONFLICT", id="version-obsoleta"),
    ],
)
def test_retry_is_only_offered_for_pending_checks_with_a_complete_copy(resource, expected_version, code):
    service, repo = make_versioned_service(resource)
    before = copy.deepcopy(repo.get_resource_by_id("ana", "rx"))
    with pytest.raises(AccountConfigurationError) as error:
        service.retry_verification("ana", "u1", "rx", expected_version=expected_version)
    assert error.value.code == code and error.value.status_code == 409
    assert repo.get_resource_by_id("ana", "rx") == before


def test_retry_respects_unit_isolation():
    service, _ = make_versioned_service(pending_from_generation(make_verified_explanation()))
    with pytest.raises(AccountConfigurationError) as error:
        service.retry_verification("otro", "u1", "rx", expected_version=1)
    assert error.value.status_code == 404


def test_a_rule_change_without_edits_keeps_the_state(monkeypatch):
    """REV-C10: si cambia la regla en el código y el recurso no se edita, conserva su estado y sigue aprobable."""
    resource = make_verified_explanation()
    service, _ = make_versioned_service(resource)
    monkeypatch.setattr(review_module, "VERIFICATION_RULE_VERSION", VERIFICATION_RULE_VERSION + 1)
    approved = service.update_resource("ana", "u1", "rx", save_changes(resource, title="Mismo contenido", status="aprobado"))
    assert approved["status"] == "aprobado"
    assert approved["verification"] == resource["verification"]  # no se recalcula


def test_after_a_rule_change_an_edit_that_changes_the_result_says_the_rule_changed(monkeypatch):
    """REV-C10: al editar se verifica con la regla vigente y, si el resultado cambia, el motivo lo indica."""
    resource = make_verified_explanation()
    service, _ = make_versioned_service(resource)
    new_rule = VERIFICATION_RULE_VERSION + 1
    monkeypatch.setattr(review_module, "VERIFICATION_RULE_VERSION", new_rule)
    saved = service.update_resource("ana", "u1", "rx", save_changes(resource, body=UNSUPPORTED_TEXT))
    verification = saved["verification"]
    assert verification["status"] == "insufficient" and verification["ruleVersion"] == new_rule
    assert f"v{VERIFICATION_RULE_VERSION} → v{new_rule}" in verification["reason"]


# --------------------------------------------------------------------------- REV-01 · verificar al leer (parte de T048)

def without_verification(resource: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in resource.items() if key != "verification"}


def test_reading_a_resource_without_verification_checks_it_once_without_changing_its_version():
    """D7: los recursos sin `verification` se verifican al leerlos y se guardan sin incrementar la versión."""
    service, repo = make_versioned_service(without_verification(make_verified_explanation(version=3)))
    listed = service.list_resources("ana", "u1")[0]
    assert listed["verification"]["status"] == "current" and listed["version"] == 3
    stored = repo.get_resource_by_id("ana", "rx")
    assert stored["verification"] == listed["verification"] and stored["version"] == 3
    assert service.get_resource("ana", "u1", "rx")["verification"] == listed["verification"]  # no se recalcula


@pytest.mark.parametrize(
    ("changes", "status", "verification_status"),
    [
        pytest.param({}, "aprobado", "current", id="aprobado-vigente-sigue-aprobado"),
        pytest.param({"citations": [{"claim": UNSUPPORTED_TEXT, "fragmentIds": [FRAGMENT_TCP]}]}, "pendiente", "insufficient",
                     id="aprobado-insuficiente-vuelve-a-revision"),
        pytest.param({"evidence": []}, "pendiente", "pending", id="aprobado-sin-copia-vuelve-a-revision"),
    ],
)
def test_reading_an_old_approved_resource_applies_the_migration_rule(changes, status, verification_status):
    """REV-R11: los aprobados con resultado vigente siguen aprobados; los demás vuelven a revisión."""
    resource = {**without_verification(make_verified_explanation(status="aprobado")), **changes}
    service, repo = make_versioned_service(resource)
    listed = service.list_resources("ana", "u1")[0]
    assert listed["status"] == status and listed["verification"]["status"] == verification_status
    assert repo.get_resource_by_id("ana", "rx")["status"] == status


def test_a_concurrent_save_wins_over_the_read_check():
    """Si el docente guardó entre la lectura y la actualización, la actualización se descarta sin error."""
    service, repo = make_versioned_service(without_verification(make_verified_explanation()))
    original = repo.save_resource_if_version
    repo.save_resource_if_version = lambda *args, **kwargs: False  # simula un guardado concurrente
    listed = service.list_resources("ana", "u1")[0]
    assert "verification" not in repo.get_resource_by_id("ana", "rx")
    assert listed["id"] == "rx"
    repo.save_resource_if_version = original
    assert service.get_summary("otro") == []