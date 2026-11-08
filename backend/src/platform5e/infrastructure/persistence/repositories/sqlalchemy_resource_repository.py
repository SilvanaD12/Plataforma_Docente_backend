"""
Persistencia de recursos revisados e historial de descargas por unidad (HU-010).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select

from platform5e.application.ports.outbound.resource_repository_port import ResourceReviewRepositoryPort
from platform5e.infrastructure.persistence.database import SessionLocal
from platform5e.infrastructure.persistence.error_translation import translate_persistence_errors
from platform5e.infrastructure.persistence.repositories.sqlalchemy_account_repository import (
    DownloadORM,
    TeacherResourceORM,
)


class SQLAlchemyResourceRepository(ResourceReviewRepositoryPort):
    """Adaptador SQLAlchemy para la revisión de los recursos generados y el historial de descargas."""

    @translate_persistence_errors
    def get_resources_by_unit(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as session:
            statement = (
                select(TeacherResourceORM)
                .where(
                    TeacherResourceORM.teacher_id == teacher_id,
                    TeacherResourceORM.unit_id == unit_id,
                )
                .order_by(TeacherResourceORM.created_at.desc())
            )
            return [entity.resource_data for entity in session.scalars(statement)]

    @translate_persistence_errors
    def get_resource_by_id(self, teacher_id: str, resource_id: str) -> dict[str, Any] | None:
        with SessionLocal() as session:
            entity = session.get(TeacherResourceORM, resource_id)
            return entity.resource_data if entity and entity.teacher_id == teacher_id else None

    @translate_persistence_errors
    def save_resources(
        self, teacher_id: str, unit_id: str, resources: list[dict[str, Any]]
    ) -> None:
        with SessionLocal() as session:
            for res in resources:
                session.merge(
                    TeacherResourceORM(
                        id=res["id"],
                        teacher_id=teacher_id,
                        unit_id=unit_id,
                        created_at=res.get("createdAt", ""),
                        resource_data=res,
                    )
                )
            session.commit()

    @translate_persistence_errors
    def delete_resource(self, teacher_id: str, resource_id: str) -> None:
        with SessionLocal() as session:
            session.execute(
                delete(TeacherResourceORM).where(
                    TeacherResourceORM.id == resource_id,
                    TeacherResourceORM.teacher_id == teacher_id,
                )
            )
            session.commit()

    @translate_persistence_errors
    def get_downloads(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as session:
            statement = (
                select(DownloadORM)
                .where(DownloadORM.teacher_id == teacher_id, DownloadORM.unit_id == unit_id)
                .order_by(DownloadORM.created_at.desc())
            )
            return [entity.download_data for entity in session.scalars(statement)]

    @translate_persistence_errors
    def save_download(
        self, teacher_id: str, unit_id: str, download_record: dict[str, Any]
    ) -> None:
        with SessionLocal() as session:
            session.add(
                DownloadORM(
                    id=download_record["id"],
                    teacher_id=teacher_id,
                    unit_id=unit_id,
                    created_at=download_record.get("createdAt", ""),
                    download_data=download_record,
                )
            )
            session.commit()

    @translate_persistence_errors
    def delete_downloads(self, teacher_id: str, unit_id: str) -> None:
        with SessionLocal() as session:
            session.execute(
                delete(DownloadORM).where(
                    DownloadORM.teacher_id == teacher_id, DownloadORM.unit_id == unit_id
                )
            )
            session.commit()
