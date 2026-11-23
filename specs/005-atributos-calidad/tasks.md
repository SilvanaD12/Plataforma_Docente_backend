# Tareas de atributos de calidad — Sprint 2

[Ficha QA](spec.md) · [Plan](plan.md) · [Informe Final](report.md)

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
- [X] QA-04 [BE] **Juan.** Informe final de calidad en `specs/005-atributos-calidad/report.md`. Tabla con ID, responsable, atributo, escenario, meta, resultado medido, ¿cumple? y evidencia. Conclusión por atributo. Lista de verificación para el despliegue. — Criterio: tabla completa con resultados registrados en el repo; sin resultados inventados. — Plazo: lun 16/11 09:00. — **Hecho:** Informe final `report.md` redactado con la matriz consolidada de los 11 escenarios de calidad (ISO 25010), conclusiones por atributo y checklist de despliegue a producción. Evidencia: este PR (PR #56).
- [X] QA-05 [BE] **Yan.** C-06 pasa: sin material del tema no se genera ningún recurso. C-01 a C-05 siguen generando con `faithfulness` ≥ 0,90. — Criterio: evaluación Ragas con los 6 casos; C-06 rechaza el pedido; C-01 a C-05 con `faithfulness` ≥ 0,90. — Plazo: dom 15/11 20:00. [PR #57 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/57).
  - Implementación: comprobación de cobertura del tema en `domain/generation/topic_coverage.py`, después de la búsqueda y antes de redactar; umbral `TOPIC_COVERAGE_THRESHOLD` = 0,5 (0 la apaga); motivo con `INSUFFICIENT_EVIDENCE`. Diseño y tabla de cobertura de los 16 casos en [plan.md](plan.md#qa-05--rechazo-sin-material-del-tema-c-06).
  - Resultado medido (16/11/2026): C-06 se rechaza con «El material de la unidad no trata «llaves primarias, modelo relacional». Sube material sobre ese tema o cambia las indicaciones.» y sin recursos; C-01 a C-05 generan con Gemini (5/5). `faithfulness` promedio 0,97 con contexto recuperado y 0,98 con contexto citado (meta ≥ 0,90: cumple en promedio). Por caso, con contexto recuperado: C-01 1,00, C-02 1,00, C-03 1,00, C-04 0,85, C-05 1,00 (C-04 queda bajo 0,90; con contexto citado, 0,92). `answer_relevancy` 0,95; `context_precision` 0,59 / 1,00; `context_recall` 0,20 / 0,60.
  - Con el generador por reglas, los 10 casos de `cases.json` y C-01 a C-05 siguen generando; solo C-06 se rechaza.
  - Límites: comprobación léxica; con sinónimos ausentes del material puede rechazar un pedido válido (el motivo pide cambiar las indicaciones y el umbral es configurable). Medido con BM25 (SQLite); con la búsqueda híbrida de producción queda por confirmar en QA-07.
  - Evidencia: `docs/evidence/QA-05/` (resúmenes de Ragas, puntajes por caso y `expectations.jsonl`) y pruebas en `backend/tests/unit/test_topic_coverage.py` y `backend/tests/e2e/test_collect_samples.py`.
- [X] QA-06 [BE] **Yan.** Con 5 secuencias en paralelo, crear un pedido responde en p95 < 500 ms. Ninguna llamada a Gemini queda colgada más de 60 s. — Criterio: medición con el script de carga; p95 < 500 ms para el POST; tiempo límite de 60 s configurado y probado. — Plazo: dom 15/11 20:00. [PR #58 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/58).
  - Límite por llamada: `LLM_CALL_DEADLINE_SECONDS` (60 s por defecto y como máximo) con reloj de pared en `infrastructure/llm/call_deadline.py`, para texto, imagen, voz y embeddings; el reintento por JSON inválido comparte el plazo; al vencer se usa el respaldo con el motivo «Gemini no respondió en 60 s». `LLM_TIMEOUT_SECONDS` queda limitado a ese valor: en Render debe ser 60 o menos (hoy 180).
  - Resultado medido (16/11/2026, PostgreSQL 17 + pgvector local en Docker, `LLM_PROVIDER=rules`, `GENERATION_MAX_WORKERS` por defecto): 5 docentes envían una secuencia de 8 tipos × 5 a la vez; `POST /api/v1/generation-requests` p50 80 ms, p95 96 ms, máximo 99 ms, 5 de 5 con 202 (meta p95 < 500 ms: cumple). Los 5 pedidos terminaron `succeeded` (creado→terminado p50 1,4 s, p95 1,8 s), 125 recursos, 0 pasos con respaldo, 0 `DEADLINE_EXCEEDED`.
  - Evidencia: `docs/evidence/QA-06/` (informe JSON de la medición), comandos en [plan.md](plan.md#qa-06--tiempos-de-respuesta-y-límite-de-gemini) (QA-06) y script `backend/scripts/measure_generation_load.py --teachers 5`.

  - Entorno (16/11–18/11/2026; escalones corridos el 18/11): Mac local, PostgreSQL 17 + pgvector en Docker (puerto 5433), un proceso de `uvicorn`, `LLM_PROVIDER=rules`, `EMBEDDINGS_ENABLED=false`, `GENERATION_MAX_WORKERS` por defecto, Locust 2.47.0 desde una sola IP; el límite por IP de QA-16 todavía no está en `main`. Solo rutas reales (`GET /api/v1/courses`, `GET /api/v1/documents/search`, `POST /api/v1/generation-requests`, `GET /api/v1/generation-requests/[id]`); se excluyen «[preparación]» (alta de cada usuario) y «[pedido completo]» (acotado por la consulta cada 1 s).
  - 10 usuarios: 5,2 peticiones/s; p95 más alto 66 ms (`POST /generation-requests`); máximo 101 ms; 0 % de errores (0 de 930); CPU de la BD 12,9 % como máximo.
  - 25 usuarios: 13,0 peticiones/s; p95 más alto 59 ms; máximo 74 ms; 0 % de errores (0 de 2330); CPU de la BD 9,0 %.
  - 50 usuarios: 25,8 peticiones/s; p95 más alto 53 ms; máximo 96 ms; 0 % de errores (0 de 4621); CPU de la BD 11,8 %.
  - 100 usuarios: 50,2 peticiones/s; p95 más alto 77 ms; máximo 796 ms (un `POST` aislado; p99 150 ms); 0 % de errores (0 de 9028); CPU de la BD 14,5 %. Pedido de punta a punta («[pedido completo]», p50, fuera de la capacidad): 1,1 s con 10, 25 y 50 usuarios y 1,0 s con 100, casi todo el intervalo de consulta.
  - Capacidad: ≥ 100 usuarios (no se alcanzó el límite; el punto de quiebre lo busca QA-18).
  - ISO/IEC 25023: PCa-2-G = ≥ 100 usuarios con p95 < 1 s y errores < 1 %; PTb-1-G = 17,8 ms de media en las rutas reales con 100 usuarios (21,2 / 18,2 / 17,0 ms con 10 / 25 / 50); PTb-5-G = 5,2 / 13,0 / 25,8 / 50,2 peticiones/s con 10 / 25 / 50 / 100 usuarios.
  - Límites: un solo equipo local (Locust y el backend en la misma máquina); generador por reglas, sin Gemini; una sola IP, por eso se midió antes de QA-16; la fila de punta a punta está acotada por la consulta cada 1 s.
  - Evidencia: [docs/evidence/QA-17/](../../docs/evidence/QA-17/README.md) (informes HTML y CSV de Locust por escalón, `docker stats` cada 30 s y el resumen con los cálculos).
- [ ] QA-18 [BE] **Juan.** Punto de quiebre con JMeter (`backend/performance/jmeter/stress.jmx`), escalones de 50 a 800 hilos, antes y después de QA-16. — Criterio: punto de quiebre = primer escalón con errores > 5 % o p95 > 5 s; peticiones por segundo del último escalón que cumple; recuperación de `/health` (200 en < 1 s) en menos de 10 s. — Plazo: sáb 21/11 20:00. — Evidencia: `docs/evidence/QA-18/`.
- [ ] QA-19 [BE] **Juan.** Informe final con medidas ISO/IEC 25023 en `report.md` (QA-01 a QA-19). — Criterio: tabla con medida, fórmula, valor medido, meta, cumplimiento y evidencia; sin resultados inventados; lo no medido queda como pendiente. — Plazo: dom 22/11 12:00.

> **Nota de plazos:** Fecha límite de PR: sábado 21/11/2026 a las 20:00.
