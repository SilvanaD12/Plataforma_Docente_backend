"""Fuente única de los tipos de recurso, etiquetas y metadatos compartidos con la interfaz."""
from __future__ import annotations

from dataclasses import dataclass


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
