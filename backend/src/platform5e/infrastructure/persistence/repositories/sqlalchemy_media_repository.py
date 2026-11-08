"""
Archivos generados de los recursos (imágenes y audios), guardados en la base junto a su descripción.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import JSON, Column, LargeBinary, String

from platform5e.application.ports.outbound.media_port import MediaRepositoryPort
from platform5e.infrastructure.persistence.database import Base, SessionLocal, engine
from platform5e.infrastructure.persistence.error_translation import translate_persistence_errors


class MediaAssetORM(Base):
    """Imagen o audio de un recurso. Tabla nueva, ya con nombres en inglés."""

    __tablename__ = "media_assets"
    id = Column(String, primary_key=True)
    teacher_id = Column(String, nullable=False, index=True)
    resource_id = Column(String, nullable=False, index=True)
    details = Column(JSON, nullable=False)
    content = Column(LargeBinary, nullable=False)


class SQLAlchemyMediaRepository(MediaRepositoryPort):
    """Adaptador SQLAlchemy del puerto MediaRepositoryPort."""

    @translate_persistence_errors
    def __init__(self) -> None:
        if engine.dialect.name == "sqlite":
            MediaAssetORM.__table__.create(engine, checkfirst=True)

    @translate_persistence_errors
    def save_media(self, teacher_id: str, media: Mapping[str, Any], content: bytes) -> None:
        with SessionLocal() as session:
            session.merge(
                MediaAssetORM(
                    id=media["id"],
                    teacher_id=teacher_id,
                    resource_id=media["resourceId"],
                    details=dict(media),
                    content=content,
                )
            )
            session.commit()

    @translate_persistence_errors
    def get_media(self, teacher_id: str, media_id: str) -> tuple[dict[str, Any], bytes] | None:
        with SessionLocal() as session:
            entity = session.get(MediaAssetORM, media_id)
            if entity is None or entity.teacher_id != teacher_id:
                return None
            return dict(entity.details), bytes(entity.content)
