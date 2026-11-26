"""
GEN-C13 (spec 002, T075, research R13): la audiencia sin rótulo en la interpretación de pedidos (HU-038).

«para» seguido de un ciclo («primer ciclo», «3.er ciclo», «ciclo III»), un nivel («pregrado», «secundaria») o
«docentes», con «estudiantes de» o «alumnos de» opcional, es la audiencia. Se normaliza: «tercer ciclo», «pregrado»,
«docentes». Cualquier otra palabra después de «para» («para explicar TCP», «para la clase del lunes») no lo es.

Todo se busca en el texto normalizado (minúsculas y sin tildes).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from platform5e.domain.materials.text_analysis import normalize_text

_ORDINAL_WORDS = {
    "primer": 1, "primero": 1, "primera": 1, "segundo": 2, "tercer": 3, "tercero": 3, "cuarto": 4, "quinto": 5,
    "sexto": 6, "septimo": 7, "setimo": 7, "octavo": 8, "noveno": 9, "decimo": 10,
}
_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}
_DISPLAY = {1: "primer", 2: "segundo", 3: "tercer", 4: "cuarto", 5: "quinto", 6: "sexto", 7: "séptimo", 8: "octavo",
            9: "noveno", 10: "décimo"}
# Niveles: el valor normalizado y su dimensión (un nivel educativo o el público docente, que no se compara).
_LEVELS = {
    "pregrado": ("pregrado", "level"), "posgrado": ("posgrado", "level"), "postgrado": ("posgrado", "level"),
    "secundaria": ("secundaria", "level"), "primaria": ("primaria", "level"),
    "docentes": ("docentes", "teachers"), "profesores": ("docentes", "teachers"), "maestros": ("docentes", "teachers"),
}

_NUMBER = r"\d{1,2}\s*(?:\.\s*)?(?:er|ero|ro|do|to|vo|mo|no|o|º|°)?"
_WORDS = "|".join(sorted(_ORDINAL_WORDS, key=len, reverse=True))
_ROMANS = "|".join(sorted(_ROMAN, key=len, reverse=True))
_CYCLE = (rf"(?:(?P<before>{_NUMBER}|(?:{_WORDS})\b|(?:{_ROMANS})\b)\s*ciclo"
          rf"|ciclo\s+(?P<after>\d{{1,2}}\b|(?:{_ROMANS})\b))")
_LEVEL = "|".join(_LEVELS)
_CORE = rf"(?:{_CYCLE}|(?P<level>{_LEVEL}))(?![\w])"
_LEAD = (r"(?:(?:los|las|el|la)\s+)?"
         r"(?:(?:estudiantes|alumnos|alumnas|ninos|ninas|jovenes)\s+(?:del?\s+)?)?"
         r"(?:(?:el|la|los|las)\s+)?")
_AUDIENCE = re.compile(rf"\bpara\s+{_LEAD}{_CORE}")
_CORE_ONLY = re.compile(_CORE)


@dataclass(frozen=True)
class Audience:
    """Una audiencia reconocida: el texto normalizado, su dimensión (`cycle`, `level` o `teachers`) y su valor."""

    text: str
    dimension: str
    value: int | str
    span: tuple[int, int] = (0, 0)


def _number(token: str) -> int | None:
    token = token.strip()
    digits = re.match(r"\d{1,2}", token)
    if digits:
        return int(digits[0])
    return _ORDINAL_WORDS.get(token) or _ROMAN.get(token)


def _from_match(match: re.Match[str]) -> Audience | None:
    if match["level"]:
        text, dimension = _LEVELS[match["level"]]
        return Audience(text, dimension, text, match.span())
    cycle = _number(match["before"] or match["after"] or "")
    if not cycle:
        return None
    return Audience(f"{_DISPLAY[cycle]} ciclo" if cycle in _DISPLAY else f"ciclo {cycle}", "cycle", cycle,
                    match.span())


def find_audiences(normalized: str) -> list[Audience]:
    """Las audiencias sin rótulo del texto normalizado, en orden, con su posición."""
    return [audience for match in _AUDIENCE.finditer(normalized) if (audience := _from_match(match))]


def is_audience_phrase(text: str) -> bool:
    """«para primer ciclo» entera es una audiencia (no una unidad)."""
    normalized = normalize_text(text).strip()
    match = _AUDIENCE.match(normalized)
    return bool(match and match.end() == len(normalized))


def classify(text: str) -> Audience | None:
    """La dimensión de un texto libre (una audiencia rotulada, o el nivel o el ciclo del curso)."""
    normalized = normalize_text(text or "").strip()
    match = _CORE_ONLY.search(normalized)
    if match:
        return _from_match(match)
    value = _number(normalized.removesuffix("ciclo").strip()) if normalized else None
    return Audience(f"{_DISPLAY.get(value, value)} ciclo", "cycle", value) if value else None


def course_conflict(audience: Audience, education_level: str | None, academic_cycle: str | None) -> str | None:
    """El dato del curso con el que no coincide la audiencia (del mismo tipo: ciclo con ciclo, nivel con nivel), o
    None si coincide o el curso no lo indica."""
    if audience.dimension == "cycle" and academic_cycle:
        course = classify(academic_cycle)
        if course and course.dimension == "cycle" and course.value != audience.value:
            return academic_cycle
    if audience.dimension == "level" and education_level:
        course = classify(education_level)
        if course and course.dimension == "level" and course.value != audience.value:
            return education_level
    return None
