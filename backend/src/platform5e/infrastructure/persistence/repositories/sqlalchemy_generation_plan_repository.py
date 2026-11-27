"""
Persistencia de los planes de generación (GEN-P1) con SQLAlchemy.

En PostgreSQL la tabla la crea la migración `20261122000001_generation_plans.sql`; en SQLite (desarrollo y pruebas) la
crea este repositorio, como los demás. Las fechas se guardan como texto ISO 8601 en UTC con microsegundos, así el
orden alfabético coincide con el temporal. `validation` y `doesNotCover` no se guardan: se calculan al leer.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import JSON, CheckConstraint, Column, Integer, String, UniqueConstraint, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from platform5e.application.ports.outbound.generation_plan_repository_port import (
    GenerationPlanRepositoryPort,
    PlanKeyTaken,
)
from platform5e.domain.generation.generation_plan import (
    GenerationPlan,
    PlanEvidence,
    PlanInputs,
    PlanItem,
    PlanStatus,
    Referent,
    SessionContext,
)
from platform5e.infrastructure.persistence.database import Base, SessionLocal, engine
from platform5e.infrastructure.persistence.error_translation import translate_persistence_errors
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_request_repository import utc_text

_STATUS_VALUES = ", ".join(f"'{status.value}'" for status in PlanStatus)


class GenerationPlanORM(Base):
    """Plan de generación del docente (tabla `gen_generation_plans`)."""

    __tablename__ = "gen_generation_plans"
    __table_args__ = (
        UniqueConstraint("teacher_id", "idempotency_key", name="uq_gen_generation_plans_teacher_key"),
        CheckConstraint(f"status IN ({_STATUS_VALUES})", name="ck_gen_generation_plans_status"),
        CheckConstraint("origin IN ('teacher', 'implicit')", name="ck_gen_generation_plans_origin"),
    )

    id = Column(String, primary_key=True)
    teacher_id = Column(String, nullable=False)
    unit_id = Column(String, nullable=False)
    idempotency_key = Column(String, nullable=False)
    payload_hash = Column(String, nullable=False)
    version = Column(Integer, nullable=False)
    status = Column(String, nullable=False)
    origin = Column(String, nullable=False)
    inputs = Column(JSON, nullable=False)
    evidence = Column(JSON, nullable=False)
    retrieval_mode = Column(String, nullable=True)
    referents = Column(JSON, nullable=False)
    session_context = Column(JSON, nullable=False)
    items = Column(JSON, nullable=False)
    generator = Column(JSON, nullable=False)
    warnings = Column(JSON, nullable=False)
    used_by_request_id = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    approved_at = Column(String, nullable=True)
    used_at = Column(String, nullable=True)


def plan_update_values(plan: GenerationPlan) -> dict:
    """Las columnas que cambian al editar, aprobar o usar el plan."""
    return {
        "version": plan.version,
        "status": PlanStatus(plan.status).value,
        "items": [item.to_payload() for item in plan.items],
        "generator": dict(plan.generator),
        "warnings": list(plan.warnings),
        "used_by_request_id": plan.used_by_request_id,
        "updated_at": utc_text(plan.updated_at),
        "approved_at": utc_text(plan.approved_at) if plan.approved_at else None,
        "used_at": utc_text(plan.used_at) if plan.used_at else None,
    }


def _to_orm(plan: GenerationPlan) -> GenerationPlanORM:
    return GenerationPlanORM(
        id=plan.id,
        teacher_id=plan.teacher_id,
        unit_id=plan.unit_id,
        idempotency_key=plan.idempotency_key,
        payload_hash=plan.payload_hash,
        origin=plan.origin,
        inputs=plan.inputs.to_payload(),
        evidence=plan.evidence.to_payload(),
        retrieval_mode=plan.evidence.retrieval_mode,
        referents=[referent.to_payload() for referent in plan.referents],
        session_context=plan.session_context.to_payload(),
        created_at=utc_text(plan.created_at),
        **plan_update_values(plan),
    )


def _from_orm(row: GenerationPlanORM) -> GenerationPlan:
    return GenerationPlan(
        id=row.id,
        teacher_id=row.teacher_id,
        unit_id=row.unit_id,
        idempotency_key=row.idempotency_key,
        payload_hash=row.payload_hash,
        version=row.version,
        status=PlanStatus(row.status),
        origin=row.origin,
        inputs=PlanInputs.from_payload(row.inputs),
        evidence=PlanEvidence.from_payload(row.evidence),
        referents=tuple(Referent.from_payload(r) for r in row.referents or []),
        session_context=SessionContext.from_payload(row.session_context or {}),
        items=tuple(PlanItem.from_payload(i) for i in row.items or []),
        warnings=tuple(row.warnings or []),
        generator=dict(row.generator or {}),
        used_by_request_id=row.used_by_request_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        approved_at=row.approved_at,
        used_at=row.used_at,
    )


class SQLAlchemyGenerationPlanRepository(GenerationPlanRepositoryPort):
    """Adaptador de infraestructura de los planes. `bind` permite otra base (pruebas)."""

    @translate_persistence_errors
    def __init__(self, bind: Engine | None = None) -> None:
        self._engine = bind if bind is not None else engine
        self._sessions = sessionmaker(bind=bind, autoflush=False) if bind is not None else SessionLocal
        if self._engine.dialect.name == "sqlite":
            GenerationPlanORM.__table__.create(bind=self._engine, checkfirst=True)

    @translate_persistence_errors
    def find_by_key(self, teacher_id: str, idempotency_key: str) -> GenerationPlan | None:
        with self._sessions() as session:
            row = session.scalars(select(GenerationPlanORM).where(
                GenerationPlanORM.teacher_id == teacher_id, GenerationPlanORM.idempotency_key == idempotency_key,
            )).first()
            return _from_orm(row) if row is not None else None

    @translate_persistence_errors
    def get(self, teacher_id: str, plan_id: str) -> GenerationPlan | None:
        with self._sessions() as session:
            row = session.scalars(select(GenerationPlanORM).where(
                GenerationPlanORM.teacher_id == teacher_id, GenerationPlanORM.id == plan_id,
            )).first()
            return _from_orm(row) if row is not None else None

    @translate_persistence_errors
    def list_for_unit(
        self, teacher_id: str, unit_id: str, status: PlanStatus | None = None, limit: int = 5
    ) -> Sequence[GenerationPlan]:
        query = select(GenerationPlanORM).where(
            GenerationPlanORM.teacher_id == teacher_id, GenerationPlanORM.unit_id == unit_id,
        )
        if status is not None:
            query = query.where(GenerationPlanORM.status == PlanStatus(status).value)
        query = query.order_by(GenerationPlanORM.updated_at.desc(), GenerationPlanORM.id).limit(limit)
        with self._sessions() as session:
            return [_from_orm(row) for row in session.scalars(query).all()]

    @translate_persistence_errors
    def list_used_for_units(
        self, teacher_id: str, unit_ids: Sequence[str], limit: int = 3
    ) -> Sequence[GenerationPlan]:
        """Return the most recently used plans in the supplied units."""
        query = (
            select(GenerationPlanORM)
            .where(
                GenerationPlanORM.teacher_id == teacher_id,
                GenerationPlanORM.unit_id.in_(unit_ids),
                GenerationPlanORM.status == PlanStatus.USED.value,
                GenerationPlanORM.used_at.is_not(None),
            )
            .order_by(GenerationPlanORM.used_at.desc(), GenerationPlanORM.id)
            .limit(limit)
        )
        with self._sessions() as session:
            return [_from_orm(row) for row in session.scalars(query).all()]

    @translate_persistence_errors
    def latest_settled_for_units(self, teacher_id: str, unit_ids: Sequence[str]) -> Sequence[GenerationPlan]:
        """R11: el último plan aprobado o usado de cada unidad del docente, por `updatedAt`."""
        if not unit_ids:
            return []
        query = (
            select(GenerationPlanORM)
            .where(
                GenerationPlanORM.teacher_id == teacher_id,
                GenerationPlanORM.unit_id.in_(list(unit_ids)),
                GenerationPlanORM.status.in_((PlanStatus.APPROVED.value, PlanStatus.USED.value)),
            )
            .order_by(GenerationPlanORM.updated_at.desc(), GenerationPlanORM.id)
        )
        latest: dict[str, GenerationPlan] = {}
        with self._sessions() as session:
            for row in session.scalars(query):
                if row.unit_id not in latest:
                    latest[row.unit_id] = _from_orm(row)
        return list(latest.values())

    @translate_persistence_errors
    def create(self, plan: GenerationPlan) -> GenerationPlan:
        with self._sessions() as session:
            session.add(_to_orm(plan))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = self.find_by_key(plan.teacher_id, plan.idempotency_key)
                if existing is None:
                    raise
                raise PlanKeyTaken(existing) from None
        return plan

    @translate_persistence_errors
    def save_if_version(self, plan: GenerationPlan, expected_version: int) -> bool:
        with self._sessions() as session:
            result = session.execute(
                update(GenerationPlanORM)
                .where(
                    GenerationPlanORM.teacher_id == plan.teacher_id,
                    GenerationPlanORM.id == plan.id,
                    GenerationPlanORM.version == expected_version,
                    GenerationPlanORM.status != PlanStatus.USED.value,
                )
                .values(**plan_update_values(plan))
            )
            session.commit()
            return result.rowcount == 1
