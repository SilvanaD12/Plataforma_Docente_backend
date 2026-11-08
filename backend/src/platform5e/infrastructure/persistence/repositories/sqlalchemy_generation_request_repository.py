"""
Persistencia de los pedidos de generación en segundo plano (GEN-01) y de sus pasos mediante SQLAlchemy.

En PostgreSQL las tablas las crea la migración `20261110000001_generation_requests.sql`; en SQLite (desarrollo y
pruebas) las crea este repositorio, como hacen los demás. Las fechas se guardan como texto ISO 8601 en UTC con
microsegundos, para que el orden alfabético coincida con el orden temporal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    and_,
    func,
    or_,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from platform5e.application.ports.outbound.evidence_provider_port import EvidenceRetrieval
from platform5e.application.ports.outbound.generation_request_repository_port import (
    GenerationRequestRepositoryPort,
    IdempotencyKeyTaken,
)
from platform5e.domain.generation.generation_request import (
    FINAL_REQUEST_STATUSES,
    GenerationMode,
    GenerationParameters,
    GenerationRequest,
    GenerationStep,
    Problem,
    RegenerationTarget,
    RequestStatus,
    StepStatus,
    interrupt,
)
from platform5e.infrastructure.persistence.database import Base, SessionLocal, engine
from platform5e.infrastructure.persistence.error_translation import translate_persistence_errors

ACTIVE_STATUSES: tuple[str, ...] = (RequestStatus.QUEUED.value, RequestStatus.RUNNING.value)
_REQUEST_STATUS_VALUES = ", ".join(f"'{status.value}'" for status in RequestStatus)
_STEP_STATUS_VALUES = ", ".join(f"'{status.value}'" for status in StepStatus)
_MODE_VALUES = ", ".join(f"'{mode.value}'" for mode in GenerationMode)


class GenerationRequestORM(Base):
    """Pedido de generación del docente (tabla `gen_generation_requests`)."""

    __tablename__ = "gen_generation_requests"
    __table_args__ = (
        UniqueConstraint("teacher_id", "idempotency_key", name="uq_gen_generation_requests_teacher_key"),
        CheckConstraint(f"mode IN ({_MODE_VALUES})", name="ck_gen_generation_requests_mode"),
        CheckConstraint(f"status IN ({_REQUEST_STATUS_VALUES})", name="ck_gen_generation_requests_status"),
    )

    id = Column(String, primary_key=True)
    teacher_id = Column(String, nullable=False)
    unit_id = Column(String, nullable=False)
    mode = Column(String, nullable=False)
    idempotency_key = Column(String, nullable=False)
    payload_hash = Column(String, nullable=False)
    parameters = Column(JSON, nullable=False)
    status = Column(String, nullable=False)
    retrieval_mode = Column(String, nullable=True)
    evidence = Column(JSON, nullable=False)
    regeneration = Column(JSON, nullable=True)
    failure = Column(JSON, nullable=True)
    created_at = Column(String, nullable=False)
    started_at = Column(String, nullable=True)
    finished_at = Column(String, nullable=True)
    heartbeat_at = Column(String, nullable=True)
    worker_boot_id = Column(String, nullable=True)


class GenerationStepORM(Base):
    """Paso de un pedido (tabla `gen_generation_steps`)."""

    __tablename__ = "gen_generation_steps"
    __table_args__ = (
        CheckConstraint(f"status IN ({_STEP_STATUS_VALUES})", name="ck_gen_generation_steps_status"),
    )

    request_id = Column(
        String, ForeignKey("gen_generation_requests.id", ondelete="CASCADE"), primary_key=True
    )
    position = Column(Integer, primary_key=True)
    stage = Column(String, nullable=False)
    resource_type = Column(String, nullable=False)
    agent = Column(String, nullable=False)
    status = Column(String, nullable=False)
    resource_ids = Column(JSON, nullable=False)
    rejections = Column(JSON, nullable=False)
    generator = Column(JSON, nullable=True)
    grounding = Column(JSON, nullable=True)
    distractor_reliability = Column(JSON, nullable=True)
    error = Column(JSON, nullable=True)
    started_at = Column(String, nullable=True)
    finished_at = Column(String, nullable=True)


def utc_text(value: datetime | str | None = None) -> str:
    """Fecha en texto ISO 8601, UTC y con microsegundos. Sin valor, el instante actual."""
    if value is None:
        moment = datetime.now(timezone.utc)
    elif isinstance(value, str):
        moment = datetime.fromisoformat(value)
    else:
        moment = value
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _problem_to_json(problem: Problem | None) -> dict[str, str] | None:
    return None if problem is None else {"code": str(problem.code), "message": problem.message}


def _problem_from_json(data: dict[str, Any] | None) -> Problem | None:
    return None if not data else Problem(code=data["code"], message=data["message"])


def _parameters_from_json(data: dict[str, Any]) -> GenerationParameters:
    return GenerationParameters(
        resource_types=tuple(data["resourceTypes"]),
        quantity=data["quantity"],
        outcome_id=data.get("outcomeId"),
        difficulty=data["difficulty"],
        option_count=data["optionCount"],
        top_k=data["topK"],
        evidence_threshold=data["evidenceThreshold"],
        instructions=data["instructions"],
        audience=data["audience"],
        competency=data["competency"],
        modalities=tuple(data["modalities"]),
    )


def _step_to_orm(request_id: str, step: GenerationStep) -> GenerationStepORM:
    row = GenerationStepORM(request_id=request_id, position=step.position)
    _copy_step(step, row)
    return row


def _copy_step(step: GenerationStep, row: GenerationStepORM) -> None:
    row.stage = step.stage
    row.resource_type = step.resource_type
    row.agent = step.agent
    row.status = StepStatus(step.status).value
    row.resource_ids = list(step.resource_ids)
    row.rejections = list(step.rejections)
    row.generator = step.generator
    row.grounding = step.grounding
    row.distractor_reliability = step.distractor_reliability
    row.error = _problem_to_json(step.error)
    row.started_at = utc_text(step.started_at) if step.started_at else None
    row.finished_at = utc_text(step.finished_at) if step.finished_at else None


def _step_from_orm(row: GenerationStepORM) -> GenerationStep:
    return GenerationStep(
        position=row.position,
        stage=row.stage,
        resource_type=row.resource_type,
        agent=row.agent,
        status=StepStatus(row.status),
        resource_ids=tuple(row.resource_ids or ()),
        rejections=tuple(row.rejections or ()),
        generator=row.generator,
        grounding=row.grounding,
        distractor_reliability=row.distractor_reliability,
        error=_problem_from_json(row.error),
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def _request_to_orm(request: GenerationRequest) -> GenerationRequestORM:
    return GenerationRequestORM(
        id=request.id,
        teacher_id=request.teacher_id,
        unit_id=request.unit_id,
        mode=GenerationMode(request.mode).value,
        idempotency_key=request.idempotency_key,
        payload_hash=request.payload_hash,
        parameters=request.parameters.to_payload(),
        status=RequestStatus(request.status).value,
        retrieval_mode=request.retrieval_mode,
        evidence=list(request.evidence),
        regeneration=request.regeneration.to_payload() if request.regeneration else None,
        failure=_problem_to_json(request.failure),
        created_at=utc_text(request.created_at),
        started_at=utc_text(request.started_at) if request.started_at else None,
        finished_at=utc_text(request.finished_at) if request.finished_at else None,
        heartbeat_at=utc_text(request.heartbeat_at) if request.heartbeat_at else None,
        worker_boot_id=request.worker_boot_id,
    )


def _request_from_orm(row: GenerationRequestORM, steps: list[GenerationStepORM]) -> GenerationRequest:
    regeneration = row.regeneration
    return GenerationRequest(
        id=row.id,
        teacher_id=row.teacher_id,
        unit_id=row.unit_id,
        mode=GenerationMode(row.mode),
        idempotency_key=row.idempotency_key,
        payload_hash=row.payload_hash,
        parameters=_parameters_from_json(row.parameters),
        created_at=row.created_at,
        steps=tuple(_step_from_orm(step) for step in sorted(steps, key=lambda s: s.position)),
        status=RequestStatus(row.status),
        retrieval_mode=row.retrieval_mode,
        evidence=tuple(row.evidence or ()),
        regeneration=(
            RegenerationTarget(regeneration["resourceId"], regeneration["resourceVersion"]) if regeneration else None
        ),
        failure=_problem_from_json(row.failure),
        started_at=row.started_at,
        finished_at=row.finished_at,
        heartbeat_at=row.heartbeat_at,
        worker_boot_id=row.worker_boot_id,
    )


class SQLAlchemyGenerationRequestRepository(GenerationRequestRepositoryPort):
    """Adaptador de infraestructura del pedido de generación.

    `bind` permite usar otra base (pruebas); sin él usa la conexión compartida de `database.py`.
    """

    @translate_persistence_errors
    def __init__(self, bind: Engine | None = None) -> None:
        self._engine = bind if bind is not None else engine
        self._sessions = sessionmaker(bind=bind, autoflush=False) if bind is not None else SessionLocal
        if self._engine.dialect.name == "sqlite":
            GenerationRequestORM.__table__.create(bind=self._engine, checkfirst=True)
            GenerationStepORM.__table__.create(bind=self._engine, checkfirst=True)

    # Lecturas

    def _load(self, session: Session, row: GenerationRequestORM | None) -> GenerationRequest | None:
        if row is None:
            return None
        steps = session.scalars(select(GenerationStepORM).where(GenerationStepORM.request_id == row.id)).all()
        return _request_from_orm(row, list(steps))

    def _find_by_key(self, session: Session, teacher_id: str, idempotency_key: str) -> GenerationRequest | None:
        row = session.scalars(
            select(GenerationRequestORM).where(
                GenerationRequestORM.teacher_id == teacher_id,
                GenerationRequestORM.idempotency_key == idempotency_key,
            )
        ).first()
        return self._load(session, row)

    @translate_persistence_errors
    def find_by_key(self, teacher_id: str, idempotency_key: str) -> GenerationRequest | None:
        with self._sessions() as session:
            return self._find_by_key(session, teacher_id, idempotency_key)

    @translate_persistence_errors
    def get(self, teacher_id: str, request_id: str) -> GenerationRequest | None:
        with self._sessions() as session:
            row = session.get(GenerationRequestORM, request_id)
            if row is None or row.teacher_id != teacher_id:
                return None
            return self._load(session, row)

    @translate_persistence_errors
    def get_for_runner(self, request_id: str) -> GenerationRequest | None:
        with self._sessions() as session:
            return self._load(session, session.get(GenerationRequestORM, request_id))

    @translate_persistence_errors
    def list_by_unit(
        self, teacher_id: str, unit_id: str, active_only: bool, limit: int
    ) -> list[GenerationRequest]:
        with self._sessions() as session:
            statement = select(GenerationRequestORM).where(
                GenerationRequestORM.teacher_id == teacher_id, GenerationRequestORM.unit_id == unit_id
            )
            if active_only:
                statement = statement.where(GenerationRequestORM.status.in_(ACTIVE_STATUSES))
            statement = statement.order_by(GenerationRequestORM.created_at.desc()).limit(limit)
            return [self._load(session, row) for row in session.scalars(statement).all()]  # type: ignore[misc]

    @translate_persistence_errors
    def count_active(self, teacher_id: str) -> int:
        with self._sessions() as session:
            return session.scalar(
                select(func.count())
                .select_from(GenerationRequestORM)
                .where(
                    GenerationRequestORM.teacher_id == teacher_id,
                    GenerationRequestORM.status.in_(ACTIVE_STATUSES),
                )
            ) or 0

    # Escrituras

    @translate_persistence_errors
    def create(self, request: GenerationRequest) -> GenerationRequest:
        with self._sessions() as session:
            # La unidad de trabajo inserta el pedido antes que sus pasos por la clave foránea.
            session.add(_request_to_orm(request))
            session.add_all(_step_to_orm(request.id, step) for step in request.steps)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = self._find_by_key(session, request.teacher_id, request.idempotency_key)
                if existing is None:
                    raise  # otra violación (por ejemplo, id repetido): DuplicateRecordError
                raise IdempotencyKeyTaken(existing) from None
            return self._load(session, session.get(GenerationRequestORM, request.id))  # type: ignore[return-value]

    @translate_persistence_errors
    def mark_running(self, request_id: str, worker_boot_id: str) -> None:
        """Solo un pedido en cola pasa a ejecución; uno interrumpido o terminado no cambia."""
        with self._sessions() as session:
            row = session.get(GenerationRequestORM, request_id)
            if row is None or row.status != RequestStatus.QUEUED.value:
                return
            now = utc_text()
            row.status = RequestStatus.RUNNING.value
            row.started_at = now
            row.heartbeat_at = now
            row.worker_boot_id = worker_boot_id
            session.commit()

    @translate_persistence_errors
    def save_evidence(self, request_id: str, retrieval: EvidenceRetrieval, retrieved_at: str) -> None:
        with self._sessions() as session:
            row = session.get(GenerationRequestORM, request_id)
            if row is None:
                return
            row.evidence = [fragment.to_dict(retrieved_at) for fragment in retrieval.fragments]
            row.retrieval_mode = retrieval.retrieval_mode
            session.commit()

    @translate_persistence_errors
    def update_step(self, request_id: str, step: GenerationStep) -> None:
        with self._sessions() as session:
            row = session.get(GenerationStepORM, (request_id, step.position))
            if row is None:
                session.add(_step_to_orm(request_id, step))
            else:
                _copy_step(step, row)
            session.commit()

    @translate_persistence_errors
    def heartbeat(self, request_id: str) -> None:
        with self._sessions() as session:
            row = session.get(GenerationRequestORM, request_id)
            if row is not None and row.status == RequestStatus.RUNNING.value:
                row.heartbeat_at = utc_text()
                session.commit()

    @translate_persistence_errors
    def finish(self, request_id: str, status: RequestStatus, failure: Problem | None) -> None:
        """Cierra el pedido. Los pasos sin terminar pasan a `interrupted` si el pedido se interrumpe y a `failed`
        en los demás casos, con el mismo motivo. Un pedido ya terminado no cambia."""
        with self._sessions() as session:
            row = session.get(GenerationRequestORM, request_id)
            if row is None or RequestStatus(row.status) in FINAL_REQUEST_STATUSES:
                return
            now = utc_text()
            row.status = RequestStatus(status).value
            row.failure = _problem_to_json(failure)
            row.finished_at = now
            step_status = StepStatus.INTERRUPTED if status == RequestStatus.INTERRUPTED else StepStatus.FAILED
            unfinished = session.scalars(
                select(GenerationStepORM).where(
                    GenerationStepORM.request_id == request_id,
                    GenerationStepORM.status.in_((StepStatus.PENDING.value, StepStatus.RUNNING.value)),
                )
            )
            for step in unfinished:
                step.status = step_status.value
                step.error = _problem_to_json(failure)
                step.finished_at = now
            session.commit()

    @translate_persistence_errors
    def mark_interrupted(self, stale_before: datetime) -> int:
        """Barrido de arranque (research R3): interrumpe los pedidos activos cuyo último latido, o su creación si
        nunca latieron, es anterior a `stale_before`. Los pasos terminados y sus recursos se conservan."""
        limit = utc_text(stale_before)
        now = utc_text()
        with self._sessions() as session:
            stale_rows = session.scalars(
                select(GenerationRequestORM).where(
                    GenerationRequestORM.status.in_(ACTIVE_STATUSES),
                    or_(
                        GenerationRequestORM.heartbeat_at < limit,
                        and_(
                            GenerationRequestORM.heartbeat_at.is_(None),
                            GenerationRequestORM.created_at < limit,
                        ),
                    ),
                )
            ).all()
            for row in stale_rows:
                interrupted = interrupt(self._load(session, row), now)  # type: ignore[arg-type]
                row.status = RequestStatus(interrupted.status).value
                row.failure = _problem_to_json(interrupted.failure)
                row.finished_at = now
                for step in interrupted.steps:
                    step_row = session.get(GenerationStepORM, (row.id, step.position))
                    if step_row is not None:
                        _copy_step(step, step_row)
            session.commit()
            return len(stale_rows)
