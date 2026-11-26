"""
Cuentas docentes, sesiones, cursos, documentos binarios y relaciones de persistencia.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    Float,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    delete,
    inspect,
    select,
    text,
)

from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort
from platform5e.infrastructure.persistence.database import Base, SessionLocal, engine, run_with_db_retry
from platform5e.infrastructure.persistence.error_translation import translate_persistence_errors
from platform5e.infrastructure.persistence.repositories.sqlalchemy_media_repository import MediaAssetORM
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_plan_repository import GenerationPlanORM
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_request_repository import (
    GenerationRequestORM,
    GenerationStepORM,
    lock_teacher_generation_requests,
)


_LEGACY_COURSE_KEYS = {"sumilla": "summary", "logro": "learningGoal"}
_LEGACY_ORIGIN_KEYS = {"fuente": "source", "licencia": "license", "tema": "topic"}


def _rename_keys(data: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    return {names.get(key, key): value for key, value in data.items()}


def adapt_legacy_course(data: dict[str, Any]) -> dict[str, Any]:
    return _rename_keys(data, _LEGACY_COURSE_KEYS)


def adapt_legacy_document(metadata: dict[str, Any]) -> dict[str, Any]:
    origin = metadata.get("origin")
    if isinstance(origin, dict):
        return {**metadata, "origin": _rename_keys(origin, _LEGACY_ORIGIN_KEYS)}
    return metadata


class UserORM(Base):
    """Cuentas de docentes (HU-001). Almacena hash PBKDF2 y sal criptográfica."""

    __tablename__ = "ep002_usuarios"
    email = Column(String, primary_key=True)
    name = Column("nombre", String, nullable=False)
    salt = Column("sal", String, nullable=False)
    password_hash = Column("clave", String, nullable=False)
    created_at = Column("creado", String, nullable=False)


class SessionORM(Base):
    """Sesiones activas del docente con huella digital SHA-256."""

    __tablename__ = "ep002_sesiones"
    fingerprint = Column("huella", String, primary_key=True)
    teacher_id = Column("docente", String, nullable=False)
    expires_at = Column("vence", Float, nullable=False)


class CourseORM(Base):
    """Cursos académicos registrados por el docente."""

    __tablename__ = "ep002_cursos"
    teacher_id = Column("docente", String, primary_key=True)
    id = Column(String, primary_key=True)
    code = Column("codigo", String, nullable=False)
    data = Column("datos", JSON, nullable=False)
    __table_args__ = (UniqueConstraint("docente", "codigo"),)


class DocumentORM(Base):
    """Documentos y material de referencia almacenados en formato binario."""

    __tablename__ = "ep002_documentos"
    id = Column(String, primary_key=True)
    teacher_id = Column("docente", String, nullable=False)
    unit_id = Column("unidad", String, nullable=False)
    file_name = Column("nombre", String, nullable=False)
    content_hash = Column("content_hash", String, nullable=True, index=True)
    metadata_json = Column("datos", JSON, nullable=False)
    content_bytes = Column("contenido", LargeBinary, nullable=False)
    __table_args__ = (UniqueConstraint("docente", "unidad", "nombre"),)


class ChunkORM(Base):
    """Fragmentos de texto procesados del material para citación y RAG."""

    __tablename__ = "ep002_fragmentos"
    id = Column(String, primary_key=True)
    teacher_id = Column("docente", String, nullable=False, index=True)
    document_id = Column("documento", String, nullable=False, index=True)
    unit_id = Column("unidad", String, nullable=False, index=True)
    order_index = Column("orden", Integer, nullable=False)
    location = Column("ubicacion", String, nullable=False)
    text_content = Column("texto", Text, nullable=False)


class TeacherResourceORM(Base):
    """Recursos pedagógicos generados para una unidad y su revisión."""

    __tablename__ = "ep002_recursos"
    id = Column(String, primary_key=True)
    teacher_id = Column("docente", String, nullable=False, index=True)
    unit_id = Column("unidad", String, nullable=False, index=True)
    created_at = Column("creado", String, nullable=False)
    resource_data = Column("datos", JSON, nullable=False)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    regeneration_claim = Column(Integer, nullable=True)
    regeneration_attempt = Column(String, nullable=True)
    regeneration_status = Column(String, nullable=True)


class DownloadORM(Base):
    """Registro histórico de descargas generadas en una unidad."""

    __tablename__ = "ep002_descargas"
    id = Column(String, primary_key=True)
    teacher_id = Column("docente", String, nullable=False, index=True)
    unit_id = Column("unidad", String, nullable=False, index=True)
    created_at = Column("creado", String, nullable=False)
    download_data = Column("datos", JSON, nullable=False)


class GenerationORM(Base):
    """Generación guardada por la ruta síncrona retirada (T046): historial de solo lectura, tal como se respondió."""

    __tablename__ = "generaciones_demo"
    id = Column(String, primary_key=True)
    result = Column("resultado", JSON, nullable=False)


class TeacherGenerationORM(Base):
    """Docente dueño de cada generación del historial (`generaciones_demo`)."""

    __tablename__ = "ep002_generaciones_docente"
    id = Column(String, primary_key=True)
    teacher_id = Column("docente", String, nullable=False)


_LEGACY_GENERATOR_KEYS = {"descripcion": "description", "usaIA": "usesAi"}


def adapt_legacy_generation(result: dict[str, Any]) -> dict[str, Any]:
    """Adapta al contrato actual una generación guardada con las claves anteriores, sin migrar la base."""
    generator = result.get("generator")
    if isinstance(generator, dict):
        generator = {_LEGACY_GENERATOR_KEYS.get(key, key): value for key, value in generator.items()}
        return {**result, "generator": generator}
    return result


TABLES_TO_REGISTER = (
    UserORM,
    SessionORM,
    CourseORM,
    DocumentORM,
    ChunkORM,
    TeacherResourceORM,
    MediaAssetORM,
    DownloadORM,
    GenerationORM,
    TeacherGenerationORM,
)


class SQLAlchemyAccountRepository(TeacherRepositoryPort):
    """Adaptador de persistencia SQLAlchemy para cuentas, sesiones, cursos y documentos."""

    @translate_persistence_errors
    def __init__(self) -> None:
        if engine.dialect.name == "sqlite":
            for table in TABLES_TO_REGISTER:
                table.__table__.create(engine, checkfirst=True)

    @translate_persistence_errors
    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        with SessionLocal() as session:
            entity = session.get(UserORM, email)
            if not entity:
                return None
            return {
                "email": entity.email,
                "nombre": entity.name,
                "sal": entity.salt,
                "clave": entity.password_hash,
            }

    @translate_persistence_errors
    def create_user(self, user_data: dict[str, Any]) -> None:
        with SessionLocal() as session:
            session.add(
                UserORM(
                    email=user_data["email"],
                    name=user_data["nombre"],
                    salt=user_data["sal"],
                    password_hash=user_data["clave"],
                    created_at=user_data["creado"],
                )
            )
            session.commit()

    @translate_persistence_errors
    def init_catalog(self, teacher_id: str) -> None:
        with SessionLocal() as session:
            exists = session.scalars(
                select(CourseORM).where(CourseORM.teacher_id == teacher_id)
            ).first()
            if exists:
                return
            fixture_path = Path(__file__).resolve().parents[1] / "seed" / "demo_generation.json"
            demo_units = json.loads(fixture_path.read_text(encoding="utf-8"))["units"]
            initial_course = {
                "id": "curso-aed",
                "code": "ICSI-205",
                "name": "Algoritmos y Estructuras de Datos",
                "term": "2026-II",
                "units": demo_units,
            }
            session.add(
                CourseORM(
                    teacher_id=teacher_id,
                    id=initial_course["id"],
                    code=initial_course["code"],
                    data=initial_course,
                )
            )
            session.commit()

    @translate_persistence_errors
    def save_session(self, fingerprint: str, teacher_id: str, expires_at: float) -> None:
        with SessionLocal() as session:
            session.add(
                SessionORM(fingerprint=fingerprint, teacher_id=teacher_id, expires_at=expires_at)
            )
            session.commit()

    @translate_persistence_errors
    def get_session(self, fingerprint: str) -> tuple[str, float] | None:
        with SessionLocal() as session:
            session_entity = session.get(SessionORM, fingerprint)
            return (session_entity.teacher_id, session_entity.expires_at) if session_entity else None

    @translate_persistence_errors
    def delete_session(self, fingerprint: str) -> None:
        with SessionLocal() as session:
            session_entity = session.get(SessionORM, fingerprint)
            if session_entity:
                session.delete(session_entity)
                session.commit()

    @translate_persistence_errors
    def get_courses(self, teacher_id: str) -> list[dict[str, Any]]:
        def _query() -> list[dict[str, Any]]:
            with SessionLocal() as session:
                statement = (
                    select(CourseORM)
                    .where(CourseORM.teacher_id == teacher_id)
                    .order_by(CourseORM.id)
                )
                return [adapt_legacy_course(course.data) for course in session.scalars(statement)]

        return run_with_db_retry(_query)

    @translate_persistence_errors
    def save_course(self, teacher_id: str, course_data: dict[str, Any]) -> None:
        with SessionLocal() as session:
            session.merge(
                CourseORM(
                    teacher_id=teacher_id,
                    id=course_data["id"],
                    code=course_data["code"],
                    data=course_data,
                )
            )
            session.commit()

    @translate_persistence_errors
    def delete_course(self, teacher_id: str, course_id: str, unit_ids: list[str]) -> None:
        with SessionLocal() as session:
            lock_teacher_generation_requests(session, teacher_id)
            resource_ids = select(TeacherResourceORM.id).where(
                TeacherResourceORM.teacher_id == teacher_id,
                TeacherResourceORM.unit_id.in_(unit_ids),
            )
            session.execute(
                delete(MediaAssetORM).where(
                    MediaAssetORM.teacher_id == teacher_id,
                    MediaAssetORM.resource_id.in_(resource_ids),
                )
            )
            for table in (ChunkORM, DocumentORM, TeacherResourceORM):
                session.execute(
                    delete(table).where(
                        table.teacher_id == teacher_id, table.unit_id.in_(unit_ids)
                    )
                )
            connection = session.connection()
            if inspect(connection).has_table(GenerationRequestORM.__tablename__):
                request_ids = select(GenerationRequestORM.id).where(
                    GenerationRequestORM.teacher_id == teacher_id,
                    GenerationRequestORM.unit_id.in_(unit_ids),
                )
                if connection.dialect.name == "sqlite" and not connection.execute(text("PRAGMA foreign_keys")).scalar():
                    session.execute(delete(GenerationStepORM).where(GenerationStepORM.request_id.in_(request_ids)))
                session.execute(
                    delete(GenerationRequestORM).where(
                        GenerationRequestORM.teacher_id == teacher_id, GenerationRequestORM.unit_id.in_(unit_ids)
                    )
                )
            if inspect(connection).has_table(GenerationPlanORM.__tablename__):
                session.execute(
                    delete(GenerationPlanORM).where(
                        GenerationPlanORM.teacher_id == teacher_id, GenerationPlanORM.unit_id.in_(unit_ids)
                    )
                )
            session.execute(
                delete(CourseORM).where(
                    CourseORM.teacher_id == teacher_id, CourseORM.id == course_id
                )
            )
            session.commit()

    @translate_persistence_errors
    def get_documents(self, teacher_id: str) -> list[dict[str, Any]]:
        def _query() -> list[dict[str, Any]]:
            with SessionLocal() as session:
                statement = (
                    select(DocumentORM)
                    .where(DocumentORM.teacher_id == teacher_id)
                    .order_by(DocumentORM.id.desc())
                )
                docs: list[dict[str, Any]] = []
                for doc in session.scalars(statement):
                    adapted = adapt_legacy_document(doc.metadata_json)
                    if doc.content_hash and not adapted.get("contentHash"):
                        adapted = {**adapted, "contentHash": doc.content_hash}
                    docs.append(adapted)
                return docs

        return run_with_db_retry(_query)

    @translate_persistence_errors
    def save_document(
        self, teacher_id: str, metadata: dict[str, Any], content: bytes
    ) -> None:
        def _write() -> None:
            with SessionLocal() as session:
                session.add(
                    DocumentORM(
                        id=metadata["id"],
                        teacher_id=teacher_id,
                        unit_id=metadata["unitId"],
                        file_name=metadata["fileName"].casefold(),
                        content_hash=metadata.get("contentHash"),
                        metadata_json=metadata,
                        content_bytes=content,
                    )
                )
                session.commit()

        run_with_db_retry(_write)

    @translate_persistence_errors
    def get_document(
        self, teacher_id: str, document_id: str
    ) -> tuple[dict[str, Any], bytes] | None:
        def _query() -> tuple[dict[str, Any], bytes] | None:
            with SessionLocal() as session:
                doc = session.get(DocumentORM, document_id)
                if doc is None or doc.teacher_id != teacher_id:
                    return None
                adapted = adapt_legacy_document(doc.metadata_json)
                if doc.content_hash and not adapted.get("contentHash"):
                    adapted = {**adapted, "contentHash": doc.content_hash}
                return adapted, doc.content_bytes

        return run_with_db_retry(_query)

    @translate_persistence_errors
    def delete_document(self, teacher_id: str, document_id: str) -> None:
        with SessionLocal() as session:
            doc = session.get(DocumentORM, document_id)
            if doc and doc.teacher_id == teacher_id:
                session.execute(
                    delete(ChunkORM).where(
                        ChunkORM.document_id == document_id, ChunkORM.teacher_id == teacher_id
                    )
                )
                session.delete(doc)
                session.commit()

    @translate_persistence_errors
    def get_history(self, teacher_id: str) -> list[dict[str, Any]]:
        with SessionLocal() as session:
            statement = (
                select(GenerationORM)
                .join(TeacherGenerationORM, GenerationORM.id == TeacherGenerationORM.id)
                .where(TeacherGenerationORM.teacher_id == teacher_id)
                .order_by(GenerationORM.id.desc())
            )
            return [gen.result["request"] for gen in session.scalars(statement)]

    @translate_persistence_errors
    def get_generation_owner(self, generation_id: str) -> str | None:
        with SessionLocal() as session:
            entity = session.get(TeacherGenerationORM, generation_id)
            return entity.teacher_id if entity else None

    @translate_persistence_errors
    def get_generation(self, generation_id: str) -> dict[str, Any] | None:
        with SessionLocal() as session:
            entity = session.get(GenerationORM, generation_id)
            return adapt_legacy_generation(entity.result) if entity else None