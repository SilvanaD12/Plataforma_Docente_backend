"""
Persistencia de solicitudes y propuestas de generación mediante SQLAlchemy.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, Column, String

from platform5e.application.ports.outbound.generation_repository_port import GenerationRepositoryPort
from platform5e.infrastructure.persistence.database import Base, SessionLocal, engine
from platform5e.infrastructure.persistence.error_translation import translate_persistence_errors


# Generaciones guardadas antes del contrato en inglés: su bloque «generator» tenía claves en español.
_LEGACY_GENERATOR_KEYS = {"descripcion": "description", "usaIA": "usesAi"}


def adapt_legacy_generation(result: dict[str, Any]) -> dict[str, Any]:
    generator = result.get("generator")
    if isinstance(generator, dict):
        generator = {_LEGACY_GENERATOR_KEYS.get(key, key): value for key, value in generator.items()}
        return {**result, "generator": generator}
    return result


class GenerationORM(Base):
    """Modelo relacional para registrar la generación completa de propuestas."""

    __tablename__ = "generaciones_demo"
    id = Column(String, primary_key=True)
    result = Column("resultado", JSON, nullable=False)


class TeacherGenerationORM(Base):
    """Asociación entre la solicitud de generación y el docente propietario."""

    __tablename__ = "ep002_generaciones_docente"
    id = Column(String, primary_key=True)
    teacher_id = Column("docente", String, nullable=False)


class SQLAlchemyGenerationRepository(GenerationRepositoryPort):
    """Adaptador de infraestructura para la persistencia del motor de generación."""

    @translate_persistence_errors
    def __init__(self) -> None:
        if engine.dialect.name == "sqlite":
            GenerationORM.__table__.create(bind=engine, checkfirst=True)
            TeacherGenerationORM.__table__.create(bind=engine, checkfirst=True)

    @translate_persistence_errors
    def get_demo_catalog(self) -> dict[str, Any]:
        """Carga el catálogo precargado para el modo de demostración."""
        # Busca el seed en ../seed/demo_generation.json o en fixtures
        fixture_path = Path(__file__).resolve().parents[1] / "seed" / "demo_generation.json"
        if not fixture_path.exists():
            fixture_path = Path(__file__).resolve().parents[2] / "fixtures" / "generacion_demo.json"
        return json.loads(fixture_path.read_text(encoding="utf-8"))

    @translate_persistence_errors
    def save(self, result: dict[str, Any], teacher_id: str | None = None) -> None:
        """Persiste la respuesta de generación y su relación con el docente."""
        with SessionLocal() as session:
            request_id = result["request"]["id"]
            session.add(GenerationORM(id=request_id, result=result))
            if teacher_id:
                session.add(TeacherGenerationORM(id=request_id, teacher_id=teacher_id))
            session.commit()

    @translate_persistence_errors
    def get_by_id(self, generation_id: str) -> dict[str, Any] | None:
        """Recupera el resultado de generación según su identificador único."""
        with SessionLocal() as session:
            entity = session.get(GenerationORM, generation_id)
            return adapt_legacy_generation(entity.result) if entity else None