"""
PLAN-C16 (specs/006-plan-de-generacion/research.md R11): conceptos de las unidades anteriores del curso, sacados de los
cursos del docente y de sus planes guardados, como `CourseSessionTypologyAdapter` (CUR-P3).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from platform5e.application.ports.outbound.generation_plan_repository_port import GenerationPlanRepositoryPort
from platform5e.application.ports.outbound.previous_unit_concepts_port import PreviousUnitConceptsPort
from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort
from platform5e.domain.accounts.teacher_account import find_course_and_unit
from platform5e.domain.generation.generation_plan import PreviousUnitConcepts
from platform5e.domain.generation.topic_coverage import concept_key

# Tope de conceptos por unidad anterior y en total (research R11).
MAX_CONCEPTS_PER_UNIT: int = 12
MAX_PREVIOUS_UNIT_CONCEPTS: int = 30


def unit_number(unit: dict[str, Any], position: int) -> int:
    """El número de la unidad; si no lo tiene, su posición en el curso (desde 1)."""
    number = unit.get("number")
    return number if isinstance(number, int) and not isinstance(number, bool) else position


class CoursePreviousUnitConceptsAdapter(PreviousUnitConceptsPort):
    def __init__(self, courses: TeacherRepositoryPort, plans: GenerationPlanRepositoryPort) -> None:
        self._courses = courses
        self._plans = plans

    def previous_unit_concepts(
        self, teacher_id: str, unit_id: str, limit: int = MAX_PREVIOUS_UNIT_CONCEPTS
    ) -> Sequence[PreviousUnitConcepts]:
        if limit <= 0:
            return ()
        match = find_course_and_unit(self._courses.get_courses(teacher_id), unit_id)
        if match is None:
            return ()
        course, _ = match
        numbered = {unit["id"]: (unit_number(unit, position), unit.get("title", ""))
                    for position, unit in enumerate(course["units"], 1)}
        current = numbered[unit_id][0]
        earlier = {uid: info for uid, info in numbered.items() if uid != unit_id and info[0] < current}
        if not earlier:
            return ()
        plans = {plan.unit_id: plan for plan in self._plans.latest_settled_for_units(teacher_id, tuple(earlier))}

        # De la unidad más cercana a la más antigua: el tope total se llena primero con lo más reciente.
        seen: set[str] = set()
        total = 0
        result: list[PreviousUnitConcepts] = []
        for uid in sorted(earlier, key=lambda u: -earlier[u][0]):
            plan = plans.get(uid)
            if plan is None or total >= limit:
                continue
            concepts: list[str] = []
            for concept in (c for item in plan.items for c in item.covers):
                key = concept_key(concept)
                if not key or key in seen:
                    continue
                if len(concepts) >= MAX_CONCEPTS_PER_UNIT or total >= limit:
                    break
                seen.add(key)
                concepts.append(concept)
                total += 1
            if concepts:
                number, title = earlier[uid]
                result.append(PreviousUnitConcepts(number, title, tuple(concepts)))
        return tuple(sorted(result, key=lambda unit: unit.unit_number))
