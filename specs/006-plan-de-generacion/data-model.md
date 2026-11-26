# Modelo de datos del plan de generación (GEN-P1 a GEN-P3)

[Ficha](spec.md) · [Plan](plan.md) · [Research](research.md) · [Contrato](contracts/generation-plans.openapi.yaml) · [Tareas](tasks.md)

Mismas convenciones que el [data-model de GEN-01](../002-generacion-multiple/data-model.md): snake_case en Python y en las columnas, camelCase en JSON, y estados y códigos de error en inglés. Este es el contrato que usan MAT-P2, CUR-P2, CUR-P3 y REV-P3.

## GenerationPlan

| Campo (JSON) | Tipo | Reglas |
| --- | --- | --- |
| `id` | `str` | `gen-plan-{uuid4}`. |
| `version` | `int` | Empieza en 1 y sube en cada `PUT`. `approve` y el pedido de generación la exigen. |
| `status` | `draft` \| `approved` \| `used` | Ver [transiciones](#transiciones-de-estado). |
| `origin` | `teacher` \| `implicit` | `implicit`: lo creó el servidor para un pedido sin plan ([research R2](research.md#r2-el-plan-es-obligatorio-compatibilidad-del-pedido-sin-plan)). |
| `unitId` | `str` | Unidad del docente (`UnitMembershipPort`). |
| `inputs` | [`PlanInputs`](#planinputs) | Lo que pidió el docente, normalizado. No cambia después de crearse. |
| `evidence` | [`PlanEvidence`](#planevidence) | Evidencia congelada al crear el plan. Los ítems y la generación solo usan esta. |
| `referents` | `list[`[`Referent`](#referent)`]` | Referentes de MAT-P2 (autores principales del tema). Puede estar vacía. |
| `sessionContext` | [`SessionContext`](#sessioncontext) | De CUR-P3. `previousTypologies` puede estar vacía. |
| `items` | `list[`[`PlanItem`](#planitem)`]` | Ordenados por etapa y después por `position`. Al menos uno para aprobar. |
| `validation` | `{valid: bool, problems: list[`[`PlanProblem`](#planproblem)`]}` | Se calcula en cada escritura ([reglas](#reglas-de-validación)). |
| `warnings` | `list[str]` | Avisos que no impiden aprobar, por ejemplo `SAME_TYPOLOGY_AS_LAST_SESSION`. |
| `generator` | `{description, usesAi, fallback, fallbackReason}` | Quién armó el plan. Mismo bloque que `steps[].generator` de GEN-01. |
| `usedByRequestId` | `str` \| `null` | El pedido de generación que lo usó. |
| `createdAt`, `updatedAt`, `approvedAt`, `usedAt` | ISO 8601 UTC \| `null` | — |

### PlanInputs

| Campo | Tipo | Reglas |
| --- | --- | --- |
| `instructions` | `str` | El tema, hasta 500 caracteres. Con QA-05, si el material no trata el tema, no se crea el plan. |
| `audience`, `competency` | `str` | Hasta 200 caracteres cada uno. |
| `outcomeId` | `str` \| `null` | Debe ser de la unidad. |
| `modality` | `Textual` \| `Gamificado` \| `Multimedia` \| `Kinestésico` \| `null` | Si viene, todos los tipos deben pertenecer a ella (HU-024). |
| `resourceTypes` | `list[{type, quantity}]` | De 1 a 8 tipos distintos del catálogo. `quantity` de 1 a 5, o `null`: decide el planificador ([research R4](research.md#r4-planificación-con-reglas-y-con-gemini)): con reglas, de 1 a 3 según los conceptos; con Gemini, de 1 a 5. |
| `difficulty`, `optionCount`, `evidenceThreshold` | como en GEN-01 | Pasan al pedido de generación. |
| `topK` | `int` | Fragmentos que se recuperan para el plan, de 3 a 12 (12 por defecto: el plan reparte la evidencia entre ítems). |

### PlanEvidence

| Campo | Tipo | Reglas |
| --- | --- | --- |
| `retrievalMode` | `hybrid` \| `bm25_fallback` | Como en GEN-01. |
| `retrievedAt` | ISO 8601 UTC | — |
| `fragments` | `list[{id, documentId, documentName, location, text, relevance, sourceUrl, license}]` | En el orden de la recuperación. Es la copia que usa la generación y que Revisión exige (002, R6). |

### Referent

| Campo | Tipo | Reglas |
| --- | --- | --- |
| `name` | `str` | Nombre del autor o referente, como aparece en el material. |
| `description` | `str` | Una línea de por qué es referente del tema. Puede estar vacía. |
| `fragmentIds` | `list[str]` | Fragmentos de la evidencia del plan donde aparece. Al crear el plan, es un subconjunto de `evidence.fragments`: los ids que no están ahí se descartan, sin informar un problema de validación ([research R10](research.md#r10-referentes-mat-p2)). Puede quedar vacía: entonces el referente se muestra, pero no se cita. |

### SessionContext

| Campo | Tipo | Reglas |
| --- | --- | --- |
| `previousTypologies` | `list[{sessionLabel, usedAt, resourceTypes}]` | Las últimas 3 sesiones del mismo curso, de la más reciente a la más antigua. Una sesión se cuenta cuando un plan pasa a `used` ([research R9](research.md#r9-contexto-de-sesión-cur-p3)). Vacía si CUR-P3 no responde o no hay sesiones. |
| `…sessionLabel` | `str` | Nombre de la sesión para el docente, lo define Cursos. |
| `…usedAt` | ISO 8601 UTC | Cuándo el plan de esa sesión pasó a `used`. |
| `…resourceTypes` | `list[str]` | Los tipos de los ítems de ese plan. |
| `previousUnitConcepts` | `list[{unitNumber, unitTitle, concepts}]` | Solo lectura. Los conceptos propios del último plan aprobado o usado de cada unidad anterior del mismo curso, de la más antigua a la más reciente, hasta 12 por unidad y 30 en total. Se congelan al crear el plan. Vacía en la primera unidad o si no hay planes ([research R11](research.md#r11-conceptos-de-unidades-anteriores)). |

### CatalogEntry (CUR-P2)

La entrada del catálogo que Generación lee por `ResourceCatalogPort` ([research R6](research.md#r6-catálogo-configurable-cur-p2)). No se guarda en el plan: el plan guarda solo `resourceType` y `stage`.

| Campo | Tipo | Reglas |
| --- | --- | --- |
| `id` | `str` | snake_case, `^[a-z][a-z0-9_]{2,59}$`. |
| `name`, `singular`, `plural` | `str` | Lo que ve el docente. |
| `stage` | `engage` … `evaluate` | Etapa del tipo. |
| `description` | `str` | Qué es el recurso y cómo se usa. Es la instrucción del prompt genérico. |
| `lengthHint` | `{minWords: int, maxWords: int}` \| `null` | Opcional. `minWords` ≥ 20, `maxWords` ≤ 600 y `minWords` ≤ `maxWords`. Guía del prompt («entre X y Y palabras»), nunca regla de rechazo. Sin él, la extensión por defecto: de 3 a 5 párrafos. |
| `verification` | `strict` \| `framed` \| `null` | En los tipos de texto nuevos ([research R6](research.md#verificación-strict-y-framed)). `strict`: cada párrafo se contrasta con el material, como en `explicacion`. `framed`: la ambientación no necesita cita, cada oración sobre un concepto sí, y hacen falta al menos 2 con respaldo. `null` en los tipos con redactor propio. |
| `modalities` | `list[str]` | Modalidades que lo incluyen (HU-024). |
| `format` | `text` \| `visual` \| `image` \| `audio` \| `interactive` | Los tipos nuevos de CUR-P2 son `text`. |
| `structure` | `str` | `none` en los tipos nuevos. |
| `active` | `bool` | Si se ofrece en el formulario. Un tipo inactivo en un plan guardado es `TYPE_NOT_IN_CATALOG`. |

### PlanItem

| Campo | Tipo | Reglas |
| --- | --- | --- |
| `position` | `int` | De 1 a N, sin huecos, en el orden de la lista. |
| `stage` | `engage` … `evaluate` | Sale del catálogo según `resourceType`. Solo lectura. |
| `resourceType` | `str` | Del catálogo (CUR-P2) y de la modalidad, si hay. |
| `quantity` | `int` | De 1 a 5. Sus `covers` se reparten en `quantity` bloques consecutivos, uno por recurso. |
| `purpose` | `str` | Para qué sirve el ítem en la clase. De 1 a 300 caracteres. No menciona la metodología 5E. |
| `covers` | `list[str]` | Conceptos que el ítem desarrolla: frases nominales de 2 a 4 palabras útiles tomadas del material, o siglas (`CONCEPT_NOT_SHORT` si no). Al menos `quantity`, de 1 a 120 caracteres cada uno. |
| `doesNotCover` | `list[str]` | Lo calcula el servidor: los `covers` de los demás ítems, en orden. Solo lectura. |
| `fragmentIds` | `list[str]` | Fragmentos de `evidence.fragments` que respaldan el ítem. Al menos uno. |

### PlanProblem

| Campo | Tipo | Reglas |
| --- | --- | --- |
| `code` | `str` | Uno de los códigos de las [reglas de validación](#reglas-de-validación). |
| `message` | `str` | En español, para el docente. |
| `itemPosition` | `int` \| `null` | El ítem afectado, o `null` si es del plan. |

## Reglas de validación

Se calculan en cada `POST` y `PUT`. El borrador inválido se guarda; `approve` responde `422 PLAN_INVALID` con los problemas en `details`.

| Código | Regla |
| --- | --- |
| `PLAN_EMPTY` | El plan tiene al menos un ítem. |
| `ITEM_WITHOUT_EVIDENCE` | Cada ítem tiene al menos un `fragmentId`. |
| `FRAGMENT_NOT_IN_EVIDENCE` | Cada `fragmentId` está en `evidence.fragments`. |
| `CONCEPT_OWNED_TWICE` | Ningún concepto normalizado (minúsculas, sin tildes, sin espacios repetidos ni palabras vacías) está en los `covers` de dos ítems. |
| `NOT_ENOUGH_CONCEPTS` | Cada ítem tiene al menos `quantity` conceptos. |
| `TYPE_NOT_IN_CATALOG` | `resourceType` existe y está activo en el catálogo. |
| `RESOURCE_TYPE_NOT_IN_MODALITY` | Con modalidad, cada tipo pertenece a ella. |
| `QUANTITY_OUT_OF_RANGE` | `quantity` de 1 a 5. |
| `TOO_MANY_TYPES` | Como máximo 8 tipos distintos, el límite de GEN-01. |
| `CONCEPT_NOT_SHORT` | Cada concepto es una frase nominal de 2 a 4 palabras útiles, o una sigla: sin comas ni signos de oración, sin negaciones ni verbos conjugados, y con 7 palabras como máximo contando las vacías ([research R4](research.md#r4-planificación-con-reglas-y-con-gemini)). Corrección tras P4. |
| `PURPOSE_REQUIRED` | `purpose` no está vacío. |

## Transiciones de estado

| Desde | Acción | Hacia | Condición |
| --- | --- | --- | --- |
| — | `POST /generation-plans` | `draft` | Unidad del docente con material procesado y tema tratado por el material (QA-05). |
| `draft` | `PUT` | `draft` | `expectedVersion` igual a `version`; sube `version`. |
| `approved` | `PUT` | `draft` | Igual que arriba: editar un plan aprobado lo devuelve a borrador. |
| `draft` | `approve` | `approved` | `expectedVersion` igual a `version` y `validation.valid`. |
| `approved` | `POST /generation-requests` | `used` | `planVersion` igual a `version` y [evidencia vigente](#evidencia-vigente). El plan queda con `usedByRequestId`. |
| `used` | cualquier escritura | — | `409 PLAN_ALREADY_USED`. Para generar otra vez se crea otro plan. |
| `used` | regeneración desde Revisión | `used` | No es una escritura: lee el ítem del recurso y no cambia `status`, `version` ni `usedByRequestId`, así que no responde `PLAN_ALREADY_USED`. Exige [evidencia vigente](#evidencia-vigente) para los fragmentos de ese ítem. |

### Evidencia vigente

El plan congela su evidencia, pero el docente puede borrar o volver a procesar un documento entre la aprobación y la generación. Al procesar de nuevo, los fragmentos reciben ids nuevos (`frag-{uuid}`), así que los anteriores dejan de existir.

| Momento | Comprobación | Si falla |
| --- | --- | --- |
| `POST /generation-requests` con plan | Cada `fragmentId` de los ítems del plan sigue existiendo en la unidad del docente (`EvidenceProviderPort.existing_fragment_ids`). | `409 PLAN_EVIDENCE_STALE`, sin crear el pedido. `details` lista los documentos afectados (`StaleDocument`: `documentId`, `documentName`, `missingFragmentIds`). El plan no cambia; el docente crea un plan nuevo. |
| Regeneración desde Revisión de un recurso con plan | Los `fragmentIds` del ítem del recurso siguen existiendo, al iniciar la regeneración y antes de crear el pedido. | La regeneración falla con `PLAN_EVIDENCE_STALE`. Revisión responde 409 en el formato común `{"error": {"code", "message", "details"}}`, con el mismo `details` (lista de `StaleDocument`), y conserva el recurso. |

## Cambios en el pedido de generación (GEN-01)

| Dónde | Cambio |
| --- | --- |
| `StartGenerationRequest` | Nuevo cuerpo `{planId, planVersion}`. El cuerpo anterior se acepta mientras `GENERATION_REQUIRE_PLAN=false`, con un plan implícito. |
| `GenerationRequest` | Columnas `plan_id` y `plan_version`. La evidencia del pedido es la del plan. |
| `GenerationStep` | Columna `plan_item_position`. Un paso por ítem. |
| `steps[].rejections[].kind` | Nuevo valor `plan`: el recurso no desarrolló sus conceptos o desarrolló los de otro ítem. |
| `params` del recurso | `planId`, `planItemPosition` y `planBlock` (el bloque de conceptos, desde 0), para regenerar ese bloque desde su ítem sin escribir el plan. |
| `regeneration` del pedido | `planBlock`, el bloque que se redacta otra vez, en una regeneración desde el plan. |
| `planWarning` del recurso | Tras P4 ([research R5](research.md#r5-generación-desde-el-plan-gen-p2)): un recurso de la IA que pasó el anclaje y la estructura, pero que después del reintento sigue sin respetar su plan, se entrega con `{kind: overlap \| missing_concepts, reason, developedConcepts, missingOwnConcepts}`. Revisión lo muestra; no bloquea la aprobación. |
| `steps[].planWarnings` | Los recursos del paso entregados con aviso: `[{title, reason, resourceId}]`. Columna `plan_warnings` (migración `20261123000002_generation_step_plan_warnings.sql`). |
| `EvidenceProviderPort` | Método nuevo `existing_fragment_ids(teacher_id, unit_id, fragment_ids) -> set[str]`, de MAT-01, para la [evidencia vigente](#evidencia-vigente). |
| Errores | `PLAN_EVIDENCE_STALE` (409) en `POST /generation-requests` y en la regeneración. |

## Persistencia

Tabla `gen_generation_plans` (migración de dbmate nueva):

- `id` (PK), `teacher_id`, `unit_id`, `idempotency_key`, `payload_hash`, `version`, `status`, `origin`.
- Columnas JSON: `inputs`, `evidence`, `referents`, `session_context`, `items`, `generator`, `warnings`.
- `retrieval_mode`, `used_by_request_id`, `created_at`, `updated_at`, `approved_at` y `used_at`.

Restricciones e índices:
- `UNIQUE (teacher_id, idempotency_key)`.
- Índice `(teacher_id, unit_id, updated_at)` para la lista de la unidad.
- Al borrar el curso se borran sus planes, como sus pedidos (T047).

`validation` y `doesNotCover` no se guardan: se calculan al leer.
