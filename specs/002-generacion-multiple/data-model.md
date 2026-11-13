# Modelo de datos de Generación (GEN-01)

[Ficha](spec.md) · [Plan](plan.md) · [Research](research.md) · [Contratos](contracts/)

Los nombres de campo siguen la convención del backend: snake_case en Python y en las columnas nuevas, y camelCase en JSON. Los estados del pedido y de los pasos son códigos nuevos en inglés. El bloque `verification` sigue el data-model de REV-01: sus estados técnicos van en inglés (`current`, `insufficient`, `pending`) y la interfaz los muestra como vigente, insuficiente y pendiente.

## GenerationRequest

Es el pedido persistido. Lo crea `StartGenerationRequest` o `StartRegeneration` y lo actualiza `RunGenerationRequest`.

| Campo | Tipo | Reglas |
| --- | --- | --- |
| `id` | `str` | `gen-req-{uuid4}`. Es la clave primaria. |
| `teacher_id` | `str` | Es obligatorio y es el docente autenticado. |
| `unit_id` | `str` | La unidad debe pertenecer al docente según `UnitMembershipPort` al crearse el pedido. |
| `mode` | `individual` \| `sequence` \| `regeneration` | `individual` tiene un tipo; `sequence` tiene entre 1 y 8 tipos; `regeneration` se crea desde Revisión por su puerto de regeneración. |
| `idempotency_key` | `str` | 8 a 128 caracteres de `[A-Za-z0-9_-]`. `UNIQUE (teacher_id, idempotency_key)`. |
| `payload_hash` | `str` | SHA-256 del pedido normalizado ([research R2](research.md#r2-contrato-de-inicio-consulta-e-idempotencia)). |
| `parameters` | `GenerationParameters` (JSON) | Es el pedido normalizado. No cambia después de crearse. |
| `status` | `RequestStatus` | Ver [transiciones](#reglas-de-transición). |
| `retrieval_mode` | `hybrid` \| `bm25_fallback` \| `null` | Se fija al recuperar la evidencia. |
| `evidence` | `list[EvidenceFragment]` (JSON) | Es la evidencia compartida por todos los pasos, recuperada una sola vez. |
| `regeneration` | `RegenerationTarget` \| `null` | Solo existe en `mode = regeneration`. |
| `failure` | `{code, message}` \| `null` | Solo existe en `failed` o `interrupted`. |
| `created_at`, `started_at`, `finished_at`, `heartbeat_at` | ISO 8601 UTC | `heartbeat_at` se renueva cada 15 s en `running`. |
| `worker_boot_id` | `str` \| `null` | Es el identificador del proceso que lo ejecuta y sirve para diagnóstico. |

### GenerationParameters

| Campo | Tipo | Reglas |
| --- | --- | --- |
| `resourceTypes` | `list[ResourceType]` | Sin repetidos y ordenados por `order_resource_types`. En modo individual tienen exactamente un elemento. |
| `quantity` | `int` | Va de 1 a 5 y es común a todos los tipos (GEN-R2). |
| `outcomeId` | `str \| null` | Si se envía, debe pertenecer a la unidad (`400 INVALID_OUTCOME`). |
| `difficulty`, `optionCount`, `topK`, `evidenceThreshold`, `instructions`, `audience`, `competency` | — | Tienen los rangos de `StartGenerationRequest` en `schemas/generation_requests.py`. |
| `modality` | `Textual` \| `Gamificado` \| `Multimedia` \| `Kinestésico` \| `null` | HU-024. Campo interno del dominio y de los parámetros guardados. Sale de `modalities` del cuerpo (lista de 0 o 1 elemento), y la respuesta la devuelve con la misma forma: `parameters.modalities` es `[modality]`, o `[]` si es `null`. Es `null` si el pedido no la envía; el servidor no aplica un valor por defecto. Si no es `null`, cada tipo de `resourceTypes` debe estar en `MODALITY_TYPES[modality]` (`422 RESOURCE_TYPE_NOT_IN_MODALITY`). Entra en `payload_hash`. Los pedidos y recursos guardados antes de HU-024 traen `modalities: ["Textual"]`, que era el valor por defecto del servidor y no una elección del docente: se leen como `modality = null` ([research R11](research.md#r11-modalidades-hu-024)). |

### MODALITY_TYPES

Grupos de tipos por modalidad, en `domain/generation/resource_formats.py`. Un tipo puede estar en más de una modalidad. `GET /resource-types` informa en cada tipo la lista `modalities` que lo incluye.

| Modalidad | Tipos |
| --- | --- |
| `Textual` | `pregunta_detonante`, `sondeo_diagnostico`, `guia_exploracion`, `caso_indagacion`, `exploracion_guiada`, `explicacion`, `glosario`, `ejercicio_aplicacion`, `caso_aplicado`, `item_opcion_multiple` |
| `Gamificado` | `reto_prediccion`, `emparejamiento`, `ordenar_pasos`, `verdadero_falso`, `completar_espacios`, `item_opcion_multiple` |
| `Multimedia` | `imagen_ilustrativa`, `audio_detonante`, `podcast_resumen`, `diagrama_proceso`, `mapa_conceptual`, `infografia` |
| `Kinestésico` | `actividad_kinestesica` |

Todo tipo del catálogo pertenece al menos a una modalidad. `exploracion_guiada` y `caso_aplicado` están en Textual porque se responden por escrito.

### RegenerationTarget

| Campo | Tipo | Reglas |
| --- | --- | --- |
| `resourceId` | `str` | Es el recurso de Revisión que pertenece al docente y a la unidad. |
| `resourceVersion` | `int` | Versión del recurso que Revisión registró al pedir la regeneración. Forma parte de la clave `regen-{resourceId}-v{resourceVersion}`. Generación no la compara ni descarta recursos ([research R9](research.md#r9-regeneración-y-edición-durante-el-pedido)). |

## GenerationStep

Es un paso por tipo de recurso, en orden 5E. En los modos `individual` y `regeneration` hay un solo paso.

| Campo | Tipo | Reglas |
| --- | --- | --- |
| `request_id`, `position` | `str`, `int` | La clave primaria es `(request_id, position)`. `position` sigue el orden 5E desde 0. |
| `stage` | `Stage` | `resource_stage(resource_type)`. |
| `resource_type` | `ResourceType` | — |
| `agent` | `str` | `stage_agent(resource_type)`. |
| `status` | `StepStatus` | Ver [transiciones](#reglas-de-transición). |
| `resource_ids` | `list[str]` | Son los recursos entregados a Revisión en este paso. |
| `rejections` | `list[{title, reason, kind}]` | `kind` puede ser `grounding`, `repetition`, `structure` o `distractor`. |
| `generator` | `{description, usesAi, fallback}` \| `null` | `fallback = true` indica que redactó el generador por reglas. |
| `grounding`, `distractor_reliability` | JSON | Son los informes de `build_grounding_report` y `reliability_report` del paso. |
| `error` | `{code, message}` \| `null` | Solo existe en `failed` o `interrupted`. |
| `started_at`, `finished_at` | ISO 8601 UTC | — |

## Reglas de transición

### RequestStatus

```text
queued ──► running ──► succeeded
   │          ├──────► partially_succeeded
   │          └──────► failed
   └──────────┴──────► interrupted   (barrido de arranque, latido vencido)
```

| Estado final | Condición |
| --- | --- |
| `succeeded` | Todos los pasos quedaron en `succeeded`. |
| `partially_succeeded` | Al menos un paso quedó en `succeeded` y al menos uno en `rejected` o `failed` (GEN-C3). |
| `failed` | Ningún paso quedó en `succeeded`. `failure` resume el motivo (GEN-C6). También se usa si la recuperación de evidencia falla al empezar. |
| `interrupted` | El servidor se reinició con el pedido en `queued` o `running`. Los recursos ya guardados se conservan. |

Los estados finales no cambian. Reenviar la clave de un pedido terminado o interrumpido devuelve el mismo pedido.

### StepStatus

```text
pending ──► running ──► succeeded | rejected | failed
   └───────────┴──────► interrupted
```

- `succeeded`: al menos un recurso se entregó a Revisión, con `verification.status` igual a `current` o `pending`.
- `rejected`: todos los borradores se rechazaron por verificación, estructura o repetición. `rejections` explica cada caso.
- `failed`: hubo un error de infraestructura o del generador sin respaldo útil, o se superó el tiempo máximo (`DEADLINE_EXCEEDED`).

## EvidenceFragment

Es la salida de `EvidenceProviderPort`, que se guarda en `GenerationRequest.evidence`.

| Campo | Tipo | Origen |
| --- | --- | --- |
| `chunkId` | `str` | MAT-01 `chunk_id` |
| `documentId` | `str` | MAT-01 `document_id` |
| `documentName` | `str` | MAT-01 |
| `location` | `str` | MAT-01 |
| `text` | `str` | MAT-01 |
| `relevance` | `float` 0–1 | MAT-01 |
| `sourceUrl` | `str \| null` | MAT-01 (`document.origin.url`) |
| `license` | `str \| null` | MAT-01 (`document.origin.license`) |
| `retrievedAt` | ISO 8601 UTC | Instante de la recuperación en Generación |

## Recurso entregado a Revisión

Se mantiene el diccionario actual de `_build_resource_dict` (`ep002_recursos.datos`) y se agregan estos campos, todos obligatorios para un recurso de GEN-01:

| Campo | Tipo | Reglas |
| --- | --- | --- |
| `requestId` | `str` | `GenerationRequest.id` (hoy `sol-api-…`). |
| `agent` | `str` | Agente de la etapa. |
| `params` | `GenerationParameters` del paso | Ya existe. Lo usa la regeneración (GEN-R6). Incluye `modality` solo si el docente eligió una (HU-024); los recursos anteriores no la tienen y conservan su comportamiento al exportarse. La regeneración no la comprueba. |
| `generatorKind` | `ia` \| `respaldo` | Ya existe. |
| `evidence` | `list[EvidenceSnapshotItem]` | Es la copia histórica de **todos** los fragmentos referenciados ([research R6](research.md#r6-copia-histórica-de-la-evidencia)). |
| `verification` | `VerificationResult` | Lo calcula `ResourceVerificationPort.verify`. Incluye la huella en `verification.fingerprint` (GEN-R7). |
| `version` | `int` | Empieza en 1 (columna de REV-01) y lo incrementa Revisión en cada guardado. |
| `regeneratedFrom` | `{resourceId, version}` \| ausente | Solo en recursos de un pedido `regeneration`. |

### EvidenceSnapshotItem

Contiene `id`, `text`, `location`, `documentId`, `documentName`, `sourceUrl`, `license` y `retrievedAt`. Se copia de `EvidenceFragment`, donde `id` es `chunkId`.

Los ids referenciados se obtienen con `referenced_fragment_ids(resource)` de REV-01 desde:

- `citations[].fragmentIds`
- `options[].sourceFragmentIds`
- `structure.guidedSteps[].fragmentIds`
- `structure.predictions[].fragmentIds`
- `structure.criteria[].fragmentIds`

### actividad_kinestesica

Tipo nuevo de la etapa Explorar (HU-024, modalidad Kinestésico). Formato `interactive`. La estructura sigue la de `exploracion_guiada`:

| Campo | Tipo | Reglas |
| --- | --- | --- |
| `guidedSteps` | `list[{title, instruction, question, fragmentIds}]` | Mínimo 3 pasos (`MIN_ITEMS`). `question` puede ser la pregunta de cierre del paso, por ejemplo «¿Qué observaron?». Cada paso cita sus fragmentos; la verificación los enlaza como en `exploracion_guiada`. |
| `materials` | `list[str]` | Materiales para la actividad. Puede estar vacía. |
| `estimatedMinutes` | `int` | Tiempo estimado, de 5 a 90 minutos. |
| `space` | `str` | Texto corto: dónde se hace la actividad (aula, patio…). |

Solo los pasos se verifican contra el material. `materials`, `estimatedMinutes` y `space` no se contrastan con la evidencia, pero forman parte de la huella (`content_fingerprint`). La casilla «Lo hicimos» es del paquete SCORM, no del contenido. Los fragmentos de `guidedSteps[].fragmentIds` ya entran en la copia histórica.

### VerificationResult

Es el bloque que define REV-01 en `specs/001-revision-citas/data-model.md`. Generación no agrega campos.

| Campo | Tipo | Reglas |
| --- | --- | --- |
| `status` | `current` \| `insufficient` \| `pending` | Un recurso de GEN-01 llega con `current` o `pending`. Un borrador `insufficient` se rechaza en el paso. |
| `reason` | `str \| null` | Motivo en español. Obligatorio si `status` no es `current`. |
| `fingerprint` | `sha256:<hex>` | `content_fingerprint(resource)` de REV-01. |
| `verifiedVersion` | `int` | `version` del recurso al verificar: 1 al crearlo. |
| `evidenceThreshold` | `float` | Es el valor del pedido. |
| `ruleVersion` | `int` | `VERIFICATION_RULE_VERSION` de `grounding.py`. |
| `checkedAt` | ISO 8601 UTC | — |
| `retryAvailable` | `bool` | `true` solo si `status = pending` y la copia histórica está completa. |
| `summary` | JSON | La misma forma de `ResourceGrounding`. |

## Persistencia

Una migración nueva en `backend/database/migrations/`, con creación equivalente en SQLite como hace hoy `SQLAlchemyGenerationRepository.__init__`:

```text
gen_generation_requests
  id PK, teacher_id NOT NULL, unit_id NOT NULL, mode, idempotency_key NOT NULL, payload_hash NOT NULL,
  parameters JSONB, status, retrieval_mode, evidence JSONB, regeneration JSONB, failure JSONB,
  created_at, started_at, finished_at, heartbeat_at, worker_boot_id
  UNIQUE (teacher_id, idempotency_key)
  INDEX (teacher_id, unit_id, created_at DESC)
  INDEX (status, heartbeat_at)          -- barrido de arranque

gen_generation_steps
  request_id FK → gen_generation_requests ON DELETE CASCADE, position, PK (request_id, position),
  stage, resource_type, agent, status, resource_ids JSONB, rejections JSONB, generator JSONB,
  grounding JSONB, distractor_reliability JSONB, error JSONB, started_at, finished_at
```

Los recursos siguen en `ep002_recursos`, detrás de `ResourceReviewRepositoryPort`. `generaciones_demo` y `ep002_generaciones_docente` quedan en solo lectura. El borrado de un curso, coordinado con CC-01, elimina los pedidos de sus unidades.
