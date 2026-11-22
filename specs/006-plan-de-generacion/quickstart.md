# Guía de validación del plan de generación

[Ficha](spec.md) · [Plan](plan.md) · [Research](research.md) · [Modelo de datos](data-model.md) · [Contrato](contracts/generation-plans.openapi.yaml) · [Tareas](tasks.md)

## Preparación

- **Base de datos:** el backend local de [005 QA-17](../005-atributos-calidad/plan.md#qa-17--concurrencia-y-capacidad-con-locust), con PostgreSQL en Docker, o SQLite.
- **Variables:** `LLM_PROVIDER=rules`, `EMBEDDINGS_ENABLED=false` y `GENERATION_REQUIRE_PLAN=false`. Gemini solo en V3, V9 y V10, con la clave local y nunca en Render.
- **Datos:** un docente con una unidad de redes y el corpus de T067 procesado (`backend/evaluation/corpus_t067`), como en `collect_samples.py`.
- **Interfaz:** frontend en `http://localhost:5173` para V11.

## Pruebas automáticas

```bash
cd backend
.venv/bin/python -m pytest tests/unit/test_generation_plan*.py tests/unit/test_planned_generation.py \
  tests/e2e/test_generation_plans_api.py -q
.venv/bin/python -m pytest tests/unit tests/architecture tests/integration tests/e2e -q \
  --cov=platform5e.domain --cov=platform5e.application --cov-fail-under=80
python scripts/export_openapi.py && git diff --exit-code -- ../docs/api/openapi.json
```

## Escenarios

| ID | Caso | Pasos | Resultado esperado |
| --- | --- | --- | --- |
| V1 | PLAN-C1, PLAN-C2 | `POST /generation-plans` con `pregunta_detonante`, `explicacion` (cantidad `null`) e `item_opcion_multiple` × 2, con `LLM_PROVIDER=rules`. Repetirlo con la misma clave. | `201` con `status: draft`, `version: 1`, ítems en orden de etapa, cada uno con `covers` y al menos un `fragmentId` de `evidence.fragments`, y `doesNotCover` igual a los `covers` de los demás. `generator.usesAi: false`. Con la misma clave, `200` y el mismo plan. Dos corridas con la misma evidencia dan el mismo plan. |
| V2 | PLAN-C3 | Pedir un plan con las indicaciones de C-06 («tablas y llaves primarias en un modelo relacional») en la unidad de redes. | `422 INSUFFICIENT_EVIDENCE` con «El material de la unidad no trata «llaves primarias, modelo relacional»…». No se crea ningún plan. |
| V3 | PLAN-C2 | Con Gemini: (a) respuesta válida; (b) proveedor falso que tarda más de 60 s; (c) un plan con un concepto en dos ítems. | (a) `generator.usesAi: true` y plan válido. (b) y (c) Plan por reglas con `fallback: true` y `fallbackReason` genérico. (b) responde en menos de 60 s más la recuperación. |
| V4 | PLAN-C4 | `PUT` con `expectedVersion: 1`: (a) mover un concepto de un ítem a otro; (b) dejar un concepto repetido en dos ítems y un ítem sin fragmentos. | (a) `version: 2`, `status: draft` y `doesNotCover` de los dos ítems actualizado. (b) Se guarda con `validation.valid: false` y los problemas `CONCEPT_OWNED_TWICE` e `ITEM_WITHOUT_EVIDENCE`, cada uno con su `itemPosition`. |
| V5 | PLAN-C5 | `approve` con una versión vieja; después con la actual sobre el plan inválido; después corregido. | `409 PLAN_VERSION_CONFLICT`; `422 PLAN_INVALID` con los problemas en `details`; `200` con `status: approved`. |
| V6 | PLAN-C6, PLAN-C8, PLAN-C9 | `POST /generation-requests` con `{planId, planVersion}`; repetir con el mismo plan y otra clave; pedir con un plan en borrador. | `202` con un paso por ítem; el plan queda `used` con `usedByRequestId`. Cada recurso cita solo fragmentos del plan, y su `params` trae `planId` y `planItemPosition`. Con el mismo plan y otra clave, `409 PLAN_ALREADY_USED`; en borrador, `422 PLAN_NOT_APPROVED`. Un recurso que desarrolla conceptos ajenos se rechaza con `kind: plan`. |
| V7 | PLAN-R5, PLAN-C10 | (a) Cuerpo anterior de GEN-01 sin plan; (b) lo mismo con `GENERATION_REQUIRE_PLAN=true`; (c) regenerar desde Revisión un recurso del plan. | (a) `202` y un plan implícito `origin: implicit`, `status: used`. (b) `422 PLAN_REQUIRED`. (c) La regeneración lee el ítem del recurso, no crea un plan nuevo y no escribe el plan: sin `PLAN_ALREADY_USED`, y el plan sigue con la misma `version`. |
| V8 | PLAN-C7, PLAN-R9 | Otro docente hace `GET`, `PUT`, `approve` y genera con el plan. | `404 PLAN_NOT_FOUND` en todo, igual que con un plan inexistente. |
| V12 | PLAN-C15, PLAN-C10 | Aprobar un plan; borrar un documento y volver a procesar otro de los que cita; pedir la generación. Después, con otro plan ya usado, borrar un documento de un recurso y regenerarlo desde Revisión. | Generación: `409 PLAN_EVIDENCE_STALE` con `details` por documento (`documentId`, `documentName`, `missingFragmentIds`); no se crea el pedido y el plan sigue `approved`. Regeneración: 409 con el mismo código; el recurso se conserva y el plan sigue `used` sin cambios. Con los documentos intactos, la regeneración del plan usado funciona (sin `PLAN_ALREADY_USED`). |

## V9 · Tiempos

Con 20 planes seguidos de la secuencia de V1, medir el tiempo de `POST /generation-plans`: p95 < 1 s con reglas, y p95 < 30 s con Gemini (nunca más de 60 s más la recuperación). Si el p95 con Gemini pasa de 30 s, revisar la decisión síncrona ([research R1](research.md#r1-el-plan-como-recurso-propio-creado-de-forma-síncrona)).

## V10 · Duplicación (P4)

[Research R7](research.md#r7-medición-de-la-duplicación-p4):
- **Corpus:** `corpus_t067`.
- **Pedido:** secuencia de 8 tipos de texto × 2 recursos; 3 corridas por generador (reglas y Gemini).
- **Comparación:** sin plan (línea base de `main` antes de GEN-P1) frente a plan aprobado sin cambios.

Registrar en `docs/evidence/GEN-P4/` la tasa de pares duplicados (indicador de REV-P3, τ = 0,85 mientras REV-P3 no fije otro), la similitud máxima media, los recursos entregados y la `faithfulness` media.

**Meta.** Duplicación ≤ 5 % y al menos 50 % menos que la línea base, sin perder recursos ni bajar la `faithfulness` de 0,90.

## V11 · Recorrido en interfaz (PLAN-C12 a PLAN-C14, PLAN-R8)

1. En Generación, elegir tipos (con cantidad opcional), escribir el tema y pulsar «Planificar».
2. Revisar los ítems por etapa (nombre de la etapa, tipo, cantidad, propósito, conceptos propios editables, conceptos de otros ítems de solo lectura, fragmentos con su texto) y los referentes y tipologías anteriores, si hay.
3. Mover un concepto a otro ítem y guardar; ver los problemas junto al ítem si el plan queda inválido; corregir y aprobar.
4. Recargar la página: el plan vuelve con los cambios guardados.
5. Pulsar «Generar» (solo se habilita con el plan aprobado) y seguir el pedido como hoy.
6. En ninguna pantalla aparece «5E», «modelo 5E» ni «metodología 5E»; sí los nombres de las etapas.
