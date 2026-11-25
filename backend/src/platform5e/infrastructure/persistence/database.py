"""
Configuración de la conexión a la base de datos con SQLAlchemy (SQLite / PostgreSQL psycopg 3).
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base, sessionmaker

from platform5e.infrastructure.persistence.migration_runner import apply_database_migrations

T = TypeVar("T")


def normalize_database_url(url: str) -> str:
    """Acepta las URL de Neon, Render o dbmate (postgres:// o postgresql://) y usa psycopg 3."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


DATABASE_URL: str = normalize_database_url(os.getenv("DATABASE_URL", "sqlite:///./demo.db"))

if DATABASE_URL.startswith("sqlite"):
    # SQLite requiere connect_args especiales para permitir múltiples hilos
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # pool_pre_ping evita errores cuando la base de datos se suspende por inactividad (Neon, Render).
    # pool_recycle=240 recicla conexiones antes del umbral de suspensión de 5 minutos en Neon.
    # prepare_threshold=None: sin sentencias preparadas, compatible con el pooler de Neon (PgBouncer).
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=240,
        connect_args={"prepare_threshold": None, "connect_timeout": 15},
    )
    apply_database_migrations(engine)


def run_with_db_retry(operation: Callable[[], T], retries: int = 2, delay: float = 1.5) -> T:
    """Reintenta operaciones de BD ante desconexiones transitorias cuando Neon sale de estado Idle."""
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return operation()
        except OperationalError as exc:
            last_error = exc
            if attempt == retries:
                raise
            time.sleep(delay * (attempt + 1))
    assert last_error is not None
    raise last_error


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()