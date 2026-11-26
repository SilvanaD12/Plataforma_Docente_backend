"""
Cursos con sumilla, logro y resultados de aprendizaje estructurados.
"""

from __future__ import annotations

from typing import Any

import pytest

from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort
from platform5e.application.services.accounts.account_service import AccountService
from platform5e.domain.accounts.teacher_account import AccountConfigurationError


class MockCoursesRepository(TeacherRepositoryPort):
    def __init__(self) -> None:
        self.saved_courses: dict[str, dict[str, Any]] = {}

    def get_courses(self, teacher_id: str) -> list[dict[str, Any]]:
        return list(self.saved_courses.values())

    def save_course(self, teacher_id: str, course_data: dict[str, Any]) -> None:
        self.saved_courses[course_data["id"]] = course_data

    def init_catalog(self, teacher_id: str) -> None: ...
    def get_user_by_email(self, email: str) -> dict[str, Any] | None: return None
    def create_user(self, user_data: dict[str, Any]) -> None: ...
    def save_session(self, fingerprint: str, teacher_id: str, expires_at: float) -> None: ...
    def get_session(self, fingerprint: str) -> tuple[str, float] | None: return None
    def delete_session(self, fingerprint: str) -> None: ...
    def delete_course(self, teacher_id: str, course_id: str, unit_ids: list[str]) -> None: ...
    def get_documents(self, teacher_id: str) -> list[dict[str, Any]]: return []
    def save_document(self, teacher_id: str, metadata: dict[str, Any], content: bytes) -> None: ...
    def get_document(self, teacher_id: str, document_id: str) -> tuple[dict[str, Any], bytes] | None: return None
    def delete_document(self, teacher_id: str, document_id: str) -> None: ...
    def get_history(self, teacher_id: str) -> list[dict[str, Any]]: return []
    def get_generation_owner(self, generation_id: str) -> str | None: return None


def make_course_payload(**overrides) -> dict[str, Any]:
    return {
        "code": "red-101",
        "name": "Redes",
        "term": "2026-II",
        "summary": " Curso de redes. ",
        "learningGoal": "Explica redes.",
        "units": [
            {
                "title": "Protocolos",
                "outcomes": [
                    {"text": " Distingue  TCP y UDP "},
                    {"code": "RA-X", "text": "Compara OSI"},
                    {"text": "  "},
                ],
            }
        ],
        **overrides,
    }


def test_create_course_saves_summary_goal_and_coded_outcomes():
    service = AccountService(MockCoursesRepository(), "docente@5e.demo", "clave")
    created = service.save_course("d", make_course_payload())
    assert created["code"] == "RED-101" and created["summary"] == "Curso de redes." and created["learningGoal"] == "Explica redes."
    outcomes = created["units"][0]["outcomes"]
    assert [(r["code"], r["text"]) for r in outcomes] == [("RA1.1", "Distingue TCP y UDP"), ("RA-X", "Compara OSI")]
    assert all(r["id"].startswith("ra-") for r in outcomes)


def test_edit_keeps_outcome_ids_and_unsent_data():
    repo = MockCoursesRepository()
    service = AccountService(repo, "docente@5e.demo", "clave")
    created = service.save_course("d", make_course_payload())
    unit = created["units"][0]
    first_outcome = unit["outcomes"][0]
    edited = service.save_course(
        "d",
        make_course_payload(
            summary=None,
            learningGoal=None,
            units=[
                {
                    "id": unit["id"],
                    "title": "Protocolos",
                    "outcomes": [
                        {
                            "id": first_outcome["id"],
                            "code": first_outcome["code"],
                            "text": "Distingue TCP, UDP e IP",
                        }
                    ],
                },
                {"title": "Dispositivos"},
            ],
        ),
        created["id"],
    )
    assert edited["summary"] == "Curso de redes."
    assert edited["units"][0]["outcomes"] == [
        {"id": first_outcome["id"], "code": "RA1.1", "text": "Distingue TCP, UDP e IP"}
    ]
    assert edited["units"][1]["outcomes"] == []
    no_changes = service.save_course(
        "d",
        make_course_payload(
            units=[
                {"id": unit["id"], "title": "Protocolos"},
                {"id": edited["units"][1]["id"], "title": "Dispositivos"},
            ]
        ),
        created["id"],
    )
    assert no_changes["units"][0]["outcomes"] == edited["units"][0]["outcomes"]


