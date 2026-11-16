# Tareas de atributos de calidad — Sprint 2

[Ficha QA](spec.md) · [Plan](plan.md)

## Cómo leer las tareas

Formato: `- [ ] QA-xx [BE]/[FE]/[E2E] **Responsable.** Descripción — criterio de cierre — plazo`.

| Marca | Significado |
| --- | --- |
| `[BE]` | Repositorio `Plataforma_Docente_backend` |
| `[FE]` | Repositorio `Plataforma_Docente_frontend` |
| `[E2E]` | Recorrido de punta a punta o validación manual |

## Definición de hecho

- PR integrado con CI en verde.
- Tarea marcada `[x]` con enlace al PR.
- Resultado medido junto a su meta, aunque no la alcance.
- Evidencia en el repo o enlazada (carpeta `docs/evidence/<ID>/`).
- Aprobación del dueño del módulo.

## Tareas

- [x] QA-01 [BE] **Juan.** Crear `specs/005-atributos-calidad/` con `spec.md`, `plan.md` y `tasks.md`. Un escenario de calidad por tarea, con las seis partes (fuente, estímulo, entorno, artefacto, respuesta y medida). — Evidencia: este PR. — Plazo: sáb 14/11 23:30.

- [x] QA-02 [BE] **Juan.** `GET /health/dependencies` informa el estado de la base de datos, Gemini y Wikipedia sin gastar tokens. Puerto `DependencyProbePort`, caso de uso con comprobaciones en paralelo (3 s de límite cada una) y adaptadores. Respuesta 200 siempre (503 solo si la BD está caída), con caché de 30 s. Motivos genéricos con `redact_secrets`. — Criterio: la ruta responde `degraded` cuando Gemini o Wikipedia no responden en 3 s; pruebas unitarias y e2e sin salir a internet; OpenAPI regenerado; Yan y Sergio validan el comportamiento con la dependencia caída. — Plazo: dom 15/11 18:00. — **Hecho:** 16 pruebas unitarias (`test_check_dependencies.py`) y 8 pruebas e2e (`test_dependency_health_api.py`) pasando; contrato OpenAPI actualizado con `/health/dependencies` (32 rutas); caché de 30 s y sanitización con `redact_secrets`. Revisores: Yan y Sergio.

- [x] QA-03 [BE] [FE] [E2E] **Juan.** Exportar `verdadero_falso` (`<question type="truefalse">`) y `emparejamiento` (`<question type="matching">`) a Moodle XML. Actualizar la elegibilidad de exportación. Importación real en Moodle 5.3.1, con capturas. Matriz TA-006 en `docs/compatibility/TA-006-matriz.md`. — Criterio: los tres tipos se importan sin errores en Moodle 5.3.1, con calificación y retroalimentación correctas; pruebas unitarias del exportador y del validador; frontend actualizado si hay mensajes que limiten a opción múltiple. — Evidencia: este PR, `docs/evidence/QA-03/` y `docs/compatibility/TA-006-matriz.md`. — Plazo: dom 15/11 20:00.

- [ ] QA-04 [BE] **Juan.** Informe final de calidad en `specs/005-atributos-calidad/report.md`. Tabla con ID, responsable, atributo, escenario, meta, resultado medido, ¿cumple? y evidencia. Conclusión por atributo. Lista de verificación para el despliegue. — Criterio: tabla completa con resultados registrados en el repo; sin resultados inventados. — Plazo: lun 16/11 09:00.

