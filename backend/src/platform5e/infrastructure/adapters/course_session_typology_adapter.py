"""Course session history derived from persisted used plans."""

from __future__ import annotations

from collections.abc import Sequence

from platform5e.application.ports.outbound.session_typology_port import SessionTypologyPort
from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort
from platform5e.domain.accounts.teacher_account import find_course_and_unit
from platform5e.domain.generation.generation_plan import PreviousTypology
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_plan_repository import (
    SQLAlchemyGenerationPlanRepository,
)


class CourseSessionTypologyAdapter(SessionTypologyPort):
    def __init__(
        self, courses: TeacherRepositoryPort, plans: SQLAlchemyGenerationPlanRepository
    ) -> None:
        self._courses = courses
        self._plans = plans

    def previous_typologies(
        self, teacher_id: str, unit_id: str, limit: int = 3
    ) -> Sequence[PreviousTypology]:
        if limit <= 0:
            return ()

        match = find_course_and_unit(self._courses.get_courses(teacher_id), unit_id)
        if match is None:
            return ()

        course, _ = match
        unit_titles = {unit["id"]: unit["title"] for unit in course["units"]}
        plans = self._plans.list_used_for_units(teacher_id, tuple(unit_titles), min(limit, 3))
        return tuple(
            PreviousTypology(
                session_label=unit_titles[plan.unit_id],
                used_at=plan.used_at,
                resource_types=tuple(dict.fromkeys(item.resource_type for item in plan.items)),
            )
            for plan in plans
            if plan.used_at is not None
        )

    def record_typology(
        self, teacher_id: str, unit_id: str, plan_id: str,
        resource_types: Sequence[str], used_at: str,
    ) -> None:
        """The persisted used plan is the history record; no second write is needed."""
        return None
