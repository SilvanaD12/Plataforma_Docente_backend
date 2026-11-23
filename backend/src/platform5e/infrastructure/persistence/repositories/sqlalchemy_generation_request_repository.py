"""
Persistencia de los pedidos de generación en segundo plano (GEN-01) y de sus pasos mediante SQLAlchemy.

En PostgreSQL las tablas las crea la migración `20261110000001_generation_requests.sql`; en SQLite (desarrollo y
pruebas) las crea este repositorio, como hacen los demás. Las fechas se guardan como texto ISO 8601 en UTC con
microsegundos, para que el orden alfabético coincida con el orden temporal.

Las escrituras del ejecutor son `UPDATE` sobre filas existentes: si el curso se borró mientras se generaba, no
insertan nada y devuelven False. El alta con cupo (`create_within_limit`) serializa los envíos de un mismo docente con
`pg_advisory_xact_lock` en PostgreSQL y con `BEGIN IMMEDIATE` en SQLite.

GEN-P2: el pedido guarda el plan del que parte (`plan_id`, `plan_version`) y cada paso su ítem (`plan_item_position`).
Las columnas las agrega la migración `20261123000001_generation_request_plan.sql`; en una base SQLite que ya existía,
este repositorio las agrega al iniciar. El plan pasa a usado en la misma transacción que el alta del pedido.
"""

from __future__ import annotations

from collections.abc import Callable
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
    exists,
    func,
    inspect,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from platform5e.application.ports.outbound.evidence_provider_port import EvidenceRetrieval
from platform5e.application.ports.outbound.generation_request_repository_port import (
    ActiveRequestLimitReached,
    GenerationRequestRepositoryPort,
    IdempotencyKeyTaken,
    PlanClaim,
    PlanClaimLost,
    UnitNoLongerOwned,
)
from platform5e.domain.generation.generation_plan import PlanStatus
from platform5e.domain.generation.generation_request import (
    FINAL_REQUEST_STATUSES,
    GenerationMode,
    GenerationParameters,
    GenerationRequest,
    GenerationStep,
    PlanReference,
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
    # GEN-P2: el plan del que parte el pedido; NULL en los pedidos anteriores al plan.
    plan_id = Column(String, nullable=True)
    plan_version = Column(Integer, nullable=True)


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
    # GEN-P2: el ítem del plan que redacta el paso; NULL en los pedidos sin plan.
    plan_item_position = Column(Integer, nullable=True)
    # GEN-P2 (tras P4): avisos de solapamiento de los recursos de la IA entregados; NULL o [] si no hay.
    plan_warnings = Column(JSON, nullable=True)


# Columnas de GEN-P2 que una base SQLite anterior no tiene (PostgreSQL usa la migración).
PLAN_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "gen_generation_requests": (("plan_id", "VARCHAR NULL"), ("plan_version", "INTEGER NULL")),
    "gen_generation_steps": (("plan_item_position", "INTEGER NULL"), ("plan_warnings", "JSON NULL")),
}


def ensure_plan_columns_in_sqlite(bind: Engine) -> None:
    """En SQLite `create(checkfirst=True)` no agrega columnas a una tabla que ya existe: se agregan aquí para
    conservar las bases locales, como hace el repositorio de recursos (REV-01, H12)."""
    if bind.dialect.name != "sqlite":
        return
    inspector = inspect(bind)
    with bind.begin() as connection:
        for table, columns in PLAN_COLUMNS.items():
            present = {column["name"] for column in inspector.get_columns(table)}
            for name, definition in columns:
                if name not in present:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text


def _plan_table():
    """La tabla de planes. Se importa aquí porque el repositorio de planes usa `utc_text` de este módulo."""
    from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_plan_repository import (
        GenerationPlanORM,
    )

    return GenerationPlanORM.__table__


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
        modality=_saved_modality(data),
    )


def _saved_modality(data: dict[str, Any]) -> str | None:
    """La modalidad guardada. Los pedidos de antes de HU-024 traen `modalities: ["Textual"]`, que era el valor por
    defecto del servidor y no una elección del docente: se leen sin modalidad (research R11)."""
    modality = data.get("modality")
    return modality if isinstance(modality, str) and modality else None


def _step_to_orm(request_id: str, step: GenerationStep) -> GenerationStepORM:
    row = GenerationStepORM(request_id=request_id, position=step.position)
    _copy_step(step, row)
    return row