- [x] QA-05 [BE] **Yan.** C-06 pasa: sin material del tema no se genera ningún recurso. C-01 a C-05 siguen generando con `faithfulness` ≥ 0,90. — Criterio: evaluación Ragas con los 6 casos; C-06 rechaza el pedido; C-01 a C-05 con `faithfulness` ≥ 0,90. — Plazo: dom 15/11 20:00. PR del backend (enlace pendiente).
  - Implementación: comprobación de cobertura del tema en `domain/generation/topic_coverage.py`, después de la búsqueda y antes de redactar; umbral `TOPIC_COVERAGE_THRESHOLD` = 0,5 (0 la apaga); motivo con `INSUFFICIENT_EVIDENCE`. Diseño y tabla de cobertura de los 16 casos en [plan.md](plan.md#qa-05--rechazo-sin-material-del-tema-c-06).
  - Resultado medido (16/11/2026): C-06 se rechaza con «El material de la unidad no trata «llaves primarias, modelo relacional». Sube material sobre ese tema o cambia las indicaciones.» y sin recursos; C-01 a C-05 generan con Gemini (5/5). `faithfulness` promedio 0,97 con contexto recuperado y 0,98 con contexto citado (meta ≥ 0,90: cumple en promedio). Por caso, con contexto recuperado: C-01 1,00, C-02 1,00, C-03 1,00, C-04 0,85, C-05 1,00 (C-04 queda bajo 0,90; con contexto citado, 0,92). `answer_relevancy` 0,95; `context_precision` 0,59 / 1,00; `context_recall` 0,20 / 0,60.
  - Con el generador por reglas, los 10 casos de `cases.json` y C-01 a C-05 siguen generando; solo C-06 se rechaza.
  - Límites: comprobación léxica; con sinónimos ausentes del material puede rechazar un pedido válido (el motivo pide cambiar las indicaciones y el umbral es configurable). Medido con BM25 (SQLite); con la búsqueda híbrida de producción queda por confirmar en QA-07.
  - Evidencia: `docs/evidence/QA-05/` (resúmenes de Ragas, puntajes por caso y `expectations.jsonl`) y pruebas en `backend/tests/unit/test_topic_coverage.py` y `backend/tests/e2e/test_collect_samples.py`.

- [ ] QA-06 [BE] **Yan.** Con 5 secuencias en paralelo, crear un pedido responde en p95 < 500 ms. Ninguna llamada a Gemini queda colgada más de 60 s. — Criterio: medición con el script de carga; p95 < 500 ms para el POST; tiempo límite de 60 s configurado y probado. — Plazo: dom 15/11 20:00.

- [x] QA-07 [BE] **Sergio.** `context_recall` ≥ 0,60 con pgvector. Ningún fragmento del documento distractor en C-01 a C-05. – Criterio: evaluación Ragas con pgvector; `context_recall` ≥ 0,60; sin fragmentos del distractor. Depende del PR #40 de Yan. – Plazo: dom 15/11 20:00. – **Resultado (15/11):** Completado con `pgvector` en modo `hybrid` (`gemini-3.8-flash`); `context_recall = 0.60`, `faithfulness = 0.98`, `answer_relevancy = 0.90`, `context_precision = 0.58`, trazabilidad I22 `5/5` y `0` fragmentos del documento distractor en C-01 a C-05 (`backend/evaluation/results/summary.md`).

- [x] QA-08 [BE] **Sergio.** Al 6.º intento fallido en 15 min para el mismo correo e IP, 429 con `Retry-After` y sin revelar si el correo existe. Cabeceras `X-Content-Type-Options: nosniff`, `Content-Security-Policy: frame-ancestors 'none'` y `Referrer-Policy`. `pip-audit` sin vulnerabilidades altas. – Criterio: pruebas e2e del 429 y de las cabeceras; `pip-audit` limpio. – Plazo: dom 15/11 20:00. – Evidencia: pruebas e2e en `tests/e2e/test_auth_security.py` aprobadas (`429` con `Retry-After` al 6.º intento fallido en 15 min sin enumeración de usuarios, y cabeceras `X-Content-Type-Options: nosniff`, `Content-Security-Policy: frame-ancestors 'none'` y `Referrer-Policy`); `pip-audit` integrado en CI sin vulnerabilidades altas en dependencias de aplicación.

- [ ] QA-09 [FE] **Silvana.** 0 violaciones serias o críticas de WCAG 2.1 AA (axe) en todas las páginas. Recorrido completo solo con teclado. — Criterio: `@axe-core/playwright` integrado; 0 violaciones serias o críticas; recorrido con teclado sin bloqueos. — Plazo: dom 15/11 20:00.

- [ ] QA-10 [FE] **Silvana.** JavaScript inicial < 200 kB comprimido. La CI falla si se pasa del presupuesto o si `npm audit` encuentra vulnerabilidades altas. — Criterio: carga diferida implementada; presupuesto en CI; `npm audit` en CI; JavaScript < 200 kB gzip. — Plazo: dom 15/11 20:00.

- [ ] QA-11 [BE] **Juan.** *(Opcional, solo si QA-01 a QA-04 están integrados.)* Cada frase del guion de `audio_detonante` y `podcast_resumen` tiene respaldo en el material. Subir `VERIFICATION_RULE_VERSION`. Los audios aprobados antes del cambio se reverifican al leerlos. — Criterio: pruebas de guion respaldado → `current`; frase sin respaldo → `insufficient` con motivo; aprobado antiguo → reverificado al leer. — Plazo: dom 15/11 20:00.
