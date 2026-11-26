"""Fuente única de los tipos de recurso, etiquetas y metadatos compartidos con la interfaz."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ResourceTypeDefinition:
    id: str
    name: str
    singular: str
    count: tuple[str, str]
    stage: str
    group: str
    format: str
    has_options: bool = False


RESOURCE_TYPES: tuple[ResourceTypeDefinition, ...] = (
    ResourceTypeDefinition('pregunta_detonante', 'Pregunta detonante', 'Pregunta detonante', ('pregunta detonante', 'preguntas detonantes'), 'engage', 'Para iniciar la clase', 'text'),
    ResourceTypeDefinition('sondeo_diagnostico', 'Sondeo de ideas previas', 'Sondeo de ideas previas', ('sondeo', 'sondeos'), 'engage', 'Para iniciar la clase', 'text'),
    ResourceTypeDefinition('audio_detonante', 'Cápsula de audio detonante', 'Cápsula de audio', ('audio', 'audios'), 'engage', 'Para iniciar la clase', 'audio'),
    ResourceTypeDefinition('reto_prediccion', 'Reto de predicción', 'Reto de predicción', ('reto de predicción', 'retos de predicción'), 'engage', 'Para iniciar la clase', 'interactive'),
    ResourceTypeDefinition('guia_exploracion', 'Guía de exploración', 'Guía de exploración', ('guía', 'guías'), 'explore', 'Para explorar', 'text'),
    ResourceTypeDefinition('caso_indagacion', 'Caso con preguntas', 'Caso con preguntas', ('caso', 'casos'), 'explore', 'Para explorar', 'text'),
    ResourceTypeDefinition('imagen_ilustrativa', 'Imagen ilustrativa', 'Imagen ilustrativa', ('imagen', 'imágenes'), 'explore', 'Para explorar', 'image'),
    ResourceTypeDefinition('diagrama_proceso', 'Diagrama de proceso', 'Diagrama de proceso', ('diagrama', 'diagramas'), 'explore', 'Para explorar', 'visual'),
    ResourceTypeDefinition('exploracion_guiada', 'Exploración guiada', 'Exploración guiada', ('exploración guiada', 'exploraciones guiadas'), 'explore', 'Para explorar', 'interactive'),
    ResourceTypeDefinition('actividad_kinestesica', 'Actividad kinestésica', 'Actividad kinestésica', ('actividad kinestésica', 'actividades kinestésicas'), 'explore', 'Para explorar', 'interactive'),
    ResourceTypeDefinition('explicacion', 'Explicación del tema', 'Explicación del tema', ('explicación', 'explicaciones'), 'explain', 'Para explicar', 'text'),
    ResourceTypeDefinition('glosario', 'Glosario', 'Glosario', ('glosario', 'glosarios'), 'explain', 'Para explicar', 'text'),
    ResourceTypeDefinition('mapa_conceptual', 'Mapa conceptual', 'Mapa conceptual', ('mapa conceptual', 'mapas conceptuales'), 'explain', 'Para explicar', 'visual'),
    ResourceTypeDefinition('infografia', 'Infografía', 'Infografía', ('infografía', 'infografías'), 'explain', 'Para explicar', 'visual'),
    ResourceTypeDefinition('podcast_resumen', 'Resumen en pódcast', 'Resumen en pódcast', ('pódcast', 'pódcasts'), 'explain', 'Para explicar', 'audio'),
    ResourceTypeDefinition('ejercicio_aplicacion', 'Ejercicio de aplicación', 'Ejercicio de aplicación', ('ejercicio', 'ejercicios'), 'elaborate', 'Para aplicar', 'text'),
    ResourceTypeDefinition('caso_aplicado', 'Caso aplicado', 'Caso aplicado', ('caso aplicado', 'casos aplicados'), 'elaborate', 'Para aplicar', 'interactive'),
    ResourceTypeDefinition('emparejamiento', 'Relacionar conceptos', 'Actividad de relacionar', ('actividad de relacionar', 'actividades de relacionar'), 'elaborate', 'Para aplicar', 'interactive'),
    ResourceTypeDefinition('ordenar_pasos', 'Ordenar pasos', 'Actividad de ordenar', ('actividad de ordenar', 'actividades de ordenar'), 'elaborate', 'Para aplicar', 'interactive'),
    ResourceTypeDefinition('item_opcion_multiple', 'Preguntas de opción múltiple', 'Pregunta de opción múltiple', ('pregunta', 'preguntas'), 'evaluate', 'Para evaluar', 'text', has_options=True),
    ResourceTypeDefinition('verdadero_falso', 'Verdadero o falso', 'Verdadero o falso', ('verdadero o falso', 'verdadero o falso'), 'evaluate', 'Para evaluar', 'interactive'),
    ResourceTypeDefinition('completar_espacios', 'Completar espacios', 'Completar espacios', ('completar espacios', 'completar espacios'), 'evaluate', 'Para evaluar', 'interactive'),
)

_CUR_P2_GROUPS = {
    "engage": "Para iniciar la clase",
    "explore": "Para explorar",
    "explain": "Para explicar",
    "elaborate": "Para aplicar",
    "evaluate": "Para evaluar",
}
_CUR_P2_DATA = Path(__file__).with_name("cur_p2_text_types.json")
CUR_P2_TEXT_TYPES = {
    entry["id"]: entry
    for entry in json.loads(_CUR_P2_DATA.read_text(encoding="utf-8"))
    if entry["active"] is True
}
RESOURCE_TYPES += tuple(
    ResourceTypeDefinition(
        id=entry["id"],
        name=entry["name"],
        singular=entry["singular"],
        count=(entry["singular"].lower(), entry["plural"].lower()),
        stage=entry["stage"],
        group=_CUR_P2_GROUPS[entry["stage"]],
        format=entry["format"],
        has_options=entry["hasOptions"],
    )
    for entry in CUR_P2_TEXT_TYPES.values()
)
