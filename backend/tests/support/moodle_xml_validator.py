"""Validador del Moodle XML que exporta la plataforma (TA-007, indicadores I17 e I19).

Las reglas salen de la muestra que se importó con éxito en Moodle durante SP-003
(tests/fixtures/verified_moodle_sample.xml): si lo exportado tiene la misma estructura y
cumple las reglas de un ítem de opción múltiple, Moodle lo importa sin pérdidas.

Uso desde la terminal:
    python -m tests.support.moodle_xml_validator archivo.xml
"""

from __future__ import annotations

from dataclasses import dataclass
import html
from pathlib import Path
import re
import sys
from xml.etree import ElementTree as ET

VERIFIED_SAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "verified_moodle_sample.xml"
ALLOWED_TYPES = {"category", "multichoice"}
MIN_OPTIONS, MAX_OPTIONS = 3, 5


@dataclass(frozen=True)
class ExportedQuestion:
    """Lo que el docente verá en Moodle, sin etiquetas HTML."""

    name: str
    prompt: str
    general_feedback: str
    options: list[tuple[str, str, str]]  # (texto, fracción, retroalimentación)


def plain_text(value: str | None) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def _child_tags(question: ET.Element) -> set[str]:
    return {child.tag for child in question}


def reference_tags() -> set[str]:
    """Etiquetas de un ítem de opción múltiple en la muestra que Moodle importó bien."""
    root = ET.parse(VERIFIED_SAMPLE).getroot()
    question = root.find("question[@type='multichoice']")
    assert question is not None, "la muestra verificada no tiene ítems de opción múltiple"
    return _child_tags(question)


def validate(content: bytes | str) -> list[str]:
    """Devuelve la lista de problemas encontrados. Lista vacía = el archivo es importable."""
    problems: list[str] = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError as error:
        return [f"El XML no está bien formado: {error}"]

    if root.tag != "quiz":
        return [f"La raíz debe ser <quiz> y es <{root.tag}>."]

    questions = root.findall("question")
    if not [q for q in questions if q.get("type") == "multichoice"]:
        problems.append("No hay ninguna pregunta de opción múltiple.")

    reference = reference_tags()
    for position, question in enumerate(questions, start=1):
        kind = question.get("type")
        where = f"Pregunta {position}"
        if kind not in ALLOWED_TYPES:
            problems.append(f"{where}: tipo «{kind}» no verificado en Moodle (se admiten {sorted(ALLOWED_TYPES)}).")
            continue
        if kind == "category":
            if not (question.findtext("category/text") or "").strip():
                problems.append(f"{where}: la categoría no tiene nombre.")
            continue

        name = (question.findtext("name/text") or "").strip()
        where = f"{where} «{name or 'sin nombre'}»"
        if not name:
            problems.append(f"{where}: falta el nombre.")

        missing = reference - _child_tags(question)
        if missing:
            problems.append(f"{where}: faltan etiquetas que tenía la muestra verificada: {sorted(missing)}.")

        prompt = question.find("questiontext")
        if prompt is None or prompt.get("format") != "html" or not plain_text(prompt.findtext("text")):
            problems.append(f"{where}: el enunciado debe existir, tener texto y formato html.")

        if (question.findtext("single") or "").strip() != "true":
            problems.append(f"{where}: <single> debe ser true (una sola respuesta correcta).")

        answers = question.findall("answer")
        if not MIN_OPTIONS <= len(answers) <= MAX_OPTIONS:
            problems.append(
                f"{where}: tiene {len(answers)} alternativas; deben ser entre {MIN_OPTIONS} y {MAX_OPTIONS}."
            )

        fractions = [a.get("fraction") for a in answers]
        if fractions.count("100") != 1:
            problems.append(
                f"{where}: debe haber exactamente una alternativa con fraction=\"100\" y hay {fractions.count('100')}."
            )
        others = [f for f in fractions if f != "100"]
        if any(f != "0" for f in others):
            problems.append(f"{where}: las alternativas incorrectas deben tener fraction=\"0\" y hay {others}.")

        texts = [plain_text(a.findtext("text")) for a in answers]
        if any(not t for t in texts):
            problems.append(f"{where}: hay alternativas sin texto.")
        if len(set(texts)) != len(texts):
            problems.append(f"{where}: hay alternativas repetidas.")
        for letter, answer in zip("ABCDE", answers):
            if not plain_text(answer.findtext("feedback/text")):
                problems.append(f"{where}: la alternativa {letter} no tiene retroalimentación (I19).")
    return problems


def read_questions(content: bytes | str) -> list[ExportedQuestion]:
    """Extrae el contenido de cada ítem tal como lo mostrará Moodle."""
    root = ET.fromstring(content)
    return [
        ExportedQuestion(
            name=(q.findtext("name/text") or "").strip(),
            prompt=plain_text(q.findtext("questiontext/text")),
            general_feedback=plain_text(q.findtext("generalfeedback/text")),
            options=[
                (plain_text(a.findtext("text")), a.get("fraction") or "", plain_text(a.findtext("feedback/text")))
                for a in q.findall("answer")
            ],
        )
        for q in root.findall("question[@type='multichoice']")
    ]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: python -m tests.support.moodle_xml_validator <archivo.xml>")
    found = validate(Path(sys.argv[1]).read_bytes())
    if found:
        print("NO importable:")
        for problem in found:
            print(" -", problem)
        sys.exit(1)
    print("OK: el archivo cumple la estructura verificada en Moodle.")
