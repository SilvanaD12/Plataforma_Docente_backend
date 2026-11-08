"""
Cuentas docentes, sesiones, cursos, documentos binarios y relaciones de persistencia.
"""

from __future__ import annotations

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
    select,
)

from platform5e.application.ports.outbound.generation_repository_port import GenerationRepositoryPort
from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort
from platform5e.infrastructure.persistence.database import Base, SessionLocal, engine
from platform5e.infrastructure.persistence.error_translation import translate_persistence_errors
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_repository import (
    GenerationORM,
    TeacherGenerationORM,
)


# Cursos y documentos guardados antes del contrato en inglés (octubre de 2026) traen claves en español.
# Se adaptan al leer, sin migrar la base; el Sprint 2 los migra y quita esta adaptación.
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


class DownloadORM(Base):
    """Registro histórico de descargas generadas en una unidad."""

    __tablename__ = "ep002_descargas"
    id = Column(String, primary_key=True)
    teacher_id = Column("docente", String, nullable=False, index=True)
    unit_id = Column("unidad", String, nullable=False, index=True)
    created_at = Column("creado", String, nullable=False)
    download_data = Column("datos", JSON, nullable=False)


TABLES_TO_REGISTER = (
    UserORM,
    SessionORM,
    CourseORM,
    DocumentORM,
    ChunkORM,
    TeacherResourceORM,
    DownloadORM,
)


class SQLAlchemyAccountRepository(TeacherRepositoryPort):
    """Adaptador de persistencia SQLAlchemy para cuentas, sesiones, cursos y documentos."""

    @translate_persistence_errors
    def __init__(self, generation_repository: GenerationRepositoryPort) -> None:
        self._generation_repository = generation_repository
        if engine.dialect.name == "sqlite":
            for table in (*TABLES_TO_REGISTER, TeacherGenerationORM):
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
            demo_units = self._generation_repository.get_demo_catalog()["units"]
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
        with SessionLocal() as session:
            statement = (
                select(CourseORM)
                .where(CourseORM.teacher_id == teacher_id)
                .order_by(CourseORM.id)
            )
            return [adapt_legacy_course(course.data) for course in session.scalars(statement)]

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
            for table in (ChunkORM, DocumentORM, TeacherResourceORM, DownloadORM):
                session.execute(
                    delete(table).where(
                        table.teacher_id == teacher_id, table.unit_id.in_(unit_ids)
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
        with SessionLocal() as session:
            statement = (
                select(DocumentORM)
                .where(DocumentORM.teacher_id == teacher_id)
                .order_by(DocumentORM.id.desc())
            )
            return [adapt_legacy_document(doc.metadata_json) for doc in session.scalars(statement)]

    @translate_persistence_errors
    def save_document(
        self, teacher_id: str, metadata: dict[str, Any], content: bytes
    ) -> None:
        with SessionLocal() as session:
            session.add(
                DocumentORM(
                    id=metadata["id"],
                    teacher_id=teacher_id,
                    unit_id=metadata["unitId"],
                    file_name=metadata["fileName"].casefold(),
                    metadata_json=metadata,
                    content_bytes=content,
                )
            )
            session.commit()

    @translate_persistence_errors
    def get_document(
        self, teacher_id: str, document_id: str
    ) -> tuple[dict[str, Any], bytes] | None:
        with SessionLocal() as session:
            doc = session.get(DocumentORM, document_id)
            if doc is None or doc.teacher_id != teacher_id:
                return None
            return adapt_legacy_document(doc.metadata_json), doc.content_bytes

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