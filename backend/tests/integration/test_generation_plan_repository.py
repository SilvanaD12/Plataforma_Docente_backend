"""GEN-P1 (T005): repositorio de planes con SQLAlchemy (SQLite en estas pruebas; PostgreSQL en la CI e2e)."""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import create_engine

from platform5e.application.ports.outbound.generation_plan_repository_port import PlanKeyTaken
from platform5e.domain.generation.generation_plan import PlanStatus, Referent, approve_plan, edit_plan, mark_plan_used
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
