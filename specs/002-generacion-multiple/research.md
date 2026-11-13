# Research de Generación (GEN-01)

[Ficha](spec.md) · [Plan](plan.md) · [Modelo de datos](data-model.md) · [Contratos](contracts/)

Cada decisión indica qué se eligió, por qué y qué alternativas se descartaron. Las rutas son relativas a `backend/src/platform5e` salvo que se indique otra raíz.

## R1. Evaluación del código existente

| Archivo | Decisión | Motivo |
| --- | --- | --- |
| `application/services/generation/generation_service.py` | **Se adapta y se divide** | La lógica de cada paso sirve: `_draft_resources` (principal y respaldo), `_filter_repeated`, `_build_resource_dict`, `build_grounding_report` y `_save_for_review`. El servicio actual es síncrono, mezcla individual, secuencia y demostración, y consulta `TeacherRepositoryPort`, `ChunkRepositoryPort` y `EvidenceRetrieverPort` directamente. Se reparte en cuatro casos de uso: `StartGenerationRequest`, `RunGenerationRequest`, `GetGenerationRequest` y `StartRegeneration`. **T046 lo retiró**; la redacción de cada paso quedó en `step_drafting.py`. Los tres primeros dependen de los puertos de [R5](#r5-puertos-hacia-otros-módulos). El modo `_generate_demo` se retira de este flujo porque entrega recursos sin verificar y sin material procesado, lo que contradice GEN-R4 y GEN-C6. Hay que corregir el armado de evidencia (ver [R6](#r6-copia-histórica-de-la-evidencia)) y reemplazar los `assert` por errores de dominio. |
| `domain/generation/sequence.py` | **Se conserva** con una adición | `order_resource_types`, `stage_agent`, `resource_text`, `most_similar` y `SIMILARITY_THRESHOLD` implementan el orden 5E y el control de repetición vigente (GEN-R2). Se añade `plan_steps(mode, resource_types, quantity)`, que devuelve los pasos ordenados y trata el modo individual como una secuencia de un paso. `MAX_SEQUENCE_TYPES = 8` se mantiene (ver [R4](#r4-límites-de-carga)). |
| `application/services/generation/prompt_drafting.py` | **Se conserva** con una adaptación menor | `build_generation_context`, `build_prompt_instructions`, `structure_from_model` y `normalize_generated_resources` ya resuelven las etiquetas F1…Fn, los fragmentos por paso, predicción y criterio, la verificación de anclaje y la fiabilidad de distractores. Solo cambia la entrada: recibirá `UnitContext` y `EvidenceFragment` de los puertos (o un diccionario construido a partir de ellos) en lugar del curso y la unidad en bruto. |
| `application/services/generation/rule_based_generator.py` | **Se conserva** | Es el respaldo de redacción por reglas detrás de `ResourceGeneratorPort`. Su salida ya pasa por `normalize_generated_resources`, así que recibe la misma verificación. Se agrega una prueba que confirma que un recurso por reglas sin fragmento referenciado llega como `pending` (GEN-C8). |
| `infrastructure/llm/gemini_language_model.py` | **Se conserva** | Es un adaptador limpio de `ResourceGeneratorPort`, con esquema de respuesta, reintento y `LLM_TIMEOUT_SECONDS`. Es síncrono (`httpx.Client`) y por eso funciona dentro del ejecutor por hilos de [R3](#r3-ejecución-en-segundo-plano-y-reinicio). No se cambia. |
| `domain/generation/resource_catalog.py` | **Se conserva** | Es la fuente única de tipos, etapas y formatos, compartida con la interfaz por `GET /resource-types`. Revisión depende de él (spec, dependencias). |
| `domain/generation/resource_formats.py` | **Se conserva** | `normalize_structure`, `structure_problems` y `MIN_ITEMS` definen los mínimos por tipo. Si cambia un mínimo, sube `VERIFICATION_RULE_VERSION` ([R7](#r7-resultado-de-verificación-y-versión-de-reglas)). |
| `domain/generation/grounding.py` | **Se conserva** | Ya contiene `VERIFICATION_RULE_VERSION = 1` (lo agregó REV-01). Contrasta citas, párrafos, pasos, predicciones y criterios (`verify_citations`, `verify_statements`, `link_*_sources`). Su `summary()` alimenta el resumen del resultado de verificación. |
| `domain/generation/distractor_reliability.py` | **Se conserva** | Aplica la regla de fiabilidad de distractores (Constitución III). `reliability_report` sigue en el informe del pedido. |
| `infrastructure/http/routers/generations.py` | **Se reemplaza** | El `POST /api/v1/generations` síncrono no cubre el pedido en segundo plano, la clave de idempotencia ni la consulta por paso, y acepta pedidos anónimos (modo demostración). Se crea `routers/generation_requests.py` con el contrato de [contracts/generation-requests.openapi.yaml](contracts/generation-requests.openapi.yaml). `GET /api/v1/generator` se mueve sin cambios. `POST /api/v1/generations` quedó `deprecated` mientras `evaluation/collect_samples.py` y `scripts/export_contracts.py` migraban (T045) y **T046 lo retiró**. `GET /api/v1/generations` y `GET /api/v1/generations/{id}` se conservan solo para leer generaciones históricas; desde T046 ese historial es de Cuentas (`AccountService` y `SQLAlchemyAccountRepository`). |
| `tests/e2e/test_sequence_api.py` | **Se adapta** | Se reutilizan `_unit_with_material` y las aserciones de orden y agente. El flujo pasa a `202` y consulta hasta el estado final. Se agregan los casos GEN-C1 a GEN-C9 (ver [quickstart.md](quickstart.md)). |

Otros archivos afectados:

- `application/ports/outbound/generation_repository_port.py` y `sqlalchemy_generation_repository.py` se sustituyen por `GenerationRequestRepositoryPort` y su adaptador. Las tablas `generaciones_demo` y `ep002_generaciones_docente` quedan en solo lectura para el historial. **T046 los retiró** (PR #22 y PR #24 con CC-01): Cuentas siembra el curso de demostración desde `persistence/seed/demo_generation.json` y es dueña de las clases ORM del historial y de la pertenencia, con las que lee `GET /api/v1/generations` y `GET /api/v1/generations/{id}`.
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

**Comparación del contenido.** Se compara `payload_hash`, el SHA-256 del JSON canónico (claves ordenadas, sin espacios) del pedido ya normalizado. Incluye el `mode`, el `unitId` y los parámetros, con los valores por defecto aplicados y `resourceTypes` deduplicado en el orden en que se recibió; en una regeneración, también el `resourceId` y la `resourceVersion`. Así, enviar el mismo pedido con y sin un campo por defecto no produce un conflicto, pero reutilizar la clave con los mismos parámetros en otra unidad o en otro modo sí responde `409 IDEMPOTENCY_KEY_REUSED`. La modalidad no tiene valor por defecto en el servidor: omitirla y enviar `["Textual"]` producen hashes distintos ([R11](#r11-modalidades-hu-024)).

**Orden de las comprobaciones.** El inicio valida primero la clave y la pertenencia de la unidad, y después busca la clave. Si ya tiene un pedido, lo devuelve (mismo hash) o responde el conflicto (otro hash) sin aplicar las demás reglas: un pedido aceptado se recupera aunque la unidad se haya quedado sin material o el docente ya tenga dos pedidos activos. Solo un pedido nuevo pasa por el resultado de aprendizaje, el plan de pasos, el material procesado y el límite de pedidos activos.

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
4. Calcula el estado final del pedido ([data-model](data-model.md#reglas-de-transición)).

**Pedido borrado durante la ejecución.** Si el docente borra el curso mientras se genera, `delete_course` elimina el pedido y sus pasos (T047). El ejecutor no debe recrearlos ni dejar recursos sueltos:

- `save_evidence`, `update_step`, `heartbeat` y `finish` solo actualizan filas existentes (`UPDATE`, nunca `INSERT`) y devuelven si el pedido existía. `update_step` exige que existan el pedido y el paso.
- Cada paso escribe en este orden:
  1. Marca el paso como `running` (`update_step`).
  2. Redacta y verifica los recursos. No escribe nada.
  3. Comprueba que el pedido sigue existiendo y que la unidad sigue siendo del docente.
  4. Genera la imagen o el audio de los recursos que se entregan, **sin guardarlos** (`generate_media`).
  5. Vuelve a comprobar el pedido y la unidad: la multimedia pudo tardar.
  6. Guarda la multimedia (`MediaRepositoryPort.save_media`) y después los recursos (`save_resources`).
  7. Confirma el paso (`update_step`). Es la última escritura del paso.
- Si una comprobación falla porque el pedido ya no existe, el paso se detiene sin escribir nada más. Si el pedido existe pero la unidad ya no es del docente, el pedido se cierra como `failed` con `UNIT_NOT_FOUND`, sin guardar recursos ni multimedia.
- Si la confirmación devuelve que el pedido ya no existe (el curso se borró entre el paso 5 y el 7), quita lo que ese paso guardó: los recursos de Revisión y sus archivos de `media_assets` (`MediaRepositoryPort.delete_media`).
- Si el guardado del paso 6 falla a medias, quita también lo que alcanzó a guardar, y el paso queda `failed`.
- `save_media` solo se llama en el paso 6. «Generar de nuevo» en Revisión y la generación anterior siguen usando `attach_generated_media`, fuera de los pedidos.

**Latido.** El ejecutor (`ThreadPoolGenerationRunner`) renueva `heartbeat_at` cada 15 s de **todos** los pedidos que tiene en su cola o en ejecución, y lo hace también al recibirlos. Así un pedido que espera un hilo libre tiene dueño, aunque todavía no haya empezado.

**Reinicio y pedidos sin dueño.** Un pedido activo sin latido reciente no tiene dueño: lo dejó un proceso que se reinició o se detuvo. `GenerationRequestRepositoryPort.mark_interrupted(stale_before)` marca como `interrupted` los pedidos en `queued` o `running` cuyo `heartbeat_at` (o `created_at`, si no tienen latido) sea anterior al límite, y marca como `interrupted` sus pasos no terminados. Los recursos ya guardados se conservan. Se llama en dos momentos, siempre con `stale_before = ahora − 60 s`:

- **Barrido de arranque:** en el `lifespan`, antes de aceptar tráfico.
- **Barrido periódico:** `StaleRequestSweeper`, cada `GENERATION_SWEEP_INTERVAL_SECONDS` (30 s por defecto), mientras la API está en marcha. Se inicia en el `lifespan` junto al ejecutor y se detiene al apagar. Cubre el pedido que el barrido de arranque no alcanza: uno que quedó en cola menos de 60 s antes del arranque se interrumpe en cuanto vence su plazo, sin otro reinicio.

El límite por latido, en lugar de «todo lo que no terminó», evita que un proceso de uvicorn interrumpa los pedidos vivos de otro: el ejecutor dueño renueva su latido cada 15 s, muy por debajo de los 60 s.

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

**Cupo atómico.** Contar los pedidos activos y después guardar el nuevo deja una carrera: con un pedido activo, dos envíos simultáneos con claves distintas cuentan 1 los dos y se aceptan los dos (tres activos). Por eso el repositorio comprueba el cupo y registra el pedido en una sola operación, `create_within_limit(request, max_active)`, serializada por docente:

- **PostgreSQL:** `pg_advisory_xact_lock(hashtextextended('gen_generation_requests:' || teacher_id, 0))` al empezar la transacción. El bloqueo dura hasta el `COMMIT` y solo afecta a los envíos del mismo docente.
- **SQLite:** la transacción empieza con `BEGIN IMMEDIATE`, que toma el bloqueo de escritura antes de contar. El otro envío espera el `busy timeout` en vez de leer el mismo recuento.

Dentro de la transacción se aplica primero la clave: si `(teacher_id, idempotency_key)` ya existe, lanza `IdempotencyKeyTaken(existing)` aunque el cupo esté lleno, y el reenvío devuelve el pedido como siempre. Después vuelve a comprobar la unidad con `unit_still_owned()`: si el curso se borró después de que `StartGenerationRequest` validara la unidad, lanza `UnitNoLongerOwned` sin insertar nada, y el caso de uso responde `UNIT_NOT_FOUND`. Si no, cuenta los pedidos en `queued` o `running`. Si llegan a `max_active`, lanza `ActiveRequestLimitReached`, que `StartGenerationRequest` traduce a `429 TOO_MANY_ACTIVE_REQUESTS`. Si no, inserta el pedido con sus pasos. La violación de la clave única sigue tratándose como `IdempotencyKeyTaken`.

**Alta y borrado del curso (T047).** `delete_course` toma el mismo bloqueo por docente al empezar su transacción en PostgreSQL; en SQLite su transacción de escritura ya espera la del alta. Así, si el borrado llega antes, el alta ve la unidad borrada y no guarda nada. Si llega después, espera a que el alta confirme y elimina el pedido recién guardado con sus pasos.

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
- **Reintento después de un fallo.** Si el último intento de esa versión terminó `failed` o `interrupted`, o terminó bien pero el docente ya borró todos sus recursos nuevos, `StartRegeneration` crea otro con la clave siguiente: `regen-{resource_id}-v{resource_version}-r2`, `-r3`… Si el último intento sigue en curso o terminó `succeeded` con algún recurso nuevo en Revisión, devuelve ese mismo pedido sin crear otro. Así un fallo después de crear el pedido (por ejemplo, la IA no citó el material) no deja la versión bloqueada, y dos reintentos simultáneos comparten el mismo intento nuevo porque la clave es la misma. Después de 20 intentos fallidos de una versión responde `REGENERATION_ATTEMPTS_EXHAUSTED`. Un rechazo al iniciar (`NO_PROCESSED_MATERIAL`, `TOO_MANY_ACTIVE_REQUESTS`…) no crea pedido ni consume un intento.
- `request_regeneration` espera el resultado hasta `GENERATION_REGENERATION_WAIT_SECONDS` (10 s por defecto) consultando el pedido. Si termina, devuelve `succeeded` o `failed`; si no, `pending` o `running`, y Revisión sigue con `get_regeneration`. Con 0 responde enseguida con el estado al crear el pedido.
- `get_regeneration(teacher_id, request_id)` llama a `GetGenerationRequest` y traduce el estado: `queued` → `pending`; `running` → `running`; `succeeded` → `succeeded`; `failed` o `interrupted` → `failed`, con `reason`. Devuelve en `new_resource_ids` solo los recursos nuevos que siguen en Revisión; si el pedido terminó bien pero el docente los borró todos, devuelve `failed` con `REGENERATED_RESOURCE_NOT_FOUND`. Revisión repite esa comprobación al ver `succeeded`, porque el borrado puede ocurrir entre la respuesta y el descarte.
- Si una consulta del pedido falla de forma inesperada cuando el pedido ya existe, el adaptador la registra y devuelve el último estado conocido (`pending` o `running`) con el id del pedido. Así Revisión guarda el `requestId` y sigue con `get_regeneration`, en vez de quedar en `running` sin pedido.
- Cada recurso nuevo se guarda con `version = 1`, su `verification` completo, `evidence[].retrievedAt` y `regeneratedFrom: {resourceId, version}`, que escribe Generación porque es quien lo crea.
- Generación no descarta ni modifica el recurso anterior. Cuando Revisión ve `succeeded`, lo pasa a `descartado` con `discardReason = "regenerado"` solo si sigue en la versión registrada. Si el docente lo editó mientras tanto, quedan los dos en revisión (REV-C12). Si la regeneración falla, el anterior queda igual (REV-C13).
- Un recurso antiguo sin `params` no se puede regenerar: `StartRegeneration` lanza `REGENERATION_PARAMETERS_MISSING` y el adaptador devuelve `failed` con el motivo.
- **Códigos de rechazo de la regeneración** (acordados con REV-01): `REGENERATION_PARAMETERS_MISSING` (422: sin `params` o sin `resourceType`), `REGENERATION_TARGET_INVALID` (422: id o versión del recurso no válidos) y `REGENERATION_ATTEMPTS_EXHAUSTED` (409: se agotaron los intentos de la versión). El adaptador los devuelve en `RegenerationStatus.code` y **Revisión asigna el estado HTTP** de su ruta; los estados indicados son los previstos para el PR de cierre de REV-01. `REGENERATION_UNAVAILABLE` queda solo para el 503 propio de Revisión («la regeneración no está disponible en el servidor»).

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

## R11. Modalidades (HU-024)

**Decisión.** Acordada con CC-01 (Silvana, frontend) y REV-01 (Juan). Una modalidad es un grupo de tipos de recurso, no un modo distinto de generar: cada paso sigue siendo un tipo en su etapa 5E, con la misma redacción, verificación y copia histórica. Las modalidades son Textual, Gamificado, Multimedia y Kinestésico, y sus tipos están en `MODALITY_TYPES` de `domain/generation/resource_formats.py` ([data-model](data-model.md#modality_types)):

- **Textual:** los tipos que se leen o se responden por escrito (`pregunta_detonante`, `sondeo_diagnostico`, `guia_exploracion`, `caso_indagacion`, `exploracion_guiada`, `explicacion`, `glosario`, `ejercicio_aplicacion`, `caso_aplicado` e `item_opcion_multiple`). `exploracion_guiada` y `caso_aplicado` son interactivos, pero se responden por escrito y deben poder elegirse con «Textual», la modalidad por defecto del selector.
- **Gamificado:** `reto_prediccion`, `emparejamiento`, `ordenar_pasos`, `verdadero_falso`, `completar_espacios` e `item_opcion_multiple`.
- **Multimedia:** `imagen_ilustrativa`, `audio_detonante`, `podcast_resumen`, `diagrama_proceso`, `mapa_conceptual` e `infografia`.
- **Kinestésico:** el tipo nuevo `actividad_kinestesica`.

Un tipo puede estar en más de una modalidad: `item_opcion_multiple` está en Textual y en Gamificado. Todo tipo del catálogo pertenece al menos a una modalidad.

- **Catálogo.** `GET /api/v1/resource-types` agrega a cada tipo la lista `modalities` que lo incluye, y el frontend filtra con ella el selector de tipos. El valor por defecto «Textual» vive en el selector del frontend, no en el servidor.
- **Contrato.** `modalities` sigue siendo una lista opcional, con los cuatro valores y como máximo un elemento: una modalidad por pedido. El servidor deja de aplicar `["Textual"]` por defecto. La respuesta conserva su forma: `parameters.modalities` es una lista de 0 o 1 modalidad, vacía si el pedido no la envió, así que no cambia para los clientes actuales (`generationRequest.ts` del frontend lee `parameters.modalities`). Internamente, el dominio y los parámetros guardados usan el campo singular `modality` (`str | None`).
- **Validación.** Si el pedido envía `modalities`, cada tipo de `resourceTypes` debe pertenecer a esa modalidad; si no, responde `422 RESOURCE_TYPE_NOT_IN_MODALITY` sin crear el pedido. Se comprueba junto con el plan de pasos, después de buscar la clave ([R2](#r2-contrato-de-inicio-consulta-e-idempotencia)): reenviar un pedido ya aceptado lo devuelve sin volver a validar. Si el pedido no envía `modalities`, se mantiene el comportamiento actual: no se filtran los tipos y el pedido se guarda sin modalidad.
- **Huella del pedido.** `payload_hash` incluye `modality`, que es `null` si no se envió. Un pedido creado antes del cambio guardó `["Textual"]` (el valor por defecto del servidor); si el cliente lo reintenta con la misma clave después del despliegue y sin `modalities`, el hash cambia y responde `409 IDEMPOTENCY_KEY_REUSED`. Es un caso de borde del despliegue: los pedidos duran minutos y el docente puede crear uno nuevo.
- **Regeneración.** No comprueba la modalidad: regenera un recurso que ya existe, con su propio tipo y la `modality` guardada si la tiene. Los recursos anteriores guardan `modalities: ["Textual"]`, que se lee como «sin modalidad». Prueba obligatoria: regenerar una imagen y un audio antiguos guardados con `["Textual"]` sigue funcionando.
- **Dónde se guarda.** Si el docente eligió una modalidad, se guarda en el campo singular `modality` de los parámetros del pedido y de los `params` de cada recurso. Los recursos sin ese campo (todos los existentes) conservan su comportamiento al exportarse. El ítem de opción múltiple tiene el mismo contenido, las mismas citas y la misma verificación en Textual y en Gamificado.
- **Instrucción al modelo.** Si el pedido trae modalidad, el prompt agrega una línea con su intención (por ejemplo, en Kinestésico, una actividad para hacer con el cuerpo en el aula). No cambia las reglas de citas ni de formato del tipo.
- **Actividad kinestésica.** Usa la estructura de `exploracion_guiada`: `guidedSteps` con `title`, `instruction`, `question` (opcional, por ejemplo «¿Qué observaron?») y `fragmentIds`, con un mínimo de 3 pasos. A nivel del recurso agrega `materials` (lista de textos, puede estar vacía), `estimatedMinutes` (entero de 5 a 90) y `space` (texto corto). Solo los pasos se verifican contra el material, cada uno con sus fragmentos; materiales, tiempo y espacio no se contrastan con la evidencia, pero entran en la huella. La casilla «Lo hicimos» es del paquete SCORM, no del contenido. El generador por reglas tiene un redactor para este tipo. Agregar el tipo no cambia las reglas de los tipos existentes, así que no se espera subir `VERIFICATION_RULE_VERSION`; Juan lo confirma en T059.

**Decisión abierta de REV-01.** Si en SCORM un ítem de opción múltiple se muestra como cuestionario simple, sin puntos, cuando `modality` es explícitamente «Textual». La decide Juan, en este sprint o en el sprint 2; no es un requisito de GEN-01. Hoy todos los ítems van a la evaluación por niveles.

**Fuera de esta entrega.** Moodle XML sigue exportando solo el ítem de opción múltiple; verdadero o falso y relacionar quedan para el sprint 2 (REV-01). La verificación del guion de audio oración por oración es una tarea aparte de REV-01 para el sprint 2 y sube `VERIFICATION_RULE_VERSION`.

**Alternativas descartadas.** Selección múltiple de modalidades: obliga a normalizar el orden para el hash, a validar contra la unión de grupos y a un selector más complejo, y una clase suele tener una sola modalidad; se puede revisar después sin cambiar el contrato, que ya es una lista. La modalidad como modo del generador: duplicaría instrucciones, verificación y exportación por modalidad, cuando el tipo ya define el formato y la etapa. Kinestésico como un grupo de tipos existentes (`ordenar_pasos`, `emparejamiento`, `exploracion_guiada`, `caso_aplicado`): son actividades en pantalla, no con el cuerpo, y al docente le faltarían los materiales, el tiempo y el espacio.
