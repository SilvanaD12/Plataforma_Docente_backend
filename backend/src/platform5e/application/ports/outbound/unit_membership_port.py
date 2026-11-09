"""
Puerto de pertenencia de unidad (CC-01 · Cuentas y Cursos): Generación pregunta si la unidad es del docente y obtiene
los datos del curso y de la unidad que necesita el prompt, sin depender del servicio de Cuentas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OutcomeRef:
    """Resultado de aprendizaje de la unidad."""

    id: str
    code: str
    text: str


@dataclass(frozen=True)
class UnitContext:
    """Curso y unidad del docente, con lo que usa la generación."""

    course_id: str
    course_name: str
    course_summary: str
    learning_goal: str
    unit_id: str
    unit_number: int | None
    unit_title: str
    outcomes: tuple[OutcomeRef, ...]


class UnitMembershipPort(Protocol):
    """Contrato que Cuentas ofrece a Generación para comprobar la pertenencia de una unidad."""

    def get_unit_context(self, teacher_id: str, unit_id: str) -> UnitContext | None:
        """Unidad del docente con los datos que necesita el prompt. Devuelve None si no existe o es ajena."""
        ...
