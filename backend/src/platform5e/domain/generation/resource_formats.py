"""
Catálogo de tipos de recurso por etapa 5E y su formato: texto, visual (SVG), imagen, audio o actividad interactiva.

Los recursos que no son solo texto guardan su contenido estructurado en `structure` (claves en inglés). Este módulo
valida y limpia esa estructura; lo usan la generación (IA o reglas), la revisión docente y las exportaciones.
"""

from __future__ import annotations

import re
from typing import Any

from platform5e.domain.generation.resource_catalog import RESOURCE_TYPES

TEXT = "text"
VISUAL = "visual"
IMAGE = "image"
AUDIO = "audio"
INTERACTIVE = "interactive"

# Tipo de recurso (valor guardado) -> (etapa 5E, formato).
RESOURCE_CATALOG: dict[str, tuple[str, str]] = {
    entry.id: (entry.stage, entry.format) for entry in RESOURCE_TYPES
}

# HU-024 (research R11): una modalidad es un grupo de tipos, no un modo distinto de generar. Un tipo puede estar en
# más de una.
MODALITIES: tuple[str, ...] = ("Textual", "Gamificado", "Multimedia", "Kinestésico")
MODALITY_TYPES: dict[str, frozenset[str]] = {
    "Textual": frozenset({
        "pregunta_detonante", "sondeo_diagnostico", "guia_exploracion", "caso_indagacion", "exploracion_guiada",
        "explicacion", "glosario", "ejercicio_aplicacion", "caso_aplicado", "item_opcion_multiple",
    }),
    "Gamificado": frozenset({
        "reto_prediccion", "emparejamiento", "ordenar_pasos", "verdadero_falso", "completar_espacios",
        "item_opcion_multiple",
    }),
    "Multimedia": frozenset({
        "imagen_ilustrativa", "audio_detonante", "podcast_resumen", "diagrama_proceso", "mapa_conceptual",
        "infografia",
    }),
    "Kinestésico": frozenset({"actividad_kinestesica"}),
}

BLANK = "____"
MAX_ITEMS = 10
MAX_SHORT = 160
MAX_LONG = 600
MAX_SCRIPT = 2400
MAX_MATERIAL = 80
MIN_MINUTES = 5
MAX_MINUTES = 90

# Mínimo de elementos para que la actividad o el gráfico tengan sentido.
MIN_ITEMS: dict[str, int] = {
    "mapa_conceptual": 3,
    "infografia": 3,
    "diagrama_proceso": 3,
    "exploracion_guiada": 3,
    "actividad_kinestesica": 3,
    "reto_prediccion": 3,
    "caso_aplicado": 3,
    "emparejamiento": 3,
    "ordenar_pasos": 3,
    "verdadero_falso": 3,
    "completar_espacios": 2,
}


def resource_format(resource_type: str) -> str:
    return RESOURCE_CATALOG.get(resource_type, ("", TEXT))[1]


def modalities_of(resource_type: str) -> list[str]:
    """Modalidades que incluyen el tipo, en el orden de `MODALITIES`."""
    return [modality for modality in MODALITIES if resource_type in MODALITY_TYPES[modality]]


def types_outside_modality(modality: str, resource_types: list[str] | tuple[str, ...]) -> list[str]:
    """Tipos pedidos que no pertenecen a la modalidad, sin repetir y en el orden recibido."""
    allowed = MODALITY_TYPES.get(modality, frozenset())
    return [resource_type for resource_type in dict.fromkeys(resource_types) if resource_type not in allowed]


def resource_stage(resource_type: str) -> str:
    return RESOURCE_CATALOG.get(resource_type, ("", TEXT))[0]


def needs_structure(resource_type: str) -> bool:
    return resource_format(resource_type) != TEXT


def _short(value: Any, limit: int = MAX_SHORT) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def _items(value: Any) -> list[Any]:
    return value[:MAX_ITEMS] if isinstance(value, list) else []


def _is_true(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "verdadero", "verdadera", "v", "sí", "si")
    return value is True


def _titled_points(value: Any) -> list[dict[str, str]]:
    points = []
    for item in _items(value):
        if isinstance(item, dict):
            title, text = _short(item.get("title")), _short(item.get("text"), MAX_LONG)
            if title or text:
                points.append({"title": title or text[:60], "text": text})
    return points


def _with_blank(sentence: str, answer: str) -> str:
    """Asegura el espacio en blanco: si la oración trae la respuesta, la oculta."""
    if BLANK in sentence or re.search(r"_{3,}", sentence):
        return re.sub(r"_{3,}", BLANK, sentence, count=1)
    masked = re.sub(rf"(?<!\w){re.escape(answer)}(?!\w)", BLANK, sentence, count=1, flags=re.IGNORECASE)
    return masked if masked != sentence else ""