def _step_values(step: GenerationStep) -> dict[str, Any]:
    """Columnas del paso que cambian durante la ejecución."""
    return {
        "stage": step.stage,
        "resource_type": step.resource_type,
        "agent": step.agent,
        "status": StepStatus(step.status).value,
        "resource_ids": list(step.resource_ids),
        "rejections": list(step.rejections),
        "generator": step.generator,
        "grounding": step.grounding,
        "distractor_reliability": step.distractor_reliability,
        "error": _problem_to_json(step.error),
        "started_at": utc_text(step.started_at) if step.started_at else None,
        "finished_at": utc_text(step.finished_at) if step.finished_at else None,
        "plan_item_position": step.plan_item_position,
        "plan_warnings": list(step.plan_warnings),
    }


def _copy_step(step: GenerationStep, row: GenerationStepORM) -> None:
    for column, value in _step_values(step).items():
        setattr(row, column, value)


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
        plan_item_position=row.plan_item_position,
        plan_warnings=tuple(row.plan_warnings or ()),
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
        plan_id=request.plan.plan_id if request.plan else None,
        plan_version=request.plan.plan_version if request.plan else None,
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
            RegenerationTarget(regeneration["resourceId"], regeneration["resourceVersion"],
                               regeneration.get("planBlock"))
            if regeneration else None
        ),
        failure=_problem_from_json(row.failure),
        started_at=row.started_at,
        finished_at=row.finished_at,
        heartbeat_at=row.heartbeat_at,
        worker_boot_id=row.worker_boot_id,
        plan=PlanReference(row.plan_id, row.plan_version) if row.plan_id else None,
    )


