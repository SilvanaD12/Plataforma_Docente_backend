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
- [x] QA-06 [BE] **Yan.** Con 5 secuencias en paralelo, crear un pedido responde en p95 < 500 ms. Ninguna llamada a Gemini queda colgada más de 60 s. — Criterio: medición con el script de carga; p95 < 500 ms para el POST; tiempo límite de 60 s configurado y probado. — Plazo: dom 15/11 20:00. [PR #58 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/58).
  - Límite por llamada: `LLM_CALL_DEADLINE_SECONDS` (60 s por defecto y como máximo) con reloj de pared en `infrastructure/llm/call_deadline.py`, para texto, imagen, voz y embeddings; el reintento por JSON inválido comparte el plazo; al vencer se usa el respaldo con el motivo «Gemini no respondió en 60 s». `LLM_TIMEOUT_SECONDS` queda limitado a ese valor: en Render debe ser 60 o menos (hoy 180).
  - Resultado medido (16/11/2026, PostgreSQL 17 + pgvector local en Docker, `LLM_PROVIDER=rules`, `GENERATION_MAX_WORKERS` por defecto): 5 docentes envían una secuencia de 8 tipos × 5 a la vez; `POST /api/v1/generation-requests` p50 80 ms, p95 96 ms, máximo 99 ms, 5 de 5 con 202 (meta p95 < 500 ms: cumple). Los 5 pedidos terminaron `succeeded` (creado→terminado p50 1,4 s, p95 1,8 s), 125 recursos, 0 pasos con respaldo, 0 `DEADLINE_EXCEEDED`.
  - Límite de 60 s: probado con un proveedor simulado lento (respuesta por partes que supera el plazo; cada llamada termina dentro del plazo + 0,25 s y usa el respaldo) en `backend/tests/unit/test_llm_call_deadline.py` (17 pruebas); no se midió con Gemini real.
  - Evidencia: `docs/evidence/QA-06/` (informe JSON de la medición), comandos en [plan.md](plan.md#qa-06--tiempos-de-respuesta-y-límite-de-gemini) (QA-06) y script `backend/scripts/measure_generation_load.py --teachers 5`.
- [x] QA-07 [BE] **Sergio.** `context_recall` ≥ 0,60 con pgvector. Ningún fragmento del documento distractor en C-01 a C-05. – Criterio: evaluación Ragas con pgvector; `context_recall` ≥ 0,60; sin fragmentos del distractor. Depende del PR #40 de Yan. – Plazo: dom 15/11 20:00. – Evidencia: PR #51 y [docs/evidence/QA-07/summary.md](../../docs/evidence/QA-07/summary.md) (`context_recall = 0.6` / `0.6000` sin redondeo, `faithfulness = 0.9778`, `answer_relevancy = 0.8972`, `context_precision = 0.5758`, trazabilidad `5/5` y `0` fragmentos del documento distractor en C-01 a C-05).
- [x] QA-08 [BE] **Sergio.** Al 6.º intento fallido en 15 min para el mismo correo e IP, 429 con `Retry-After` y sin revelar si el correo existe. Cabeceras `X-Content-Type-Options: nosniff`, `Content-Security-Policy: frame-ancestors 'none'` y `Referrer-Policy`. `pip-audit` sin vulnerabilidades altas. – Criterio: pruebas e2e del 429 y de las cabeceras; `pip-audit` limpio. – Plazo: dom 15/11 20:00. – Evidencia: PR #50 y PR de seguimiento en `tests/e2e/test_auth_security.py` (reserva atómica de intentos antes de validar contraseña, resolución de IP validando `TRUSTED_PROXIES` contra spoofing de `X-Forwarded-For`, `429` con `Retry-After` al 6.º intento secuencial o concurrente y cabeceras HTTP de seguridad); `pip-audit` limpio en CI.
- [ ] QA-09 [FE] **Silvana.** 0 violaciones serias o críticas de WCAG 2.1 AA (axe) en todas las páginas. Recorrido completo solo con teclado. — Criterio: `@axe-core/playwright` integrado; 0 violaciones serias o críticas; recorrido con teclado sin bloqueos. — Plazo: dom 15/11 20:00.
- [ ] QA-10 [FE] **Silvana.** JavaScript inicial < 200 kB comprimido. La CI falla si se pasa del presupuesto o si `npm audit` encuentra vulnerabilidades altas. — Criterio: carga diferida implementada; presupuesto en CI; `npm audit` en CI; JavaScript < 200 kB gzip. — Plazo: dom 15/11 20:00.
- [ ] QA-11 [BE] **Juan.** *(Opcional, solo si QA-01 a QA-04 están integrados.)* Cada frase del guion de `audio_detonante` y `podcast_resumen` tiene respaldo en el material. Subir `VERIFICATION_RULE_VERSION`. Los audios aprobados antes del cambio se reverifican al leerlos. — Criterio: pruebas de guion respaldado → `current`; frase sin respaldo → `insufficient` con motivo; aprobado antiguo → reverificado al leer. — Plazo: dom 15/11 20:00.