def _guided_steps(value: Any, question_required: bool = True) -> list[dict[str, Any]]:
    """HU-048: pasos de la exploración guiada. Cada paso conserva los fragmentos del material que lo respaldan.

    En la actividad kinestésica (HU-024) la pregunta de cierre del paso es opcional."""
    steps = []
    for item in _items(value):
        if not isinstance(item, dict):
            continue
        step = {
            "title": _short(item.get("title"), 80),
            "instruction": _short(item.get("instruction"), MAX_LONG),
            "question": _short(item.get("question"), MAX_LONG),
            "fragmentIds": [f for f in (item.get("fragmentIds") or []) if isinstance(f, str) and f][:3],
        }
        if step["title"] and step["instruction"] and (step["question"] or not question_required):
            steps.append(step)
    return steps


def _materials(value: Any) -> list[str]:
    """HU-024: materiales de la actividad kinestésica, sin repetir. Puede quedar vacía."""
    materials: list[str] = []
    for item in _items(value):
        text = _short(item, MAX_MATERIAL) if isinstance(item, str) else ""
        if text and text.casefold() not in {material.casefold() for material in materials}:
            materials.append(text)
    return materials


def _estimated_minutes(value: Any) -> int | None:
    """HU-024: minutos enteros de 5 a 90. Acepta un número entero o un texto con solo dígitos; si no, None."""
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if MIN_MINUTES <= value <= MAX_MINUTES else None


def complete_guided_steps(value: Any, question_required: bool = True) -> int:
    """Cuántos pasos guiados están completos (título y consigna, y pregunta si se exige). Lo usa la generación para
    explicar por qué rechaza una actividad."""
    return len(_guided_steps(value, question_required))


def estimated_minutes(value: Any) -> int | None:
    """Los minutos de la actividad kinestésica si son un entero de 5 a 90; si no, None."""
    return _estimated_minutes(value)


def _predictions(value: Any) -> list[dict[str, Any]]:
    """HU-047: predicciones del reto de Enganchar. El estudiante elige entre dos o tres opciones antes de ver lo que
    dice el material (`reveal`), y cada predicción conserva los fragmentos que la respaldan."""
    predictions = []
    for item in _items(value):
        if not isinstance(item, dict):
            continue
        prediction = {
            "question": _short(item.get("question"), MAX_LONG),
            "correctOption": _short(item.get("correctOption")),
            "otherOption": _short(item.get("otherOption")),
            "extraOption": _short(item.get("extraOption")),
            "reveal": _short(item.get("reveal"), MAX_LONG),
            "fragmentIds": [f for f in (item.get("fragmentIds") or []) if isinstance(f, str) and f][:3],
        }
        options = [prediction["correctOption"], prediction["otherOption"], prediction["extraOption"]]
        filled = [option.casefold() for option in options if option]
        if len(set(filled)) != len(filled):
            continue  # dos opciones iguales no son una elección
        if prediction["question"] and prediction["correctOption"] and prediction["otherOption"] and prediction["reveal"]:
            predictions.append(prediction)
    return predictions


def _criteria(value: Any) -> list[dict[str, Any]]:
    """HU-050: criterios de logro del caso aplicado. Cada uno conserva los fragmentos con el concepto que aplica; dos
    criterios iguales cuentan como uno."""
    criteria, seen = [], set()
    for item in _items(value):
        if not isinstance(item, dict):
            continue
        text = _short(item.get("criterion"), MAX_LONG)
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            criteria.append(
                {
                    "criterion": text,
                    "fragmentIds": [f for f in (item.get("fragmentIds") or []) if isinstance(f, str) and f][:3],
                }
            )
    return criteria


