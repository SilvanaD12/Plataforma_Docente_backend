"""
Redacción de recursos pedagógicos con evidencia: prepara el contexto,
construye los prompts para el LLM y valida formalmente el esquema devuelto.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from platform5e.application.ports.outbound.evidence_provider_port import EvidenceFragment
from platform5e.application.ports.outbound.unit_membership_port import UnitContext
from platform5e.domain.generation.distractor_reliability import assess_distractor
from platform5e.domain.generation.grounding import (
    DEFAULT_THRESHOLD,
    link_criterion_sources,
    link_prediction_sources,
    link_step_sources,
    verify_citations,
    verify_statements,
)
from platform5e.domain.generation.resource_formats import (
    AUDIO,
    IMAGE,
    INTERACTIVE,
    MAX_MINUTES,
    MIN_ITEMS,
    MIN_MINUTES,
    TEXT,
    VISUAL,
    complete_guided_steps,
    estimated_minutes,
    normalize_structure,
    resource_format,
)

PHASES_5E: dict[str, tuple[str, str]] = {
    "engage": ("Enganchar", "activar ideas previas y despertar la curiosidad"),
    "explore": ("Explorar", "que el estudiante indague y descubra a partir de actividades"),
    "explain": ("Explicar", "formalizar el concepto con lenguaje disciplinar preciso"),
    "elaborate": ("Elaborar", "aplicar lo aprendido a situaciones nuevas"),
    "evaluate": ("Evaluar", "comprobar el logro del resultado de aprendizaje"),
}

RESOURCE_TYPES: dict[str, tuple[str, str]] = {
    "pregunta_detonante": (
        "Pregunta detonante",
        "Una situación breve tomada del material y una pregunta abierta que despierte curiosidad.",
    ),
    "sondeo_diagnostico": (
        "Sondeo diagnóstico de ideas previas",
        "Entre 4 y 6 afirmaciones de verdadero o falso para detectar concepciones alternativas.",
    ),
    "reto_prediccion": (
        "Reto de predicción",
        "Un juego para iniciar la clase: de 3 a 5 preguntas en las que el estudiante predice qué pasa o qué es, "
        "eligiendo entre 2 o 3 opciones, antes de ver lo que dice el material. Las preguntas deben despertar "
        "curiosidad (una idea intuitiva o común entre las opciones equivocadas) y la respuesta correcta sale de un "
        "fragmento.",
    ),
    "guia_exploracion": (
        "Guía de exploración",
        "Objetivo, materiales y de 4 a 6 pasos de indagación guiada con preguntas de registro.",
    ),
    "exploracion_guiada": (
        "Exploración guiada",
        "Una actividad interactiva de 3 a 5 pasos para que el estudiante explore el material: en cada paso, qué "
        "observa o hace y una pregunta guía para registrar lo que encuentra. Cada paso se apoya en un fragmento.",
    ),
    "actividad_kinestesica": (
        "Actividad kinestésica",
        "Una actividad de 3 a 5 pasos que los estudiantes hacen con el cuerpo en el aula: se mueven, manipulan "
        "objetos o representan ideas del material. En cada paso, qué hacen y, si ayuda, una pregunta para comentar "
        "lo que observaron. Cada paso se apoya en un fragmento. Indica los materiales, el tiempo y el espacio.",
    ),
    "caso_indagacion": (
        "Caso con preguntas de indagación",
        "Un caso breve basado en el material y de 3 a 4 preguntas reflexivas.",
    ),
    "explicacion": (
        "Explicación citada",
        "Una explicación estructurada de 3 a 5 párrafos separados por una línea en blanco. Cada párrafo usa solo "
        "información del material y se apoya en una cita.",
    ),
    "glosario": (
        "Glosario de la unidad",
        "De 6 a 10 términos clave, uno por línea con el formato «Término: definición», con la definición tomada "
        "estrictamente del material.",
    ),
    "ejercicio_aplicacion": (
        "Ejercicio de aplicación",
        "Un ejercicio de transferencia a un contexto nuevo con consigna y criterios de logro.",
    ),
    "caso_aplicado": (
        "Caso aplicado",
        "Un caso para aplicar lo aprendido a una situación nueva: una situación de 3 a 5 oraciones en un contexto que "
        "no aparece en el material (el entorno del estudiante, una empresa, una comunidad), una consigna con lo que "
        "debe resolver o proponer, y de 3 a 5 criterios de logro con los que el docente valora la solución. La "
        "situación es nueva, pero los conceptos que se aplican y cada criterio salen solo de los fragmentos.",
    ),
    "item_opcion_multiple": (
        "Ítem de opción múltiple",
        "Un enunciado con 1 respuesta correcta y distractores plausibles con retroalimentación.",
    ),
    "audio_detonante": (
        "Cápsula de audio detonante",
        "Un guion de 45 a 75 segundos para escuchar al iniciar la clase: una situación del material y una pregunta abierta.",
    ),
    "podcast_resumen": (
        "Resumen en formato podcast",
        "Un guion de 90 a 150 segundos que resume las ideas centrales, como un pódcast breve narrado por una voz.",
    ),
    "imagen_ilustrativa": (
        "Imagen ilustrativa",
        "Una ilustración didáctica de una idea del material, sin texto dentro de la imagen, y una pregunta para observarla.",
    ),
    "diagrama_proceso": (
        "Diagrama de proceso",
        "De 3 a 7 pasos o fases en orden, cada uno con un título corto y una explicación breve.",
    ),
    "mapa_conceptual": (
        "Mapa conceptual",
        "Un concepto central y de 4 a 7 conceptos relacionados, cada uno con una relación o detalle breve.",
    ),
    "infografia": (
        "Infografía",
        "Un titular y de 3 a 6 datos o ideas clave, cada uno con un título corto y una explicación breve.",
    ),
    "emparejamiento": (
        "Actividad de emparejamiento",
        "De 4 a 8 pares término-definición para que el estudiante relacione cada término con su definición.",
    ),
    "ordenar_pasos": (
        "Actividad de ordenar pasos",
        "De 4 a 7 pasos o eventos de un proceso del material, en el orden correcto; el estudiante los ordenará.",
    ),
    "verdadero_falso": (
        "Verdadero o falso",
        "De 4 a 8 afirmaciones, unas verdaderas y otras falsas según el material, con retroalimentación.",
    ),
    "completar_espacios": (
        "Completar espacios",
        "De 3 a 6 oraciones del material con un término clave reemplazado por ____ y su respuesta.",
    ),
}

# Instrucción para el campo «estructura» según el tipo (claves del contrato con el modelo).
STRUCTURE_INSTRUCTIONS: dict[str, str] = {
    "audio_detonante": '"estructura": {"guion": "texto para leer en voz alta, sin acotaciones ni efectos de sonido"}',
    "podcast_resumen": '"estructura": {"guion": "texto para leer en voz alta, sin acotaciones ni efectos de sonido"}',
    "imagen_ilustrativa": (
        '"estructura": {"descripcion_imagen": "descripción visual detallada para un ilustrador, sin texto escrito '
        'en la imagen", "texto_alternativo": "...", "leyenda": "..."}'
    ),
    "diagrama_proceso": '"estructura": {"pasos": [{"titulo": "...", "texto": "..."}]}',
    "exploracion_guiada": (
        '"estructura": {"pasos_guiados": [{"titulo": "...", "consigna": "qué observa, lee o compara el estudiante en '
        'el material", "pregunta": "pregunta guía para registrar lo que encontró", "fragmentos": ["F1"]}]}. '
        "Cada paso cita en «fragmentos» la etiqueta del fragmento en que se apoya"
    ),
    "actividad_kinestesica": (
        '"estructura": {"pasos_guiados": [{"titulo": "...", "consigna": "qué hacen los estudiantes con el cuerpo o '
        'con objetos del aula", "pregunta": "pregunta para comentar lo que observaron (opcional)", "fragmentos": '
        '["F1"]}], "materiales": ["objetos del aula que se necesitan"], "minutos_estimados": 20, "espacio": "dónde se '
        'hace: aula, patio…"}. Cada paso cita en «fragmentos» la etiqueta del fragmento en que se apoya. '
        # Gemini devolvía cada paso como un recurso aparte, o sin tiempo ni espacio: el recurso se rechazaba.
        "Es UN solo recurso: todos sus pasos van dentro de «pasos_guiados»; nunca un recurso por paso. "
        "«minutos_estimados» (entero de 5 a 90) y «espacio» son obligatorios. "
        "La consigna de cada paso se basa en una oración del fragmento que cita"
    ),
    "reto_prediccion": (
        '"estructura": {"predicciones": [{"pregunta": "¿Qué crees que pasa si…?", "correcta": "opción que dice el '
        'material", "otra": "opción equivocada pero creíble", "extra": "otra opción equivocada (opcional)", '
        '"revelacion": "lo que dice el material, en una o dos oraciones", "fragmentos": ["F1"]}]}. '
        "Cada predicción cita en «fragmentos» la etiqueta del fragmento que contiene la respuesta correcta"
    ),
    "caso_aplicado": (
        '"estructura": {"situacion": "situación nueva donde se aplica lo aprendido", "consigna": "qué debe resolver '
        'o proponer el estudiante", "criterios": [{"criterio": "lo que demuestra una buena solución, nombrando el '
        'concepto del material que aplica", "fragmentos": ["F1"]}]}. '
        "Cada criterio cita en «fragmentos» la etiqueta del fragmento con el concepto que aplica"
    ),
    "mapa_conceptual": '"estructura": {"central": "...", "nodos": [{"etiqueta": "...", "detalle": "..."}]}',
    "infografia": '"estructura": {"central": "titular", "puntos": [{"titulo": "...", "texto": "..."}]}',
    "emparejamiento": '"estructura": {"pares": [{"termino": "...", "definicion": "..."}]}',
    "ordenar_pasos": '"estructura": {"secuencia": ["primer paso", "segundo paso", "..."]}',
    "verdadero_falso": (
        '"estructura": {"afirmaciones": [{"texto": "...", "verdadera": true, "retroalimentacion": "..."}]}'
    ),
    "completar_espacios": '"estructura": {"espacios": [{"oracion": "El ____ ...", "respuesta": "..."}]}',
}

FORMAT_RULES: dict[str, str] = {
    TEXT: "Genera solo texto: no incluyas imágenes, enlaces a video o audio.",
    AUDIO: "El guion se convertirá en audio con una voz sintética: escribe frases cortas y naturales para el oído.",
    IMAGE: "La imagen la dibujará un modelo de imágenes: describe la escena con detalle y sin texto escrito en ella.",
    VISUAL: "La plataforma dibuja el gráfico con tu estructura: usa títulos cortos (máximo 6 palabras).",
    INTERACTIVE: "La plataforma arma la actividad interactiva con tu estructura y la califica automáticamente.",
}

# Tipos interactivos que no se califican automáticamente: la solución la valora el docente.
TYPE_FORMAT_RULES: dict[str, str] = {
    "actividad_kinestesica": (
        "La plataforma arma la actividad con tu estructura: los estudiantes la hacen en el aula guiados por el "
        "docente, que marca cuándo la terminaron; no se califica automáticamente."
    ),
    "caso_aplicado": (
        "La plataforma arma la actividad con tu estructura: el estudiante escribe su solución y la revisa con los "
        "criterios de logro; la califica el docente."
    ),
}

# HU-024 (T055): intención de cada modalidad. Se agrega una línea al pedido; no cambia las reglas de citas ni de formato.
MODALITY_INTENTS: dict[str, str] = {
    "Textual": "Recursos para leer, escribir y responder por escrito.",
    "Gamificado": "Recursos con dinámica de juego: retos, puntos o niveles que motiven a participar.",
    "Multimedia": "Recursos visuales o de audio que apoyen la comprensión con imágenes, gráficos o sonido.",
    "Kinestésico": "Una actividad que los estudiantes hacen con el cuerpo en el aula: se mueven, manipulan objetos o "
    "representan ideas.",
}

DIFFICULTY_LABELS: dict[str, str] = {
    "basica": "básica",
    "intermedia": "intermedia",
    "avanzada": "avanzada",
}

# Tipos cuyos pasos (`guidedSteps`) se enlazan con su fragmento, y cómo se nombra la actividad en el motivo.
GUIDED_STEP_TYPES: dict[str, str] = {
    "exploracion_guiada": "la exploración",
    "actividad_kinestesica": "la actividad kinestésica",
}

MAX_TITLE_CHARS: int = 160
MAX_CONTENT_CHARS: int = 8000
MAX_CLAIM_CHARS: int = 600
MAX_OPTION_CHARS: int = 600
# Mínimo de distractores fiables por ítem: el mismo de la aprobación (regla R3).
MIN_RELIABLE_DISTRACTORS: int = 2


def format_fragment_tag(index: int) -> str:
    """Retorna la etiqueta canónica de citación (F1, F2...)."""
    return f"F{index + 1}"


def build_generation_context(
    course: dict[str, Any],
    unit: dict[str, Any],
    request_data: dict[str, Any],
    chunks: list[dict[str, Any]],
    documents: dict[str, str],
) -> dict[str, Any]:
    """Empaqueta los metadatos y fragmentos rotulados para alimentar el generador."""
    matched_outcomes = [
        outcome
        for outcome in unit.get("outcomes", [])
        if not request_data.get("outcomeId") or outcome["id"] == request_data["outcomeId"]
    ]
    return {
        "curso": {
            "nombre": course.get("name", ""),
            "sumilla": course.get("summary", ""),
            "logro": course.get("learningGoal", ""),
        },
        "unidad": {
            "numero": unit.get("number"),
            "titulo": unit.get("title", ""),
            "resultados": [f"{o.get('code', '')}: {o.get('text', '')}" for o in matched_outcomes],
        },
        "solicitud": {
            "etapa": request_data["stage"],
            "tipo": request_data["resourceType"],
            "cantidad": request_data["quantity"],
            "dificultad": request_data.get("difficulty", "intermedia"),
            "alternativas": request_data.get("optionCount", 4),
            "indicaciones": request_data.get("instructions", ""),
            "publico": request_data.get("audience", ""),
            "competencia": request_data.get("competency", ""),
            "modalidades": [request_data["modality"]] if request_data.get("modality") else [],
            "umbralEvidencia": request_data.get("evidenceThreshold", DEFAULT_THRESHOLD),
        },
        "fragmentos": [
            {
                "etiqueta": format_fragment_tag(i),
                "id": chunk["id"],
                "ubicacion": chunk.get("location") or chunk.get("ubicacion", ""),
                "documento": documents.get(chunk.get("documentId") or chunk.get("documento_id", ""), ""),
                "texto": chunk.get("text") or chunk.get("texto", ""),
            }
            for i, chunk in enumerate(chunks)
        ],
    }


def build_step_context(
    unit_context: UnitContext,
    request_data: dict[str, Any],
    fragments: Sequence[EvidenceFragment],
) -> dict[str, Any]:
    """GEN-01 (T014): el mismo contexto de `build_generation_context`, a partir de los puertos de Cuentas y Material.

    Traduce `UnitContext` y `EvidenceFragment` a la forma que ya usa la generación, así las etiquetas F1…Fn, el
    pedido y `secuenciaPrevia` (que agrega quien llama) no cambian.
    """
    course = {
        "id": unit_context.course_id,
        "name": unit_context.course_name,
        "summary": unit_context.course_summary,
        "learningGoal": unit_context.learning_goal,
    }
    unit = {
        "id": unit_context.unit_id,
        "number": unit_context.unit_number,
        "title": unit_context.unit_title,
        "outcomes": [{"id": o.id, "code": o.code, "text": o.text} for o in unit_context.outcomes],
    }
    chunks = [
        {"id": f.chunk_id, "documentId": f.document_id, "location": f.location, "text": f.text} for f in fragments
    ]
    documents = {f.document_id: f.document_name for f in fragments}
    return build_generation_context(course, unit, request_data, chunks, documents)


def build_prompt_instructions(context: dict[str, Any]) -> tuple[str, str]:
    """Genera las instrucciones estructuradas del sistema y del usuario para el LLM."""
    req = context["solicitud"]
    stage_name, purpose = PHASES_5E[req["etapa"]]
    type_name, format_desc = RESOURCE_TYPES[req["tipo"]]

    system_prompt = (
        f"Eres un asistente pedagógico que redacta recursos para la etapa «{stage_name}» del modelo 5E ({purpose}). "
        "Escribes en español claro para docentes universitarios del Perú. "
        "No menciones el modelo 5E ni el nombre de la etapa en los títulos ni en el contenido. "
        "Usa SOLO la información de los FRAGMENTOS del material: no agregues datos ajenos. "
        "Cada afirmación importante debe citar las etiquetas de los fragmentos que la respaldan (F1, F2…). "
        "Si los fragmentos no alcanzan, devuelve menos recursos. "
        f"{TYPE_FORMAT_RULES.get(req['tipo']) or FORMAT_RULES[resource_format(req['tipo'])]} "
        "Responde únicamente con JSON válido, sin delimitadores adicionales."
    )

    course, unit = context["curso"], context["unidad"]
    lines = [
        f"CURSO: {course['nombre']}",
        f"SUMILLA: {course['sumilla'] or 'no registrada'}",
        f"LOGRO DEL CURSO: {course['logro'] or 'no registrado'}",
        f"UNIDAD {unit['numero']}: {unit['titulo']}",
        "RESULTADOS DE APRENDIZAJE: " + ("; ".join(unit["resultados"]) or "no registrados"),
        "",
        f"PEDIDO: {req['cantidad']} recurso(s) de tipo «{type_name}». {format_desc}",
        f"Dificultad: {DIFFICULTY_LABELS.get(req['dificultad'], req['dificultad'])}.",
    ]
    modality = next(iter(req.get("modalidades") or []), None)
    if modality in MODALITY_INTENTS:
        lines.append(f"Modalidad de la clase: {modality}. {MODALITY_INTENTS[modality]}")

    if req["tipo"] == "item_opcion_multiple":
        lines.append(
            f"Cada ítem debe tener exactamente {req['alternativas']} alternativas: 1 correcta y {req['alternativas'] - 1} distractores."
        )
        lines.append(MISCONCEPTION_INSTRUCTION)
    if req["publico"]:
        lines.append(f"Público: {req['publico']}.")
    if req["competencia"]:
        lines.append(f"Competencia a desarrollar: {req['competencia']}.")
    if req["indicaciones"]:
        lines.append(f"Indicaciones del docente: {req['indicaciones']}")

    lines += [
        "",
        "FORMATO DE RESPUESTA (JSON):",
        '{"recursos": [{"titulo": "...", "contenido": "...",',
        ' "citas": [{"afirmacion": "...", "fragmentos": ["F1"]}],',
        ' "alternativas": [{"texto": "...", "correcta": true, "retroalimentacion": "...", "fragmentos": ["F2"]},',
        '                  {"texto": "...", "correcta": false, "retroalimentacion": "...", "error_conceptual": "...",'
        ' "fragmentos": ["F3"]}]}]}',
        "«alternativas» solo se llena en ítems de opción múltiple; en los demás tipos usa [].",
    ]
    if req["tipo"] in STRUCTURE_INSTRUCTIONS:
        lines += [
            "Agrega también a cada recurso: " + STRUCTURE_INSTRUCTIONS[req["tipo"]],
            "En «contenido» escribe la consigna o una explicación breve para el estudiante.",
        ]
    previous_resources = context.get("secuenciaPrevia") or []
    if previous_resources:
        lines += [
            "",
            "RECURSOS QUE OTROS AGENTES YA REDACTARON PARA ESTA CLASE (no repitas sus preguntas, ejemplos ni "
            "explicaciones; tu recurso debe complementarlos desde su propia etapa):",
        ]
        lines += [f"- {previous['titulo']}: {previous['resumen']}" for previous in previous_resources]
    lines += [
        "",
        "FRAGMENTOS DEL MATERIAL:",
    ]

    for frag in context["fragmentos"]:
        origin = ", ".join(x for x in (frag["documento"], frag["ubicacion"]) if x)
        lines += [f"[{frag['etiqueta']}] ({origin})", frag["texto"], ""]

    return system_prompt, "\n".join(lines).strip()


def parse_json_response(raw_text: str) -> Any:
    """Extrae y parsea el objeto JSON incluso si viene encerrado en bloques markdown."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError("La respuesta del modelo está vacía.")
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start_idx = cleaned.find("{")
    end_idx = cleaned.rfind("}")
    if start_idx != -1 and end_idx > start_idx:
        try:
            return json.loads(cleaned[start_idx : end_idx + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError("La respuesta del modelo no es JSON válido.")


def _clean_inline_text(value: Any, max_len: int) -> str:
    """Limpia saltos de línea y normaliza espacios simples."""
    return " ".join(value.split())[:max_len] if isinstance(value, str) else ""


def _clean_multiline_block(value: Any, max_len: int) -> str:
    """Conserva párrafos y saltos de línea intencionales limitando el largo total."""
    if not isinstance(value, str):
        return ""
    lines = [" ".join(line.split()) for line in value.replace("\r", "").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()[:max_len]


def _resolve_fragment_ids(value: Any, tag_mapping: dict[str, str]) -> list[str]:
    """Mapea etiquetas F1, F2 a sus identificadores de base de datos."""
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        value = [value]
    if not isinstance(value, list):
        return []
    resolved_ids: list[str] = []
    for item in value:
        if isinstance(item, bool):
            continue
        digits = [str(item)] if isinstance(item, int) else re.findall(r"\d+", str(item))
        for digit in digits:
            tag_key = f"F{int(digit)}"
            if tag_key in tag_mapping and tag_mapping[tag_key] not in resolved_ids:
                resolved_ids.append(tag_mapping[tag_key])
    return resolved_ids


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def structure_from_model(
    resource_type: str, raw: Any, body: str, title: str, tag_mapping: dict[str, str] | None = None
) -> dict[str, Any] | None:
    """Traduce la «estructura» del contrato con el modelo (claves en español) a la del recurso y la valida.

    `tag_mapping` (F1 → id del fragmento) se usa en la exploración guiada (HU-048), el reto de predicción (HU-047) y
    el caso aplicado (HU-050), cuyos pasos, predicciones o criterios citan su fragmento.
    """
    data = raw if isinstance(raw, dict) else {}
    converted: dict[str, Any] = {}
    if resource_type in ("audio_detonante", "podcast_resumen"):
        converted = {"script": data.get("guion") or body}
    elif resource_type == "imagen_ilustrativa":
        converted = {
            "prompt": data.get("descripcion_imagen"),
            "alt": data.get("texto_alternativo"),
            "caption": data.get("leyenda") or title,
        }
    elif resource_type == "diagrama_proceso":
        converted = {"steps": [{"title": i.get("titulo"), "text": i.get("texto")} for i in _list_of_dicts(data.get("pasos"))]}
    elif resource_type in ("exploracion_guiada", "actividad_kinestesica"):
        converted = {
            "guidedSteps": [
                {
                    "title": i.get("titulo"),
                    "instruction": i.get("consigna"),
                    "question": i.get("pregunta"),
                    "fragmentIds": _resolve_fragment_ids(i.get("fragmentos"), tag_mapping or {}),
                }
                for i in _list_of_dicts(data.get("pasos_guiados"))
            ]
        }
        if resource_type == "actividad_kinestesica":
            # HU-024: datos de la actividad; van en `structure`, pero no se contrastan con el material.
            converted.update(
                {
                    "materials": data.get("materiales"),
                    "estimatedMinutes": data.get("minutos_estimados"),
                    "space": data.get("espacio"),
                }
            )
    elif resource_type == "reto_prediccion":
        converted = {
            "predictions": [
                {
                    "question": i.get("pregunta"),
                    "correctOption": i.get("correcta"),
                    "otherOption": i.get("otra"),
                    "extraOption": i.get("extra"),
                    "reveal": i.get("revelacion"),
                    "fragmentIds": _resolve_fragment_ids(i.get("fragmentos"), tag_mapping or {}),
                }
                for i in _list_of_dicts(data.get("predicciones"))
            ]
        }
    elif resource_type == "caso_aplicado":
        converted = {
            "scenario": data.get("situacion"),
            "task": data.get("consigna"),
            "criteria": [
                {
                    "criterion": i.get("criterio"),
                    "fragmentIds": _resolve_fragment_ids(i.get("fragmentos"), tag_mapping or {}),
                }
                for i in _list_of_dicts(data.get("criterios"))
            ],
        }
    elif resource_type == "mapa_conceptual":
        converted = {
            "central": data.get("central") or title,
            "nodes": [{"label": i.get("etiqueta"), "detail": i.get("detalle")} for i in _list_of_dicts(data.get("nodos"))],
        }
    elif resource_type == "infografia":
        converted = {
            "headline": data.get("central") or title,
            "points": [{"title": i.get("titulo"), "text": i.get("texto")} for i in _list_of_dicts(data.get("puntos"))],
        }
    elif resource_type == "emparejamiento":
        converted = {
            "pairs": [{"term": i.get("termino"), "definition": i.get("definicion")} for i in _list_of_dicts(data.get("pares"))]
        }
    elif resource_type == "ordenar_pasos":
        converted = {"sequence": data.get("secuencia")}
    elif resource_type == "verdadero_falso":
        converted = {
            "statements": [
                {"text": i.get("texto"), "isTrue": i.get("verdadera"), "feedback": i.get("retroalimentacion")}
                for i in _list_of_dicts(data.get("afirmaciones"))
            ]
        }
    elif resource_type == "completar_espacios":
        converted = {
            "blanks": [{"sentence": i.get("oracion"), "answer": i.get("respuesta")} for i in _list_of_dicts(data.get("espacios"))]
        }
    return normalize_structure(resource_type, converted)


def _parse_is_correct(alternative: dict[str, Any]) -> bool:
    """Determina si una opción es la clave correcta aceptando variantes sintácticas."""
    raw_val = next(
        (alternative[k] for k in ("correcta", "esCorrecta", "correct", "isCorrect") if k in alternative),
        False,
    )
    if isinstance(raw_val, str):
        return raw_val.strip().lower() in ("true", "sí", "si", "verdadero", "correcta")
    return raw_val is True


def _structure_rejection_reason(resource_type: str, raw_structure: Any, title: str) -> str:
    """Por qué la «estructura» que devolvió el modelo no alcanza para el recurso, en palabras del docente."""
    if resource_type == "actividad_kinestesica":
        data = raw_structure if isinstance(raw_structure, dict) else {}
        problems = []
        steps = data.get("pasos_guiados")
        minimum = MIN_ITEMS[resource_type]
        if not isinstance(steps, list) or not steps:
            problems.append(
                "no trae los pasos dentro de «pasos_guiados»: la actividad es un solo recurso con todos sus pasos, "
                "no un recurso por paso"
            )
        else:
            converted = [{"title": i.get("titulo"), "instruction": i.get("consigna")} for i in _list_of_dicts(steps)]
            complete = complete_guided_steps(converted, question_required=False)
            if complete < minimum:
                problems.append(
                    f"solo {complete} paso(s) completos (título y consigna); la actividad necesita al menos {minimum}"
                )
        minutes = data.get("minutos_estimados")
        if estimated_minutes(minutes) is None:
            received = "" if minutes is None or str(minutes).strip() == "" else f"; llegó «{minutes}»"
            problems.append(f"falta el tiempo estimado (entero de {MIN_MINUTES} a {MAX_MINUTES} minutos){received}")
        space = data.get("espacio")
        if not (isinstance(space, str) and space.strip()):
            problems.append("falta el espacio donde se hace la actividad")
        if problems:
            return f"«{title}»: " + "; ".join(problems) + "."
    minimum = MIN_ITEMS.get(resource_type)
    detail = f" (necesita al menos {minimum} elementos completos)" if minimum else ""
    return f"«{title}»: la estructura de «{RESOURCE_TYPES[resource_type][0]}» está incompleta o no es válida{detail}."


def _reject_structure(rejections: list[dict[str, Any]] | None, title: str, reason: str) -> None:
    """Un recurso que se descarta por su forma (no por su respaldo) queda como rechazo `structure` con su motivo."""
    if rejections is not None:
        rejections.append({"title": title, "reason": reason, "kind": "structure"})


def normalize_generated_resources(
    raw_payload: Any, context: dict[str, Any], rejections: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Valida que cada recurso tenga contenido, evidencia verificable y alternativas válidas.

    HU-016: cada afirmación citada se contrasta con los fragmentos recuperados (verificación de anclaje). Las que no
    tienen respaldo se quitan; si queda menos de la mitad, el recurso se rechaza. Cada rechazo se agrega a `rejections`
    con su motivo, y cada recurso conservado guarda su verificación en «verificacion».

    HU-049: en la explicación y el glosario también se contrasta el contenido, párrafo por párrafo. Los párrafos sin
    respaldo se quitan del contenido y, si queda menos de la mitad, el recurso se rechaza.
    """
    tag_mapping = {f["etiqueta"]: f["id"] for f in context["fragmentos"]}
    fragments_by_id = {f["id"]: f.get("texto", "") for f in context["fragmentos"]}
    req = context["solicitud"]
    threshold = float(req.get("umbralEvidencia", DEFAULT_THRESHOLD))
    type_name = RESOURCE_TYPES[req["tipo"]][0]
    items_list = raw_payload.get("recursos") if isinstance(raw_payload, dict) else raw_payload
    if not isinstance(items_list, list):
        _reject_structure(rejections, type_name, "La respuesta del modelo no trae la lista «recursos».")
        return []

    verified_resources: list[dict[str, Any]] = []
    for position, raw_item in enumerate(items_list, 1):
        if len(verified_resources) >= req["cantidad"]:
            continue  # ya están los recursos pedidos: los demás sobran
        if not isinstance(raw_item, dict):
            _reject_structure(
                rejections,
                f"{type_name} {position}",
                f"El elemento {position} de la respuesta no es un recurso (se esperaba un objeto JSON).",
            )
            continue

        body = _clean_multiline_block(raw_item.get("contenido"), MAX_CONTENT_CHARS)
        valid_citations: list[dict[str, Any]] = []

        for cit in raw_item.get("citas") or []:
            if isinstance(cit, dict):
                matched_ids = _resolve_fragment_ids(cit.get("fragmentos"), tag_mapping)
                claim = _clean_inline_text(cit.get("afirmacion"), MAX_CLAIM_CHARS)
                if matched_ids and claim:
                    valid_citations.append({"claim": claim, "fragmentIds": matched_ids})

        title = (
            _clean_inline_text(raw_item.get("titulo"), MAX_TITLE_CHARS)
            or f"{RESOURCE_TYPES[req['tipo']][0]} {len(verified_resources) + 1}"
        )
        if not body:
            _reject_structure(rejections, title, f"«{title}»: llegó sin contenido.")
            continue

        grounding = verify_citations(valid_citations, fragments_by_id, threshold)
        if not grounding.accepted:
            if rejections is not None:
                rejections.append(
                    {
                        "title": title,
                        "reason": grounding.rejection_reason(title),
                        "grounding": grounding.summary(),
                        "kind": "grounding",
                    }
                )
            continue
        valid_citations = [
            {"claim": check.claim, "fragmentIds": check.fragment_ids} for check in grounding.supported
        ]
        verification = grounding.summary()

        statements = verify_statements(body, req["tipo"], fragments_by_id, threshold)
        if statements is not None:
            verification.update(statements.summary())
            if not statements.accepted:
                if rejections is not None:
                    rejections.append(
                        {
                            "title": title,
                            "reason": statements.rejection_reason(title),
                            "grounding": verification,
                            "kind": "grounding",
                        }
                    )
                continue
            body = statements.kept_body()

        structure = None
        if req["tipo"] in STRUCTURE_INSTRUCTIONS:
            structure = structure_from_model(req["tipo"], raw_item.get("estructura"), body, title, tag_mapping)
            if structure is None:
                _reject_structure(
                    rejections, title, _structure_rejection_reason(req["tipo"], raw_item.get("estructura"), title)
                )
                continue
            if req["tipo"] in GUIDED_STEP_TYPES:
                # HU-048 C02 y HU-024: cada paso queda enlazado al fragmento que lo respalda; los que no se apoyan se
                # quitan. En la actividad kinestésica, materiales, tiempo y espacio no se contrastan con el material.
                linked = link_step_sources(structure["guidedSteps"], fragments_by_id)
                verification.update(linked.summary())
                minimum = MIN_ITEMS[req["tipo"]]
                if len(linked.steps) < minimum:
                    if rejections is not None:
                        rejections.append(
                            {
                                "title": title,
                                "reason": (
                                    f"«{title}»: solo {len(linked.steps)} paso(s) se apoyan en el material; "
                                    f"{GUIDED_STEP_TYPES[req['tipo']]} necesita al menos {minimum}."
                                ),
                                "grounding": verification,
                                "kind": "grounding",
                            }
                        )
                    continue
                structure = {**structure, "guidedSteps": linked.steps}
            if req["tipo"] == "reto_prediccion":
                # HU-047 C02: cada predicción queda enlazada al fragmento que respalda su respuesta.
                linked = link_prediction_sources(structure["predictions"], fragments_by_id)
                verification.update(linked.summary())
                if len(linked.predictions) < MIN_ITEMS["reto_prediccion"]:
                    if rejections is not None:
                        rejections.append(
                            {
                                "title": title,
                                "reason": (
                                    f"«{title}»: solo {len(linked.predictions)} predicción(es) tienen su respuesta "
                                    f"en el material; el reto necesita al menos {MIN_ITEMS['reto_prediccion']}."
                                ),
                                "grounding": verification,
                                "kind": "grounding",
                            }
                        )
                    continue
                structure = {**structure, "predictions": linked.predictions}
            if req["tipo"] == "caso_aplicado":
                # HU-050 C01: cada criterio de logro queda enlazado al fragmento con el concepto que aplica.
                linked = link_criterion_sources(structure["criteria"], fragments_by_id)
                verification.update(linked.summary())
                if len(linked.criteria) < MIN_ITEMS["caso_aplicado"]:
                    if rejections is not None:
                        rejections.append(
                            {
                                "title": title,
                                "reason": (
                                    f"«{title}»: solo {len(linked.criteria)} criterio(s) de logro se apoyan en el "
                                    f"material; el caso necesita al menos {MIN_ITEMS['caso_aplicado']}."
                                ),
                                "grounding": verification,
                                "kind": "grounding",
                            }
                        )
                    continue
                structure = {**structure, "criteria": linked.criteria}

        alternatives = None
        if req["tipo"] == "item_opcion_multiple":
            alternatives = _validate_alternatives(
                raw_item.get("alternativas"),
                tag_mapping,
                valid_citations,
                req["alternativas"],
            )
            if alternatives is None:
                _reject_structure(
                    rejections,
                    title,
                    f"«{title}»: las alternativas no son válidas: hace falta 1 correcta y {req['alternativas'] - 1} "
                    "distractores, cada uno con su retroalimentación y su error conceptual.",
                )
                continue
            reliable = _review_distractor_reliability(alternatives, body, fragments_by_id)
            needed = min(MIN_RELIABLE_DISTRACTORS, len(alternatives) - 1)
            if reliable < needed:
                if rejections is not None:
                    rejections.append(
                        {
                            "title": title,
                            "reason": (
                                f"«{title}»: solo {reliable} distractor(es) fiable(s); el material muestra como "
                                "correctos los demás."
                            ),
                            "kind": "distractor",
                        }
                    )
                continue

        verified_resources.append(
            {
                "titulo": title,
                "contenido": body,
                "citas": valid_citations,
                "alternativas": alternatives,
                "estructura": structure,
                "verificacion": verification,
            }
        )

    return verified_resources


MISCONCEPTION_KEYS: tuple[str, ...] = ("error_conceptual", "errorConceptual", "error")
MISCONCEPTION_INSTRUCTION: str = (
    "En cada distractor, «retroalimentacion» justifica por qué es incorrecto según el material y «error_conceptual» "
    "nombra la concepción errónea que representa (qué confunde el estudiante que lo elige). "
    "Un distractor nunca puede ser correcto según el material."
)


def _review_distractor_reliability(
    alternatives: list[dict[str, Any]], body: str, fragments_by_id: dict[str, str]
) -> int:
    """HU-019 C02: marca los distractores que la evidencia muestra como correctos. Devuelve cuántos quedan fiables."""
    key = next(alt for alt in alternatives if alt["correcta"])
    reliable = 0
    for alternative in alternatives:
        if alternative["correcta"]:
            continue
        issue = assess_distractor(body, key["texto"], alternative["texto"], fragments_by_id)
        if issue is None:
            reliable += 1
        else:
            alternative["tambienCorrecto"] = issue.reason
    return reliable


def _validate_alternatives(
    raw_options: Any,
    tag_mapping: dict[str, str],
    citations: list[dict[str, Any]],
    target_count: int,
) -> list[dict[str, Any]] | None:
    """Valida que exista exactamente una clave correcta y el número requerido de distractores."""
    if not isinstance(raw_options, list):
        return None

    fallback_citations = citations[0]["fragmentIds"]
    seen_texts: set[str] = set()
    correct_key: dict[str, Any] | None = None
    distractors: list[dict[str, Any]] = []

    for option in raw_options:
        if not isinstance(option, dict):
            continue
        text = _clean_inline_text(option.get("texto"), MAX_OPTION_CHARS)
        if not text or text.casefold() in seen_texts:
            continue
        seen_texts.add(text.casefold())

        justification = _clean_inline_text(option.get("retroalimentacion"), MAX_OPTION_CHARS)
        parsed_option = {
            "texto": text,
            "correcta": _parse_is_correct(option),
            "retroalimentacion": justification or "Revisa el material de la unidad.",
            "fragmentos": _resolve_fragment_ids(option.get("fragmentos"), tag_mapping)
            or fallback_citations,
        }

        if parsed_option["correcta"]:
            if correct_key is not None:
                return None  # Múltiples claves: ítem inválido
            correct_key = parsed_option
        else:
            # HU-019 C01: un distractor sin justificación o sin el error conceptual que representa no se usa.
            misconception = _clean_inline_text(
                next((option.get(k) for k in MISCONCEPTION_KEYS if option.get(k)), ""), MAX_OPTION_CHARS
            )
            if justification and misconception:
                distractors.append({**parsed_option, "errorConceptual": misconception})

    if correct_key is None or len(distractors) < target_count - 1:
        return None

    return [correct_key, *distractors[: target_count - 1]]