"""
GEN-C13 (spec 002, T075, research R13): palabras de uso común que el intérprete de pedidos (HU-038) reconoce como tipos
del catálogo, además de sus ids, nombres y alias de conteo.

- `TYPE_SYNONYMS`: la palabra sirve para un solo tipo.
- `AMBIGUOUS_SYNONYMS`: la palabra sirve para varios tipos; el intérprete no elige y devuelve las opciones (filtradas por
  la modalidad del mensaje).

Las claves se escriben como las diría el docente; se comparan en minúsculas y sin tildes. No se agregan palabras que
suelen ser parte del tema de la clase («historia», «ejemplo», «práctica», «definiciones»), ni las que ya son alias del
catálogo (lo comprueba `tests/unit/test_interpret_synonyms_audience.py`, junto con que cada destino exista).
"""

from __future__ import annotations

TYPE_SYNONYMS: dict[str, str] = {
    # Enganchar
    "pregunta motivadora": "pregunta_detonante",
    "preguntas motivadoras": "pregunta_detonante",
    "pregunta generadora": "pregunta_detonante",
    "preguntas generadoras": "pregunta_detonante",
    "pregunta inicial": "pregunta_detonante",
    "preguntas iniciales": "pregunta_detonante",
    "pregunta provocadora": "pregunta_detonante",
    "ideas previas": "sondeo_diagnostico",
    "saberes previos": "sondeo_diagnostico",
    "evaluación diagnóstica": "sondeo_diagnostico",
    "evaluaciones diagnósticas": "sondeo_diagnostico",
    "frase célebre": "frase_celebre_comentada",
    "frases célebres": "frase_celebre_comentada",
    "dilema": "dilema_inicial",
    "dilemas": "dilema_inicial",
    "cuento": "historia_corta",
    "cuentos": "historia_corta",
    "cuento corto": "historia_corta",
    "cuentos cortos": "historia_corta",
    # Explorar
    "diagrama de flujo": "diagrama_proceso",
    "diagramas de flujo": "diagrama_proceso",
    "flujograma": "diagrama_proceso",
    "flujogramas": "diagrama_proceso",
    # Explicar
    "resumen": "resumen_ideas_clave",
    "resúmenes": "resumen_ideas_clave",
    "síntesis": "resumen_ideas_clave",
    "ideas clave": "resumen_ideas_clave",
    "glosario de términos": "glosario",
    "glosarios de términos": "glosario",
    "vocabulario": "glosario",
    "términos clave": "glosario",
    "mapa mental": "mapa_conceptual",
    "mapas mentales": "mapa_conceptual",
    "cuadro comparativo": "comparacion_conceptos",
    "cuadros comparativos": "comparacion_conceptos",
    "analogía": "analogia_comentada",
    "analogías": "analogia_comentada",
    "errores comunes": "errores_frecuentes",
    "problema resuelto": "ejemplo_resuelto",
    "problemas resueltos": "ejemplo_resuelto",
    # Elaborar
    "ejercicios prácticos": "ejercicio_aplicacion",
    "ejercicio práctico": "ejercicio_aplicacion",
    "relacionar columnas": "emparejamiento",
    "unir con flechas": "emparejamiento",
    "pareo": "emparejamiento",
    # Evaluar
    "quiz": "item_opcion_multiple",
    "quizzes": "item_opcion_multiple",
    "quices": "item_opcion_multiple",
    "cuestionario": "item_opcion_multiple",
    "cuestionarios": "item_opcion_multiple",
    "pregunta de alternativas": "item_opcion_multiple",
    "preguntas de alternativas": "item_opcion_multiple",
    "preguntas de alternativa múltiple": "item_opcion_multiple",
    "pregunta de selección múltiple": "item_opcion_multiple",
    "preguntas de selección múltiple": "item_opcion_multiple",
    "verdadero y falso": "verdadero_falso",
    "espacios en blanco": "completar_espacios",
    "rellenar espacios": "completar_espacios",
    "pregunta abierta": "respuesta_corta",
    "preguntas abiertas": "respuesta_corta",
    "pregunta de respuesta breve": "respuesta_corta",
    "preguntas de respuesta breve": "respuesta_corta",
    "boleto de salida": "ticket_salida",
    "boletos de salida": "ticket_salida",
    "autoevaluación": "autoevaluacion_guiada",
    "autoevaluaciones": "autoevaluacion_guiada",
}

AMBIGUOUS_SYNONYMS: dict[str, tuple[str, ...]] = {
    "caso de estudio": ("caso_indagacion", "caso_aplicado", "analisis_caso_evaluativo"),
    "casos de estudio": ("caso_indagacion", "caso_aplicado", "analisis_caso_evaluativo"),
    "estudio de caso": ("caso_indagacion", "caso_aplicado", "analisis_caso_evaluativo"),
    "estudios de caso": ("caso_indagacion", "caso_aplicado", "analisis_caso_evaluativo"),
    "problema": ("ejercicio_aplicacion", "problema_abierto"),
    "problemas": ("ejercicio_aplicacion", "problema_abierto"),
    "examen": ("item_opcion_multiple", "verdadero_falso", "completar_espacios", "respuesta_corta"),
    "exámenes": ("item_opcion_multiple", "verdadero_falso", "completar_espacios", "respuesta_corta"),
    "prueba escrita": ("item_opcion_multiple", "verdadero_falso", "completar_espacios", "respuesta_corta"),
    "organizador gráfico": ("mapa_conceptual", "infografia", "comparacion_conceptos"),
    "organizadores gráficos": ("mapa_conceptual", "infografia", "comparacion_conceptos"),
}
