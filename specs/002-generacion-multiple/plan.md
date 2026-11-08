# Plan de Generación individual y secuencia 5E

**Rama** `feat/generacion` (feature `002-generacion-multiple`) · **Fecha** 2026-11-08 · **Ficha** [GEN-01 · HU-003](spec.md)

[Research](research.md) · [Modelo de datos](data-model.md) · [Contrato OpenAPI](contracts/generation-requests.openapi.yaml) · [Puertos](contracts/ports.md) · [Validación](quickstart.md)

## Resumen

Se pasa la generación síncrona actual (`POST /api/v1/generations`) a un **pedido persistido que se ejecuta en segundo plano**. El pedido tiene clave de idempotencia por docente, estado consultable por paso y se marca `interrupted` cuando el servidor se reinicia. El modo individual es una secuencia de un paso, con el mismo mecanismo.

Se reutilizan el dominio de generación (orden 5E, control de repetición, verificación de anclaje, fiabilidad de distractores, catálogo y formatos) y los generadores (Gemini y reglas). Se divide `GenerationService` en casos de uso que dependen de tres puertos hacia otros módulos: pertenencia de unidad (Cuentas), evidencia (Material) y huella (Revisión). También se corrige la copia histórica para que incluya los fragmentos de pasos guiados, predicciones y criterios. Cada recurso llega a Revisión con huella, resultado de verificación (`vigente` o `pendiente`) y `VERIFICATION_RULE_VERSION`.

## Contexto técnico

