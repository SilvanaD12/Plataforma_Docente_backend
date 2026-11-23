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
- [x] T002 [BE] [GEN-P1] **Depende de T001.** Validación (`validate_plan`) con los códigos de [data-model](data-model.md#reglas-de-validación) y cálculo de `doesNotCover`.
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

- [x] T023 [BE] [GEN-P1] **Depende de T008.** Referentes dentro de la evidencia del plan ([research R10](research.md#r10-referentes-mat-p2)): al crear el plan, `CreateGenerationPlan` deja en los `fragmentIds` de cada referente solo los ids de `evidence.fragments`, y conserva con `fragmentIds: []` el referente que se queda sin ninguno. No es un problema de validación.
  - Pruebas unitarias en `tests/unit/test_generation_plan_use_cases.py`, con un doble de `ReferentsPort`: un referente con un id de la evidencia y otro ajeno guarda solo el primero; un referente con solo ids ajenos se guarda con `fragmentIds: []`; el plan sigue válido y sin problemas nuevos; el orden de los referentes no cambia.
  - Prueba e2e en `tests/e2e/test_generation_plans_api.py`: el `GET` del plan devuelve los referentes ya filtrados.
  - Hecho en el PR del backend (#69). El filtro es `within_evidence` en `create_generation_plan.py`, aplicado al resultado de `ReferentsPort` antes del planificador, así que vale para cualquier adaptador de MAT-P2. Pruebas en `tests/unit/test_generation_plan_use_cases.py` con un doble que devuelve ids dentro, fuera y mezclados; leen el plan guardado en el repositorio real (SQLite) con `GetGenerationPlan`. La prueba e2e queda para cuando llegue el adaptador de MAT-P2: hoy `main.py` usa `NoReferentsAdapter` y el API siempre devuelve `referents: []`.

## 5. Generación desde el plan (GEN-P2)

- [x] T011 [BE] [GEN-P2] **Depende de T010.** `StartGenerationRequest` acepta `{planId, planVersion}` ([research R2](research.md#r2-el-plan-es-obligatorio-compatibilidad-del-pedido-sin-plan)).
  - Exige un plan aprobado y en esa versión, y lo marca `used`.
  - El modo sale del plan, y el pedido guarda `plan_id` y `plan_version`.
  - Con el cuerpo anterior, crea un plan implícito; con `GENERATION_REQUIRE_PLAN=true`, responde `422 PLAN_REQUIRED`.
  - Al usar el plan, llama a `record_typology`.
  - Antes de crear el pedido, comprueba la [evidencia vigente](data-model.md#evidencia-vigente): si falta algún fragmento del plan, `409 PLAN_EVIDENCE_STALE` con `StaleDocument` por documento, sin crear el pedido ni cambiar el plan.
  - Pruebas: V6, V7 (a, b) y V12 de [quickstart](quickstart.md); `PLAN_ALREADY_USED` y `PLAN_NOT_APPROVED`; idempotencia con plan; un documento borrado y otro procesado de nuevo después de aprobar dan `PLAN_EVIDENCE_STALE` con los dos documentos y sus fragmentos.
  - Hecho en el PR del backend (enlace pendiente).
    - `StartGenerationRequest.execute_planned` y el plan implícito (`CreateGenerationPlan.create_implicit`, `origin: implicit`); el plan pasa a usado en la misma transacción que el alta del pedido (`PlanClaim` en `create_within_limit`), así que un límite de pedidos activos o una carrera con otro envío lo dejan aprobado.
    - Migración `20261123000001_generation_request_plan.sql` (`plan_id`, `plan_version`, `plan_item_position`); en SQLite las agrega el repositorio. `GENERATION_REQUIRE_PLAN` está en `settings.py`, con `false` por defecto.
    - Pruebas en `tests/unit/test_planned_generation.py` (con dos documentos vencidos), `tests/unit/test_planned_request_domain.py` y `tests/e2e/test_planned_generation_api.py` (V6, V7 a y b, V12 con un documento procesado de nuevo).
    - **Cambio visible:** con el cuerpo anterior, unas indicaciones que el material no trata ahora responden `422 INSUFFICIENT_EVIDENCE` al iniciar (el plan implícito comprueba el tema), en vez de un pedido que termina `failed`. `collect_samples.py` cuenta ese rechazo como «sin evidencia» (`pass`).
- [x] T012 [BE] [GEN-P2] **Depende de T003 y T011.** `RunGenerationRequest` desde el plan ([research R5](research.md#r5-generación-desde-el-plan-gen-p2)).
  - Un paso por ítem, la evidencia del plan, y cada recurso redactado por separado con su bloque de conceptos, el propósito, los conceptos ajenos y el resumen de lo ya cubierto.
  - Se quita «devuelve menos recursos» para los ítems del plan.
  - Pruebas en `tests/unit/test_planned_generation.py`:
    - el prompt de cada recurso trae su bloque y el resumen de los anteriores;
    - un recurso solo cita fragmentos del plan;
    - con reglas, cada recurso usa las oraciones de sus conceptos.
  - Hecho en el PR del backend (enlace pendiente). `application/services/generation/planned_drafting.py`, el camino del plan en `RunGenerationRequest` y el foco del plan en `rule_based_generator.py`. Sin una búsqueda nueva ni la comprobación del tema (QA-05), que ya hizo el plan. Cada recurso guarda `planId`, `planItemPosition` y `planBlock` en `params`. Pruebas en `tests/unit/test_planned_generation.py`.
- [x] T013 [BE] [GEN-P2] **Depende de T012.** Comprobación de cobertura y rechazo `kind: plan`, con un reintento con la indicación del problema; el filtro de repetición actual sigue activo y su reintento nombra los conceptos ajenos. `RejectionKind` suma `plan` en el contrato y en OpenAPI.
  - Pruebas: con un Gemini falso que desarrolla un concepto ajeno, se rechaza con `kind: plan` y motivo; un recurso que no menciona ninguno de sus conceptos se rechaza igual; un recurso correcto pasa sin reintento.
  - Recursos de un solo párrafo ([research R5](research.md#r5-generación-desde-el-plan-gen-p2)): la regla «en más de un párrafo» no se cumple nunca, así que rige la estricta. Pruebas: una `pregunta_detonante` con un concepto ajeno completo en la pregunta se rechaza con `kind: plan`; un `item_opcion_multiple` con un concepto ajeno completo en una opción se rechaza igual; el mismo concepto solo en la retroalimentación, o una palabra suelta de un concepto de varias palabras, no cuenta; un recurso de varios párrafos sigue con la regla de «más de un párrafo».
  - Falsos rechazos, con el corpus de T067 (`backend/evaluation/corpus_t067`): un conjunto fijo de recursos cortos (`pregunta_detonante`, `item_opcion_multiple`, `audio_detonante`) armados con sus fragmentos y marcados a mano como correctos o no, guardado en `tests/fixtures/`. La prueba falla si la regla estricta rechaza más del 5 % de los correctos o deja pasar alguno marcado como incorrecto. Si falla por falsos rechazos, se afloja la regla y se registra en research R5. Sin llamadas a Gemini.
  - Hecho en el PR del backend (enlace pendiente). La comprobación es `domain/generation/plan_coverage.py`; `RejectionKind` suma `plan` en el contrato de GEN-01, en el de esta ficha y en OpenAPI. Pruebas en `tests/unit/test_plan_coverage.py`, `tests/unit/test_planned_generation.py` y `tests/unit/test_plan_coverage_corpus.py`, con `tests/fixtures/plan_coverage_short_resources.json`: 16 recursos (10 correctos, 6 incorrectos), 0 falsos rechazos. **Pendiente:** Sergio revisa las marcas con el corpus; las puso Yan.
- [x] T014 [BE] [GEN-P2] **Depende de T012.** Regeneración desde Revisión con el ítem del plan (`params.planId`, `params.planItemPosition`): lee el plan sin escribirlo, así que un plan `used` no responde `PLAN_ALREADY_USED`; comprueba la evidencia vigente de los fragmentos del ítem. Un recurso sin plan se regenera como hoy.
  - La comprobación se hace al iniciar la regeneración, antes de crear el pedido, como en T011: así Revisión recibe el rechazo en la respuesta de `POST …/regenerations` y no en el estado del pedido.
  - El 409 `PLAN_EVIDENCE_STALE` de Revisión usa el formato común `{"error": {"code", "message", "details"}}`, con el mismo `details` que en la generación: una lista de [`StaleDocument`](contracts/generation-plans.openapi.yaml) (`documentId`, `documentName`, `missingFragmentIds`), uno por documento afectado. Revisión pasa el `details` de Generación sin cambiarlo.
  - El contrato de Revisión (`specs/001-revision-citas`, de Juan) debe sumar `PLAN_EVIDENCE_STALE` a la respuesta 409 de `POST …/regenerations`, con este `details`. No se edita desde esta ficha: se le pide a Juan con REV-01.
  - Pruebas: V7 (c) y V12 de [quickstart](quickstart.md); regenerar con el plan `used` no cambia su `status`, `version` ni `usedByRequestId`; con un fragmento del ítem borrado, la regeneración falla con `PLAN_EVIDENCE_STALE`, Revisión responde 409 con ese código y un `details` igual al de la generación (los mismos campos y documentos, comparados con el esquema `StaleDocument`), y el recurso se conserva; un recurso anterior sin plan.
  - Hecho en el PR del backend (enlace pendiente), del lado de Generación. `StartRegeneration` lee `planId`, `planItemPosition` y `planBlock`; el pedido rehace ese bloque con la evidencia del plan y el resumen de los demás recursos del plan. Pruebas en `tests/unit/test_planned_generation.py` y V7 (c) en `tests/e2e/test_planned_generation_api.py`.
  - **Pendiente en Revisión (REV-01, Juan):** el adaptador entrega a Revisión `failed` con el código `PLAN_EVIDENCE_STALE`, pero hoy Revisión lo responde con 422 y sin `details`. `domain/review/errors.py` no lo tiene entre los códigos de 409, y `RegenerationStatus` no lleva `details`. No se editó desde esta ficha.
- [x] T015 [BE] [GEN-P2] **Depende de T004 y CUR-P2.** Tipos de texto nuevos del catálogo ([research R6](research.md#r6-catálogo-configurable-cur-p2)): prompt genérico con la `description`, redactor genérico por reglas y verificación de citas y párrafos como `explicacion`.
  - Pruebas: un tipo nuevo de prueba en el catálogo se planifica, se genera con reglas y con Gemini falso, y Revisión lo muestra con su etiqueta.
  - Hecho en el PR del backend (enlace pendiente). `CatalogEntry` suma `length_hint` y `verification` (`strict` o `framed`, [research R6](research.md#verificación-strict-y-framed)); `domain/generation/text_types.py`, `grounding.verify_framed` y el redactor genérico `_catalog_text`. El `lengthHint` llega al prompt también para los tipos actuales que lo tengan. Pruebas en `tests/unit/test_text_type_verification.py` y `tests/unit/test_planned_generation.py`, con entradas falsas de los dos modos.
  - **Pendiente:** los 28 tipos nuevos siguen inactivos hasta que CUR-P2 cablee el catálogo. Mientras tanto, la etiqueta en Revisión y el esquema HTTP de `resourceType` (lista cerrada) no los aceptan todavía.

- [ ] T027 [BE] [GEN-P2] **Depende de T026.** Problemas que encontró la v4 de P4 ([research R7](research.md#r7-medición-de-la-duplicación-p4)):
  - [x] **(a) Opción múltiple:** `item_opcion_multiple` (ítem 8 del plan) fue al respaldo por reglas en las 5 corridas con plan, sobre todo por «sin citas válidas».
    - **Causa:** no era del plan. En `backend/p4.db` también fue al respaldo en las corridas sin plan (4 de 5 por estructura, 1 sin conexión), con el mismo rechazo «structure»: «hace falta 1 correcta y 3 distractores, cada uno con su retroalimentación y su error conceptual».
      - El esquema de respuesta compartido (`GEMINI_RESPONSE_SCHEMA` en `infrastructure/llm/gemini_language_model.py`) declaraba en cada alternativa solo `texto`, `correcta`, `retroalimentacion` y `fragmentos`, aunque el prompt pide `error_conceptual` (`MISCONCEPTION_INSTRUCTION` y el formato de `build_prompt_instructions`).
      - Con el esquema impuesto, Gemini devuelve solo los campos declarados. `_validate_alternatives` (`prompt_drafting.py`) descarta los distractores sin error conceptual, así que no quedaba ninguno.
      - El límite de salida no influía (no se fija `maxOutputTokens`).
      - Lo único propio del plan era «como este recurso es breve, no los nombres», que podía acortar las alternativas.
    - **Arreglo:**
      - El ítem tiene su propio esquema, como la actividad kinestésica (T073): cada alternativa exige `texto`, `correcta`, `retroalimentacion`, `error_conceptual` y `fragmentos`, con tantas alternativas como `optionCount` y `recursos` limitado a la cantidad. El esquema compartido no cambia.
      - Con plan, el prompt aclara que la brevedad es del enunciado.
    - **Motivo del respaldo:** decía «no devolvió recursos con citas válidas» aunque todos los rechazos fueran de estructura. Ahora dice el rechazo que más pesó en la llamada (`fallback_warning` en `step_drafting.py`), con textos fijos sin el texto del proveedor: estructura, citas, distractores, plan o repetición. En un empate, gana en ese orden.
    - **Títulos dañados** («Evaluaci3n», «transmisi3n», «m3nima»): vienen del modelo. Los fragmentos guardados están bien, y nuestro código no cambia los caracteres: se lee el JSON tal cual y solo se normalizan los espacios. Aparecen 14 veces en los 234 recursos de `p4.db`; no se corrigen.
    - Pruebas en `tests/unit/test_mcq_generation.py`, con `tests/fixtures/gemini_mcq_without_misconception.json` (el patrón de las respuestas rechazadas). Hecho en el PR del backend (enlace pendiente). **Pendiente:** confirmarlo en la próxima medición con Gemini.
  - [x] **(b) Plan de Gemini:** falló la validación dos veces (con su reintento) en 4 de 5 corridas de la v4: `NOT_ENOUGH_CONCEPTS` ×3 y `CONCEPT_OWNED_TWICE` ×1.
    - **Causa (planificador con Gemini):**
      - con 8 tipos y cantidad 2, cada ítem necesita al menos 2 conceptos cortos y distintos: 16 en total, ninguno repetido entre ítems, con 12 fragmentos;
      - el esquema (`plan_response_schema`) solo pedía `covers.minItems` 1 y el prompt decía «al menos tantos conceptos como su cantidad», sin el número exacto por tipo;
      - `items_from_model` descartaba en silencio los conceptos que no eran frases cortas (T024), así que un ítem con 2 podía quedar con 1;
      - el reintento solo decía «Hacen falta al menos 2 conceptos», sin nombrar el concepto descartado ni el ítem por su tipo;
      - con 3 tipos hacen falta 6 conceptos y casi nunca fallaba (`t027a-mcq-check.json`).
    - **Arreglo (planificador con Gemini):**
      - El esquema es un objeto con una propiedad por tipo pedido, cada una con su mínimo exacto (`covers.minItems` = la cantidad); la cantidad solo se pide si el docente la dejó libre. La respuesta en lista se sigue aceptando.
      - El prompt dice el mínimo de cada tipo, el total y que un concepto no se repite con otra forma.
      - El reintento nombra el ítem por su tipo, sus conceptos válidos, los descartados por largos y qué hacer; y en un concepto repetido, los dos ítems y en cuál dejarlo.
      - Arreglos seguros sin otra llamada (`repair_items`), registrados en `generator.repairs`:
        - un concepto que ya tiene un ítem anterior se quita del posterior si a este le siguen alcanzando sus conceptos;
        - una cantidad que eligió la IA (nunca una pedida por el docente) baja a su número de conceptos.
    - **Causa (planificador por reglas):**
      - las frases se armaban con la lista de palabras de cada fragmento, sin mirar los signos («puerto de destino, longitud» → «destino longitud»; «FTP, SFTP» → «ftp sftp»);
      - entraban los encabezados de página («Ingeniería de redes  Página 1» → «redes página») y pedazos de oración («udp proporciona»);
      - a cada ítem se le daban los fragmentos en el orden de la evidencia, aunque no mencionaran sus conceptos.
    - **Arreglo (planificador por reglas):**
      - Nuevo `application/services/generation/concept_extraction.py`, que usan el planificador y `candidate_concepts` (la medición). Corta el texto en signos, paréntesis, barras, guiones y «Página N», y quita los encabezados repetidos al comienzo de los fragmentos y las líneas de título (una línea de 8 palabras o menos que no termina como oración, como «Unidad 1: Protocolos de transporte»), porque ninguna oración las desarrolla y el recurso por reglas no podía cubrirlas.
      - Arma frases de términos unidos por «de» («puerto de destino», «bloqueo de cabeza de línea», «saludo de tres vías»), pares seguidos, nombres con mayúscula («Transmission Control Protocol») y un sustantivo con su sigla («modelo OSI»).
      - Las siglas (TCP, UDP, RTT) van solas; singular y plural son el mismo concepto.
      - Las frases que aparecen una sola vez sin «de» quedan de último recurso, solo si faltan conceptos para el plan (con poco material).
      - Cada ítem recibe los fragmentos que mencionan sus conceptos (el término completo), primero los que mencionan más; la evidencia congelada no cambia.
    - Pruebas en `tests/unit/test_plan_generator_t027b.py`, con Gemini falso y el texto real del corpus de T067 (la petición de P4: 8 tipos × 2). Hecho en el PR del backend (enlace pendiente). **Pendiente:** confirmarlo en la próxima medición con Gemini.
  - [x] **(c) Fidelidad:** la `faithfulness` de los recursos redactados desde el plan no se había medido (meta ≥ 0,90).
    - **Arreglo:** `measure_duplication.py --faithfulness`, en una corrida nueva o con `--recompute`. Usa la `Faithfulness` de Ragas con el juez de `run_ragas.py` (el mismo modelo y la misma configuración; nuevo `faithfulness_evaluator`). Por cada recurso entregado: la respuesta es el recurso sin título, el contexto son los textos que cita (guardados en el informe) y la pregunta, las indicaciones del pedido.
    - Los recursos sin citas se omiten y se cuentan; un error del juez queda en el recurso y la medición sigue. Las llamadas van con 2 hilos y con progreso.
    - El informe trae la media, la parte con 0,90 o más y los calificados, omitidos y errores, por corrida y en el resumen, en `aiOnly` y por tipo; `--compare` agrega la diferencia y si el plan mantiene 0,90.
    - Documentado en [research R7](research.md#r7-medición-de-la-duplicación-p4) («Fidelidad» y «Comparabilidad con la v5») y en [plan](plan.md#medición-de-p4) («Medición final (v5)»).
    - Pruebas en `tests/unit/test_measure_faithfulness.py`, con un juez falso. **Pendiente:** la medición v5 con Gemini.
  - [x] **(d) Tiempos:** los demás respaldos de la v4 fueron por el límite de 60 s de cada llamada a Gemini (`LLM_CALL_DEADLINE_SECONDS`, QA-06).
    - **Decisión:** el límite se mantiene a propósito. Es el tope de Render y lo que se le promete al docente: un paso que no responde a tiempo se redacta con reglas en lugar de dejar el pedido esperando. Sin cambios en el código.
    - En la v5, esos respaldos se leen en `fallbacks` (con su motivo) y no cuentan como recursos de la IA (`aiOnly`).
  - **Pendiente:** la medición v5 (baseline y plan, 5 corridas cada uno, τ = 0,885, oraciones 0,865, `--faithfulness`) para confirmar (a), (b) y la fidelidad.
- [x] T026 [BE] [GEN-P2] **Depende de T025.** Correcciones de la medición tras la v3 ([research R7](research.md#r7-medición-de-la-duplicación-p4)):
  - las oraciones sin títulos ni encabezados, y las tres cifras (todos, `crossType` como principal y `variants`), también en la tasa de pares;
  - la tabla por concepto (mencionado, desarrollado, definido);
  - `--recompute` para recalcular un informe sin generar, con `--compare`, y las métricas solo con los recursos de la IA (`aiOnly`);
  - por corrida, los pasos del respaldo con su motivo y los recursos no entregados con sus rechazos;
  - en la calibración, un error claro si la API no devuelve el pedido, y embeddings por lotes con avance;
  - en la documentación, la cuenta debe ser la misma que creó los informes.
  - Hecho en el PR del backend (enlace pendiente). Pruebas en `tests/unit/test_measure_duplication.py` y `tests/unit/test_plan_coverage.py`. La v3 se recalculó con embeddings (`v3r-gemini-*.json`) y se repitió la medición con plan (`v4-gemini-plan.json`); resultado en [research R7](research.md#r7-medición-de-la-duplicación-p4).
- [x] T025 [BE] [GEN-P2] **Depende de T024.** Segunda corrida de P4: la baja de la tasa de pares fue −1,4 % con la IA en los dos modos.
  - **Planificador con Gemini:** un plan no válido se pide una vez más con sus problemas, y `generator.attempts` lo registra ([research R4](research.md#r4-planificación-con-reglas-y-con-gemini)).
  - **Medición:** oraciones casi repetidas y conceptos explicados otra vez como evidencia principal, `--calibrate` para los umbrales, 5 corridas por defecto, y el origen del plan por corrida ([research R7](research.md#r7-medición-de-la-duplicación-p4)).
  - Hecho en el PR del backend (enlace pendiente). Pruebas en `tests/unit/test_plan_drafting.py`, `test_measure_duplication.py`, `test_plan_coverage.py` y `test_plan_concepts.py`. Calibrado con los informes de la v2 (`calibration-v2.json`: τ = 0,885 y 0,865 en oraciones) y medido con 5 corridas (v3 y v4).
    - El reintento no alcanzó: en 4 de 5 corridas de la v4, el plan de Gemini volvió a fallar la validación y se armó con reglas (T027).
- [x] T024 [BE] [GEN-P2] **Depende de T013.** Corrección tras la medición de P4 con Gemini. En la medición, 14 de 24 pasos con plan fueron al respaldo por reglas, por rechazos `plan` de dos clases: paráfrasis de conceptos largos y simples menciones de términos de fondo.
  - **Conceptos cortos** ([research R4](research.md#r4-planificación-con-reglas-y-con-gemini)): frases de 2 a 4 palabras del material o siglas, en los dos planificadores y en la validación (`CONCEPT_NOT_SHORT`).
  - **Comprobación** ([research R5](research.md#r5-generación-desde-el-plan-gen-p2)): el concepto propio cuenta con el 60 % de sus palabras en un párrafo; el ajeno, solo si se desarrolla (dos oraciones o una definición); los conceptos de fondo no son ajenos.
  - **Política:** el recurso de la IA que solo falla el plan se entrega con `planWarning`, y el rechazo `plan` queda para el camino por reglas.
  - **Medición:** `measure_duplication.py` cuenta los pasos de la IA, los del respaldo y los avisos de cada corrida.
  - Hecho en el PR del backend (enlace pendiente). Pruebas en `tests/unit/test_plan_concepts.py`, `test_plan_coverage.py`, `test_plan_coverage_p4.py` (con `tests/fixtures/plan_coverage_p4_cases.json`, del corpus de T067), `test_plan_coverage_corpus.py`, `test_planned_generation.py` y `test_measure_duplication.py`. **Pendiente:** repetir la medición de P4 con Gemini.

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
  - Línea base sin plan frente a plan aprobado, con reglas y con Gemini, 5 corridas cada uno, en el mismo servidor y la misma base: `--mode plan` con `GENERATION_IMPLICIT_PLAN=true` y `--mode baseline` con `false` (interruptor solo de medición, nunca en Render).
  - Resultados en `docs/evidence/GEN-P4/`.
  - Meta: duplicación ≤ 5 % y al menos 50 % menos que la línea base, sin perder recursos ni bajar la `faithfulness` de 0,90.
  - El script ya está (PR del backend, enlace pendiente): `backend/evaluation/measure_duplication.py`, con pruebas en `tests/unit/test_measure_duplication.py` (backend y embeddings falsos). `--similarity auto` usa embeddings si hay modelo y si no la similitud léxica, registrada como provisional; `--compare` agrega la comparación con la meta.
  - **Medición con Gemini hecha** ([resultado en research R7](research.md#r7-medición-de-la-duplicación-p4)): `v3r-gemini-baseline.json`, `v3r-gemini-plan.json` y `v4-gemini-plan.json`.
    - Oraciones casi repetidas entre tipos distintos (principal): 32,4 % → 21,2 % y 21,1 % (−35 % en las dos corridas con plan).
    - Pares entre tipos distintos: 6,0 % → 2,7 % y 4,1 %.
    - Meta de P4 cumplida en parte: ≤ 5 % en las dos; −50 % solo en la v3.
  - **Pendiente:** la medición con reglas, la `faithfulness` (T027) y REV-P3.
- [ ] T020 [E2E] [GEN-P1] **Depende de T010.** Tiempos de creación del plan, V9 de [quickstart](quickstart.md): p95 < 1 s con reglas y < 30 s con Gemini. Si no se cumple con Gemini, revisar la decisión síncrona de [research R1](research.md#r1-el-plan-como-recurso-propio-creado-de-forma-síncrona).
- [ ] T021 [BE] [GEN-P2] **Depende de T011 y T018.** Fin de la transición: `GENERATION_REQUIRE_PLAN=true` por defecto, y `collect_samples.py` y `measure_generation_load.py` crean el plan antes de generar. Pruebas de los dos scripts con backend falso.
- [ ] T022 Preguntas abiertas para el profesor: P8 (referentes en la recuperación) y P10 (editor WYSIWYG). Registrar sus respuestas en [spec](spec.md#preguntas-abiertas-para-el-profesor) y ajustar R10 y GEN-P3 si cambian el alcance.

## Dependencias y trabajo en paralelo

- **Primero:** T001 a T003, en ese orden. T004 y T005 pueden ir en paralelo con T002 y T003.
- **Backend:** T006 → T007 → T008 → T009 → T010. T023 va después de T008, en paralelo con T009 y T010. El frontend (T016 y T017) puede empezar con el [contrato](contracts/generation-plans.openapi.yaml) y un API simulado antes de T010.
- **Generación:** T011 → T012 → T013 y T014. T015 espera el catálogo de CUR-P2 (el adaptador provisional basta para probar).
- **Cierre:** T019 necesita REV-P3 (o la medición provisional léxica, registrada como tal). T021 va al final, cuando GEN-P3 ya esté integrado.
