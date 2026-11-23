"""GEN-P1 (T005): repositorio de planes con SQLAlchemy (SQLite en estas pruebas; PostgreSQL en la CI e2e)."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine

from platform5e.application.ports.outbound.generation_plan_repository_port import PlanKeyTaken
from platform5e.domain.generation.generation_plan import PlanStatus, Referent, approve_plan, edit_plan, mark_plan_used
from platform5e.infrastructure.adapters.course_session_typology_adapter import CourseSessionTypologyAdapter
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_plan_repository import (
    SQLAlchemyGenerationPlanRepository,
)
from tests.unit.test_generation_plan import VALID


@pytest.fixture
def repository(tmp_path) -> SQLAlchemyGenerationPlanRepository:
    return SQLAlchemyGenerationPlanRepository(create_engine(f"sqlite:///{tmp_path / 'plans.db'}"))


def test_a_plan_round_trips_with_every_field(repository):
    plan = replace(VALID, referents=(Referent("Andrew Tanenbaum", "Autor de Redes de computadoras", ("f1",)),),
                   warnings=("SAME_TYPOLOGY_AS_LAST_SESSION",))
    repository.create(plan)
    assert repository.get("docente-a", plan.id) == plan
    assert repository.find_by_key("docente-a", plan.idempotency_key) == plan


def test_the_same_key_of_a_teacher_creates_one_plan(repository):
    repository.create(VALID)
    with pytest.raises(PlanKeyTaken) as taken:
        repository.create(replace(VALID, id="gen-plan-2"))
    assert taken.value.existing.id == VALID.id
    repository.create(replace(VALID, id="gen-plan-3", teacher_id="docente-b"))  # otro docente, misma clave


def test_another_teacher_does_not_read_the_plan(repository):
    repository.create(VALID)
    assert repository.get("docente-b", VALID.id) is None
    assert repository.list_for_unit("docente-b", VALID.unit_id) == []


def test_the_list_of_a_unit_is_newest_first_with_status_and_limit(repository):
    for number in range(3):
        repository.create(replace(VALID, id=f"gen-plan-{number}", idempotency_key=f"clave-plan-{number}",
                                  updated_at=f"2026-11-22T10:0{number}:00.000000+00:00"))
    approved = approve_plan(repository.get("docente-a", "gen-plan-0"), 1, [], "2026-11-22T10:09:00.000000+00:00")
    assert repository.save_if_version(approved, 1)
    assert [p.id for p in repository.list_for_unit("docente-a", "u1")] == ["gen-plan-0", "gen-plan-2", "gen-plan-1"]
    assert [p.id for p in repository.list_for_unit("docente-a", "u1", PlanStatus.APPROVED)] == ["gen-plan-0"]
    assert len(repository.list_for_unit("docente-a", "u1", limit=2)) == 2


def test_saving_is_conditional_on_the_version_and_never_on_a_used_plan(repository):
    repository.create(VALID)
    first = edit_plan(VALID, 1, VALID.items, "2026-11-22T10:01:00.000000+00:00")
    second = edit_plan(VALID, 1, VALID.items[:1], "2026-11-22T10:02:00.000000+00:00")
    assert repository.save_if_version(first, 1) is True
    assert repository.save_if_version(second, 1) is False  # otra pestaña ganó con la misma versión
    assert repository.get("docente-a", VALID.id).version == 2

    approved = approve_plan(repository.get("docente-a", VALID.id), 2, [], "2026-11-22T10:03:00.000000+00:00")
    used = mark_plan_used(approved, 2, "gen-req-1", "2026-11-22T10:04:00.000000+00:00")
    assert repository.save_if_version(used, 2) is True
    assert repository.save_if_version(edit_plan(approved, 2, VALID.items, "2026-11-22T10:05:00.000000+00:00"), 2) is False  # ya está usado
    assert repository.get("docente-a", VALID.id).status == PlanStatus.USED

def test_used_plans_are_limited_to_the_teacher_and_course_units(repository):
    for number, (teacher, unit, used) in enumerate([
        ("docente-a", "u1", True),
        ("docente-a", "u2", True),
        ("docente-a", "u1", True),
        ("docente-a", "u2", True),
        ("docente-a", "u1", False),
        ("docente-a", "u3", True),
        ("docente-b", "u1", True),
    ]):
        timestamp = f"2026-11-22T10:0{number}:00.000000+00:00"
        plan = replace(
            VALID,
            id=f"gen-plan-{number}",
            idempotency_key=f"key-{number}",
            teacher_id=teacher,
            unit_id=unit,
            updated_at=timestamp,
        )
        if used:
            approved = approve_plan(plan, 1, [], timestamp)
            plan = mark_plan_used(approved, 1, f"gen-req-{number}", timestamp)
        repository.create(plan)

    history = repository.list_used_for_units("docente-a", ["u1", "u2"])
    assert [plan.id for plan in history] == ["gen-plan-3", "gen-plan-2", "gen-plan-1"]
    assert [plan.unit_id for plan in history] == ["u2", "u1", "u2"]
    assert repository.list_used_for_units("docente-a", []) == []

    courses = Mock()
    courses.get_courses.return_value = [
        {"units": [{"id": "u1", "title": "TCP"}, {"id": "u2", "title": "UDP"}]},
        {"units": [{"id": "u3", "title": "Otro curso"}]},
    ]
    adapter = CourseSessionTypologyAdapter(courses, repository)
    history = adapter.previous_typologies("docente-a", "u1", limit=10)
    assert [entry.session_label for entry in history] == ["UDP", "TCP", "UDP"]
    assert [entry.used_at for entry in history] == [
        f"2026-11-22T10:0{number}:00.000000+00:00" for number in (3, 2, 1)
    ]
    assert history[0].resource_types == tuple(dict.fromkeys(item.resource_type for item in VALID.items))
    assert adapter.previous_typologies("docente-a", "missing") == ()