| Campo | Valor |
| --- | --- |
| Lenguaje | Python 3.11+ (la CI usa 3.12). Frontend en React 18, TypeScript y Vite, sobre la base de CC-01 ya integrada en `main` ([R10](research.md#r10-frontend)). |
| Dependencias principales | FastAPI, Pydantic 2, SQLAlchemy 2, httpx y `concurrent.futures` de la biblioteca estándar. No se agregan dependencias. |
| Almacenamiento | PostgreSQL con pgvector en despliegue y SQLite en desarrollo y pruebas. Tablas nuevas `gen_generation_requests` y `gen_generation_steps`; los recursos siguen en `ep002_recursos`. |
| Pruebas | pytest (unitarias, integración, e2e con servidor real y arquitectura) en el backend. Vitest y ESLint en el frontend. |
| Plataforma | Servidor Linux con uvicorn, sin cola externa. |
| Tipo de proyecto | Servicio web con un repositorio de frontend aparte. |
| Objetivos de rendimiento | `POST` responde en menos de 500 ms (validación y persistencia, sin modelo). Una secuencia de 8 × 5 termina en menos de 10 min p95 con Gemini ([R4](research.md#r4-límites-de-carga)). |
| Restricciones | 2 hilos por proceso, 2 pedidos activos por docente, 15 min por pedido y 3 llamadas al modelo por paso. |
| Escala | Uso de curso: decenas de docentes y 40 recursos por pedido como máximo. |

No quedan puntos `NEEDS CLARIFICATION`. Las decisiones abiertas de la spec (contrato, alcance de la clave, almacenamiento del estado, límites, edición durante una regeneración y procedencia) se resuelven en [research.md](research.md). Quedan **tres acuerdos con otros módulos**, que no bloquean el diseño pero sí algunas tareas:

1. REV-01 entrega `domain/review/content_fingerprint.py`, el campo `version` del recurso y `discard_if_version`.
2. MAT-01 hace que el recuperador informe `retrieval_mode` y que la búsqueda vectorial filtre por docente.
3. CC-01 confirma la firma de `UnitMembershipPort`.

## Revisión de la Constitución

| Principio | Antes del diseño | Después del diseño |
| --- | --- | --- |
| I. Arquitectura hexagonal | ✅ El servicio actual ya usa puertos para el generador y la evidencia, pero consulta repositorios de Cuentas y Material directamente. | ✅ Hay cinco puertos nuevos o ampliados ([ports.md](contracts/ports.md)). Los casos de uso no importan servicios de otros módulos, y `test_layer_dependencies.py` lo verifica. |
| II. Contrato OpenAPI | ⚠️ `POST /generations` es síncrono y no documenta la idempotencia. | ✅ El contrato de diseño está en `contracts/` y se exporta con `scripts/export_openapi.py`. Antes de abrir cada PR se exporta y se revisa el diff de `docs/api/openapi.json` ([quickstart](quickstart.md#pruebas-automáticas)). La CI actual no hace esa comparación; agregarla se propone como tarea coordinada con CC-01, porque el workflow es compartido. La ruta antigua queda `deprecated` hasta migrar los scripts y se elimina en la entrega. |
| III. Evidencia y aprobación | ⚠️ La copia histórica omite los fragmentos de la estructura, y el modo demostración entrega recursos sin verificar. | ✅ `referenced_fragment_ids` cubre todos los orígenes. Si falta un fragmento, el recurso queda `pendiente`. Se retira el modo demostración del flujo. La huella y `VERIFICATION_RULE_VERSION` se guardan en cada recurso. |
| IV. Aislamiento por docente y unidad | ⚠️ La recuperación híbrida puede leer fragmentos sin filtrar por docente. | ✅ El puerto de evidencia exige `teacher_id`, la clave es única por docente y los pedidos ajenos responden 404. El riesgo de la búsqueda vectorial se escala a MAT-01, con una prueba de integración de dos docentes (V10). |
| V. Pruebas y entrega por módulo | ✅ | ✅ La validación cubre GEN-C1 a GEN-C9 con pruebas automáticas ([quickstart.md](quickstart.md)). El trabajo se hace en `feat/generacion` con PR a `main`. |

No hay infracciones que justificar.

## Reutilización del código existente

El detalle y los motivos de cada archivo están en [research R1](research.md#r1-evaluación-del-código-existente).

| Archivo | Decisión |
| --- | --- |
| `generation_service.py` | Se adapta y se divide en casos de uso. Se corrige la evidencia y se retira la demostración. |
| `domain/generation/sequence.py` | Se conserva y se le agrega `plan_steps`. |
| `prompt_drafting.py` | Se conserva y se adapta su entrada a los DTO de los puertos. |
| `rule_based_generator.py` | Se conserva. |
| `gemini_language_model.py` | Se conserva. |
| `resource_catalog.py` | Se conserva. |
| `resource_formats.py` | Se conserva. Un cambio en `MIN_ITEMS` sube `VERIFICATION_RULE_VERSION`. |
| `grounding.py` | Se conserva. |
| `distractor_reliability.py` | Se conserva. |
| `routers/generations.py` | Se reemplaza por `routers/generation_requests.py`. `/generator` se mantiene. |
| `tests/e2e/test_sequence_api.py` | Se adapta al flujo `202` con consulta periódica y se amplía con los casos de la spec. |

**Ajuste conocido.** `_save_for_review` y `step_chunks` solo reúnen los ids de `citations` y `options`. Se reemplazan por `domain/generation/evidence.referenced_fragment_ids`, que agrega `structure.guidedSteps`, `structure.predictions` y `structure.criteria` ([R6](research.md#r6-copia-histórica-de-la-evidencia)).

## Estructura del proyecto

### Documentación

```text
specs/002-generacion-multiple/
├── spec.md
├── plan.md                 # este archivo
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── generation-requests.openapi.yaml
│   └── ports.md
└── tasks.md                # lo genera /speckit-tasks
```

### Código fuente

```text
backend/src/platform5e/
├── domain/generation/
│   ├── sequence.py                    # + plan_steps
│   ├── evidence.py                    # nuevo: referenced_fragment_ids, build_snapshot
│   ├── verification.py                # nuevo: VERIFICATION_RULE_VERSION, verification_result
│   ├── generation_request.py          # nuevo: GenerationRequest, GenerationStep, estados y transiciones
│   ├── grounding.py, distractor_reliability.py, resource_catalog.py, resource_formats.py   # sin cambios
│   └── errors.py                      # + códigos nuevos
├── application/
│   ├── ports/outbound/
│   │   ├── unit_membership_port.py            # nuevo (CC-01)
│   │   ├── evidence_provider_port.py          # nuevo (MAT-01), sustituye el uso directo de EvidenceRetrieverPort
│   │   ├── content_fingerprint_port.py        # nuevo (REV-01)
│   │   ├── generation_request_repository_port.py   # nuevo, sustituye generation_repository_port.py
│   │   ├── generation_job_runner_port.py      # nuevo
│   │   └── resource_repository_port.py        # + discard_if_version
│   ├── services/generation/
│   │   ├── prompt_drafting.py, rule_based_generator.py
│   │   └── step_drafting.py           # nuevo: _draft_resources, _filter_repeated y _build_resource_dict extraídos
│   └── use_cases/generation/
│       ├── start_generation_request.py
│       ├── run_generation_request.py
│       ├── get_generation_request.py
│       └── regenerate_resource.py
├── infrastructure/
│   ├── http/routers/generation_requests.py    # nuevo; generations.py queda deprecado y se elimina
│   ├── http/schemas/generation_requests.py    # nuevo
│   ├── adapters/                              # nuevo: membership, material_evidence, review_fingerprint
│   ├── jobs/thread_pool_generation_runner.py  # nuevo
│   └── persistence/repositories/sqlalchemy_generation_request_repository.py
└── main.py                    # inyección, lifespan del ejecutor y barrido de arranque

backend/database/migrations/2026111xxxxxxx_generation_requests.sql
backend/tests/{unit,integration,e2e,architecture}/   # ver quickstart.md

Plataforma_Docente_frontend/src/features/generation/
├── api/            # generationApi.ts sobre src/shared/api/httpClient.ts
├── model/          # tipos del pedido escritos a mano según docs/api/openapi.json
├── hooks/          # useStartGeneration (clave en sessionStorage) y useGenerationRequest (consulta periódica)
├── components/     # selector de modo, lista de pasos 5E, rechazos y avisos de respaldo
└── pages/GenerationPage.tsx  # ya existe como marcador; recibe course, unit y token del contexto de UnitLayout
```

**Decisión de estructura.** Se mantiene el hexágono existente. Los casos de uso de Generación pasan a `application/use_cases/generation/`, como ya están `catalog`, `export` y `media`. Los adaptadores hacia otros módulos se agrupan en `infrastructure/adapters/` para que cada responsable revise el suyo.

## Orden de entrega

1. **Dominio:** `evidence.py`, con la corrección de la copia y pruebas; `verification.py`; `generation_request.py` y `plan_steps`. Ninguno depende de otro módulo.
2. **Puertos y adaptadores:** el repositorio de pedidos con su migración y el ejecutor por hilos con el barrido de arranque. Después, los adaptadores de pertenencia y evidencia.
3. **Casos de uso** `Start`, `Run` y `Get`, y el router nuevo. Exportar OpenAPI y adaptar `test_sequence_api.py`.
4. **Huella y regeneración,** cuando REV-01 entregue `content_fingerprint.py`, `version` y `discard_if_version`.
5. **Frontend** `src/features/generation`, desde `main` del frontend, que ya tiene la base de CC-01 y la ruta `/courses/:courseId/units/:unitId/generation`. Antes, acordar con CC-01 la ampliación de `httpClient.ts` ([R10](research.md#r10-frontend)).
6. **Validación de carga** (V11) y retirada de `POST /generations` cuando migre `evaluation/collect_samples.py`.

## Seguimiento de complejidad

No aplica: no hay infracciones de la Constitución.
