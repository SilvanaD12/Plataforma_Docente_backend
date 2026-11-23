# Tareas del plan de generación

[Ficha](spec.md) · [Plan](plan.md) · [Research](research.md) · [Modelo de datos](data-model.md) · [Contrato](contracts/generation-plans.openapi.yaml) · [Validación](quickstart.md)

Las tareas son de Yan salvo que indiquen otro responsable.
- **Rutas:** las rutas `backend/…` son del repositorio `Plataforma_Docente_backend`, y las rutas `src/…`, del repositorio `Plataforma_Docente_frontend`.
- **Fichas:** cada tarea indica su ficha (`GEN-P1`, `GEN-P2` o `GEN-P3`) y las pruebas que se escriben primero.
- **Reglas de siempre:** se prueba sin proveedores reales (Gemini falso con transporte HTTP falso) y con `LLM_PROVIDER=rules`.

Dependencias externas, cada una con lo que se usa mientras no esté:

| Ficha | Responsable | Qué entrega | Mientras no esté |
| --- | --- | --- | --- |
| MAT-P2 | Sergio | `ReferentsPort.referents_for(teacher_id, unit_id, topic)` → `[{name, description, fragmentIds}]` | Adaptador que devuelve `[]`. |
| CUR-P3 | Silvana | `SessionTypologyPort.previous_typologies(...)` (las últimas 3 del curso, la más reciente primero) y `record_typology(...)`. Una sesión es un plan que pasa a `used`. | Adaptador vacío: `previous_typologies` devuelve `[]` y `record_typology` no hace nada. |
| CUR-P2 | Silvana | Catálogo configurable con los campos de [research R6](research.md#r6-catálogo-configurable-cur-p2), por `ResourceCatalogPort`. Por cada tipo nuevo: `stage`, `description`, `lengthHint` opcional, `modalities`, `format: text`, `structure: none` y `active`. | Adaptador sobre `domain/generation/resource_catalog.py`. |
| REV-P3 | Juan | Indicador de duplicación por similitud de embeddings, con su umbral τ. | Similitud léxica de `most_similar` para la medición provisional. |
| QA-16 | Sergio | `POST /generation-plans` en las rutas costosas con límite por IP. | — |

## 1. Dominio del plan (GEN-P1)

- [x] T001 [BE] [GEN-P1] `domain/generation/generation_plan.py`: `GenerationPlan`, `PlanInputs`, `PlanItem`, `PlanEvidence`, `Referent`, `PlanStatus` y las transiciones de [data-model](data-model.md#transiciones-de-estado).
  - Pruebas en `tests/unit/test_generation_plan.py`, una por cada transición permitida (`draft→approved→used`, y `approved` que vuelve a `draft` al editar). Cada transición no permitida falla con su código (`PLAN_ALREADY_USED`, `PLAN_VERSION_CONFLICT`).
  - Hecho en el PR del backend (enlace pendiente). Pruebas en `tests/unit/test_generation_plan.py`.
- [x] T002 [BE] [GEN-P1] **Depende de T001.** Validación (`validate_plan`) con los 10 códigos de [data-model](data-model.md#reglas-de-validación) y cálculo de `doesNotCover`.
  - Normalización de conceptos con la de QA-05 (`topic_coverage.normalize`).
  - Pruebas en `tests/unit/test_generation_plan_validation.py`, una por código; además: un concepto con otra forma («Control de flujo» frente a «control  de flújo») cuenta como el mismo, y `doesNotCover` cambia al editar los `covers` de otro ítem.
  - Hecho en el PR del backend (enlace pendiente). La validación está en `domain/generation/plan_validation.py`; la normalización es `topic_coverage.concept_key` (la de QA-05 sin palabras vacías). Las pruebas quedaron en `tests/unit/test_generation_plan.py`, junto con las de T001.
- [x] T003 [BE] [GEN-P1] **Depende de T002.** Reparto de los `covers` de un ítem en `quantity` bloques consecutivos (para GEN-P2). Pruebas: reparto estable y error con menos conceptos que la cantidad.
  - Hecho en el PR del backend (enlace pendiente). `plan_validation.split_covers`; pruebas en `tests/unit/test_generation_plan.py`.

## 2. Puertos y adaptadores (GEN-P1)

- [x] T004 [BE] [GEN-P1] Puertos `ReferentsPort` (MAT-P2), `SessionTypologyPort` (CUR-P3) y `ResourceCatalogPort` (CUR-P2) en `application/ports/outbound/`, con adaptadores provisionales, y el método `existing_fragment_ids(teacher_id, unit_id, fragment_ids)` de `EvidenceProviderPort` (con MAT-01) sobre el repositorio de fragmentos.
  - Prueba de integración de `existing_fragment_ids`: un fragmento de otro docente o de otra unidad no cuenta como existente; al volver a procesar un documento, sus ids anteriores dejan de existir.
  - Prueba de arquitectura: Generación no importa los servicios de Material ni de Cursos.
  - Pruebas de los adaptadores provisionales (lista vacía; el catálogo actual con su descripción y sin `structure` para los tipos de texto).
  - Hecho en el PR del backend (enlace pendiente). `existing_fragment_ids` se probó en `tests/integration/test_generation_evidence_isolation.py`; los adaptadores, en `tests/unit/test_plan_context_adapters.py`; la regla de arquitectura de GEN-01 ahora incluye los puertos del plan. `CatalogEntry` todavía no tiene `structure`: llega con T015 y CUR-P2.
- [x] T005 [BE] [GEN-P1] **Depende de T001.** Repositorio `GenerationPlanRepositoryPort` con SQLAlchemy y migración de dbmate de `gen_generation_plans` ([data-model](data-model.md#persistencia)): `UNIQUE (teacher_id, idempotency_key)`, guardado condicional por versión, y borrado con el curso (como T047 de 002).
  - Pruebas de integración en SQLite y PostgreSQL: dos `PUT` simultáneos con la misma versión (gana uno y el otro recibe `PLAN_VERSION_CONFLICT`); dos `POST` con la misma clave (crean un solo plan); otro docente no lo lee.
  - Hecho en el PR del backend (enlace pendiente). Migración `20261122000001_generation_plans.sql`. Pruebas en `tests/integration/test_generation_plan_repository.py` (SQLite) y el borrado con el curso en `test_course_generation_requests_deletion.py`. Los dos `PUT` simultáneos se prueban en `tests/unit/test_generation_plan_use_cases.py`. En PostgreSQL, las e2e del plan (con el borrado del curso) pasaron con PostgreSQL 17 local y corren en la CI.

## 3. Planificadores (GEN-P1)

- [x] T006 [BE] [GEN-P1] **Depende de T002.** Planificador por reglas (`application/services/generation/rule_based_planner.py`, [research R4](research.md#r4-planificación-con-reglas-y-con-gemini)).
  - Pruebas en `tests/unit/test_rule_based_planner.py` con el corpus de T067:
    - el plan es válido y determinista (dos corridas iguales);
    - todo ítem cita evidencia y no hay conceptos repetidos;
    - con cantidad `null`, el planificador elige según los conceptos;
    - con pocos conceptos, baja la cantidad o informa `NOT_ENOUGH_CONCEPTS`.
  - Hecho en el PR del backend (enlace pendiente). El planificador por reglas quedó en `application/services/generation/plan_drafting.py` (`RuleBasedPlanner`) y sus pruebas, en `tests/unit/test_plan_drafting.py`.
- [x] T007 [BE] [GEN-P1] **Depende de T006.** Planificador con Gemini: un solo `generate_plan`, con esquema de respuesta propio (como T073), el límite de 60 s de QA-06 y el respaldo por reglas con `fallbackReason`.
  - Pruebas con transporte HTTP falso:
    - el esquema exige `items`, `covers` y `fragmentos`;
    - una respuesta válida da un plan con `usesAi`;
    - una respuesta que gotea más del límite, un JSON inválido o un concepto en dos ítems pasan al respaldo con su motivo genérico;
    - el prompt no pide mencionar la metodología 5E.
  - Hecho en el PR del backend (enlace pendiente). `GeminiLanguageModel.draft_plan` y `GenerationPlanner` en `plan_drafting.py`; pruebas en `tests/unit/test_plan_drafting.py`.

## 4. Casos de uso y router (GEN-P1)

- [x] T008 [BE] [GEN-P1] **Depende de T004 a T007.** `CreateGenerationPlan`: idempotencia, unidad del docente, material procesado, recuperación una sola vez, comprobación del tema de QA-05 (con `422 INSUFFICIENT_EVIDENCE`), referentes, contexto de sesión, aviso `SAME_TYPOLOGY_AS_LAST_SESSION`, planificador y validación.
  - Pruebas unitarias con dobles de los puertos (PLAN-C1 a PLAN-C3).
  - Hecho en el PR del backend (enlace pendiente). Pruebas en `tests/unit/test_generation_plan_use_cases.py`.
- [x] T009 [BE] [GEN-P1] **Depende de T008.** `GetGenerationPlan`, `ListGenerationPlans`, `UpdateGenerationPlan` y `ApproveGenerationPlan`. Pruebas de PLAN-C4, PLAN-C5 y PLAN-C7.
  - Hecho en el PR del backend (enlace pendiente). `GetGenerationPlan` incluye el listado. Pruebas en `tests/unit/test_generation_plan_use_cases.py`.
- [x] T010 [BE] [GEN-P1] **Depende de T009.** Router `routers/generation_plans.py` y esquemas `schemas/generation_plans.py` según el [contrato](contracts/generation-plans.openapi.yaml); exportar OpenAPI.
  - Pruebas e2e en `tests/e2e/test_generation_plans_api.py`: V1, V2 y V4 a V8 de [quickstart](quickstart.md).
  - Pruebas de mensajes: ningún mensaje al docente dice «5E» (PLAN-R8).
  - Hecho en el PR del backend (enlace pendiente). E2E de V1, V2, V4, V5 y V8 (V6, V7 y la generación de V8 son de GEN-P2). Conformidad con el contrato en `tests/integration/test_generation_plans_contract.py`; el contrato documenta ahora `503 EVIDENCE_UNAVAILABLE` en la creación. La creación del plan cuenta para el límite por IP de QA-16.

## 5. Generación desde el plan (GEN-P2)

- [ ] T011 [BE] [GEN-P2] **Depende de T010.** `StartGenerationRequest` acepta `{planId, planVersion}` ([research R2](research.md#r2-el-plan-es-obligatorio-compatibilidad-del-pedido-sin-plan)).
  - Exige un plan aprobado y en esa versión, y lo marca `used`.
  - El modo sale del plan, y el pedido guarda `plan_id` y `plan_version`.
  - Con el cuerpo anterior, crea un plan implícito; con `GENERATION_REQUIRE_PLAN=true`, responde `422 PLAN_REQUIRED`.
  - Al usar el plan, llama a `record_typology`.
  - Antes de crear el pedido, comprueba la [evidencia vigente](data-model.md#evidencia-vigente): si falta algún fragmento del plan, `409 PLAN_EVIDENCE_STALE` con `StaleDocument` por documento, sin crear el pedido ni cambiar el plan.
  - Pruebas: V6, V7 (a, b) y V12 de [quickstart](quickstart.md); `PLAN_ALREADY_USED` y `PLAN_NOT_APPROVED`; idempotencia con plan; un documento borrado y otro procesado de nuevo después de aprobar dan `PLAN_EVIDENCE_STALE` con los dos documentos y sus fragmentos.
- [ ] T012 [BE] [GEN-P2] **Depende de T003 y T011.** `RunGenerationRequest` desde el plan ([research R5](research.md#r5-generación-desde-el-plan-gen-p2)).
  - Un paso por ítem, la evidencia del plan, y cada recurso redactado por separado con su bloque de conceptos, el propósito, los conceptos ajenos y el resumen de lo ya cubierto.
  - Se quita «devuelve menos recursos» para los ítems del plan.
  - Pruebas en `tests/unit/test_planned_generation.py`:
    - el prompt de cada recurso trae su bloque y el resumen de los anteriores;
    - un recurso solo cita fragmentos del plan;
    - con reglas, cada recurso usa las oraciones de sus conceptos.
- [ ] T013 [BE] [GEN-P2] **Depende de T012.** Comprobación de cobertura y rechazo `kind: plan`, con un reintento con la indicación del problema; el filtro de repetición actual sigue activo y su reintento nombra los conceptos ajenos. `RejectionKind` suma `plan` en el contrato y en OpenAPI.
  - Pruebas: con un Gemini falso que desarrolla un concepto ajeno, se rechaza con `kind: plan` y motivo; un recurso que no menciona ninguno de sus conceptos se rechaza igual; un recurso correcto pasa sin reintento.
- [ ] T014 [BE] [GEN-P2] **Depende de T012.** Regeneración desde Revisión con el ítem del plan (`params.planId`, `params.planItemPosition`): lee el plan sin escribirlo, así que un plan `used` no responde `PLAN_ALREADY_USED`; comprueba la evidencia vigente de los fragmentos del ítem. Un recurso sin plan se regenera como hoy.
  - Pruebas: V7 (c) de [quickstart](quickstart.md); regenerar con el plan `used` no cambia su `status`, `version` ni `usedByRequestId`; con un fragmento del ítem borrado, la regeneración falla con `PLAN_EVIDENCE_STALE`, Revisión responde 409 con ese código y el recurso se conserva; un recurso anterior sin plan.
- [ ] T015 [BE] [GEN-P2] **Depende de T004 y CUR-P2.** Tipos de texto nuevos del catálogo ([research R6](research.md#r6-catálogo-configurable-cur-p2)): prompt genérico con la `description`, redactor genérico por reglas y verificación de citas y párrafos como `explicacion`.
  - Pruebas: un tipo nuevo de prueba en el catálogo se planifica, se genera con reglas y con Gemini falso, y Revisión lo muestra con su etiqueta.

## 6. Frontend (GEN-P3)

- [ ] T016 [FE] [GEN-P3] **Depende de T010.** `src/features/generation`: «Planificar» crea el plan desde el formulario actual (y desde el borrador del chat de HU-038).
  - La pantalla del plan muestra:
    - los ítems por etapa, con el nombre de la etapa, tipo, cantidad y propósito;
    - los conceptos propios editables y los conceptos de otros ítems de solo lectura;
    - los fragmentos con su texto;
    - los referentes, las tipologías anteriores y el aviso de tipología repetida;
    - el aviso de respaldo por reglas.
  - Pruebas de componentes: muestra el plan y sus problemas junto a cada ítem; «Generar» solo con el plan aprobado; ningún texto dice «5E».
- [ ] T017 [FE] [GEN-P3] **Depende de T016.** Edición y aprobación: mover conceptos entre ítems, cambiar el propósito, la cantidad y los fragmentos, agregar o quitar ítems, guardar con `expectedVersion`, aprobar y generar con `{planId, planVersion}`.
  - Recuperar el último plan de la unidad al recargar.
  - Manejar `PLAN_VERSION_CONFLICT` (ofrecer recargar) y `PLAN_INVALID`.
  - Pruebas: PLAN-C12 a PLAN-C14 con el API simulado.
- [ ] T018 [E2E] [GEN-P3] **Depende de T017.** Recorrido V11 de [quickstart](quickstart.md) con Playwright y el backend local con reglas; captura de cada paso en `docs/evidence/GEN-P3/` del frontend.

## 7. Medición y cierre

- [ ] T019 [E2E] [GEN-P2] **Depende de T012, T013 y REV-P3.** Script `backend/evaluation/measure_duplication.py` (`--mode baseline|plan`, `--runs`, `--quantity`, `--out`; comandos en [plan](plan.md#medición-de-p4)) y medición de P4 ([research R7](research.md#r7-medición-de-la-duplicación-p4)), V10 de [quickstart](quickstart.md). Pruebas del script con backend falso: la tasa de duplicación con pares conocidos y que no escribe tokens ni contraseñas.
  - Línea base sin plan frente a plan aprobado, con reglas y con Gemini, 3 corridas cada uno.
  - Resultados en `docs/evidence/GEN-P4/`.
  - Meta: duplicación ≤ 5 % y al menos 50 % menos que la línea base, sin perder recursos ni bajar la `faithfulness` de 0,90.
- [ ] T020 [E2E] [GEN-P1] **Depende de T010.** Tiempos de creación del plan, V9 de [quickstart](quickstart.md): p95 < 1 s con reglas y < 30 s con Gemini. Si no se cumple con Gemini, revisar la decisión síncrona de [research R1](research.md#r1-el-plan-como-recurso-propio-creado-de-forma-síncrona).
- [ ] T021 [BE] [GEN-P2] **Depende de T011 y T018.** Fin de la transición: `GENERATION_REQUIRE_PLAN=true` por defecto, y `collect_samples.py` y `measure_generation_load.py` crean el plan antes de generar. Pruebas de los dos scripts con backend falso.
- [ ] T022 Preguntas abiertas para el profesor: P8 (referentes en la recuperación) y P10 (editor WYSIWYG). Registrar sus respuestas en [spec](spec.md#preguntas-abiertas-para-el-profesor) y ajustar R10 y GEN-P3 si cambian el alcance.

## Dependencias y trabajo en paralelo

- **Primero:** T001 a T003, en ese orden. T004 y T005 pueden ir en paralelo con T002 y T003.
- **Backend:** T006 → T007 → T008 → T009 → T010. El frontend (T016 y T017) puede empezar con el [contrato](contracts/generation-plans.openapi.yaml) y un API simulado antes de T010.
- **Generación:** T011 → T012 → T013 y T014. T015 espera el catálogo de CUR-P2 (el adaptador provisional basta para probar).
- **Cierre:** T019 necesita REV-P3 (o la medición provisional léxica, registrada como tal). T021 va al final, cuando GEN-P3 ya esté integrado.