def test_repeated_or_foreign_id_creates_a_new_one():
    repo = MockCoursesRepository()
    service = AccountService(repo, "docente@5e.demo", "clave")
    created = service.save_course("d", make_course_payload())
    unit = created["units"][0]
    ident = unit["outcomes"][0]["id"]
    edited = service.save_course(
        "d",
        make_course_payload(
            units=[
                {
                    "id": unit["id"],
                    "title": "Protocolos",
                    "outcomes": [
                        {"id": ident, "text": "Uno"},
                        {"id": ident, "text": "Dos"},
                        {"id": "ra-inventado", "text": "Tres"},
                    ],
                }
            ]
        ),
        created["id"],
    )
    outcome_ids = [r["id"] for r in edited["units"][0]["outcomes"]]
    assert outcome_ids[0] == ident and len(set(outcome_ids)) == 3 and "ra-inventado" not in outcome_ids

def test_course_audience_round_trip():
    from platform5e.infrastructure.http.schemas.courses import CourseInput, CourseResponse

    service = AccountService(MockCoursesRepository(), "docente@5e.demo", "clave")
    audience = {
        "educationLevel": "Pregrado",
        "academicCycle": "Septimo ciclo",
        "activityType": "workshop",
    }
    payload = {
        "code": "AUD-01",
        "name": "Redes",
        "term": "2026-II",
        "units": [{"title": "Protocolos"}],
    }
    body = CourseInput.model_validate({**payload, **audience})
    created = service.save_course("d", body.model_dump(by_alias=True))
    response = CourseResponse.model_validate(created).model_dump(by_alias=True)
    assert {key: response[key] for key in audience} == audience

    payload["units"][0]["id"] = created["units"][0]["id"]
    body = CourseInput.model_validate(payload)
    updated = service.save_course("d", body.model_dump(by_alias=True), created["id"])
    saved = service.list_courses("d")[0]
    assert {key: updated[key] for key in audience} == audience
    assert {key: saved[key] for key in audience} == audience

    empty_audience = dict.fromkeys(audience, "")
    body = CourseInput.model_validate({**payload, **empty_audience})
    cleared = service.save_course("d", body.model_dump(by_alias=True), created["id"])
    assert {key: cleared[key] for key in audience} == empty_audience

def test_duplicate_unit_title_ignores_case_accents_and_spaces():
    repo = MockCoursesRepository()
    service = AccountService(repo, "docente@5e.demo", "clave")
    payload = make_course_payload(units=[
        {"title": "Introducci\u00f3n a Redes"},
        {"title": "  INTRODUCCION   A REDES  "},
    ])

    with pytest.raises(AccountConfigurationError) as error:
        service.save_course("d", payload)

    assert (error.value.code, error.value.status_code) == ("DUPLICATE_UNIT_TITLE", 409)
    assert error.value.details == [{"field": "title", "unitIndex": 1}]
    assert not repo.saved_courses


def test_edit_rejects_an_outcome_code_already_saved_in_another_unit():
    repo = MockCoursesRepository()
    service = AccountService(repo, "docente@5e.demo", "clave")
    created = service.save_course("d", make_course_payload())
    [unit] = created["units"]
    payload = make_course_payload(units=[
        {"id": unit["id"], "title": unit["title"]},
        {"title": "Dispositivos", "outcomes": [{"code": " ra-x ", "text": "Identifica un router"}]},
    ])

    with pytest.raises(AccountConfigurationError) as error:
        service.save_course("d", payload, created["id"])

    assert (error.value.code, error.value.status_code) == ("DUPLICATE_OUTCOME", 409)
    assert error.value.details == [{"field": "code", "unitIndex": 1, "outcomeIndex": 0}]
    assert repo.saved_courses[created["id"]] == created


def test_other_courses_can_reuse_unit_titles_and_outcome_codes():
    service = AccountService(MockCoursesRepository(), "docente@5e.demo", "clave")
    first = service.save_course("d", make_course_payload())
    second = service.save_course("d", make_course_payload(code="red-102"))

    assert first["id"] != second["id"]
    assert first["units"][0]["title"] == second["units"][0]["title"]
    assert first["units"][0]["outcomes"][0]["code"] == second["units"][0]["outcomes"][0]["code"]
