"""
Gamificación de la evaluación (HU-051): cada ítem de opción múltiple tiene un nivel y vale puntos según la
dificultad con que el docente lo pidió; al terminar, el puntaje obtenido da una insignia.

Lo usan los exportadores: el SCORM arma la evaluación por niveles y el Moodle XML agrupa los ítems en una
categoría por nivel, con su puntaje.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Level:
    """Nivel de un ítem: número (orden en que se juega), nombre que ve el estudiante y puntos que vale."""

    number: int
    label: str
    points: int

    @property
    def title(self) -> str:
        return f"Nivel {self.number} · {self.label}"


# Dificultad guardada en los parámetros del pedido -> nivel. Los valores siguen en español (deuda de ADR-009);
# se aceptan ya los nombres en inglés para cuando se migren.
LEVELS: dict[str, Level] = {
    "basica": Level(1, "Básico", 10),
    "intermedia": Level(2, "Intermedio", 20),
    "avanzada": Level(3, "Avanzado", 30),
}
LEVEL_ALIASES: dict[str, str] = {"basic": "basica", "intermediate": "intermedia", "advanced": "avanzada"}
DEFAULT_DIFFICULTY: str = "intermedia"

# Porcentaje mínimo del puntaje total -> insignia, de la mayor a la menor. Bajo 60 % no hay insignia,
# el mismo umbral de aprobado que el SCORM envía al LMS.
BADGES: tuple[tuple[int, str], ...] = ((90, "Oro"), (75, "Plata"), (60, "Bronce"))
PASSING_PERCENT: int = 60


def item_level(resource: Mapping[str, Any]) -> Level:
    """Nivel del ítem según la dificultad del pedido que lo generó; intermedio si no se conoce."""
    params = resource.get("params") or {}
    difficulty = str(params.get("difficulty") or DEFAULT_DIFFICULTY).strip().lower()
    return LEVELS.get(LEVEL_ALIASES.get(difficulty, difficulty), LEVELS[DEFAULT_DIFFICULTY])


def badge_for(percent: float) -> str | None:
    """Insignia que corresponde a un porcentaje del puntaje total, o None si no alcanza ninguna."""
    for threshold, badge in BADGES:
        if percent >= threshold:
            return badge
    return None


def by_level(resources: list[Mapping[str, Any]]) -> list[tuple[Level, list[Mapping[str, Any]]]]:
    """Agrupa los ítems por nivel, del 1 al 3, conservando el orden original dentro de cada nivel."""
    groups: dict[int, tuple[Level, list[Mapping[str, Any]]]] = {}
    for resource in resources:
        level = item_level(resource)
        groups.setdefault(level.number, (level, []))[1].append(resource)
    return [groups[number] for number in sorted(groups)]
