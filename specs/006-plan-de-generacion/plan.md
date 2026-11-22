# Plan del plan de generación

**Rama** `docs/gen-p1-generation-plan-spec` (feature `006-plan-de-generacion`) · **Fecha** 2026-11-22 · **Ficha** [GEN-P1 · GEN-P2 · GEN-P3](spec.md)

[Research](research.md) · [Modelo de datos](data-model.md) · [Contrato OpenAPI](contracts/generation-plans.openapi.yaml) · [Validación](quickstart.md) · [Tareas](tasks.md)

## Resumen

Se agrega una etapa de planificación obligatoria antes de generar. El plan es un recurso propio (`generation-plans`), creado de forma síncrona con una llamada a la IA acotada a 60 s (QA-06) o con un planificador por reglas determinista. Congela la evidencia, reparte los conceptos del tema entre los ítems sin repetirlos y se valida en cada escritura. El docente lo revisa, lo edita y lo aprueba en la pestaña Generación.

El pedido de generación de GEN-01 parte del plan aprobado (`{planId, planVersion}`): un paso por ítem, la evidencia del plan, cada recurso redactado por separado con su bloque de conceptos y el resumen de lo ya cubierto, y una comprobación de cobertura que rechaza con `kind: plan` lo que se sale de su ítem. Mientras el frontend no use el plan, el cuerpo anterior crea un plan implícito; la regeneración desde Revisión lee el ítem del recurso sin escribir el plan. Si algún fragmento del plan ya no existe, generar o regenerar responde `409 PLAN_EVIDENCE_STALE`.

## Contexto técnico

