# Modelo de datos de Generación (GEN-01)

[Ficha](spec.md) · [Plan](plan.md) · [Research](research.md) · [Contratos](contracts/)

Los nombres de campo siguen la convención del backend: snake_case en Python y en las columnas nuevas, y camelCase en JSON. Los estados del pedido y de los pasos son códigos nuevos en inglés. Los estados de verificación (`vigente`, `pendiente`, `insuficiente`) se guardan en español porque los comparte Revisión, igual que los estados de revisión actuales.

## GenerationRequest

Es el pedido persistido. Lo crea `StartGenerationRequest` o `RegenerateResource` y lo actualiza `RunGenerationRequest`.

| Campo | Tipo | Reglas |
| --- | --- | --- |
| `id` | `str` | `gen-req-{uuid4}`. Es la clave primaria. |
| `teacher_id` | `str` | Es obligatorio y es el docente autenticado. |
| `unit_id` | `str` | La unidad debe pertenecer al docente según `UnitMembershipPort` al crearse el pedido. |
| `mode` | `individual` \| `sequence` \| `regeneration` | `individual` tiene un tipo; `sequence` tiene entre 1 y 8 tipos; `regeneration` se crea desde Revisión. |
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
| `difficulty`, `optionCount`, `topK`, `evidenceThreshold`, `instructions`, `audience`, `competency`, `modalities` | — | Tienen los mismos rangos que hoy tiene `GenerationRequest` en `schemas/generations.py`. |

### RegenerationTarget

| Campo | Tipo | Reglas |
| --- | --- | --- |
| `resourceId` | `str` | Es el recurso de Revisión que pertenece al docente y a la unidad. |
| `expectedVersion` | `int` | Debe coincidir con la versión actual al crear el pedido (`409 RESOURCE_VERSION_CHANGED`). |
| `outcome` | `replaced` \| `kept_version_changed` \| `kept_failed` \| `null` | Lo fija el paso al terminar ([research R9](research.md#r9-edición-durante-una-regeneración)). |

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

- `succeeded`: al menos un recurso se entregó a Revisión, como `vigente` o `pendiente`.
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
| `params` | `GenerationParameters` del paso | Ya existe. Lo usa la regeneración (GEN-R6). |
| `generatorKind` | `ia` \| `respaldo` | Ya existe. |
| `evidence` | `list[EvidenceSnapshotItem]` | Es la copia histórica de **todos** los fragmentos referenciados ([research R6](research.md#r6-copia-histórica-de-la-evidencia)). |
| `contentFingerprint` | `str` | La calcula `ContentFingerprintPort` (GEN-R7). |
| `verification` | `VerificationResult` | — |
| `version` | `int` | Empieza en 1 y lo incrementa Revisión en cada edición (acuerdo con REV-01). |

### EvidenceSnapshotItem

Contiene `id`, `text`, `location`, `documentId`, `documentName`, `sourceUrl`, `license` y `retrievedAt`. Se copia de `EvidenceFragment`, donde `id` es `chunkId`.

Los ids referenciados se obtienen con `referenced_fragment_ids(resource)` desde:

- `citations[].fragmentIds`
- `options[].sourceFragmentIds`
- `structure.guidedSteps[].fragmentIds`
- `structure.predictions[].fragmentIds`
- `structure.criteria[].fragmentIds`

### VerificationResult

| Campo | Tipo | Reglas |
| --- | --- | --- |
| `status` | `vigente` \| `pendiente` | Generación no emite `insuficiente`. |
| `evidenceThreshold` | `float` | Es el valor del pedido. |
| `ruleVersion` | `int` | `VERIFICATION_RULE_VERSION`. |
| `checkedAt` | ISO 8601 UTC | — |
| `reasons` | `list[{code, message}]` | Va vacío en `vigente`. Los códigos posibles son `MISSING_REFERENCED_FRAGMENT`, `NO_VERIFIABLE_CLAIMS`, `CHECK_NOT_COMPLETED` y `BELOW_THRESHOLD`. |
| `summary` | JSON | `grounding.summary()`, los resúmenes de `link_*_sources` y la fiabilidad de distractores. |

`BELOW_THRESHOLD` se aplica cuando `supportedClaims / checkedClaims` del recurso, incluidas las afirmaciones quitadas, es menor que `evidenceThreshold`, aunque llegue al 50 % que exige `grounding` para no rechazarlo.

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
