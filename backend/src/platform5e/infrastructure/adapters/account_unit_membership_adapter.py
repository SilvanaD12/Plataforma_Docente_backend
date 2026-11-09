"""
Adaptador inicial de `UnitMembershipPort` sobre el repositorio de Cuentas (CC-01).

Lee los cursos ya filtrados por docente, así que una unidad ajena y una inexistente dan el mismo resultado: None.
La firma se coordina con la tarea T007 de CC-01; si Cuentas publica su propio adaptador, reemplaza a este.
"""

from __future__ import annotations

from typing import Any

from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort
from platform5e.application.ports.outbound.unit_membership_port import (
    OutcomeRef,
    UnitContext,
    UnitMembershipPort,
)
from platform5e.domain.accounts.teacher_account import find_course_and_unit


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


class AccountUnitMembershipAdapter(UnitMembershipPort):
    """Comprueba la pertenencia de la unidad con `TeacherRepositoryPort.get_courses` y `find_course_and_unit`."""

    def __init__(self, teacher_repository: TeacherRepositoryPort) -> None:
        self._teacher_repository = teacher_repository

    def get_unit_context(self, teacher_id: str, unit_id: str) -> UnitContext | None:
        if not teacher_id or not unit_id:
            return None
        match = find_course_and_unit(self._teacher_repository.get_courses(teacher_id), unit_id)
        if match is None:
            return None
        course, unit = match
        number = unit.get("number")
        return UnitContext(
            course_id=_text(course.get("id")),
            course_name=_text(course.get("name")),
            course_summary=_text(course.get("summary")),
            learning_goal=_text(course.get("learningGoal")),
            unit_id=_text(unit.get("id")),
            unit_number=number if isinstance(number, int) and not isinstance(number, bool) else None,
            unit_title=_text(unit.get("title")),
            outcomes=tuple(
                OutcomeRef(id=_text(outcome.get("id")), code=_text(outcome.get("code")), text=_text(outcome.get("text")))
                for outcome in unit.get("outcomes") or []
                if isinstance(outcome, dict) and outcome.get("id")
            ),
        )
