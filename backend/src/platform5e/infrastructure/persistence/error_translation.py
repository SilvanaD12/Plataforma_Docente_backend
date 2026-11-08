"""
Traduce excepciones técnicas de SQLAlchemy a errores de negocio del dominio.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from platform5e.domain.shared.errors import DuplicateRecordError, PersistenceUnavailableError


def translate_persistence_errors(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorador que intercepta fallos de SQLAlchemy y los transforma en excepciones de dominio."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except IntegrityError as exc:
            raise DuplicateRecordError() from exc
        except SQLAlchemyError as exc:
            raise PersistenceUnavailableError() from exc

    return wrapper