def normalize_structure(resource_type: str, raw: Any) -> dict[str, Any] | None:
    """Devuelve la estructura limpia del tipo, o None si no alcanza para un recurso útil."""
    if not needs_structure(resource_type):
        return None
    data = raw if isinstance(raw, dict) else {}
    kind = resource_format(resource_type)
    structure: dict[str, Any]

    if resource_type == "mapa_conceptual":
        nodes = []
        for item in _items(data.get("nodes")):
            if isinstance(item, dict) and _short(item.get("label")):
                nodes.append({"label": _short(item.get("label"), 60), "detail": _short(item.get("detail"), 200)})
        structure = {"central": _short(data.get("central"), 80), "nodes": nodes}
        if not structure["central"]:
            return None
    elif resource_type == "infografia":
        structure = {"headline": _short(data.get("headline"), 120), "points": _titled_points(data.get("points"))}
    elif resource_type == "diagrama_proceso":
        structure = {"steps": _titled_points(data.get("steps"))}
    elif resource_type == "exploracion_guiada":
        structure = {"guidedSteps": _guided_steps(data.get("guidedSteps"))}
    elif resource_type == "actividad_kinestesica":
        # HU-024: los pasos van primero (el mínimo se cuenta sobre la primera lista). Materiales, tiempo y espacio
        # quedan dentro de `structure` para que la huella de REV-01 los cubra; no se contrastan con el material.
        minutes = _estimated_minutes(data.get("estimatedMinutes"))
        structure = {
            "guidedSteps": _guided_steps(data.get("guidedSteps"), question_required=False),
            "materials": _materials(data.get("materials")),
            "estimatedMinutes": minutes,
            "space": _short(data.get("space"), MAX_MATERIAL),
        }
        if minutes is None or not structure["space"]:
            return None
    elif resource_type == "reto_prediccion":
        structure = {"predictions": _predictions(data.get("predictions"))}
    elif resource_type == "caso_aplicado":
        structure = {
            "scenario": _short(data.get("scenario"), MAX_LONG),
            "task": _short(data.get("task"), MAX_LONG),
            "criteria": _criteria(data.get("criteria")),
        }
        if not structure["scenario"] or not structure["task"]:
            return None  # sin situación o sin consigna no hay caso que resolver
    elif resource_type == "ordenar_pasos":
        sequence = [_short(step, MAX_LONG) for step in _items(data.get("sequence"))]
        structure = {"sequence": [step for step in sequence if step]}
    elif resource_type == "emparejamiento":
        pairs, seen = [], set()
        for item in _items(data.get("pairs")):
            if isinstance(item, dict):
                term, definition = _short(item.get("term"), 80), _short(item.get("definition"), MAX_LONG)
                if term and definition and term.casefold() not in seen:
                    seen.add(term.casefold())
                    pairs.append({"term": term, "definition": definition})
        structure = {"pairs": pairs}
    elif resource_type == "verdadero_falso":
        statements = []
        for item in _items(data.get("statements")):
            if isinstance(item, dict) and _short(item.get("text"), MAX_LONG):
                statements.append(
                    {
                        "text": _short(item.get("text"), MAX_LONG),
                        "isTrue": _is_true(item.get("isTrue")),
                        "feedback": _short(item.get("feedback"), MAX_LONG),
                    }
                )
        structure = {"statements": statements}
    elif resource_type == "completar_espacios":
        blanks = []
        for item in _items(data.get("blanks")):
            if isinstance(item, dict):
                answer = _short(item.get("answer"), 80)
                sentence = _with_blank(_short(item.get("sentence"), MAX_LONG), answer) if answer else ""
                if sentence:
                    blanks.append({"sentence": sentence, "answer": answer})
        structure = {"blanks": blanks}
    elif kind == AUDIO:
        script = data.get("script")
        structure = {"script": " ".join(script.split())[:MAX_SCRIPT] if isinstance(script, str) else ""}
        return structure if len(structure["script"].split()) >= 15 else None
    elif kind == IMAGE:
        structure = {
            "prompt": _short(data.get("prompt"), MAX_LONG),
            "alt": _short(data.get("alt"), 300),
            "caption": _short(data.get("caption"), 300),
        }
        if not structure["prompt"]:
            return None
        structure["alt"] = structure["alt"] or structure["prompt"][:300]
        return structure
    else:
        return None

    lists = [value for value in structure.values() if isinstance(value, list)]
    if lists and len(lists[0]) < MIN_ITEMS.get(resource_type, 1):
        return None
    if resource_type == "verdadero_falso":
        answers = {s["isTrue"] for s in structure["statements"]}
        if answers != {True, False}:
            return None  # una actividad de verdadero o falso necesita de los dos tipos
    return structure


def structure_problems(resource_type: str, structure: Any) -> list[str]:
    """Motivos que impiden aprobar un recurso con estructura (para la revisión docente)."""
    if not needs_structure(resource_type):
        return []
    if normalize_structure(resource_type, structure) is None:
        minimum = MIN_ITEMS.get(resource_type)
        if minimum:
            return [f"La actividad necesita al menos {minimum} elementos completos para poder aprobarla."]
        return ["Completa el contenido del recurso para poder aprobarlo."]
    return []
