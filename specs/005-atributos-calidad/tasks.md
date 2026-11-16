# Tareas de atributos de calidad — Sprint 2

[Ficha QA](spec.md) · [Plan](plan.md)

## Cómo leer las tareas

Formato: `- [ ] QA-xx [BE]/[FE]/[E2E] **Responsable.** Descripción — criterio de cierre — plazo`.

| Marca     | Significado                                     |
| --------- | ----------------------------------------------- |
| `[BE]`  | Repositorio `Plataforma_Docente_backend`      |
| `[FE]`  | Repositorio `Plataforma_Docente_frontend`     |
| `[E2E]` | Recorrido de punta a punta o validación manual |

## Definición de hecho

- PR integrado con CI en verde.
- Tarea marcada `[x]` con enlace al PR.
- Resultado medido junto a su meta, aunque no la alcance.
- Evidencia en el repo o enlazada (carpeta `docs/evidence/<ID>/`).
- Aprobación del dueño del módulo.

## Tareas

- [X] QA-01 [BE] **Juan.** Crear `specs/005-atributos-calidad/` con `spec.md`, `plan.md` y `tasks.md`. Un escenario de calidad por tarea, con las seis partes (fuente, estímulo, entorno, artefacto, respuesta y medida). — Evidencia: este PR. — Plazo: sáb 14/11 23:30.
- [X] QA-02 [BE] **Juan.** `GET /health/dependencies` informa el estado de la base de datos, Gemini y Wikipedia sin gastar tokens. Puerto `DependencyProbePort`, caso de uso con comprobaciones en paralelo (3 s de límite cada una) y adaptadores. Respuesta 200 siempre (503 solo si la BD está caída), con caché de 30 s. Motivos genéricos con `redact_secrets`. — Criterio: la ruta responde `degraded` cuando Gemini o Wikipedia no responden en 3 s; pruebas unitarias y e2e sin salir a internet; OpenAPI regenerado; Yan y Sergio validan el comportamiento con la dependencia caída. — Plazo: dom 15/11 18:00. — **Hecho:** 16 pruebas unitarias (`test_check_dependencies.py`) y 8 pruebas e2e (`test_dependency_health_api.py`) pasando; contrato OpenAPI actualizado con `/health/dependencies` (32 rutas); caché de 30 s y sanitización con `redact_secrets`. Revisores: Yan y Sergio.
- [X] QA-03 [BE] [FE] [E2E] **Juan.** Exportar `verdadero_falso` (`<question type="truefalse">`) y `emparejamiento` (`<question type="matching">`) a Moodle XML. Actualizar la elegibilidad de exportación. Importación real en Moodle 5.3.1, con capturas. Matriz TA-006 en `docs/compatibility/TA-006-matriz.md`. — Criterio: los tres tipos se importan sin errores en Moodle 5.3.1, con calificación y retroalimentación correctas; pruebas unitarias del exportador y del validador; frontend actualizado si hay mensajes que limiten a opción múltiple. — Evidencia: este PR, `docs/evidence/QA-03/` y `docs/compatibility/TA-006-matriz.md`. — Plazo: dom 15/11 20:00.
- [ ] QA-04 [BE] **Juan.** Informe final de calidad en `specs/005-atributos-calidad/report.md`. Tabla con ID, responsable, atributo, escenario, meta, resultado medido, ¿cumple? y evidencia. Conclusión por atributo. Lista de verificación para el despliegue. — Criterio: tabla completa con resultados registrados en el repo; sin resultados inventados. — Plazo: lun 16/11 09:00.
- [ ] QA-05 [BE] **Yan.** C-06 pasa: sin material del tema no se genera ningún recurso. C-01 a C-05 siguen generando con `faithfulness` ≥ 0,90. — Criterio: evaluación Ragas con los 6 casos; C-06 rechaza el pedido; C-01 a C-05 con `faithfulness` ≥ 0,90. — Plazo: dom 15/11 20:00.
- [ ] QA-06 [BE] **Yan.** Con 5 secuencias en paralelo, crear un pedido responde en p95 < 500 ms. Ninguna llamada a Gemini queda colgada más de 60 s. — Criterio: medición con el script de carga; p95 < 500 ms para el POST; tiempo límite de 60 s configurado y probado. — Plazo: dom 15/11 20:00.
- [x] QA-07 [BE] **Sergio.** `context_recall` ≥ 0,60 con pgvector. Ningún fragmento del documento distractor en C-01 a C-05. – Criterio: evaluación Ragas con pgvector; `context_recall` ≥ 0,60; sin fragmentos del distractor. Depende del PR #40 de Yan. – Plazo: dom 15/11 20:00. – Evidencia: PR #51 y [docs/evidence/QA-07/summary.md](../../docs/evidence/QA-07/summary.md) (`context_recall = 0.6` / `0.6000` sin redondeo, `faithfulness = 0.9778`, `answer_relevancy = 0.8972`, `context_precision = 0.5758`, trazabilidad `5/5` y `0` fragmentos del documento distractor en C-01 a C-05).
- [x] QA-08 [BE] **Sergio.** Al 6.º intento fallido en 15 min para el mismo correo e IP, 429 con `Retry-After` y sin revelar si el correo existe. Cabeceras `X-Content-Type-Options: nosniff`, `Content-Security-Policy: frame-ancestors 'none'` y `Referrer-Policy`. `pip-audit` sin vulnerabilidades altas. – Criterio: pruebas e2e del 429 y de las cabeceras; `pip-audit` limpio. – Plazo: dom 15/11 20:00. – Evidencia: PR #50 y PR de seguimiento en `tests/e2e/test_auth_security.py` (reserva atómica de intentos antes de validar contraseña, resolución de IP validando `TRUSTED_PROXIES` contra spoofing de `X-Forwarded-For`, `429` con `Retry-After` al 6.º intento secuencial o concurrente y cabeceras HTTP de seguridad); `pip-audit` limpio en CI.
- [ ] QA-09 [FE] **Silvana.** 0 violaciones serias o críticas de WCAG 2.1 AA (axe) en todas las páginas. Recorrido completo solo con teclado. — Criterio: `@axe-core/playwright` integrado; 0 violaciones serias o críticas; recorrido con teclado sin bloqueos. — Plazo: dom 15/11 20:00.
- [ ] QA-10 [FE] **Silvana.** JavaScript inicial < 200 kB comprimido. La CI falla si se pasa del presupuesto o si `npm audit` encuentra vulnerabilidades altas. — Criterio: carga diferida implementada; presupuesto en CI; `npm audit` en CI; JavaScript < 200 kB gzip. — Plazo: dom 15/11 20:00.

