# Tareas de Generación

[Ficha GEN-01](spec.md) · [Plan](plan.md) · [Research](research.md) · [Modelo de datos](data-model.md) · [Contrato](contracts/generation-requests.openapi.yaml) · [Puertos](contracts/ports.md) · [Validación](quickstart.md)

Las tareas siguen el [orden de entrega del plan](plan.md#orden-de-entrega). Las rutas `backend/…` son del repositorio `Plataforma_Docente_backend`, y las rutas `src/…` son del repositorio `Plataforma_Docente_frontend`. Los casos GEN-C1 a GEN-C6 son de la historia de pedido y recuperación; GEN-C7 a GEN-C9, de la historia de evidencia verificada; GEN-C10 y GEN-C11, de la historia de modalidad (HU-024).

Dependencias externas que bloquean tareas:

- **REV-01 PR 1**: integración en `main` de `domain/review/content_fingerprint.py`, `domain/review/resource_verification.py` (`verify_resource`, `referenced_fragment_ids`), la columna `version` y `application/ports/outbound/resource_regeneration_port.py` con su adaptador síncrono provisional.
- **CC-01 httpClient**: ampliación de `src/shared/api/httpClient.ts`, con cabeceras opcionales y `ApiError.status` y `ApiError.code`.
- **MAT-01 retrieval_mode**: `HybridEvidenceRetriever` informa `hybrid` o `bm25_fallback` y filtra la búsqueda vectorial por docente.

## 1. Dominio

- [x] T001 [BE] Agregar `plan_steps(mode, resource_types, quantity)` en `backend/src/platform5e/domain/generation/sequence.py`. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - Devuelve los pasos con `position`, `stage`, `resource_type`, `agent` y `quantity`, en el orden de `order_resource_types`.
  - El modo `individual` exige exactamente un tipo; si no, lanza `SequenceError` (se traduce a `INVALID_SEQUENCE`).
  - El modo `sequence` admite de 1 a `MAX_SEQUENCE_TYPES = 8` tipos distintos.
  - Pruebas en `backend/tests/unit/test_sequence_orchestrator.py`.
  - Casos GEN-C1 y GEN-C2.
- [x] T002 [BE] Crear `backend/src/platform5e/domain/generation/generation_request.py`. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - Clases `GenerationRequest`, `GenerationStep`, `GenerationParameters` y `RegenerationTarget`, como dataclasses según [data-model](data-model.md).
  - `RequestStatus`: `queued`, `running`, `succeeded`, `partially_succeeded`, `failed`, `interrupted`.
  - `StepStatus`: `pending`, `running`, `succeeded`, `rejected`, `failed`, `interrupted`.
  - Funciones puras de transición: `final_status(steps)` (todos `succeeded` → `succeeded`; alguno → `partially_succeeded`; ninguno → `failed`) e `interrupt(request)`. Un estado final no se modifica.
  - `payload_hash(mode, unit_id, parameters, regeneration)` es el SHA-256 del JSON canónico (claves ordenadas, sin espacios, valores por defecto aplicados y `resourceTypes` deduplicado en el orden recibido).
  - `validate_idempotency_key` con el patrón `^[A-Za-z0-9_-]{8,128}$`.
  - Pruebas en `backend/tests/unit/test_generation_request.py`.
  - Casos GEN-C3, GEN-C4 y GEN-C6.
- [x] T003 [BE] Agregar en `backend/src/platform5e/domain/generation/errors.py` los códigos de la entrega. Casos GEN-C5 y GEN-C6. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - Validación: `IDEMPOTENCY_KEY_REQUIRED`, `IDEMPOTENCY_KEY_REUSED`, `INVALID_SEQUENCE`.
  - No encontrados: `GENERATION_REQUEST_NOT_FOUND`, `UNIT_NOT_FOUND`.
  - Límites y ejecución: `TOO_MANY_ACTIVE_REQUESTS`, `DEADLINE_EXCEEDED`, `EVIDENCE_UNAVAILABLE`.
  - Regeneración: `REGENERATION_PARAMETERS_MISSING` (422: sin `params` o sin `resourceType`), `REGENERATION_TARGET_INVALID` (422: id o versión del recurso no válidos) y `REGENERATION_ATTEMPTS_EXHAUSTED` (409: se agotaron los intentos de la versión). Los estados HTTP son los previstos; los asigna Revisión en su ruta (PR de cierre de REV-01, rama `feat/revision-cierre`). `REGENERATION_UNAVAILABLE` ya no es de Generación: queda solo para el 503 propio de Revisión.
- [x] T004 [BE] Crear `backend/src/platform5e/domain/generation/evidence.py` con `build_snapshot(referenced_ids, fragments, retrieved_at)`. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - Devuelve los `EvidenceSnapshotItem` (`id`, `text`, `location`, `documentId`, `documentName`, `sourceUrl`, `license`, `retrievedAt`) y la lista de ids que faltan.
  - Recibe los ids ya calculados, sin importar `domain/review`.
  - Pruebas en `backend/tests/unit/test_generation_evidence_snapshot.py`, con ids de `citations`, `options`, `structure.guidedSteps`, `structure.predictions` y `structure.criteria`, y con un id ausente.
  - Caso GEN-C8.

## 2. Puertos y adaptadores

- [x] T005 [BE] Declarar en `backend/src/platform5e/application/ports/outbound/` los puertos propios con las firmas de [ports.md](contracts/ports.md#propios-de-generación). Casos GEN-C4 y GEN-C5. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - `generation_request_repository_port.py`, incluida la excepción `IdempotencyKeyTaken(existing)`.
  - `generation_job_runner_port.py`.
- [x] T006 [BE] Declarar en `backend/src/platform5e/application/ports/outbound/` los puertos hacia otros módulos. Casos GEN-C5, GEN-C6 y GEN-C9. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - `unit_membership_port.py`, con `UnitContext` y `OutcomeRef`.
  - `evidence_provider_port.py`, con `EvidenceQuery`, `EvidenceFragment`, `EvidenceRetrieval`, `NoProcessedMaterial` y `EvidenceUnavailable`.
  - `retrieval_mode` se declara `Literal["hybrid", "bm25_fallback"] | None` hasta T031.
- [x] T007 [BE] Crear la migración `backend/database/migrations/20261110000001_generation_requests.sql`. Casos GEN-C4 y GEN-C5. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - Tablas `gen_generation_requests` y `gen_generation_steps`, según [data-model](data-model.md#persistencia).
  - Restricción `UNIQUE (teacher_id, idempotency_key)`.
  - Índices `(teacher_id, unit_id, created_at DESC)` y `(status, heartbeat_at)`.
  - Clave foránea de los pasos con `ON DELETE CASCADE`.
- [x] T008 [BE] Implementar `backend/src/platform5e/infrastructure/persistence/repositories/sqlalchemy_generation_request_repository.py`. Casos GEN-C4 y GEN-C5. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - Crea las tablas en SQLite como `SQLAlchemyGenerationRepository.__init__`.
  - `create` traduce la violación de unicidad a `IdempotencyKeyTaken` con el pedido existente.
  - `get` filtra por docente.
  - `mark_interrupted(stale_before)` pasa a `interrupted` los pedidos `queued` o `running` con `heartbeat_at` (o `created_at`) anterior al límite, y también sus pasos no terminados.
  - Pruebas en `backend/tests/integration/test_generation_request_repository.py`: misma clave en dos docentes, misma clave repetida en un docente, inserción concurrente y barrido de arranque que conserva los pedidos con latido reciente.
- [x] T009 [BE] Implementar `backend/src/platform5e/infrastructure/jobs/thread_pool_generation_runner.py` sobre `ThreadPoolExecutor`. Casos GEN-C2 y GEN-C4. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - Agregar `GENERATION_MAX_WORKERS` (2) y `GENERATION_REQUEST_DEADLINE_SECONDS` (900) a `backend/src/platform5e/infrastructure/settings.py`.
  - Una excepción no controlada en la tarea deja el pedido `failed` y se registra en el log.
- [x] T010 [BE] Implementar `backend/src/platform5e/infrastructure/adapters/account_unit_membership_adapter.py` sobre `TeacherRepositoryPort.get_courses` y `find_course_and_unit`. Caso GEN-C5. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - Devuelve `None` tanto para una unidad ajena como para una inexistente.
  - Pruebas de unidad propia, ajena e inexistente.
  - Coordinar la firma con la tarea T007 de [CC-01](../003-cuentas-y-cursos/tasks.md).
- [x] T011 [BE] Implementar `backend/src/platform5e/infrastructure/adapters/material_evidence_adapter.py`. Casos GEN-C2 y GEN-C6. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - `has_processed_material` se basa en `ChunkRepositoryPort.get_chunks_by_unit(teacher_id, unit_id)`.
  - `retrieve` siempre pasa los fragmentos del docente a `HybridEvidenceRetriever` y nunca usa `get_chunks_by_unit("", …)`.
  - `documentName`, `sourceUrl` y `license` salen de `TeacherRepositoryPort.get_documents` (`fileName` y `origin`).
  - `retrieval_mode = None` hasta T031.
- [x] T012 [BE] Ampliar `backend/tests/architecture/test_layer_dependencies.py`: `application/use_cases/generation/` no importa `application/services/{accounts,materials,review}` ni `domain/review`. Constitución I. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).

## 3. Casos de uso y router

- [x] T013 [BE] Extraer de `generation_service.py` a `backend/src/platform5e/application/services/generation/step_drafting.py` las funciones `_draft_resources`, `_filter_repeated`, `_build_resource_dict` y `build_grounding_report`. Caso GEN-C3. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - Cada rechazo lleva `kind` (`grounding`, `repetition`, `structure` o `distractor`).
  - `generation_service.py` delega en el módulo nuevo hasta T046, que lo retira.
  - Mover las pruebas afectadas de `backend/tests/unit/test_generation_with_material.py`.
- [x] T014 [BE] Adaptar `build_generation_context` en `backend/src/platform5e/application/services/generation/prompt_drafting.py` para recibir `UnitContext` y `EvidenceFragment`. Caso GEN-C2. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - Las etiquetas `F1…Fn` y `secuenciaPrevia` no cambian.
  - Prueba de equivalencia con el contexto actual.
- [x] T015 [BE] Crear `backend/src/platform5e/application/use_cases/generation/start_generation_request.py`, que aplica estas reglas en orden. Casos GEN-C4, GEN-C5 y GEN-C6. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  1. Clave: `validate_idempotency_key` (`IDEMPOTENCY_KEY_REQUIRED` o `INVALID_PARAMETERS`).
  2. Pertenencia: si es `None`, `UNIT_NOT_FOUND`.
  3. `find_by_key`: si la clave ya tiene un pedido, con el mismo hash (`mode`, `unitId`, parámetros y regeneración) lo devuelve con `created = False`; con otro hash, `IDEMPOTENCY_KEY_REUSED`. En los dos casos no se aplican las reglas siguientes, así que un pedido aceptado se recupera aunque la unidad ya no tenga material.
  4. `outcomeId` de la unidad: si no, `INVALID_OUTCOME`.
  5. `plan_steps`.
  6. `has_processed_material`: si es falso, `NO_PROCESSED_MATERIAL`, sin crear el pedido.
  7. `count_active >= 2`: `TOO_MANY_ACTIVE_REQUESTS`.
  8. `create`, que ante `IdempotencyKeyTaken` aplica la regla 3 al pedido ganador, y luego `submit`.
- [x] T016 [BE] Crear `backend/src/platform5e/application/use_cases/generation/run_generation_request.py`. Casos GEN-C1, GEN-C2, GEN-C3 y GEN-C6. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - **Inicio:** `mark_running`, nueva comprobación de pertenencia y una sola llamada a `retrieve`, guardada con `save_evidence` y `retrievedAt`.
  - **Cada paso en orden 5E:** marcarlo `running`, redactar con `step_drafting`, aplicar el control de repetición contra los recursos aceptados de los pasos anteriores, adjuntar multimedia, guardar los recursos con `ResourceReviewRepositoryPort.save_resources` (incluidos `requestId`, `agent`, `params`, `generatorKind` y `evidence`) y después confirmar el paso con `update_step`.
  - **Durante la ejecución:** latido cada 15 s y plazo de `GENERATION_REQUEST_DEADLINE_SECONDS`, tras el cual los pasos restantes pasan a `failed` con `DEADLINE_EXCEEDED`.
  - **Final:** `finish(final_status(steps))`.
  - El bloque `verification` se agrega en T026. Esta rama no se integra a `main` sin T026.
- [x] T017 [BE] Crear `backend/src/platform5e/application/use_cases/generation/get_generation_request.py` con `get(teacher_id, request_id)` y `list(teacher_id, unit_id, active_only, limit)`. Casos GEN-C4 y GEN-C5. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - Un pedido ajeno o inexistente lanza `GENERATION_REQUEST_NOT_FOUND`.
  - `list` exige la pertenencia de la unidad.
  - Cada paso incluye la vista corta de sus recursos (`id`, `title` y `verificationStatus`).
- [x] T018 [BE] Crear `backend/src/platform5e/infrastructure/http/schemas/generation_requests.py` con `StartGenerationRequest`, `GenerationRequestSummary`, `GenerationRequestStatus` y `GenerationStep`, según [el contrato](contracts/generation-requests.openapi.yaml). Casos GEN-C1 y GEN-C2. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - Se reutilizan `ResourceType`, `Difficulty`, `GroundingReport` y `DistractorReliability` de `schemas/generations.py`.
  - Rangos: `resourceTypes` de 1 a 8 elementos, `quantity` de 1 a 5, `optionCount` de 2 a 5, `topK` de 1 a 50, `evidenceThreshold` de 0 a 1, `instructions` hasta 500 caracteres, `audience` y `competency` hasta 200.
- [x] T019 [BE] Crear `backend/src/platform5e/infrastructure/http/routers/generation_requests.py`. Casos GEN-C1 a GEN-C6. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - `POST /api/v1/generation-requests` responde `202` con `Location` si crea el pedido y `200` si ya existía.
  - Sin `Idempotency-Key`: `400 IDEMPOTENCY_KEY_REQUIRED`. Con formato inválido: `422 INVALID_PARAMETERS`.
  - `429` incluye `Retry-After`.
  - `GET /api/v1/generation-requests/{requestId}` y `GET /api/v1/generation-requests?unitId=&active=&limit=`.
  - Mover `GET /api/v1/generator` sin cambios y marcar `POST /api/v1/generations` con `deprecated=True` en `routers/generations.py`.
  - Agregar `429` a `ERROR_DESCRIPTIONS` en `backend/src/platform5e/infrastructure/http/schemas/common.py`.
- [x] T020 [BE] Conectar en `backend/src/platform5e/main.py` los puertos y adaptadores de T008 a T011 y los casos de uso de T015 a T017. Caso GEN-C4. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - El `lifespan` crea y cierra el ejecutor.
  - Antes de aceptar tráfico, llama a `mark_interrupted(now - 60 s)`.
  - `worker_boot_id` es un uuid por proceso.
- [x] T021 [BE] Ejecutar `python backend/scripts/export_openapi.py`, revisar el diff de `docs/api/openapi.json` contra `contracts/generation-requests.openapi.yaml` y actualizar `backend/tests/integration/test_openapi_documentation.py` y `backend/tests/unit/test_api_documentation.py`. Constitución II. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
- [x] T022 [BE] Agregar pruebas de `RunGenerationRequest` con generadores falsos en `backend/tests/unit/test_run_generation_request.py`. Casos GEN-C2, GEN-C3 y GEN-C6. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - Un paso rechazado y otro válido dan `partially_succeeded`, con `rejections[].reason`.
  - Todos los pasos fallidos dan `failed` con `failure.message`.
  - La IA falla y responde el generador por reglas con `generator.fallback = true`.
  - Un recurso repetido se rechaza tras un reintento.
  - Se supera el plazo.
  - La evidencia se recupera una sola vez para todos los pasos.
- [x] T023 [E2E] Adaptar `backend/tests/e2e/test_sequence_api.py` al flujo `202` con consulta hasta el estado final, conservando `_unit_with_material` y las aserciones de etapa y agente. Caso GEN-C2. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
- [x] T024 [E2E] Crear `backend/tests/e2e/test_generation_requests_api.py` para comprobar el contrato HTTP de punta a punta. Casos GEN-C1, GEN-C4, GEN-C5 y GEN-C6, y V10. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - **Pedido individual:** se crea y termina.
  - **Idempotencia:** la misma clave y el mismo cuerpo responden `200` con el mismo `id` y sin recursos nuevos; la misma clave con otro cuerpo responde `409`.
  - **Aislamiento:** un segundo docente recibe `404` al consultar el pedido y `404 UNIT_NOT_FOUND` en la unidad ajena.
  - **Sin material:** responde `400 NO_PROCESSED_MATERIAL` y no crea ningún pedido.
  - **Límite:** el tercer pedido activo responde `429`.

## 4. Verificación y regeneración

- [x] T025 [BE] **Depende de REV-01 PR 1.** Declarar `backend/src/platform5e/application/ports/outbound/resource_verification_port.py` e implementar `backend/src/platform5e/infrastructure/adapters/review_verification_adapter.py`, que delega en `content_fingerprint` y en `verify_resource` y `referenced_fragment_ids` de REV-01. Caso GEN-C8. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
- [x] T026 [BE] **Depende de T025.** Integrar la verificación en `run_generation_request.py`. Casos GEN-C1 y GEN-C8. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - Reemplazar las dos comprensiones que solo reúnen `citations` y `options` por `referenced_fragment_ids` del puerto, tanto para filtrar los fragmentos del paso como para `build_snapshot`.
  - Llamar a `verify(resource, evidenceThreshold)` después de la copia.
  - Si devuelve `insufficient`, el borrador se rechaza con `kind = grounding`.
  - Si lanza un error, el recurso se guarda con `status = pending` y el motivo.
  - Guardar el bloque `verification` completo y `version = 1`.
  - Volver obligatorio `verificationStatus` (`current` o `pending`, sin `null`) en `StepResource`, tanto en `backend/src/platform5e/infrastructure/http/schemas/generation_requests.py` como en `contracts/generation-requests.openapi.yaml`, y volver a exportar OpenAPI.
- [x] T027 [BE] **Depende de T026.** Agregar pruebas en `backend/tests/unit/test_generation_evidence_snapshot.py`. Caso GEN-C8. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - Recursos de `exploracion_guiada`, `reto_prediccion` y `caso_aplicado` redactados por reglas: la copia incluye los fragmentos de pasos, predicciones y criterios.
  - Si falta un fragmento referenciado, `verification.status = pending` con `retryAvailable = false`.
- [x] T028 [BE] **Depende de REV-01 PR 1.** Crear `backend/src/platform5e/application/use_cases/generation/start_regeneration.py`. Caso GEN-C7. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - Crea un pedido `regeneration` de un paso con los `params` guardados del recurso y la evidencia actual.
  - Usa la clave `regen-{resourceId}-v{resourceVersion}`.
  - Si el último intento de esa versión terminó `failed` o `interrupted`, o terminó bien pero el docente ya borró todos sus recursos nuevos, crea otro con la clave siguiente (`-r2`, `-r3`…). Si sigue en curso o terminó `succeeded` con algún recurso en Revisión, devuelve ese mismo ([research R9](research.md#r9-regeneración-y-edición-durante-el-pedido)).
  - Un recurso sin `params` o sin `resourceType` lanza `REGENERATION_PARAMETERS_MISSING` (422). Un id o una versión no válidos lanzan `REGENERATION_TARGET_INVALID` (422). Al agotar `MAX_REGENERATION_ATTEMPTS` lanza `REGENERATION_ATTEMPTS_EXHAUSTED` (409). Los estados los asigna Revisión.
  - Los recursos nuevos llevan `regeneratedFrom: {resourceId, version}`.
- [x] T029 [BE] **Depende de REV-01 PR 1 y T028.** Implementar `backend/src/platform5e/infrastructure/adapters/generation_regeneration_adapter.py` sobre `resource_regeneration_port.py`, y en `main.py` reemplazar con él el adaptador síncrono provisional de Revisión. Caso GEN-C7. [PR #17 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/17).
  - `request_regeneration` llama a `StartRegeneration`.
  - `get_regeneration` traduce los estados: `queued` → `pending`, `running` → `running`, `succeeded` → `succeeded`, y `failed` o `interrupted` → `failed` con `reason`.
  - Devuelve `new_resource_ids`, solo los recursos nuevos que siguen en Revisión (de la vista de `GetGenerationRequest`). Si el pedido terminó bien pero el docente los borró todos, devuelve `failed` con `REGENERATED_RESOURCE_NOT_FOUND` («El recurso regenerado ya no existe. Pide la regeneración otra vez.»), y `StartRegeneration` crea el intento siguiente (`-r2`) desde la misma versión.
  - Si una consulta del pedido falla de forma inesperada cuando el pedido ya existe, la registra y devuelve el último estado conocido (`pending` o `running`) con el id del pedido, para que Revisión siga con `get_regeneration` (revisión de Silvana en el PR #17).
- [x] T030 [E2E] **Depende de T029.** Probar la regeneración en `backend/tests/e2e/test_generation_requests_api.py` por la ruta de Revisión `POST /api/v1/units/{unitId}/resources/{resourceId}/regenerations`. Caso GEN-C7. [PR #17 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/17).
  - **Éxito:** el recurso anterior queda `descartado`.
  - **Repetición:** no crea otro pedido ni recursos.
  - **Edición durante el pedido:** conserva los dos recursos.
  - **Fallo:** no toca el recurso anterior.
- [x] T031 [BE] **Depende de MAT-01 retrieval_mode.** Mapear en `material_evidence_adapter.py` el modo que informa el recuperador, quitar `None` del tipo en `evidence_provider_port.py` y guardar `retrieval_mode` en el pedido. Caso GEN-C9. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
- [x] T032 [E2E] **Depende de T031.** Con `EMBEDDINGS_ENABLED=false`, comprobar `retrievalMode = bm25_fallback` y que `steps[].generator.fallback` solo refleja el respaldo de redacción. Caso GEN-C9. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
- [x] T033 [BE] **Depende de MAT-01 retrieval_mode (filtro por docente).** Agregar una prueba de integración con dos docentes en `backend/tests/integration/test_generation_evidence_isolation.py`: la recuperación híbrida de un docente no devuelve fragmentos del otro, aunque compartan `unit_id` en los datos de prueba. Constitución IV. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).

## 5. Frontend

- [x] T034 [FE] **Depende de CC-01 httpClient.** Acordar con CC-01, en un PR coordinado fuera de `src/features/generation`, la ampliación de `src/shared/api/httpClient.ts`. Casos GEN-C4 y GEN-C5. [PR #6 del frontend](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/6).
  - Parámetro opcional de cabeceras.
  - Acceso al código de estado de la respuesta.
  - `ApiError` con `status` y `code`.
  - Las llamadas existentes no cambian.
- [x] T035 [FE] Crear `src/features/generation/model/generationRequest.ts`. Casos GEN-C2, GEN-C3 y GEN-C8. [PR #9 del frontend](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9).
  - Tipos escritos a mano según `docs/api/openapi.json`: `RequestStatus`, `StepStatus`, `StartGenerationRequest`, `GenerationRequestStatus` y `GenerationStep`.
  - Funciones `isTerminal`, `stepLabel` y `verificationLabel` (`current` → vigente, `pending` → pendiente).
  - Pruebas en `src/features/generation/model/generationRequest.test.ts`.
- [x] T036 [FE] **Depende de T034.** Crear `src/features/generation/api/generationApi.ts` sobre `request` de `src/shared/api/httpClient.ts`. Casos GEN-C4 y GEN-C5. [PR #9 del frontend](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9).
  - `startGenerationRequest(token, key, body)` devuelve `{ request, created }` según `202` o `200`.
  - `getGenerationRequest(token, id)`.
  - `listGenerationRequests(token, unitId, active)`.
  - Pruebas en `src/features/generation/api/generationApi.test.ts`, como `coursesApi.test.ts`.
- [x] T037 [FE] **Depende de T036.** Crear `src/features/generation/hooks/useStartGeneration.ts`. Casos GEN-C4, GEN-C5 y GEN-C6. [PR #9 del frontend](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9).
  - Crea la clave con `crypto.randomUUID()` y guarda `{ key, payload, requestId }` en `sessionStorage` bajo `generation:{unitId}` antes de enviar.
  - Si falla la red, reintenta con la misma clave.
  - Muestra el `message` de `409 IDEMPOTENCY_KEY_REUSED` y ofrece un pedido nuevo con otra clave.
  - Muestra `429` y `400 NO_PROCESSED_MATERIAL`, con un enlace a la pestaña Material.
- [x] T038 [FE] **Depende de T036.** Crear `src/features/generation/hooks/useGenerationRequest.ts`. Casos GEN-C2 y GEN-C4. [PR #9 del frontend](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9).
  - Consulta cada 2 s, con espera creciente hasta 10 s, y se detiene en un estado final.
  - Al montar, recupera el `requestId` guardado o, si no hay ninguno, consulta `listGenerationRequests(…, active = true)`.
  - Ante un `404`, limpia `sessionStorage`.
- [x] T039 [FE] Crear `src/features/generation/components/GenerationForm.tsx`. Casos GEN-C1 y GEN-C2. [PR #9 del frontend](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9).
  - Selector de modo individual o secuencia.
  - Tipos tomados de `GET /api/v1/resource-types`, con un tipo en el modo individual y hasta 8 en la secuencia.
  - `quantity` de 1 a 5, común a todos los tipos.
  - Resultado de aprendizaje opcional, entre los de la unidad.
- [x] T040 [FE] Crear `src/features/generation/components/GenerationProgress.tsx`. Casos GEN-C2, GEN-C3, GEN-C6 y GEN-C8. [PR #9 del frontend](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9).
  - Muestra los pasos en orden 5E con el estado que informa el servidor.
  - Los recursos de cada paso aparecen con su estado de verificación y un enlace a Revisión.
  - Los rechazos aparecen con su motivo.
  - Muestra `failure.message` cuando el pedido falla.
  - El estado `interrupted` ofrece crear un pedido nuevo.
- [x] T041 [FE] Crear `src/features/generation/components/FallbackNotices.tsx`, con avisos distintos para `retrievalMode = bm25_fallback` y para `generator.fallback`. Con `retrievalMode = null` no muestra aviso de búsqueda. Los datos reales dependen de T031. Caso GEN-C9. [PR #9 del frontend](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9).
- [x] T042 [FE] **Depende de T037 y T038.** Reemplazar el marcador `src/features/generation/pages/GenerationPage.tsx`. Casos GEN-C1 a GEN-C6. [PR #9 del frontend](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9).
  - Usa `course`, `unit`, `token` y `onSessionExpired` del contexto de `UnitLayout`.
  - Compone el formulario, el progreso y los avisos.
  - Estilos en `src/features/generation/generation.css`.
  - Pasa `npm run lint` y `npm test`.
- [x] T043 [E2E] **Depende de T042 y T024.** Recorrer en el navegador el [recorrido de interfaz](quickstart.md#recorrido-en-interfaz) y adjuntar la evidencia. Casos GEN-C2, GEN-C4 y GEN-C9. [PR #9 del frontend](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9).
  - Recargar a mitad de una secuencia y recuperar su progreso.
  - Cortar la red al enviar y reintentar sin duplicar el pedido.
  - Distinguir los avisos de respaldo.

## 6. Carga, retirada y cierre

- [x] T044 [E2E] Medir la carga ([V11](quickstart.md#v11--carga)): 5 secuencias de 8 × 5 con `LLM_PROVIDER=gemini` y con `rules`. [PR #27 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/27).
  - Registrar aquí p50, p95, llamadas al modelo por paso y pedidos con `DEADLINE_EXCEEDED`.
  - Si el p95 con Gemini supera 10 min, bajar el tope a 20 recursos por pedido en `spec.md`, `research.md` (R4) y T018.
  - **Resultados (2026-11-12).** Servidor local con SQLite, `GENERATION_MAX_WORKERS=2` y el plazo por defecto de 15 min. 5 secuencias de 8 tipos × 5 (`pregunta_detonante`, `sondeo_diagnostico`, `guia_exploracion`, `caso_indagacion`, `explicacion`, `glosario`, `ejercicio_aplicacion`, `item_opcion_multiple`) sobre la misma unidad y el mismo material. Gemini con `gemini-3.5-flash-lite` en el plan gratuito. Script: `backend/scripts/measure_generation_load.py`; datos en `backend/evaluation/results/load-rules-20261112T055908Z.json` y `load-gemini-20261112T061006Z.json` (no se versionan). Los dos pedidos aceptados de la comprobación de concurrencia no entran en los percentiles.

    | Medida | `rules` | `gemini` |
    | --- | --- | --- |
    | Pedidos medidos y estado final | 5 (5 succeeded) | 5 (5 succeeded) |
    | Duración creado→terminado, p50 / p95 | 0.6 s / 0.6 s | 31.0 s / 107.1 s |
    | Recursos entregados (de 200) | 125 | 153 |
    | Rechazos por motivo | 50 (repetition 50) | 25 (repetition 17, grounding 8) |
    | Pasos con respaldo de redacción (de 40) | 0 | 17 |
    | Redacciones por paso (mín / prom / máx) | 1 / 1.5 / 2 | 1 / 1.23 / 2 |
    | Llamadas a IA por paso (cota inferior prom. – cota superior máx.) | 0.0 – 0 | 1.23 – 4 |
    | `DEADLINE_EXCEEDED` (pasos / pedidos) | 0 / 0 | 0 / 0 |
    | 3 pedidos simultáneos → 2 × 202 + 429 `TOO_MANY_ACTIVE_REQUESTS` | OK | OK |

    - El p95 con Gemini (107.1 s) queda muy por debajo de 10 min y no hubo `DEADLINE_EXCEEDED`: se mantiene el tope de 40 recursos por pedido de R4.
    - 17 de 40 pasos con Gemini usaron el respaldo por reglas. Según el log del servidor, sobre todo por los 429 de límite de uso del plan gratuito con 2 secuencias en paralelo, más algunos 503 (modelo sobrecargado) y borradores sin citas válidas. Las duraciones con Gemini reflejan ese límite del plan gratuito, no la latencia de la IA en todos los pasos; un plan de pago o menos pedidos en paralelo las cambiaría.
    - El generador por reglas entregó menos recursos de los pedidos con este corpus por los rechazos por repetición (50); no es un problema de carga.
    - Las llamadas al modelo por paso son cotas, no conteos exactos: la API no expone el número. Propuesta pendiente (no hecha): contar las llamadas en `draft_resources` y `draft_step` y exponerlas en `steps[].generator`.
- [x] T045 [BE] Migrar los consumidores de la ruta antigua: [PR #16 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/16).
  - `backend/evaluation/collect_samples.py` pasa a `POST /api/v1/generation-requests` con consulta hasta el estado final.
  - `backend/scripts/export_contracts.py` exporta `StartGenerationRequest` en lugar de `GenerationRequest`. Actualizar `docs/api/contracts/generation-request.v1.json`.
- [x] T046 [BE] **Depende de T045.** Retirar la ruta y el servicio antiguos. PR #22 del backend y [PR #24 del backend (con CC-01)](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/24).
  - Quitar `POST /api/v1/generations` y el modo demostración.
  - Eliminar lo que quede de `generation_service.py` y `generation_repository_port.py`.
  - Conservar la lectura de `GET /api/v1/generations/{id}` sobre `generaciones_demo` para el historial.
  - Exportar OpenAPI de nuevo, como en T021.
  - **PR #22:** se quitaron `POST /api/v1/generations` y su esquema, `generation_service.py`, el modo demostración de Generación (pedidos anónimos con ejemplos) y el adaptador síncrono provisional de regeneración (`infrastructure/generation/`) con su prueba. Las pruebas que usaban la ruta retirada pasan a `POST /api/v1/generation-requests`; las del historial insertan una generación como las que guardaba la ruta retirada; las pruebas unitarias de lo que se conserva (redacción, anclaje, agentes, multimedia) se ejecutan con `RunGenerationRequest`.
  - **PR #24 (con CC-01; Silvana revisa Cuentas, Yan revisa Generación):**
    - Cuentas siembra el curso de demostración leyendo `persistence/seed/demo_generation.json` directamente (parte de Silvana), sin `GenerationRepositoryPort.get_demo_catalog`.
    - El historial de la generación retirada es de Cuentas: `GenerationORM` y `TeacherGenerationORM` (tablas `generaciones_demo` y `ep002_generaciones_docente`, sin cambios de esquema) y `adapt_legacy_generation` están en `sqlalchemy_account_repository.py`, que crea esas tablas en SQLite y las lee en `get_history`, `get_generation_owner` y el nuevo `get_generation` (en `TeacherRepositoryPort`).
    - `GET /api/v1/generations` y `GET /api/v1/generations/{id}` mantienen rutas, respuestas, 401 y 404 y la comprobación de pertenencia; `{id}` se sirve con `AccountService.get_generation`. El router sigue en `infrastructure/http/routers/generations.py`.
    - Se eliminaron `generation_repository_port.py`, `sqlalchemy_generation_repository.py` y `get_legacy_generation.py`, con su cableado en `main.py`. OpenAPI no cambia.
- [x] T047 [BE] Al borrar un curso, eliminar los pedidos de sus unidades en `gen_generation_requests` y, en cascada, sus pasos en `gen_generation_steps`, conservando los registros de descarga. Caso CC-C9. [PR #14 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14).
  - Coordinar con CC-01 el cambio en el borrado de cursos: T008 de [CC-01](../003-cuentas-y-cursos/tasks.md) ya se integró en el [PR #8 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/8) sin estas tablas.
  - Prueba de integración: un curso con un pedido terminado y una descarga registrada; al borrarlo no quedan pedidos ni pasos de sus unidades y la descarga sigue disponible para su docente.
- [x] T048 [BE] Proponer a CC-01 un paso en `.github/workflows/backend-ci.yml` que compare la exportación de OpenAPI con `docs/api/openapi.json`. Constitución II. [PR #25 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/25) (propuesta a CC-01).
- [x] T049 [E2E] Enlazar en este archivo la evidencia de cada caso, de GEN-C1 a GEN-C9, y de los criterios de éxito de la ficha: orden de etapas, recuperación, resultados parciales, no duplicación, aislamiento, huella, verificación y copia histórica completa en los recursos vigentes (los pendientes no pueden aprobarse ni exportarse), y regeneración fallida que conserva el anterior. Ver [Evidencia de los casos y criterios](#evidencia-de-los-casos-y-criterios-t049). [PR #26 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/26).

## 7. Modalidades (HU-024)

Decisiones en [research R11](research.md#r11-modalidades-hu-024), acordadas con Silvana (CC-01, frontend) y Juan (REV-01). Las tareas de GEN-01 son de Yan; las de coordinación indican su responsable.

- [x] T050 [BE] Ampliar el contrato en `backend/src/platform5e/infrastructure/http/schemas/generation_requests.py`. Caso GEN-C10. PR del backend (enlace pendiente).
  - `modalities`: lista opcional de `Textual`, `Gamificado`, `Multimedia` o `Kinestésico`, con como máximo un elemento y sin valor por defecto en el servidor.
  - La vista de parámetros sigue devolviendo `modalities`, con la misma forma que el cuerpo: `[modalidad]`, o `[]` si el pedido no la envió. Así no cambia para los clientes actuales. El dominio y los parámetros guardados usan `modality` (`str | None`).
  - Código nuevo `RESOURCE_TYPE_NOT_IN_MODALITY` en `domain/generation/errors.py`, con estado 422 en `ERROR_STATUS` de `routers/generation_requests.py`.
- [x] T051 [BE] Agregar `MODALITY_TYPES` en `backend/src/platform5e/domain/generation/resource_formats.py` y la lista `modalities` de cada tipo en `GET /api/v1/resource-types` (`use_cases/catalog/list_resource_types.py` y `schemas/catalog.py`). Caso GEN-C10. PR del backend (enlace pendiente).
  - Prueba: los tipos de cada modalidad, `item_opcion_multiple` en Textual y Gamificado, `exploracion_guiada` y `caso_aplicado` en Textual, y que todo tipo de `RESOURCE_TYPES` pertenece al menos a una modalidad.
- [x] T052 [BE] **Depende de T050 y T051.** Validar la modalidad en `StartGenerationRequest`, junto con el plan de pasos y después de buscar la clave. Caso GEN-C10. PR del backend (enlace pendiente).
  - `GenerationParameters.modality` (`str | None`), en `to_payload()` y en `payload_hash`.
  - Con modalidad, un tipo que no pertenece a ella responde `422 RESOURCE_TYPE_NOT_IN_MODALITY` y no crea el pedido. Sin modalidad, no se filtran los tipos y el pedido se guarda con `modality = null`.
  - El repositorio lee los parámetros guardados antes de HU-024 (`modalities: ["Textual"]`) como `modality = null`.
  - Pruebas unitarias: el 422 sin pedido creado, el pedido sin modalidad, el hash con y sin modalidad, y que reenviar la misma clave de un pedido aceptado lo devuelve sin volver a validar.
- [x] T053 [BE] **Depende de T052.** Guardar `modality` en los `params` de cada recurso (`step_drafting.py`), solo si el pedido la trae (con el formulario, casi siempre: «Textual» viene preseleccionado), y conservarla al regenerar sin comprobarla (`start_regeneration.py`). Casos GEN-C7 y GEN-C10. PR del backend (enlace pendiente).
  - Prueba obligatoria: regenerar una imagen y un audio antiguos guardados con `modalities: ["Textual"]` sigue funcionando.
- [x] T054 [BE] Agregar el tipo `actividad_kinestesica` (etapa Explorar, formato `interactive`). Caso GEN-C11. PR del backend (enlace pendiente).
  - Catálogo en `resource_catalog.py`; estructura en `resource_formats.py` (`guidedSteps` como en `exploracion_guiada`, `MIN_ITEMS = 3`, `materials`, `estimatedMinutes` de 5 a 90 y `space`).
  - `materials`, `estimatedMinutes` y `space` van dentro de `structure`, y `normalize_structure` debe conservarlos: la huella se calcula sobre la estructura normalizada.
  - Instrucción de estructura y conversión en `prompt_drafting.py`; enlace de los pasos con `link_step_sources` de `grounding.py`.
  - Redactor del generador por reglas en `rule_based_generator.py`, con al menos 3 pasos citados.
  - Pruebas: normalización, redactor por reglas, copia histórica de los fragmentos de los pasos y verificación vigente.
- [x] T055 [BE] **Depende de T052.** Agregar en `prompt_drafting.py` la línea de la modalidad cuando el pedido la trae. No cambia las reglas de citas ni de formato del tipo. Caso GEN-C10. PR del backend (enlace pendiente).
- [x] T056 [E2E] **Depende de T050 a T055.** Probar en `backend/tests/e2e/test_generation_requests_api.py`, con el generador por reglas. Casos GEN-C10 y GEN-C11. PR del backend (enlace pendiente).
  - Un pedido por modalidad, con tipos compatibles.
  - Un tipo que no pertenece a la modalidad: `422 RESOURCE_TYPE_NOT_IN_MODALITY` y ningún pedido guardado.
  - Un pedido sin `modalities` funciona como hoy y devuelve `parameters.modalities = []`.
  - Actualizar `test_text_only_rejects_other_modalities` de `test_courses_and_documents_api.py`, que hoy espera 422 para Multimedia y Gamificado.
- [x] T057 [BE] **Depende de T050 y T051.** Exportar OpenAPI (`scripts/export_openapi.py`) y actualizar `docs/api/openapi.json`; la CI compara el contrato (T048). PR del backend (enlace pendiente).
- [ ] T058 [FE] **Silvana.** Formulario de generación en `src/features/generation`. Caso GEN-C10.
  - Selector de modalidad, con «Textual» por defecto, que filtra el selector de tipos con `modalities` de `GET /resource-types` y envía `modalities: [modalidad]`.
  - Al cambiar de modalidad, el formulario conserva los tipos elegidos que siguen siendo compatibles y quita los demás. Si no queda ninguno, el docente debe elegir uno antes de generar: el botón de generar queda deshabilitado, con un mensaje. Por ejemplo, de Textual a Gamificado se conserva `item_opcion_multiple` y se quita `glosario`.
  - Una sección Contexto, aparte, agrupa Resultado de aprendizaje, Audiencia y Competencia (HU-024 C02). La modalidad no forma parte de Contexto.
  - Mostrar el mensaje de `RESOURCE_TYPE_NOT_IN_MODALITY` si el servidor lo devuelve.
- [ ] T059 [BE] **Juan (REV-01).** Soportar `actividad_kinestesica` en Revisión y exportación. Caso GEN-C11.
  - `domain/review/resource_verification.py`: enlazar sus `guidedSteps` como en `exploracion_guiada` (`LINKED_ITEMS`), con mínimo 3 pasos.
  - `domain/review/content_fingerprint.py` (**depende de T054**): `materials`, `estimatedMinutes` y `space` entran en la huella porque están en `structure` y `normalize_structure` los conserva; no se agregan a `UNVERIFIED_STRUCTURE_FIELDS`. Prueba: editar cualquiera de los tres cambia la huella y devuelve el recurso a revisión.
  - `infrastructure/exporters/unit_document_exporter.py`: `RESOURCE_LABELS` con «Para explorar · Actividad kinestésica», y mostrar los materiales, el tiempo estimado y el espacio antes de los pasos.
  - `infrastructure/exporters/scorm_package_exporter.py`: `SOURCED_LISTS` con sus `guidedSteps` y la actividad en `ACTIVITY_JS`, con la casilla «Lo hicimos». También muestra los materiales, el tiempo estimado y el espacio antes de los pasos.
  - Agregar el tipo no cambia las reglas de los tipos existentes, así que no se espera subir `VERIFICATION_RULE_VERSION`. Juan lo confirma.
- T060 (movida al seguimiento del sprint 2)
- [ ] T061 [E2E] **Depende de T056, T058 y T059.** Enlazar en la [tabla de evidencia](#evidencia-de-los-casos-y-criterios-t049) los casos GEN-C10 y GEN-C11 y el criterio de éxito de modalidades (un pedido por modalidad, rechazo de un tipo incompatible y exportación de una actividad kinestésica).
- Seguimiento fuera de esta entrega (REV-01, sprint 2): exportar a Moodle XML verdadero o falso y relacionar; verificar el guion de audio oración por oración (sube `VERIFICATION_RULE_VERSION`); y decidir qué cuenta como elección explícita de Textual para el `item_opcion_multiple` en SCORM, porque Textual viene preseleccionado en el formulario y un `modality: "Textual"` guardado no indica por sí solo que el docente cambió el selector (hasta entonces, todos los ítems de opción múltiple van a la evaluación por niveles). Esta última era T060.

## 8. Evaluación RAG (TA-010)

Decisiones en [research R12](research.md#r12-contexto-de-la-evaluación-rag): la evaluación usa como contexto todo lo que recuperó el pedido, no solo lo citado (regresión del commit 6ed774a, PR #16).

- [x] T062 [BE] Caso de uso `GetGenerationEvidence` en `backend/src/platform5e/application/use_cases/generation/get_generation_evidence.py`. PR del backend (enlace pendiente).
  - Devuelve `requestId`, `retrievalMode`, `limit` (`retrieval_limit` del `topK` del pedido), `retrievedAt` y los fragmentos en el orden de la recuperación, sin `retrievedAt` en cada uno.
  - Un pedido en cola devuelve `[]`; uno ajeno o inexistente, `GENERATION_REQUEST_NOT_FOUND`.
  - Pruebas en `backend/tests/unit/test_generation_evidence.py`: orden, `[]` en cola, límite, aislamiento entre docentes y que lo citado por los recursos es parte de lo recuperado.
- [x] T063 [BE] **Depende de T062.** Ruta `GET /api/v1/generation-requests/{id}/evidence` y esquemas `GenerationEvidence` y `RetrievedFragment` (`routers/generation_requests.py`, `schemas/generation_requests.py`, `main.py`). Pruebas e2e en `test_generation_requests_api.py`: todo lo recuperado en orden, lo citado como subconjunto, y `404` para otro docente con el mismo cuerpo que un pedido inexistente. PR del backend (enlace pendiente).
- [x] T064 [BE] **Depende de T063.** Agregar la ruta a [contracts/generation-requests.openapi.yaml](contracts/generation-requests.openapi.yaml) y exportar `docs/api/openapi.json`; la CI compara el contrato (T048). PR del backend (enlace pendiente).
- [x] T065 [BE] **Depende de T063.** `backend/evaluation/collect_samples.py`. PR del backend (enlace pendiente).
  - `retrieved_contexts` con todo lo de la ruta, en orden; `cited_contexts` con la copia de cada recurso; `retrieved_count`, `limit`, `retrieval_mode` y `retrieval_query` en cada muestra. Sin `modalities` en el pedido.
  - Campos opcionales de `cases.json`: `unitTitle`, `outcomeText`, `competency`, `reference`, `expectedFragments` y `mode: "sequence"` con `resourceTypes`. Los casos sin ellos se piden igual que antes.
  - Pruebas en `backend/tests/unit/test_collect_samples_cases.py` y `backend/tests/e2e/test_collect_samples.py`.
- [x] T066 [BE] **Depende de T065.** `backend/evaluation/run_ragas.py`: `--contexts retrieved|cited` (por defecto `retrieved`) y `context_recall` solo si todas las muestras calificadas traen `reference`; si no, se omite con un mensaje. Pruebas con un evaluador falso, sin modelo, en `backend/tests/unit/test_run_ragas.py`. PR del backend (enlace pendiente).
- [ ] T067 [Sergio] Corpus de evaluación: de 4 a 6 documentos con licencia o permiso de uso (unos 50 a 60 fragmentos), con 1 o 2 documentos de otro tema, y una respuesta de referencia (`reference`) por caso de `cases.json`; de forma opcional, `expectedFragments`, `unitTitle`, `outcomeText` y `competency`. Validar también la redacción de las indicaciones y la cobertura de etapas y tipos.
- [ ] T068 [E2E] **Depende de T065, T066 y T067.** Correr `collect_samples.py` y `run_ragas.py` con el corpus de T067, con `--contexts retrieved` y `--contexts cited`, y registrar aquí los resultados (promedios, por etapa, `context_recall` y muestras de respaldo por reglas).

## 9. Interpretación de pedidos (HU-038)

Decisiones en [research R13](research.md#r13-interpretación-de-pedidos-hu-038).

- [X] T069 [BE] Implementar `InterpretGenerationRequest` con reglas deterministas. Reutilizar la validación de pertenencia, los resultados de la unidad y el catálogo de Generación. Probar mensajes sin tipos reconocidos, con uno o varios tipos, con tipos repetidos o fuera del orden 5E, con solo una etapa, con un resultado ambiguo o con una solicitud explícita de quitarlo, con cantidades incompatibles o fuera de rango y con tipos incompatibles con la modalidad. Caso GEN-C12.
  - Evidencia: [implementación en el PR #37](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/37) y [pruebas unitarias del intérprete](../../backend/tests/unit/test_interpret_generation_request.py). Pasaron 21 pruebas en la ejecución local.
- [X] T070 [BE] **Depende de T069.** Conectar la ruta autenticada, exportar sus esquemas en el OpenAPI de la aplicación y agregar pruebas HTTP para la validación del cuerpo, el 401 de sesión y el mismo 404 para una unidad ajena y una inexistente. Comprobar que interpretar solo devuelve un borrador y sus problemas, sin crear un pedido, llamar a un proveedor ni recuperar evidencia.
  - Evidencia: [ruta y OpenAPI en el PR #37](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/37) y [pruebas HTTP](../../backend/tests/e2e/test_generation_interpretation_api.py). Se verificó el borrador con HTTP 200 y cero pedidos creados, el 401 sin sesión, el mismo 404 para unidades ajenas e inexistentes y el 422 para mensajes en blanco.
- [ ] T071 [FE] **Usa el contrato de T070.** Agregar el chat a Generación y aplicar el borrador al formulario editable. Mostrar la unidad activa, la etapa de cada tipo, los problemas y, cuando corresponda, una sugerencia de unidad propia. Permitir editar cada parámetro aplicado, incluidas las instrucciones opcionales. Omitir un campo conserva su valor y `outcomeId: null` limpia el resultado de aprendizaje. Reutilizar las validaciones del formulario y confirmar con «Generar». **Dependencia de la vista previa:** usarla cuando HU-040 esté integrada. Hasta entonces, usar el formulario normal.
- [ ] T072 [E2E] **Depende de T070 y T071.** En TCP/IP, interpretar «Para TCP/IP, quiero dos glosarios», corregir la cantidad a 1 y confirmar desde el formulario. Comprobar que antes de confirmar hay cero pedidos nuevos y después hay exactamente uno con la cantidad editada. Verificar que mencionar solo una etapa pide elegir un tipo y que sugerir otra unidad propia mantiene la unidad activa. Enlazar aquí la evidencia.

## Evidencia de los casos y criterios (T049)

Pruebas automáticas en `main` (rutas desde la raíz de cada repositorio; las del frontend están en `Plataforma_Docente_frontend` y se citan con la descripción de `it`), PR donde se implementó cada caso y evidencia manual de los informes de GEN-01 en Notion.

| Caso o criterio | Pruebas automáticas | PR | Evidencia manual |
| --- | --- | --- | --- |
| GEN-C1. Pedido individual: el recurso se verifica antes de entregarse y pasa a revisión como vigente o pendiente | `backend/tests/e2e/test_generation_requests_api.py::test_an_individual_request_is_created_and_finishes`<br>`backend/tests/unit/test_run_generation_request.py::test_every_delivered_resource_has_its_verification_version_and_dated_copy`<br>`backend/tests/unit/test_run_generation_request.py::test_if_verification_fails_the_resource_is_delivered_pending_with_the_reason` | [backend #14](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14); [frontend #9](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9) | «Informe GEN-01 2 (backend, Swagger)», Evidencias 7 y 8; «Informe GEN-01 3 (frontend)», Evidencia 4 |
| GEN-C2. Secuencia en segundo plano: pasos en orden 5E, evidencia compartida y estado del servidor | `backend/tests/e2e/test_sequence_api.py::test_a_sequence_request_is_drafted_by_one_agent_per_stage`<br>`backend/tests/unit/test_run_generation_request.py::test_evidence_is_retrieved_once_and_shared_by_every_step`<br>`src/features/generation/components/components.test.tsx::"muestra los pasos en orden 5E con su estado, recursos verificados y rechazos"` | [backend #14](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14); [frontend #9](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9) | «Informe GEN-01 2 (backend, Swagger)», Evidencias 1 a 3; «Informe GEN-01 3 (frontend)», Evidencia 3; «Informe GEN-01 4 (Gemini)», ejecución real con IA |
| GEN-C3. Un paso se rechaza y otro termina: se conserva lo válido y se muestra el motivo | `backend/tests/unit/test_run_generation_request.py::test_a_rejected_step_and_a_valid_one_give_partial_success`<br>`backend/tests/unit/test_run_generation_request.py::test_a_repeated_resource_is_asked_again_and_rejected_if_it_still_repeats`<br>`src/features/generation/components/components.test.tsx::"muestra los pasos en orden 5E con su estado, recursos verificados y rechazos"` | [backend #14](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14); [frontend #9](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9) | «Informe GEN-01 3 (frontend)», Evidencia 5 |
| GEN-C4. Desconexión o recarga: se recupera el pedido y la misma clave no duplica recursos | `backend/tests/e2e/test_generation_requests_api.py::test_the_same_key_returns_the_same_request_and_other_content_conflicts`<br>`src/features/generation/hooks/useGenerationRequest.test.ts::"usa el requestId guardado sin reenviar ni consultar la lista"`<br>`src/features/generation/hooks/useStartGeneration.test.ts::"tras agotar los reintentos conserva la clave para reenviarla sin duplicar"` | [backend #14](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14); [frontend #6](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/6), [frontend #9](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9) | «Informe GEN-01 2 (backend, Swagger)», Evidencia 4 (la misma clave responde 200 con el mismo id); «Informe GEN-01 3 (frontend)», Evidencias 6, 7 y 9; «Informe GEN-01 4 (Gemini)», Evidencia 7 |
| GEN-C5. Otro docente consulta el pedido o se reutiliza la clave con otros datos | `backend/tests/e2e/test_generation_requests_api.py::test_another_teacher_cannot_see_the_request_or_use_the_unit`<br>`backend/tests/unit/test_generation_request_use_cases.py::test_the_same_key_with_other_content_is_a_conflict`<br>`src/features/generation/api/generationApi.test.ts::"conserva el status y el message de una clave reutilizada con otros datos"` | [backend #14](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14); [frontend #6](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/6), [frontend #9](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9) | «Informe GEN-01 2 (backend, Swagger)», Evidencias 5, 10 y 11 |
| GEN-C6. Sin material procesado se rechaza; si todos los pasos fallan, se informa el motivo y el estado final | `backend/tests/e2e/test_generation_requests_api.py::test_a_unit_without_processed_material_is_rejected_without_creating_a_request`<br>`backend/tests/unit/test_run_generation_request.py::test_when_every_step_fails_the_request_fails_with_a_reason`<br>`src/features/generation/components/components.test.tsx::"enlaza con Material solo cuando falta material procesado"` | [backend #14](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14); [frontend #9](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9) | «Informe GEN-01 2 (backend, Swagger)», Evidencia 9; «Informe GEN-01 3 (frontend)», Evidencia 8 |
| GEN-C7. Regeneración desde Revisión con los parámetros guardados y la evidencia actual | `backend/tests/e2e/test_generation_requests_api.py::test_regenerating_from_review_discards_the_previous_and_repeating_does_not_duplicate`<br>`backend/tests/unit/test_start_regeneration.py::test_the_new_resource_uses_current_evidence_and_records_where_it_came_from`<br>`backend/tests/e2e/test_generation_requests_api.py::test_editing_the_resource_while_it_regenerates_keeps_both` | [backend #17](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/17), [backend #23](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/23) | Sin evidencia manual todavía |
| GEN-C8. El borrador bajo el umbral se rechaza y no llega a revisión; si falta un fragmento referenciado o la verificación no puede completarse, el recurso llega pendiente y no puede aprobarse ni exportarse | `backend/tests/unit/test_run_generation_request.py::test_an_insufficient_draft_is_rejected_as_grounding_and_not_delivered`<br>`backend/tests/unit/test_legacy_stored_data.py::test_without_a_complete_copy_it_is_pending_cannot_be_retried_and_is_not_exported`<br>`backend/tests/unit/test_accounts_and_review.py::test_resource_delivered_pending_by_generation_cannot_be_approved` | [backend #14](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14) | Solo pruebas automáticas |
| GEN-C9. Sin búsqueda híbrida: `retrieval_mode = bm25_fallback`, distinto del respaldo de redacción | `backend/tests/e2e/test_generation_requests_api.py::test_without_embeddings_the_request_reports_the_bm25_fallback_apart_from_the_generator`<br>`backend/tests/unit/test_run_generation_request.py::test_the_search_fallback_and_the_drafting_fallback_are_reported_separately`<br>`src/features/generation/components/components.test.tsx::"distingue el respaldo de búsqueda del respaldo de redacción"` | [backend #14](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14); [frontend #9](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9), [frontend #11](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/11) | «Informe GEN-01 4 (Gemini)», Evidencias 3 y 4 |
| Criterio: orden de etapas | `backend/tests/unit/test_run_generation_request.py::test_a_sequence_runs_in_class_order_and_delivers_resources_to_review`<br>`backend/tests/e2e/test_sequence_api.py::test_a_sequence_request_is_drafted_by_one_agent_per_stage`<br>`src/features/generation/model/generationForm.test.ts::"arma el cuerpo del pedido en orden 5E, sin repetidos y con el resultado opcional"` | [backend #14](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14); [frontend #9](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9) | «Informe GEN-01 2 (backend, Swagger)», Evidencias 1 a 3; «Informe GEN-01 3 (frontend)», Evidencia 3 |
| Criterio: recuperación tras una desconexión | `src/features/generation/hooks/useGenerationRequest.test.ts::"un envío sin respuesta recupera su propio pedido con la clave original aunque haya otro activo"`<br>`src/features/generation/hooks/useGenerationRequest.test.ts::"sin nada guardado usa el pedido activo más reciente, o ninguno"`<br>`src/features/generation/hooks/useStartGeneration.test.ts::"reintenta con la misma clave si falla la red"` | [backend #14](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14); [frontend #6](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/6), [frontend #9](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9) | «Informe GEN-01 3 (frontend)», Evidencias 6, 7 y 9; «Informe GEN-01 4 (Gemini)», Evidencia 7 |
| Criterio: conservación de resultados parciales | `backend/tests/unit/test_run_generation_request.py::test_a_rejected_step_and_a_valid_one_give_partial_success`<br>`backend/tests/unit/test_run_generation_request.py::test_steps_after_the_deadline_fail_and_previous_ones_are_kept`<br>`backend/tests/integration/test_generation_request_sweep.py::test_an_ownerless_queued_request_is_interrupted_without_restarting_and_a_live_one_is_kept` | [backend #14](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14) | «Informe GEN-01 3 (frontend)», Evidencia 5 |
| Criterio: repetir un pedido con los mismos datos no duplica recursos | `backend/tests/e2e/test_generation_requests_api.py::test_the_same_key_returns_the_same_request_and_other_content_conflicts`<br>`backend/tests/integration/test_generation_request_repository.py::test_concurrent_inserts_with_the_same_key_create_a_single_request`<br>`src/features/generation/hooks/useStartGeneration.test.ts::"tras agotar los reintentos conserva la clave para reenviarla sin duplicar"` | [backend #14](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14); [frontend #6](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/6), [frontend #9](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/9) | «Informe GEN-01 2 (backend, Swagger)», Evidencia 4 |
| Criterio: otro docente no puede consultar el pedido | `backend/tests/e2e/test_generation_requests_api.py::test_another_teacher_cannot_see_the_request_or_use_the_unit`<br>`backend/tests/unit/test_generation_request_use_cases.py::test_a_foreign_or_missing_request_is_not_found`<br>`backend/tests/integration/test_generation_evidence_isolation.py::test_one_teacher_never_gets_fragments_of_another_with_the_same_unit_id` | [backend #14](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14) | «Informe GEN-01 2 (backend, Swagger)», Evidencias 5, 10 y 11 |
| Criterio: los recursos vigentes llegan a revisión con huella, resultado de verificación y copia histórica completa; los pendientes pueden llegar con el motivo registrado, pero no pueden aprobarse ni exportarse | `backend/tests/unit/test_run_generation_request.py::test_a_resource_is_delivered_pending_even_if_its_fingerprint_also_fails`<br>`backend/tests/unit/test_legacy_stored_data.py::test_without_a_complete_copy_it_is_pending_cannot_be_retried_and_is_not_exported`<br>`backend/tests/unit/test_accounts_and_review.py::test_resource_delivered_pending_by_generation_cannot_be_approved` | [backend #14](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/14) | «Informe GEN-01 4 (Gemini)», Evidencia 12 (verificación de 3 de 3 afirmaciones) |
| Criterio: una regeneración fallida, o sobre una versión que ya cambió, no descarta el anterior | `backend/tests/e2e/test_generation_requests_api.py::test_a_failed_regeneration_leaves_the_previous_resource_untouched`<br>`backend/tests/e2e/test_generation_requests_api.py::test_editing_the_resource_while_it_regenerates_keeps_both`<br>`backend/tests/unit/test_regenerated_resource_missing.py::test_a_succeeded_answer_whose_new_resource_no_longer_exists_keeps_the_original` | [backend #17](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/17), [backend #23](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/23) | Sin evidencia manual todavía (regeneración, como GEN-C7) |

PR transversales de GEN-01, sin un caso propio: [backend #16](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/16) (scripts de evaluación y de contratos sobre el pedido nuevo, T045), [backend #22](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/22) y [backend #24](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/24) (retiro de la ruta y el servicio síncronos, T046, el segundo con CC-01) y [backend #25](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/25) (comparación del contrato OpenAPI en la CI, T048).

Despliegue en Render: «Informe GEN-01 2 (backend, Swagger)», Evidencias 12 y 13.

## Dependencias y trabajo en paralelo

- Las tareas T001 a T004 son independientes entre sí. T005 y T006 pueden avanzar al mismo tiempo que ellas.
- T008 depende de T005 y T007. T010 y T011 dependen de T006 y pueden hacerse en paralelo.
- T015 a T017 dependen de T002, T005, T006 y T013. T019 depende de T015 a T018. T020 depende de T008 a T011 y de T019.
- El frontend puede empezar T035, T039, T040 y T041 contra el contrato del paso 3, sin esperar el backend. T036 a T038 y T042 esperan a T034.
- Bloqueadas por equipos externos:
  - **REV-01 PR 1:** T025 a T030.
  - **CC-01 httpClient:** T034, y en cadena T036 a T038, T042 y T043.
  - **MAT-01 retrieval_mode:** T031 a T033.
- HU-024: T050 y T051 son independientes; T052 depende de los dos, y T053 y T055 de T052. T058 (Silvana) puede empezar con el contrato de T050 y T051. T059 (Juan) puede avanzar en paralelo con T054, sobre la estructura de [data-model](data-model.md#actividad_kinestesica), salvo su parte de la huella, que depende de T054 (`normalize_structure` debe conservar `materials`, `estimatedMinutes` y `space`).
- TA-010: T062 a T066 van en cadena; T067 (Sergio) es independiente y T068 necesita T065, T066 y T067.
- El backend no se integra a `main` sin T026, para que ningún recurso llegue a Revisión sin `verification` y los que no tengan copia histórica completa lleguen pendientes.
