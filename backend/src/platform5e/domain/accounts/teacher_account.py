"""
Errores y reglas de negocio del módulo de cuenta y configuración del docente (EP-002).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from platform5e.domain.shared.errors import DomainError


class AccountConfigurationError(DomainError):
    """Error de validación o configuración de la cuenta del docente."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code: str = code
        self.message: str = message
        self.status_code: int = status_code
        super().__init__(message)


def find_course_and_unit(
    courses: Iterable[dict[str, Any]], unit_id: str
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Busca una unidad entre los cursos que ya se filtraron por docente."""
    for course in courses:
        for unit in course["units"]:
            if unit["id"] == unit_id:
                return course, unit
    return None
