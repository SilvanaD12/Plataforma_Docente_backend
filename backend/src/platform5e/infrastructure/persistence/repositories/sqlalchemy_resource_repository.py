"""
Persistencia de recursos revisados e historial de descargas por unidad (HU-010).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, inspect, or_, select, text, update

from platform5e.application.ports.outbound.resource_repository_port import ResourceReviewRepositoryPort
from platform5e.infrastructure.persistence.database import SessionLocal, engine
from platform5e.infrastructure.persistence.error_translation import translate_persistence_errors
from platform5e.infrastructure.persistence.repositories.sqlalchemy_account_repository import (
    DownloadORM,
    TeacherResourceORM,
)


def _ensure_version_column_in_sqlite() -> None:
    """En SQLite las migraciones SQL no se aplican y `create(checkfirst=True)` no agrega columnas a una tabla que ya
    existe: se agrega aquí para conservar las bases locales (REV-01, hallazgo H12). PostgreSQL usa la migración."""
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    table = TeacherResourceORM.__tablename__
    if not inspector.has_table(table):
        return
    columns = {column["name"] for column in inspector.get_columns(table)}
    with engine.begin() as connection:
        if "version" not in columns:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN version INTEGER NOT NULL DEFAULT 1"))
        if "regeneration_claim" not in columns:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN regeneration_claim INTEGER NULL"))
        if "regeneration_attempt" not in columns:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN regeneration_attempt VARCHAR NULL"))


def _with_version(entity: TeacherResourceORM) -> dict[str, Any]:
    """El recurso guardado con la versión de la columna, que es la vigente (los recursos antiguos están en la 1)."""
    return {**entity.resource_data, "version": entity.version or 1}


class SQLAlchemyResourceRepository(ResourceReviewRepositoryPort):
    """Adaptador SQLAlchemy para la revisión de los recursos generados y el historial de descargas."""

    @translate_persistence_errors
    def __init__(self) -> None:
        _ensure_version_column_in_sqlite()

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
            return [_with_version(entity) for entity in session.scalars(statement)]

    @translate_persistence_errors
    def get_resource_by_id(self, teacher_id: str, resource_id: str) -> dict[str, Any] | None:
        with SessionLocal() as session:
            entity = session.get(TeacherResourceORM, resource_id)
            return _with_version(entity) if entity and entity.teacher_id == teacher_id else None

    @translate_persistence_errors
    def save_resources(
        self, teacher_id: str, unit_id: str, resources: list[dict[str, Any]]
    ) -> None:
        with SessionLocal() as session:
            for res in resources:
                version = int(res.get("version") or 1)
                session.merge(
                    TeacherResourceORM(
                        id=res["id"],
                        teacher_id=teacher_id,
                        unit_id=unit_id,
                        created_at=res.get("createdAt", ""),
                        resource_data={**res, "version": version},
                        version=version,
                    )
                )
            session.commit()

    @translate_persistence_errors
    def save_resource_if_version(
        self,
        teacher_id: str,
        unit_id: str,
        resource: dict[str, Any],
        expected_version: int,
        increment: bool = True,
    ) -> bool:
        new_version = expected_version + 1 if increment else expected_version
        with SessionLocal() as session:
            result = session.execute(
                update(TeacherResourceORM)
                .where(
                    TeacherResourceORM.id == resource["id"],
                    TeacherResourceORM.teacher_id == teacher_id,
                    TeacherResourceORM.unit_id == unit_id,
                    TeacherResourceORM.version == expected_version,
                )
                .values(resource_data={**resource, "version": new_version}, version=new_version)
            )
            session.commit()
            return result.rowcount == 1

    @translate_persistence_errors
    def claim_regeneration(
        self, teacher_id: str, unit_id: str, resource: dict[str, Any], expected_version: int
    ) -> bool:
        with SessionLocal() as session:
            result = session.execute(
                update(TeacherResourceORM)
                .where(
                    TeacherResourceORM.id == resource["id"],
                    TeacherResourceORM.teacher_id == teacher_id,
                    TeacherResourceORM.unit_id == unit_id,
                    TeacherResourceORM.version == expected_version,
                    or_(
                        TeacherResourceORM.regeneration_claim.is_(None),
                        TeacherResourceORM.regeneration_claim != expected_version,
                    ),
                )
                .values(
                    resource_data={**resource, "version": expected_version},
                    regeneration_claim=expected_version,
                    regeneration_attempt=(resource.get("regeneration") or {}).get("attemptId"),
                )
            )
            session.commit()
            return result.rowcount == 1

    @translate_persistence_errors
    def save_resource_if_attempt(
        self,
        teacher_id: str,
        unit_id: str,
        resource: dict[str, Any],
        expected_version: int,
        attempt_id: str,
        increment: bool = False,
    ) -> bool:
        new_version = expected_version + 1 if increment else expected_version
        with SessionLocal() as session:
            result = session.execute(
                update(TeacherResourceORM)
                .where(
                    TeacherResourceORM.id == resource["id"],
                    TeacherResourceORM.teacher_id == teacher_id,
                    TeacherResourceORM.unit_id == unit_id,
                    TeacherResourceORM.version == expected_version,
                    TeacherResourceORM.regeneration_attempt == attempt_id,
                )
                .values(resource_data={**resource, "version": new_version}, version=new_version)
            )
            session.commit()
            return result.rowcount == 1

    @translate_persistence_errors
    def release_regeneration(self, teacher_id: str, unit_id: str, resource_id: str, attempt_id: str) -> None:
        with SessionLocal() as session:
            session.execute(
                update(TeacherResourceORM)
                .where(
                    TeacherResourceORM.id == resource_id,
                    TeacherResourceORM.teacher_id == teacher_id,
                    TeacherResourceORM.unit_id == unit_id,
                    TeacherResourceORM.regeneration_attempt == attempt_id,
                )
                .values(regeneration_claim=None)
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
    def get_downloads_by_teacher(self, teacher_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as session:
            statement = (
                select(DownloadORM)
                .where(DownloadORM.teacher_id == teacher_id)
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