| Campo | Valor |
| --- | --- |
| Lenguaje | Python 3.12 en el backend. React 18, TypeScript y Vite en el frontend (`src/features/generation`). |
| Dependencias principales | FastAPI, Pydantic 2, SQLAlchemy 2 y httpx, como GEN-01. No se agregan dependencias. |
| Almacenamiento | PostgreSQL con pgvector en despliegue y SQLite en desarrollo y pruebas. Tabla nueva `gen_generation_plans`; columnas nuevas `plan_id` y `plan_version` en `gen_generation_requests` y `plan_item_position` en `gen_generation_steps` (migración de dbmate). |
| Pruebas | pytest (unitarias, integración, e2e con servidor real y arquitectura) en el backend. Vitest y Playwright en el frontend. Sin proveedores reales: Gemini falso con transporte HTTP falso y `LLM_PROVIDER=rules`. |
| Objetivos de rendimiento | Crear un plan: p95 < 1 s con reglas y < 30 s con Gemini, nunca más de 60 s más la recuperación ([quickstart V9](quickstart.md#v9--tiempos)). Generar desde el plan no cambia los tiempos de GEN-01 más que en la comprobación de cobertura (léxica, milisegundos). |
| Restricciones | Hasta 8 tipos y de 1 a 5 recursos por tipo, como GEN-01. Una llamada a la IA por plan, con el límite de `LLM_CALL_DEADLINE_SECONDS`. `POST /generation-plans` entra en las rutas costosas de QA-16. |

Acuerdos con otros módulos (no bloquean el diseño, sí algunas tareas):

1. **MAT-P2 (Sergio):** `ReferentsPort` y, con MAT-01, `EvidenceProviderPort.existing_fragment_ids` para la evidencia vigente.
2. **CUR-P3 (Silvana):** `SessionTypologyPort`, y qué es una «sesión» del curso ([research R9](research.md#r9-contexto-de-sesión-cur-p3)).
3. **CUR-P2 (Silvana):** `ResourceCatalogPort` con los campos de [research R6](research.md#r6-catálogo-configurable-cur-p2).
4. **REV-P3 (Juan):** el indicador de duplicación por embeddings y su umbral τ para medir P4.

## Revisión de la Constitución

| Principio | Antes del diseño | Después del diseño |
| --- | --- | --- |
| I. Arquitectura hexagonal | ✅ GEN-01 ya usa puertos hacia Cuentas, Material y Revisión. | ✅ Cuatro puertos nuevos o ampliados (`ReferentsPort`, `SessionTypologyPort`, `ResourceCatalogPort`, `EvidenceProviderPort.existing_fragment_ids`) y un puerto de repositorio. El dominio del plan no depende de infraestructura; `test_layer_dependencies.py` lo verifica. |
| II. Contrato OpenAPI | ⚠️ No hay contrato del plan; los demás equipos programan contra él. | ✅ [Contrato de diseño](contracts/generation-plans.openapi.yaml) validado con `openapi-spec-validator`; se implementa y se exporta a `docs/api/openapi.json`, que la CI compara. |
| III. Evidencia y aprobación | ⚠️ Un plan podría citar fragmentos que el docente borró después. | ✅ Cada ítem cita la evidencia congelada; generar o regenerar con fragmentos que ya no existen responde `PLAN_EVIDENCE_STALE`. La verificación de anclaje de cada recurso no cambia. |
| IV. Aislamiento por docente y unidad | ✅ | ✅ Un plan ajeno responde igual que uno inexistente; `existing_fragment_ids` filtra por docente y unidad, con prueba de integración de dos docentes. |
| V. Pruebas y entrega por módulo | ✅ | ✅ Cada tarea indica sus pruebas ([tasks](tasks.md)); la validación cubre PLAN-C1 a PLAN-C15 ([quickstart](quickstart.md)). |

No hay infracciones que justificar.

## Reutilización del código existente

| Pieza | Dónde está | Uso en el plan |
| --- | --- | --- |
| Pedido en segundo plano, idempotencia y cupo | `application/use_cases/generation/` (GEN-01) | El pedido sigue igual; solo cambian su cuerpo y su origen de evidencia. La idempotencia del plan copia la regla de `payload_hash`. |
| Normalización y frases del tema | `domain/generation/topic_coverage.py` (QA-05) | Conceptos repetidos, conceptos candidatos y comprobación de cobertura. Comprobar el tema al crear el plan. |
| Límite por llamada y motivos públicos | `infrastructure/llm/call_deadline.py`, `application/services/provider_errors.py` (QA-06, PR #43) | La llamada que arma el plan y el `fallbackReason`. |
| Esquema de respuesta por tipo | `response_schema` de `gemini_language_model.py` (T073) | Esquema propio del plan. |
| Rechazos con motivo y `fallbackReason` | `prompt_drafting.py`, `step_drafting.py` (T073) | Nuevo `kind: plan`. |
| Control de repetición y `secuenciaPrevia` | `domain/generation/sequence.py`, `step_drafting.py` | Se mantienen; el resumen de lo ya cubierto agrega los conceptos de cada recurso. |
| Términos clave y BM25 | `domain/materials/text_analysis.py` | Planificador por reglas. |

## Estructura del proyecto

### Documentación

```
specs/006-plan-de-generacion/
├── spec.md, plan.md, research.md, data-model.md, quickstart.md, tasks.md
└── contracts/generation-plans.openapi.yaml
```

### Código fuente

Backend (`backend/src/platform5e/`):

| Capa | Archivo | Cambio |
| --- | --- | --- |
| Dominio | `domain/generation/generation_plan.py` | Nuevo: plan, ítems, estados y transiciones. |
| Dominio | `domain/generation/plan_validation.py` | Nuevo: `validate_plan`, `does_not_cover`, reparto de `covers` en bloques. |
| Aplicación · puertos | `application/ports/outbound/generation_plan_repository_port.py`, `referents_port.py`, `session_typology_port.py`, `resource_catalog_port.py` | Nuevos. |
| Aplicación · puertos | `application/ports/outbound/evidence_provider_port.py` | `existing_fragment_ids`. |
| Aplicación · servicios | `application/services/generation/rule_based_planner.py`, `plan_prompting.py` | Nuevos: planificador por reglas; prompt, esquema y conversión del plan de la IA. |
| Aplicación · servicios | `application/services/generation/prompt_drafting.py`, `step_drafting.py`, `rule_based_generator.py` | Ítem del plan en el prompt, comprobación de cobertura, prompt genérico y redactor genérico para tipos nuevos de texto. |
| Aplicación · casos de uso | `application/use_cases/generation/create_generation_plan.py`, `get_generation_plan.py`, `update_generation_plan.py`, `approve_generation_plan.py` | Nuevos. |
| Aplicación · casos de uso | `start_generation_request.py`, `run_generation_request.py`, `start_regeneration.py` | Plan aprobado, plan implícito, evidencia vigente, un paso por ítem, regeneración desde el ítem sin escribir el plan. |
| Infraestructura | `infrastructure/persistence/repositories/sqlalchemy_generation_plan_repository.py`, `backend/database/migrations/<fecha>_generation_plans.sql` | Nuevos. |
| Infraestructura | `infrastructure/llm/gemini_language_model.py` | `generate_plan` con su esquema y el límite de QA-06. |
| Infraestructura | `infrastructure/adapters/material_evidence_adapter.py` y adaptadores provisionales de referentes, sesiones y catálogo | `existing_fragment_ids` y adaptadores vacíos o sobre el catálogo actual. |
| Infraestructura | `infrastructure/adapters/generation_regeneration_adapter.py` | `PLAN_EVIDENCE_STALE` en la respuesta a Revisión. |
| Infraestructura · HTTP | `infrastructure/http/routers/generation_plans.py`, `schemas/generation_plans.py` | Nuevos. |
| Infraestructura · HTTP | `routers/generation_requests.py`, `schemas/generation_requests.py` | Cuerpo `{planId, planVersion}`, `kind: plan`, `PLAN_EVIDENCE_STALE`. |
| Configuración | `infrastructure/settings.py`, `main.py` | `GENERATION_REQUIRE_PLAN` y el cableado. |
| Contrato | `docs/api/openapi.json` | Exportado con `scripts/export_openapi.py`. |

Evaluación y scripts: `evaluation/collect_samples.py` y `scripts/measure_generation_load.py` crean el plan antes de generar (T021); `evaluation/measure_duplication.py`, nuevo, mide P4 (T019).

Frontend (`src/features/generation/`): `api/generationPlansApi.ts`, `model/generationPlan.ts` (tipos del contrato y reglas de edición), `hooks/useGenerationPlan.ts` (crear, recuperar, guardar con versión y aprobar) y `components/PlanReview.tsx` (ítems por etapa, conceptos, fragmentos, referentes, tipologías, problemas y avisos).

## Orden de entrega

1. **Dominio** (T001 a T003): plan, transiciones, validación y reparto de conceptos. No depende de otro módulo.
2. **Puertos y repositorio** (T004, T005): adaptadores provisionales para MAT-P2, CUR-P3 y CUR-P2; `existing_fragment_ids` con MAT-01; tabla y migración.
3. **Planificadores** (T006, T007): primero por reglas, después con Gemini y respaldo.
4. **Casos de uso y router** (T008 a T010): exportar OpenAPI. El frontend puede empezar con el contrato y un API simulado.
5. **Generación desde el plan** (T011 a T015): pedido con plan y evidencia vigente, pasos por ítem, cobertura y `kind: plan`, regeneración desde el ítem, tipos nuevos del catálogo.
6. **Frontend** (T016 a T018).
7. **Medición y cierre** (T019 a T022): tiempos, P4, fin de la transición y respuestas del profesor.

## Cómo probar en local

Backend con SQLite y el generador por reglas, sin ninguna clave de API. Desde `backend/`:

```bash
export DATABASE_URL="sqlite:///$(pwd)/plan-local.db"
export LLM_PROVIDER=rules EMBEDDINGS_ENABLED=false MEDIA_GENERATION_ENABLED=false TOPIC_SEARCH_ENABLED=false
export GENERATION_REQUIRE_PLAN=false
unset LLM_API_KEY
.venv/bin/python -m uvicorn platform5e.main:create_application --factory --app-dir src --host 127.0.0.1 --port 8000
```

Pruebas automáticas, el contrato y los escenarios de [quickstart](quickstart.md) (V1 a V8 y V12 con reglas; V3 con Gemini falso):

```bash
.venv/bin/python -m pytest tests/unit tests/architecture tests/integration tests/e2e -q \
  --cov=platform5e.domain --cov=platform5e.application --cov-fail-under=80
python scripts/export_openapi.py && git diff --exit-code -- ../docs/api/openapi.json
```

Con PostgreSQL en Docker, los mismos comandos de la pila local de [QA-17](../005-atributos-calidad/plan.md#qa-17--concurrencia-y-capacidad-con-locust), agregando `GENERATION_REQUIRE_PLAN=false`.

## Medición de P4

[Research R7](research.md#r7-medición-de-la-duplicación-p4) y [quickstart V10](quickstart.md#v10--duplicación-p4). El script `evaluation/measure_duplication.py` (T019):
- prepara la unidad con `corpus_t067`;
- pide 3 veces la secuencia de 8 tipos de texto × 2 recursos (con `--mode plan`, creando y aprobando el plan sin cambios);
- calcula la tasa de pares duplicados con el indicador de REV-P3 (o la similitud léxica, marcada como provisional);
- escribe los resultados en `docs/evidence/GEN-P4/`.

La línea base corre contra el backend de `main` antes de GEN-P1, en un árbol de trabajo aparte, sin un interruptor de medición en el código de producción. Desde la raíz del repositorio:

```bash
# Línea base: backend de main antes de GEN-P1, en otro árbol y otro puerto
git worktree add ../backend-baseline <commit de main antes de GEN-P1>
(cd ../backend-baseline/backend && LLM_PROVIDER=rules EMBEDDINGS_ENABLED=false DATABASE_URL=sqlite:///baseline.db \
  ../../Plataforma_Docente_backend/backend/.venv/bin/python -m uvicorn platform5e.main:create_application \
  --factory --app-dir src --port 8001) &

export EVAL_EMAIL=duplicacion.p4@correo.pe EVAL_PASSWORD=clave-segura-9
backend/.venv/bin/python backend/evaluation/measure_duplication.py --api http://127.0.0.1:8001 --mode baseline \
  --corpus backend/evaluation/corpus_t067 --runs 3 --quantity 2 --out docs/evidence/GEN-P4/rules-baseline.json
backend/.venv/bin/python backend/evaluation/measure_duplication.py --api http://127.0.0.1:8000 --mode plan \
  --corpus backend/evaluation/corpus_t067 --runs 3 --quantity 2 --out docs/evidence/GEN-P4/rules-plan.json
```

Con Gemini, lo mismo con la clave local en las dos terminales del backend (nunca en Render) y `--out …/gemini-*.json`, y la `faithfulness` con `run_ragas.py` sobre las muestras de cada modo. Meta: duplicación ≤ 5 % y al menos 50 % menos que la línea base, sin perder recursos ni bajar la `faithfulness` de 0,90.

## Seguimiento de complejidad

No aplica: no hay infracciones de la Constitución.
