# Research de Generación (GEN-01)

[Ficha](spec.md) · [Plan](plan.md) · [Modelo de datos](data-model.md) · [Contratos](contracts/)

Cada decisión indica qué se eligió, por qué y qué alternativas se descartaron. Las rutas son relativas a `backend/src/platform5e` salvo que se indique otra raíz.

## R1. Evaluación del código existente

| Archivo | Decisión | Motivo |
| --- | --- | --- |
| `application/services/generation/generation_service.py` | **Se adapta y se divide** | La lógica de cada paso sirve: `_draft_resources` (principal y respaldo), `_filter_repeated`, `_build_resource_dict`, `build_grounding_report` y `_save_for_review`. El servicio actual es síncrono, mezcla individual, secuencia y demostración, y consulta `TeacherRepositoryPort`, `ChunkRepositoryPort` y `EvidenceRetrieverPort` directamente. Se reparte en cuatro casos de uso: `StartGenerationRequest`, `RunGenerationRequest`, `GetGenerationRequest` y `StartRegeneration`. Los tres primeros dependen de los puertos de [R5](#r5-puertos-hacia-otros-módulos). El modo `_generate_demo` se retira de este flujo porque entrega recursos sin verificar y sin material procesado, lo que contradice GEN-R4 y GEN-C6. Hay que corregir el armado de evidencia (ver [R6](#r6-copia-histórica-de-la-evidencia)) y reemplazar los `assert` por errores de dominio. |
| `domain/generation/sequence.py` | **Se conserva** con una adición | `order_resource_types`, `stage_agent`, `resource_text`, `most_similar` y `SIMILARITY_THRESHOLD` implementan el orden 5E y el control de repetición vigente (GEN-R2). Se añade `plan_steps(mode, resource_types, quantity)`, que devuelve los pasos ordenados y trata el modo individual como una secuencia de un paso. `MAX_SEQUENCE_TYPES = 8` se mantiene (ver [R4](#r4-límites-de-carga)). |
| `application/services/generation/prompt_drafting.py` | **Se conserva** con una adaptación menor | `build_generation_context`, `build_prompt_instructions`, `structure_from_model` y `normalize_generated_resources` ya resuelven las etiquetas F1…Fn, los fragmentos por paso, predicción y criterio, la verificación de anclaje y la fiabilidad de distractores. Solo cambia la entrada: recibirá `UnitContext` y `EvidenceFragment` de los puertos (o un diccionario construido a partir de ellos) en lugar del curso y la unidad en bruto. |
| `application/services/generation/rule_based_generator.py` | **Se conserva** | Es el respaldo de redacción por reglas detrás de `ResourceGeneratorPort`. Su salida ya pasa por `normalize_generated_resources`, así que recibe la misma verificación. Se agrega una prueba que confirma que un recurso por reglas sin fragmento referenciado llega como `pending` (GEN-C8). |
| `infrastructure/llm/gemini_language_model.py` | **Se conserva** | Es un adaptador limpio de `ResourceGeneratorPort`, con esquema de respuesta, reintento y `LLM_TIMEOUT_SECONDS`. Es síncrono (`httpx.Client`) y por eso funciona dentro del ejecutor por hilos de [R3](#r3-ejecución-en-segundo-plano-y-reinicio). No se cambia. |
| `domain/generation/resource_catalog.py` | **Se conserva** | Es la fuente única de tipos, etapas y formatos, compartida con la interfaz por `GET /resource-types`. Revisión depende de él (spec, dependencias). |
| `domain/generation/resource_formats.py` | **Se conserva** | `normalize_structure`, `structure_problems` y `MIN_ITEMS` definen los mínimos por tipo. Si cambia un mínimo, sube `VERIFICATION_RULE_VERSION` ([R7](#r7-resultado-de-verificación-y-versión-de-reglas)). |
| `domain/generation/grounding.py` | **Se conserva** | Ya contiene `VERIFICATION_RULE_VERSION = 1` (lo agregó REV-01). Contrasta citas, párrafos, pasos, predicciones y criterios (`verify_citations`, `verify_statements`, `link_*_sources`). Su `summary()` alimenta el resumen del resultado de verificación. |
| `domain/generation/distractor_reliability.py` | **Se conserva** | Aplica la regla de fiabilidad de distractores (Constitución III). `reliability_report` sigue en el informe del pedido. |
| `infrastructure/http/routers/generations.py` | **Se reemplaza** | El `POST /api/v1/generations` síncrono no cubre el pedido en segundo plano, la clave de idempotencia ni la consulta por paso, y acepta pedidos anónimos (modo demostración). Se crea `routers/generation_requests.py` con el contrato de [contracts/generation-requests.openapi.yaml](contracts/generation-requests.openapi.yaml). `GET /api/v1/generator` se mueve sin cambios. `POST /api/v1/generations` queda `deprecated` mientras `evaluation/collect_samples.py` y `scripts/export_contracts.py` migran, y se elimina en la misma entrega. `GET /api/v1/generations/{id}` se conserva solo para leer generaciones históricas. |
| `tests/e2e/test_sequence_api.py` | **Se adapta** | Se reutilizan `_unit_with_material` y las aserciones de orden y agente. El flujo pasa a `202` y consulta hasta el estado final. Se agregan los casos GEN-C1 a GEN-C9 (ver [quickstart.md](quickstart.md)). |

Otros archivos afectados:

- `application/ports/outbound/generation_repository_port.py` y `sqlalchemy_generation_repository.py` se sustituyen por `GenerationRequestRepositoryPort` y su adaptador. Las tablas `generaciones_demo` y `ep002_generaciones_docente` quedan en solo lectura para el historial.
- `infrastructure/http/schemas/generations.py` se conserva para los tipos compartidos (`ResourceType`, `Difficulty`, `GroundingReport`, `DistractorReliability`). Se agrega `schemas/generation_requests.py` con los esquemas nuevos.

## R2. Contrato de inicio, consulta e idempotencia

**Decisión.** Se define un recurso REST nuevo, `generation-requests`:

- `POST /api/v1/generation-requests`, con la cabecera obligatoria `Idempotency-Key`, responde `202 Accepted` con el pedido en `queued` y la cabecera `Location`.
- Si llega la misma clave con el mismo contenido, responde `200` con el pedido existente en su estado actual, sin crear otro.
- Si llega la misma clave con otro contenido, responde `409 IDEMPOTENCY_KEY_REUSED`.
- `GET /api/v1/generation-requests/{requestId}` devuelve el estado y los resultados por paso. Un pedido de otro docente o inexistente responde `404 GENERATION_REQUEST_NOT_FOUND`, sin distinguir entre los dos casos.
- `GET /api/v1/generation-requests?unitId=…&active=true` lista los pedidos del docente en la unidad, para recuperar uno cuando el cliente perdió su identificador.
- La regeneración no tiene ruta en Generación. Revisión expone `POST /units/{unitId}/resources/{resourceId}/regenerations` y llama a Generación por su puerto ([R9](#r9-regeneración-y-edición-durante-el-pedido)).

**Alcance de la clave.** La unicidad es `(teacher_id, idempotency_key)`. Dos docentes pueden usar la misma clave sin conflicto, y ninguno puede descubrir el pedido del otro. La clave es una cadena de 8 a 128 caracteres de `[A-Za-z0-9_-]`; el cliente usa `crypto.randomUUID()`. La clave vale mientras exista el pedido; esta entrega no la hace caducar.

**Comparación del contenido.** Se compara `payload_hash`, el SHA-256 del JSON canónico (claves ordenadas, sin espacios) del pedido ya normalizado: valores por defecto aplicados, `resourceTypes` deduplicado en el orden en que se recibió y, en una regeneración, el `resourceId` y la `resourceVersion`. Así, enviar el mismo pedido con y sin un campo por defecto no produce un conflicto.

**Concurrencia.** El adaptador inserta el pedido con una restricción `UNIQUE (teacher_id, idempotency_key)`. Si dos `POST` iguales compiten, el que pierde atrapa la violación, lee el pedido ganador y responde `200` o `409` según el hash.

**Alternativas descartadas.**
- Mantener `POST /generations` y cambiar su respuesta: rompería al único consumidor conocido (el script de evaluación) sin poder anunciarlo, y su `GET` ya devuelve otro esquema.
- Llevar la clave en el cuerpo: la cabecera `Idempotency-Key` es la convención del borrador IETF y separa la clave del contenido que se compara.
- Una clave global: filtraría la existencia de pedidos ajenos (GEN-C5).
- Devolver `202` también en la repetición: el cliente no podría distinguir entre «creado» y «ya existía». Ambos códigos devuelven el mismo cuerpo.

## R3. Ejecución en segundo plano y reinicio

**Decisión.** Se crea un puerto `GenerationJobRunnerPort.submit(request_id)` y un adaptador `ThreadPoolGenerationRunner`, un `ThreadPoolExecutor` con `GENERATION_MAX_WORKERS` hilos (2 por defecto) creado y cerrado en el `lifespan` de FastAPI dentro de `main.py`. Cada tarea ejecuta `RunGenerationRequest(request_id)`, que:

1. Pasa el pedido a `running` y registra `started_at` y `worker_boot_id`.
2. Recupera la evidencia una vez y la guarda en el pedido (GEN-R2).
3. Ejecuta los pasos en orden 5E. Antes de cada paso lo marca `running` y al terminar lo marca `succeeded`, `rejected` o `failed`. Guarda los recursos en Revisión y confirma el paso, en ese orden. Así, el progreso que ve el cliente siempre lo confirmó el servidor (GEN-R3).
4. Actualiza `heartbeat_at` cada 15 s mientras trabaja.
5. Calcula el estado final del pedido ([data-model](data-model.md#reglas-de-transición)).

**Reinicio.** Al arrancar, antes de aceptar tráfico, `main.py` llama a `GenerationRequestRepositoryPort.mark_interrupted(before=now - 60 s)`. Este marca como `interrupted` los pedidos en `queued` o `running` cuyo `heartbeat_at` (o `created_at`, si no tienen latido) sea anterior al límite, y marca como `interrupted` sus pasos no terminados. Los recursos ya guardados se conservan. El límite por latido, en lugar de «todo lo que no terminó», evita que un segundo proceso de uvicorn interrumpa los pedidos vivos de otro.

Un pedido interrumpido no se reanuda. Reenviar su clave lo devuelve tal como quedó. Para reintentar, el docente crea un pedido nuevo, con otra clave, desde la interfaz.

**Alternativas descartadas.**
- `BackgroundTasks` de FastAPI: va ligado a la petición, no permite limitar la concurrencia global y no deja enganche para el arranque.
- Celery, RQ o Arq: requieren Redis y otro proceso, desproporcionado para la carga de [R4](#r4-límites-de-carga). El puerto permite cambiar más adelante sin tocar los casos de uso.
- Reanudar automáticamente los pedidos interrumpidos: duplicaría trabajo del modelo y complica la idempotencia de los recursos. La spec solo exige conservar lo generado y marcar el pedido.

## R4. Límites de carga

**Decisión.** Se mantienen los límites de partida y se agregan límites de concurrencia:

| Límite | Valor | Respuesta si se excede |
| --- | --- | --- |
| Tipos por secuencia | 1 a 8 distintos (`MAX_SEQUENCE_TYPES`) | `422 INVALID_PARAMETERS` |
| Recursos por tipo (`quantity`, común) | 1 a 5 | `422 INVALID_PARAMETERS` |
| Recursos por pedido | máximo 40 (8 × 5) | implícito |
| Llamadas al modelo por paso | máximo 3 (principal, reintento por repetición y respaldo por reglas) | — |
| Pedidos activos por docente | 2 (`queued` o `running`) | `429 TOO_MANY_ACTIVE_REQUESTS` |
| Hilos de ejecución por proceso | 2 (`GENERATION_MAX_WORKERS`) | los pedidos esperan en `queued` |
| Duración máxima de un pedido | 15 min (`GENERATION_REQUEST_DEADLINE_SECONDS`) | los pasos restantes pasan a `failed` con `DEADLINE_EXCEEDED` |

**Validación.** [quickstart.md](quickstart.md#v11--carga) mide una secuencia de 8 tipos × 5 recursos con Gemini y con el generador por reglas. Los límites se confirman si el p95 queda bajo 10 minutos con Gemini. Si no, se baja el tope a 20 recursos por pedido (`quantity × tipos ≤ 20`) y se registra el cambio en la spec.

**Alternativas descartadas.** Cola global sin límite por docente: un docente con varias pestañas acapararía los hilos. Límite de un pedido activo: impediría tener a la vez un pedido de secuencia y una regeneración pedida desde Revisión.

## R5. Puertos hacia otros módulos

Todos se declaran en `application/ports/outbound/` con `Protocol` y se inyectan en `main.py`. Las firmas completas están en [contracts/ports.md](contracts/ports.md).

| Puerto | Módulo dueño | Adaptador inicial | Acuerdo pendiente |
| --- | --- | --- | --- |
| `UnitMembershipPort.get_unit_context(teacher_id, unit_id) -> UnitContext \| None` | CC-01 (Silvana) | `AccountUnitMembershipAdapter` sobre `TeacherRepositoryPort.get_courses` y `find_course_and_unit` | Firma y errores (paso 2 del plan de CC-01). `None` cubre tanto una unidad ajena como una inexistente; Generación responde `404 UNIT_NOT_FOUND` en los dos casos. |
| `EvidenceProviderPort.retrieve(EvidenceQuery) -> EvidenceRetrieval` | MAT-01 (Sergio) | `MaterialEvidenceAdapter` sobre `ChunkRepositoryPort`, `HybridEvidenceRetriever` y `TeacherRepositoryPort.get_documents` | Que `HybridEvidenceRetriever` informe si degradó a BM25 (hoy lo hace en silencio) y que la búsqueda filtre por docente (ver riesgo abajo). |
| `ResourceVerificationPort` (`fingerprint`, `verify`, `referenced_fragment_ids`) | REV-01 (Juan) | `ReviewVerificationAdapter`, que delega en `content_fingerprint.py` y `resource_verification.py` de REV-01 | Las funciones ya existen en `feat/revision-y-exportacion` (D1 y D2 de REV-01). Las tareas que las usan dependen de que se integre su PR 1; no se escriben funciones provisionales. |
| `ResourceRegenerationPort` (`request_regeneration`, `get_regeneration`) | REV-01 (Juan) lo define | `GenerationRegenerationAdapter`, que escribe Generación sobre `StartRegeneration` y `GetGenerationRequest` | Propuesta de REV-01 en su D10. Generación la acepta tal cual ([R9](#r9-regeneración-y-edición-durante-el-pedido)). |

Generación no necesita operaciones nuevas en `ResourceReviewRepositoryPort`. El campo `version` (columna `INTEGER NOT NULL DEFAULT 1`) y el descarte condicional por versión los implementa REV-01 (REV-R12, D10).

**Riesgo de aislamiento (Constitución IV).** `HybridEvidenceRetriever.retrieve` llama a `get_chunks_by_unit("", unit_id)` cuando no recibe fragmentos, y `search_similar_chunks` filtra solo por `unit_id`. El adaptador de Generación siempre pasa los fragmentos del docente, y el puerto exige `teacher_id`. Aun así, se pide a MAT-01 que la búsqueda vectorial filtre por docente, y se agrega una prueba de integración con dos docentes.

**Alternativas descartadas.** Importar directamente `AccountService` o `MaterialService`: acoplaría casos de uso de módulos distintos y lo impide la prueba de arquitectura. Llamar a las funciones de verificación desde el dominio de Generación sin puerto: técnicamente posible, porque son dominio puro, pero el puerto permite que Revisión cambie la normalización sin coordinar importaciones. Escribir una verificación propia en Generación: duplicaría `verify_resource` y los dos módulos podrían dar resultados distintos para el mismo recurso.

## R6. Copia histórica de la evidencia

**Problema.** `_save_for_review` y el cálculo de `step_chunks` solo reúnen los ids de `citations[].fragmentIds` y `options[].sourceFragmentIds`. Los fragmentos citados por `structure.guidedSteps[]`, `structure.predictions[]` y `structure.criteria[]` (HU-048, HU-047, HU-050) quedan fuera de la copia. Además, `step_chunks` se filtra con ese mismo conjunto incompleto, de modo que el fragmento tampoco llega aunque se agregue el id.

**Decisión.** Se usa `referenced_fragment_ids(resource)` de REV-01 (`domain/review/resource_verification.py`), por `ResourceVerificationPort`. Reúne, sin repetir y en orden de aparición, los ids de citas, alternativas y de cualquier `fragmentIds` de la estructura (pasos guiados, predicciones y criterios). La usan tanto el filtrado de fragmentos del paso como la copia histórica, en lugar de las dos comprensiones duplicadas. Así Generación copia exactamente los fragmentos que Revisión exigirá al verificar.

La copia (`EvidenceSnapshot`) guarda por fragmento: `id`, `text`, `location`, `documentId`, `documentName`, `sourceUrl`, `license` y `retrievedAt`. Si algún id referenciado no está entre los fragmentos recuperados, `verify_resource` deja el recurso en `pending` con el motivo de copia incompleta (`incomplete_copy_reason`) y `retryAvailable = false` (GEN-R8, GEN-C8).

**Procedencia.** MAT-01 entrega `sourceUrl` y `license` por fragmento, tomados de `document.origin`. Para un archivo subido por el docente, los dos son `null`. `retrievedAt` es el instante en que Generación recuperó la evidencia del pedido: es único por pedido y coincide con el contenido copiado. La fecha del documento sigue disponible por `documentId`.

**Alternativa descartada.** Que `retrievedAt` sea la fecha en que Material obtuvo el documento: el puerto de Material hoy no la expone de forma uniforme para archivos y fuentes abiertas, y lo que la copia histórica debe fechar es el texto que se usó.

## R7. Resultado de verificación y versión de reglas

**Decisión.** Generación no escribe una verificación propia. Al terminar cada borrador, y después de armar la copia histórica, llama a `ResourceVerificationPort.verify(resource, threshold)`, que delega en `verify_resource` de REV-01 con `VERIFICATION_RULE_VERSION` de `grounding.py`. El resultado es el bloque `verification` que define REV-01 en su data-model ([data-model](data-model.md#verificationresult)): `status`, `reason`, `fingerprint`, `verifiedVersion`, `evidenceThreshold`, `ruleVersion`, `checkedAt`, `retryAvailable` y `summary`. Los valores técnicos del estado están en inglés (`current`, `insufficient`, `pending`) y la interfaz los muestra como vigente, insuficiente y pendiente.

| Resultado | Condición |
| --- | --- |
| Rechazado (no llega a revisión) | `grounding` no acepta el borrador (menos del 50 % de afirmaciones con respaldo), la estructura no alcanza `MIN_ITEMS`, se repite con otro recurso del pedido tras el reintento, o `verify` devuelve `insufficient`. Se informa en `step.rejections`. |
| `pending` | `verify` devuelve `pending`: falta algún fragmento referenciado en la copia o la comprobación no pudo terminar. También si `verify` lanza un error; el paso guarda el recurso con `status = pending` y el motivo. |
| `current` | `verify` devuelve `current`. |

Así, los recursos de GEN-01 llegan a Revisión como vigentes o pendientes (GEN-R4), y vale igual para el generador por reglas (GEN-C8). `VERIFICATION_RULE_VERSION` vive en `grounding.py`, que es de Generación: quien cambie un umbral o mínimo de ese archivo o de `MIN_ITEMS` la sube en el mismo commit. Sin edición, el resultado no se recalcula (GEN-R7, REV-C10).

**Por confirmar con REV-01:** que los recursos que ya traen `verification` con la huella vigente no se vuelvan a verificar al leerlos. La lectura con verificación de su adaptador provisional queda solo para recursos sin `verification` (REV-R11).

## R8. Respaldo de búsqueda y de redacción

**Decisión.** Se informan como dos campos independientes:

- `retrievalMode` del pedido: `hybrid` o `bm25_fallback`, tal como lo devuelve el puerto de Material (GEN-C9).
- `generator` de cada paso: `{ description, usesAi, fallback }`. `fallback = true` significa que redactó el generador por reglas tras fallar el modelo.

La interfaz muestra un aviso distinto para cada caso. Se descarta un único campo `fallback`, porque mezclaría dos degradaciones con consecuencias distintas para el docente.

## R9. Regeneración y edición durante el pedido

**Decisión.** Se adopta la propuesta D10 de REV-01. Revisión define `application/ports/outbound/resource_regeneration_port.py`, expone la ruta `POST /units/{unitId}/resources/{resourceId}/regenerations` con `expectedVersion` y decide qué pasa con el recurso anterior. Generación escribe el adaptador `GenerationRegenerationAdapter`, que reemplaza el adaptador síncrono provisional de Revisión:

- `request_regeneration(teacher_id, resource_id, resource_version, params)` llama a `StartRegeneration`. Crea un pedido en modo `regeneration` de un paso, con los `params` guardados y la evidencia actual del material, no la copia histórica (GEN-R6). La clave de idempotencia es `regen-{resource_id}-v{resource_version}`, única por docente: pedir dos veces la misma versión devuelve el mismo pedido y no duplica recursos.
- `get_regeneration(teacher_id, request_id)` llama a `GetGenerationRequest` y traduce el estado: `queued` → `pending`; `running` → `running`; `succeeded` → `succeeded`; `failed` o `interrupted` → `failed`, con `reason`. Devuelve `new_resource_ids`.
- Cada recurso nuevo se guarda con `version = 1`, su `verification` completo, `evidence[].retrievedAt` y `regeneratedFrom: {resourceId, version}`, que escribe Generación porque es quien lo crea.
- Generación no descarta ni modifica el recurso anterior. Cuando Revisión ve `succeeded`, lo pasa a `descartado` con `discardReason = "regenerado"` solo si sigue en la versión registrada. Si el docente lo editó mientras tanto, quedan los dos en revisión (REV-C12). Si la regeneración falla, el anterior queda igual (REV-C13).
- Un recurso antiguo sin `params` no se puede regenerar: `StartRegeneration` lanza `REGENERATION_UNAVAILABLE` y el adaptador devuelve `failed` con el motivo.

**Alternativas descartadas.** Una ruta de regeneración propia de Generación con `discard_if_version`: obligaba a Generación a modificar recursos de Revisión y duplicaba la ruta que REV-01 ya expone. Una llamada de vuelta de Generación a Revisión al terminar: crearía una dependencia en sentido contrario.

## R10. Frontend

**Decisión.** El frontend ya tiene en `main` la base de CC-01: React 18, TypeScript, Vite y React Router, con `src/app`, `src/shared/api/httpClient.ts`, `src/shared/types/courses.ts`, Vitest, ESLint y su CI. La ruta `/courses/:courseId/units/:unitId/generation` existe y `src/features/generation/pages/GenerationPage.tsx` es un marcador. `UnitLayout` entrega `course`, `unit`, `token` y `onSessionExpired` por el contexto del `Outlet`. Generación trabaja solo en `src/features/generation`:

- `api/generationApi.ts` usa el cliente compartido `request` de `httpClient.ts`.
- `model/` define a mano los tipos del pedido y de los pasos según `docs/api/openapi.json`. No se agrega un generador de tipos, para no sumar una herramienta que el equipo no usa. Si el contrato cambia, se actualizan en el mismo PR.
- `useStartGeneration` crea la clave con `crypto.randomUUID()` y la guarda en `sessionStorage`, junto al pedido y su `requestId`, por unidad, antes de enviar. Si la red falla, reenvía la misma clave.
- `useGenerationRequest(requestId)` consulta cada 2 s, con espera creciente hasta 10 s, y se detiene en un estado final.
- Al montar la página, recupera el pedido guardado o, si no hay ninguno, consulta `GET /generation-requests?unitId=…&active=true`.
- Componentes: selector de modo individual o secuencia, lista de pasos en orden 5E con el estado del servidor, y rechazos con su motivo.
- Las pruebas de `api/` y `model/` usan Vitest, como `coursesApi.test.ts`.

**Ajuste compartido.** Hoy `request` no permite enviar cabeceras propias ni expone el código de estado ni el `code` del error. Generación necesita enviar `Idempotency-Key`, distinguir `202` de `200` y reconocer `409 IDEMPOTENCY_KEY_REUSED` y `429 TOO_MANY_ACTIVE_REQUESTS`. Se propone a CC-01 un parámetro opcional de cabeceras y que `ApiError` incluya `code`, sin cambiar las llamadas existentes. El cambio se hace en un PR coordinado y no dentro de la carpeta de Generación.

**Alternativas descartadas.** SSE o WebSocket: el proxy y la recuperación tras recargar son más frágiles, y la consulta periódica basta para pedidos de minutos. Generar la clave en el servidor: no permitiría reintentar un `POST` cuya respuesta se perdió. Un cliente HTTP propio de Generación: duplicaría el manejo de sesión y errores del cliente compartido.