def lock_teacher_generation_requests(session: Session, teacher_id: str) -> None:
    """En PostgreSQL toma el bloqueo por docente de los pedidos de generación hasta el final de la transacción
    (`pg_advisory_xact_lock`). Lo usan el alta de pedidos y el borrado de cursos (T047), para que no se crucen. En
    otros motores no hace nada: en SQLite la transacción de escritura ya serializa."""
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"gen_generation_requests:{teacher_id}"},
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
            # El alta con plan (GEN-P2) escribe en la tabla de planes en la misma transacción.
            _plan_table().create(bind=self._engine, checkfirst=True)
            ensure_plan_columns_in_sqlite(self._engine)

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
    def create_within_limit(
        self,
        request: GenerationRequest,
        max_active: int,
        unit_still_owned: Callable[[], bool] | None = None,
        plan_claim: PlanClaim | None = None,
    ) -> GenerationRequest:
        with self._sessions() as session:
            # Mientras dura la transacción, ningún otro envío del docente cuenta ni registra pedidos, y el borrado de
            # un curso del docente espera (T047).
            self._lock_teacher(session, request.teacher_id)
            existing = self._find_by_key(session, request.teacher_id, request.idempotency_key)
            if existing is not None:
                session.rollback()
                raise IdempotencyKeyTaken(existing)
            if unit_still_owned is not None and not unit_still_owned():
                session.rollback()
                raise UnitNoLongerOwned()
            active = session.scalar(
                select(func.count())
                .select_from(GenerationRequestORM)
                .where(
                    GenerationRequestORM.teacher_id == request.teacher_id,
                    GenerationRequestORM.status.in_(ACTIVE_STATUSES),
                )
            ) or 0
            if active >= max_active:
                session.rollback()
                raise ActiveRequestLimitReached(max_active)
            if plan_claim is not None and not self._claim_plan(session, plan_claim):
                session.rollback()
                raise PlanClaimLost()
            session.add(_request_to_orm(request))
            session.add_all(_step_to_orm(request.id, step) for step in request.steps)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = self._find_by_key(session, request.teacher_id, request.idempotency_key)
                if existing is None:
                    raise
                raise IdempotencyKeyTaken(existing) from None
            return self._load(session, session.get(GenerationRequestORM, request.id))  # type: ignore[return-value]

    @staticmethod
    def _claim_plan(session: Session, claim: PlanClaim) -> bool:
        """GEN-P2: el plan pasa a usado solo si sigue aprobado y en la versión leída, en la transacción del alta."""
        from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_plan_repository import (
            GenerationPlanORM,
            plan_update_values,
        )

        plan = claim.plan
        result = session.execute(
            update(GenerationPlanORM)
            .where(
                GenerationPlanORM.teacher_id == plan.teacher_id,
                GenerationPlanORM.id == plan.id,
                GenerationPlanORM.version == claim.expected_version,
                GenerationPlanORM.status == PlanStatus.APPROVED.value,
            )
            .values(**plan_update_values(plan))
        )
        return result.rowcount == 1

    @staticmethod
    def _lock_teacher(session: Session, teacher_id: str) -> None:
        """Bloqueo por docente hasta el final de la transacción (research R4)."""
        dialect = session.get_bind().dialect.name
        if dialect == "postgresql":
            lock_teacher_generation_requests(session, teacher_id)
        elif dialect == "sqlite":
            # Toma el bloqueo de escritura antes de contar: otro envío espera (busy timeout) en vez de leer lo mismo.
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")

    @staticmethod
    def _exists(session: Session, request_id: str) -> bool:
        return bool(session.scalar(select(exists().where(GenerationRequestORM.id == request_id))))

    @translate_persistence_errors
    def mark_running(self, request_id: str, worker_boot_id: str) -> None:
        """Solo un pedido en cola pasa a ejecución; uno interrumpido, terminado o borrado no cambia."""
        now = utc_text()
        with self._sessions() as session:
            session.execute(
                update(GenerationRequestORM)
                .where(
                    GenerationRequestORM.id == request_id,
                    GenerationRequestORM.status == RequestStatus.QUEUED.value,
                )
                .values(
                    status=RequestStatus.RUNNING.value,
                    started_at=now,
                    heartbeat_at=now,
                    worker_boot_id=worker_boot_id,
                )
            )
            session.commit()

    @translate_persistence_errors
    def save_evidence(self, request_id: str, retrieval: EvidenceRetrieval, retrieved_at: str) -> bool:
        with self._sessions() as session:
            result = session.execute(
                update(GenerationRequestORM)
                .where(GenerationRequestORM.id == request_id)
                .values(
                    evidence=[fragment.to_dict(retrieved_at) for fragment in retrieval.fragments],
                    retrieval_mode=retrieval.retrieval_mode,
                )
            )
            session.commit()
            return result.rowcount > 0

    @translate_persistence_errors
    def update_step(self, request_id: str, step: GenerationStep) -> bool:
        """Actualiza el paso solo si el pedido y el paso existen; nunca lo inserta (no deja pasos huérfanos)."""
        with self._sessions() as session:
            result = session.execute(
                update(GenerationStepORM)
                .where(
                    GenerationStepORM.request_id == request_id,
                    GenerationStepORM.position == step.position,
                    exists().where(GenerationRequestORM.id == request_id),
                )
                .values(**_step_values(step))
            )
            session.commit()
            return result.rowcount > 0

    @translate_persistence_errors
    def heartbeat(self, request_id: str) -> bool:
        """Renueva el latido de un pedido en cola o en ejecución (el ejecutor lo hace con todos los que tiene)."""
        with self._sessions() as session:
            result = session.execute(
                update(GenerationRequestORM)
                .where(
                    GenerationRequestORM.id == request_id,
                    GenerationRequestORM.status.in_(ACTIVE_STATUSES),
                )
                .values(heartbeat_at=utc_text())
            )
            session.commit()
            return result.rowcount > 0 or self._exists(session, request_id)

    @translate_persistence_errors
    def finish(self, request_id: str, status: RequestStatus, failure: Problem | None) -> bool:
        """Cierra el pedido. Los pasos sin terminar pasan a `interrupted` si el pedido se interrumpe y a `failed`
        en los demás casos, con el mismo motivo. Un pedido ya terminado no cambia."""
        now = utc_text()
        step_status = StepStatus.INTERRUPTED if status == RequestStatus.INTERRUPTED else StepStatus.FAILED
        with self._sessions() as session:
            closed = session.execute(
                update(GenerationRequestORM)
                .where(
                    GenerationRequestORM.id == request_id,
                    GenerationRequestORM.status.not_in([s.value for s in FINAL_REQUEST_STATUSES]),
                )
                .values(status=RequestStatus(status).value, failure=_problem_to_json(failure), finished_at=now)
            )
            if closed.rowcount:
                session.execute(
                    update(GenerationStepORM)
                    .where(
                        GenerationStepORM.request_id == request_id,
                        GenerationStepORM.status.in_((StepStatus.PENDING.value, StepStatus.RUNNING.value)),
                    )
                    .values(status=step_status.value, error=_problem_to_json(failure), finished_at=now)
                )
            session.commit()
            return closed.rowcount > 0 or self._exists(session, request_id)

    @translate_persistence_errors
    def mark_interrupted(self, stale_before: datetime) -> int:
        """Barridos de arranque y periódico (research R3): interrumpe los pedidos activos cuyo último latido, o su
        creación si nunca latieron, es anterior a `stale_before`. Los pasos terminados y sus recursos se conservan."""
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
