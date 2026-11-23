"""Repositorio SQLAlchemy para almacenar referentes por docente y unidad (MAT-P2)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, String, Text, delete, select

from platform5e.application.ports.outbound.referent_repository_port import ReferentRepositoryPort
from platform5e.domain.generation.generation_plan import Referent
from platform5e.infrastructure.persistence.database import Base, SessionLocal
from platform5e.infrastructure.persistence.error_translation import translate_persistence_errors


class ReferentORM(Base):
    __tablename__ = "ep004_referentes"

    id = Column(String(64), primary_key=True)
    teacher_id = Column(String(128), nullable=False, index=True)
    unit_id = Column(String(128), nullable=False, index=True)
    document_id = Column(String(128), nullable=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=False, default="")
    fragment_ids_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime(timezone=True), nullable=False)


class SQLAlchemyReferentRepository(ReferentRepositoryPort):
    @translate_persistence_errors
    def replace_unit_referents(
        self,
        teacher_id: str,
        unit_id: str,
        referents: Sequence[Referent],
        document_id: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        with SessionLocal() as session:
            if document_id:
                session.execute(
                    delete(ReferentORM).where(
                        ReferentORM.teacher_id == teacher_id,
                        ReferentORM.unit_id == unit_id,
                        ReferentORM.document_id == document_id,
                    )
                )
            else:
                session.execute(
                    delete(ReferentORM).where(
                        ReferentORM.teacher_id == teacher_id,
                        ReferentORM.unit_id == unit_id,
                    )
                )

            rows = [
                ReferentORM(
                    id=f"ref-{uuid4().hex[:16]}",
                    teacher_id=teacher_id,
                    unit_id=unit_id,
                    document_id=document_id,
                    name=ref.name,
                    description=ref.description,
                    fragment_ids_json=json.dumps(list(ref.fragment_ids), ensure_ascii=False),
                    created_at=now,
                )
                for ref in referents
            ]
            session.add_all(rows)
            session.commit()

    @translate_persistence_errors
    def get_unit_referents(self, teacher_id: str, unit_id: str) -> list[Referent]:
        with SessionLocal() as session:
            stmt = (
                select(ReferentORM)
                .where(ReferentORM.teacher_id == teacher_id, ReferentORM.unit_id == unit_id)
                .order_by(ReferentORM.created_at, ReferentORM.id)
            )
            entities = session.scalars(stmt).all()
            result: list[Referent] = []
            for entity in entities:
                try:
                    fids = json.loads(entity.fragment_ids_json or "[]")
                except ValueError:
                    fids = []
                result.append(
                    Referent(
                        name=entity.name,
                        description=entity.description or "",
                        fragment_ids=tuple(str(fid) for fid in fids if isinstance(fid, str)),
                    )
                )
            return result