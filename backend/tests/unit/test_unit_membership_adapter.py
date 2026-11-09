"""Puerto de pertenencia de unidad (CC-01): adaptador inicial sobre el repositorio de Cuentas, con un repositorio
falso. Sin red y sin base de datos."""

from __future__ import annotations

from typing import Any

from platform5e.application.ports.outbound.unit_membership_port import OutcomeRef, UnitContext
from platform5e.infrastructure.adapters.account_unit_membership_adapter import AccountUnitMembershipAdapter

COURSES: dict[str, list[dict[str, Any]]] = {
    "docente-a": [
        {
            "id": "curso-1",
            "code": "RED-302",
            "name": "Redes",
            "summary": "Fundamentos de redes.",
            "learningGoal": "Diseña redes pequeñas.",
            "units": [
                {
                    "id": "u1",
                    "number": 1,
                    "title": "Protocolos",
                    "outcomes": [{"id": "ra-1", "code": "RA1.1", "text": "Distingue TCP y UDP"}],
                },
                {
                    "id": "u2",
                    "number": 2,
                    "title": "Enrutamiento",
                    "outcomes": [
                        {"id": "ra-2", "code": "RA2.1", "text": "Explica cómo decide el enrutador el camino"},
                        {"id": "ra-3", "code": "RA2.2", "text": "Configura una tabla de rutas estática"},
                        {"id": "ra-4", "text": "Compara rutas estáticas y dinámicas"},
                    ],
                },
            ],
        }
    ],
    "docente-b": [{"id": "curso-2", "code": "BD-1", "name": "Datos", "units": [{"id": "u9", "title": "SQL"}]}],
}


class FakeTeacherRepository:
    """Devuelve solo los cursos del docente, como `TeacherRepositoryPort.get_courses`."""

    def get_courses(self, teacher_id: str) -> list[dict[str, Any]]:
        return COURSES.get(teacher_id, [])


def adapter() -> AccountUnitMembershipAdapter:
    return AccountUnitMembershipAdapter(FakeTeacherRepository())


def test_an_own_unit_returns_its_course_and_unit_context():
    assert adapter().get_unit_context("docente-a", "u1") == UnitContext(
        course_id="curso-1",
        course_name="Redes",
        course_summary="Fundamentos de redes.",
        learning_goal="Diseña redes pequeñas.",
        unit_id="u1",
        unit_number=1,
        unit_title="Protocolos",
        outcomes=(OutcomeRef("ra-1", "RA1.1", "Distingue TCP y UDP"),),
    )


def test_a_foreign_and_a_missing_unit_give_the_same_answer():
    """Una unidad ajena y una inexistente devuelven None, sin revelar los datos de la unidad ajena."""
    membership = adapter()
    assert membership.get_unit_context("docente-a", "u9") is None  # unidad de docente-b
    assert membership.get_unit_context("docente-a", "no-existe") is None
    assert membership.get_unit_context("docente-sin-cursos", "u1") is None
    assert membership.get_unit_context("", "u1") is None
    assert membership.get_unit_context("docente-a", "") is None


def test_outcomes_keep_their_ids_codes_and_texts_in_order():
    context = adapter().get_unit_context("docente-a", "u2")
    assert [(o.id, o.code, o.text) for o in context.outcomes] == [
        ("ra-2", "RA2.1", "Explica cómo decide el enrutador el camino"),
        ("ra-3", "RA2.2", "Configura una tabla de rutas estática"),
        ("ra-4", "", "Compara rutas estáticas y dinámicas"),  # sin código guardado
    ]
    assert all(isinstance(o, OutcomeRef) for o in context.outcomes)


def test_missing_optional_course_fields_become_empty():
    context = adapter().get_unit_context("docente-b", "u9")
    assert (context.course_summary, context.learning_goal, context.unit_number, context.outcomes) == ("", "", None, ())
