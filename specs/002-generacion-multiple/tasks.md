# Tareas de Generación

[Ficha GEN-01](spec.md) · [Plan](plan.md) · [Research](research.md) · [Modelo de datos](data-model.md) · [Contrato](contracts/generation-requests.openapi.yaml) · [Puertos](contracts/ports.md) · [Validación](quickstart.md)

Las tareas siguen el [orden de entrega del plan](plan.md#orden-de-entrega). Las rutas `backend/…` son del repositorio `Plataforma_Docente_backend`, y las rutas `src/…` son del repositorio `Plataforma_Docente_frontend`. Los casos GEN-C1 a GEN-C6 son de la historia de pedido y recuperación; GEN-C7 a GEN-C9, de la historia de evidencia verificada.

Dependencias externas que bloquean tareas:

- **REV-01 PR 1**: integración en `main` de `domain/review/content_fingerprint.py`, `domain/review/resource_verification.py` (`verify_resource`, `referenced_fragment_ids`), la columna `version` y `application/ports/outbound/resource_regeneration_port.py` con su adaptador síncrono provisional.
- **CC-01 httpClient**: ampliación de `src/shared/api/httpClient.ts`, con cabeceras opcionales y `ApiError.status` y `ApiError.code`.
- **MAT-01 retrieval_mode**: `HybridEvidenceRetriever` informa `hybrid` o `bm25_fallback` y filtra la búsqueda vectorial por docente.

## 1. Dominio

- [ ] T001 [BE] Agregar `plan_steps(mode, resource_types, quantity)` en `backend/src/platform5e/domain/generation/sequence.py`.
  - Devuelve los pasos con `position`, `stage`, `resource_type`, `agent` y `quantity`, en el orden de `order_resource_types`.
  - El modo `individual` exige exactamente un tipo; si no, lanza `SequenceError` (se traduce a `INVALID_SEQUENCE`).
  - El modo `sequence` admite de 1 a `MAX_SEQUENCE_TYPES = 8` tipos distintos.
  - Pruebas en `backend/tests/unit/test_sequence_orchestrator.py`.
  - Casos GEN-C1 y GEN-C2.
- [ ] T002 [BE] Crear `backend/src/platform5e/domain/generation/generation_request.py`.
  - Clases `GenerationRequest`, `GenerationStep`, `GenerationParameters` y `RegenerationTarget`, como dataclasses según [data-model](data-model.md).
  - `RequestStatus`: `queued`, `running`, `succeeded`, `partially_succeeded`, `failed`, `interrupted`.
  - `StepStatus`: `pending`, `running`, `succeeded`, `rejected`, `failed`, `interrupted`.
  - Funciones puras de transición: `final_status(steps)` (todos `succeeded` → `succeeded`; alguno → `partially_succeeded`; ninguno → `failed`) e `interrupt(request)`. Un estado final no se modifica.
  - `payload_hash(mode, unit_id, parameters, regeneration)` es el SHA-256 del JSON canónico (claves ordenadas, sin espacios, valores por defecto aplicados y `resourceTypes` deduplicado en el orden recibido).
  - `validate_idempotency_key` con el patrón `^[A-Za-z0-9_-]{8,128}$`.
  - Pruebas en `backend/tests/unit/test_generation_request.py`.
  - Casos GEN-C3, GEN-C4 y GEN-C6.
- [ ] T003 [BE] Agregar en `backend/src/platform5e/domain/generation/errors.py` los códigos de la entrega. Casos GEN-C5 y GEN-C6.
  - Validación: `IDEMPOTENCY_KEY_REQUIRED`, `IDEMPOTENCY_KEY_REUSED`, `INVALID_SEQUENCE`.
  - No encontrados: `GENERATION_REQUEST_NOT_FOUND`, `UNIT_NOT_FOUND`.
  - Límites y ejecución: `TOO_MANY_ACTIVE_REQUESTS`, `DEADLINE_EXCEEDED`, `EVIDENCE_UNAVAILABLE`.
  - Regeneración: `REGENERATION_UNAVAILABLE`.
- [ ] T004 [BE] Crear `backend/src/platform5e/domain/generation/evidence.py` con `build_snapshot(referenced_ids, fragments, retrieved_at)`.
  - Devuelve los `EvidenceSnapshotItem` (`id`, `text`, `location`, `documentId`, `documentName`, `sourceUrl`, `license`, `retrievedAt`) y la lista de ids que faltan.
  - Recibe los ids ya calculados, sin importar `domain/review`.
  - Pruebas en `backend/tests/unit/test_generation_evidence_snapshot.py`, con ids de `citations`, `options`, `structure.guidedSteps`, `structure.predictions` y `structure.criteria`, y con un id ausente.
  - Caso GEN-C8.

## 2. Puertos y adaptadores

- [ ] T005 [BE] Declarar en `backend/src/platform5e/application/ports/outbound/` los puertos propios con las firmas de [ports.md](contracts/ports.md#propios-de-generación). Casos GEN-C4 y GEN-C5.
  - `generation_request_repository_port.py`, incluida la excepción `IdempotencyKeyTaken(existing)`.
  - `generation_job_runner_port.py`.
- [ ] T006 [BE] Declarar en `backend/src/platform5e/application/ports/outbound/` los puertos hacia otros módulos. Casos GEN-C5, GEN-C6 y GEN-C9.
  - `unit_membership_port.py`, con `UnitContext` y `OutcomeRef`.
  - `evidence_provider_port.py`, con `EvidenceQuery`, `EvidenceFragment`, `EvidenceRetrieval`, `NoProcessedMaterial` y `EvidenceUnavailable`.
  - `retrieval_mode` se declara `Literal["hybrid", "bm25_fallback"] | None` hasta T031.
- [ ] T007 [BE] Crear la migración `backend/database/migrations/20261110000001_generation_requests.sql`. Casos GEN-C4 y GEN-C5.
  - Tablas `gen_generation_requests` y `gen_generation_steps`, según [data-model](data-model.md#persistencia).
  - Restricción `UNIQUE (teacher_id, idempotency_key)`.
  - Índices `(teacher_id, unit_id, created_at DESC)` y `(status, heartbeat_at)`.
  - Clave foránea de los pasos con `ON DELETE CASCADE`.
- [ ] T008 [BE] Implementar `backend/src/platform5e/infrastructure/persistence/repositories/sqlalchemy_generation_request_repository.py`. Casos GEN-C4 y GEN-C5.
  - Crea las tablas en SQLite como `SQLAlchemyGenerationRepository.__init__`.
  - `create` traduce la violación de unicidad a `IdempotencyKeyTaken` con el pedido existente.
  - `get` filtra por docente.
  - `mark_interrupted(stale_before)` pasa a `interrupted` los pedidos `queued` o `running` con `heartbeat_at` (o `created_at`) anterior al límite, y también sus pasos no terminados.
  - Pruebas en `backend/tests/integration/test_generation_request_repository.py`: misma clave en dos docentes, misma clave repetida en un docente, inserción concurrente y barrido de arranque que conserva los pedidos con latido reciente.
- [ ] T009 [BE] Implementar `backend/src/platform5e/infrastructure/jobs/thread_pool_generation_runner.py` sobre `ThreadPoolExecutor`. Casos GEN-C2 y GEN-C4.
  - Agregar `GENERATION_MAX_WORKERS` (2) y `GENERATION_REQUEST_DEADLINE_SECONDS` (900) a `backend/src/platform5e/infrastructure/settings.py`.
  - Una excepción no controlada en la tarea deja el pedido `failed` y se registra en el log.
- [ ] T010 [BE] Implementar `backend/src/platform5e/infrastructure/adapters/account_unit_membership_adapter.py` sobre `TeacherRepositoryPort.get_courses` y `find_course_and_unit`. Caso GEN-C5.
  - Devuelve `None` tanto para una unidad ajena como para una inexistente.
  - Pruebas de unidad propia, ajena e inexistente.
  - Coordinar la firma con la tarea T007 de [CC-01](../003-cuentas-y-cursos/tasks.md).
- [ ] T011 [BE] Implementar `backend/src/platform5e/infrastructure/adapters/material_evidence_adapter.py`. Casos GEN-C2 y GEN-C6.
  - `has_processed_material` se basa en `ChunkRepositoryPort.get_chunks_by_unit(teacher_id, unit_id)`.
  - `retrieve` siempre pasa los fragmentos del docente a `HybridEvidenceRetriever` y nunca usa `get_chunks_by_unit("", …)`.
  - `documentName`, `sourceUrl` y `license` salen de `TeacherRepositoryPort.get_documents` (`fileName` y `origin`).
  - `retrieval_mode = None` hasta T031.
- [ ] T012 [BE] Ampliar `backend/tests/architecture/test_layer_dependencies.py`: `application/use_cases/generation/` no importa `application/services/{accounts,materials,review}` ni `domain/review`. Constitución I.

## 3. Casos de uso y router

- [ ] T013 [BE] Extraer de `generation_service.py` a `backend/src/platform5e/application/services/generation/step_drafting.py` las funciones `_draft_resources`, `_filter_repeated`, `_build_resource_dict` y `build_grounding_report`. Caso GEN-C3.
  - Cada rechazo lleva `kind` (`grounding`, `repetition`, `structure` o `distractor`).
  - `generation_service.py` delega en el módulo nuevo hasta T046.
  - Mover las pruebas afectadas de `backend/tests/unit/test_generation_with_material.py`.
- [ ] T014 [BE] Adaptar `build_generation_context` en `backend/src/platform5e/application/services/generation/prompt_drafting.py` para recibir `UnitContext` y `EvidenceFragment`. Caso GEN-C2.
  - Las etiquetas `F1…Fn` y `secuenciaPrevia` no cambian.
  - Prueba de equivalencia con el contexto actual.
- [ ] T015 [BE] Crear `backend/src/platform5e/application/use_cases/generation/start_generation_request.py`, que aplica estas reglas en orden. Casos GEN-C4, GEN-C5 y GEN-C6.
  1. Clave: `validate_idempotency_key` (`IDEMPOTENCY_KEY_REQUIRED` o `INVALID_PARAMETERS`).
  2. Pertenencia: si es `None`, `UNIT_NOT_FOUND`.
  3. `find_by_key`: si la clave ya tiene un pedido, con el mismo hash (`mode`, `unitId`, parámetros y regeneración) lo devuelve con `created = False`; con otro hash, `IDEMPOTENCY_KEY_REUSED`. En los dos casos no se aplican las reglas siguientes, así que un pedido aceptado se recupera aunque la unidad ya no tenga material.
  4. `outcomeId` de la unidad: si no, `INVALID_OUTCOME`.
  5. `plan_steps`.
  6. `has_processed_material`: si es falso, `NO_PROCESSED_MATERIAL`, sin crear el pedido.
  7. `count_active >= 2`: `TOO_MANY_ACTIVE_REQUESTS`.
  8. `create`, que ante `IdempotencyKeyTaken` aplica la regla 3 al pedido ganador, y luego `submit`.
- [ ] T016 [BE] Crear `backend/src/platform5e/application/use_cases/generation/run_generation_request.py`. Casos GEN-C1, GEN-C2, GEN-C3 y GEN-C6.
  - **Inicio:** `mark_running`, nueva comprobación de pertenencia y una sola llamada a `retrieve`, guardada con `save_evidence` y `retrievedAt`.
  - **Cada paso en orden 5E:** marcarlo `running`, redactar con `step_drafting`, aplicar el control de repetición contra los recursos aceptados de los pasos anteriores, adjuntar multimedia, guardar los recursos con `ResourceReviewRepositoryPort.save_resources` (incluidos `requestId`, `agent`, `params`, `generatorKind` y `evidence`) y después confirmar el paso con `update_step`.
  - **Durante la ejecución:** latido cada 15 s y plazo de `GENERATION_REQUEST_DEADLINE_SECONDS`, tras el cual los pasos restantes pasan a `failed` con `DEADLINE_EXCEEDED`.
  - **Final:** `finish(final_status(steps))`.
  - El bloque `verification` se agrega en T026. Esta rama no se integra a `main` sin T026.
- [ ] T017 [BE] Crear `backend/src/platform5e/application/use_cases/generation/get_generation_request.py` con `get(teacher_id, request_id)` y `list(teacher_id, unit_id, active_only, limit)`. Casos GEN-C4 y GEN-C5.
  - Un pedido ajeno o inexistente lanza `GENERATION_REQUEST_NOT_FOUND`.
  - `list` exige la pertenencia de la unidad.
  - Cada paso incluye la vista corta de sus recursos (`id`, `title` y `verificationStatus`).
- [ ] T018 [BE] Crear `backend/src/platform5e/infrastructure/http/schemas/generation_requests.py` con `StartGenerationRequest`, `GenerationRequestSummary`, `GenerationRequestStatus` y `GenerationStep`, según [el contrato](contracts/generation-requests.openapi.yaml). Casos GEN-C1 y GEN-C2.
  - Se reutilizan `ResourceType`, `Difficulty`, `GroundingReport` y `DistractorReliability` de `schemas/generations.py`.
  - Rangos: `resourceTypes` de 1 a 8 elementos, `quantity` de 1 a 5, `optionCount` de 2 a 5, `topK` de 1 a 50, `evidenceThreshold` de 0 a 1, `instructions` hasta 500 caracteres, `audience` y `competency` hasta 200.
- [ ] T019 [BE] Crear `backend/src/platform5e/infrastructure/http/routers/generation_requests.py`. Casos GEN-C1 a GEN-C6.
  - `POST /api/v1/generation-requests` responde `202` con `Location` si crea el pedido y `200` si ya existía.
  - Sin `Idempotency-Key`: `400 IDEMPOTENCY_KEY_REQUIRED`. Con formato inválido: `422 INVALID_PARAMETERS`.
  - `429` incluye `Retry-After`.
  - `GET /api/v1/generation-requests/{requestId}` y `GET /api/v1/generation-requests?unitId=&active=&limit=`.
  - Mover `GET /api/v1/generator` sin cambios y marcar `POST /api/v1/generations` con `deprecated=True` en `routers/generations.py`.
  - Agregar `429` a `ERROR_DESCRIPTIONS` en `backend/src/platform5e/infrastructure/http/schemas/common.py`.
- [ ] T020 [BE] Conectar en `backend/src/platform5e/main.py` los puertos y adaptadores de T008 a T011 y los casos de uso de T015 a T017. Caso GEN-C4.
  - El `lifespan` crea y cierra el ejecutor.
  - Antes de aceptar tráfico, llama a `mark_interrupted(now - 60 s)`.
  - `worker_boot_id` es un uuid por proceso.
- [ ] T021 [BE] Ejecutar `python backend/scripts/export_openapi.py`, revisar el diff de `docs/api/openapi.json` contra `contracts/generation-requests.openapi.yaml` y actualizar `backend/tests/integration/test_openapi_documentation.py` y `backend/tests/unit/test_api_documentation.py`. Constitución II.
- [ ] T022 [BE] Agregar pruebas de `RunGenerationRequest` con generadores falsos en `backend/tests/unit/test_run_generation_request.py`. Casos GEN-C2, GEN-C3 y GEN-C6.
  - Un paso rechazado y otro válido dan `partially_succeeded`, con `rejections[].reason`.
  - Todos los pasos fallidos dan `failed` con `failure.message`.
  - La IA falla y responde el generador por reglas con `generator.fallback = true`.
  - Un recurso repetido se rechaza tras un reintento.
  - Se supera el plazo.
  - La evidencia se recupera una sola vez para todos los pasos.
- [ ] T023 [E2E] Adaptar `backend/tests/e2e/test_sequence_api.py` al flujo `202` con consulta hasta el estado final, conservando `_unit_with_material` y las aserciones de etapa y agente. Caso GEN-C2.
- [ ] T024 [E2E] Crear `backend/tests/e2e/test_generation_requests_api.py` para comprobar el contrato HTTP de punta a punta. Casos GEN-C1, GEN-C4, GEN-C5 y GEN-C6, y V10.
  - **Pedido individual:** se crea y termina.
  - **Idempotencia:** la misma clave y el mismo cuerpo responden `200` con el mismo `id` y sin recursos nuevos; la misma clave con otro cuerpo responde `409`.
  - **Aislamiento:** un segundo docente recibe `404` al consultar el pedido y `404 UNIT_NOT_FOUND` en la unidad ajena.
  - **Sin material:** responde `400 NO_PROCESSED_MATERIAL` y no crea ningún pedido.
  - **Límite:** el tercer pedido activo responde `429`.

## 4. Verificación y regeneración

- [ ] T025 [BE] **Depende de REV-01 PR 1.** Declarar `backend/src/platform5e/application/ports/outbound/resource_verification_port.py` e implementar `backend/src/platform5e/infrastructure/adapters/review_verification_adapter.py`, que delega en `content_fingerprint` y en `verify_resource` y `referenced_fragment_ids` de REV-01. Caso GEN-C8.
- [ ] T026 [BE] **Depende de T025.** Integrar la verificación en `run_generation_request.py`. Casos GEN-C1 y GEN-C8.
  - Reemplazar las dos comprensiones que solo reúnen `citations` y `options` por `referenced_fragment_ids` del puerto, tanto para filtrar los fragmentos del paso como para `build_snapshot`.
  - Llamar a `verify(resource, evidenceThreshold)` después de la copia.
  - Si devuelve `insufficient`, el borrador se rechaza con `kind = grounding`.
  - Si lanza un error, el recurso se guarda con `status = pending` y el motivo.
  - Guardar el bloque `verification` completo y `version = 1`.
- [ ] T027 [BE] **Depende de T026.** Agregar pruebas en `backend/tests/unit/test_generation_evidence_snapshot.py`. Caso GEN-C8.
  - Recursos de `exploracion_guiada`, `reto_prediccion` y `caso_aplicado` redactados por reglas: la copia incluye los fragmentos de pasos, predicciones y criterios.
  - Si falta un fragmento referenciado, `verification.status = pending` con `retryAvailable = false`.
- [ ] T028 [BE] **Depende de REV-01 PR 1.** Crear `backend/src/platform5e/application/use_cases/generation/start_regeneration.py`. Caso GEN-C7.
  - Crea un pedido `regeneration` de un paso con los `params` guardados del recurso y la evidencia actual.
  - Usa la clave `regen-{resourceId}-v{resourceVersion}`.
  - Un recurso sin `params` lanza `REGENERATION_UNAVAILABLE`.
  - Los recursos nuevos llevan `regeneratedFrom: {resourceId, version}`.
- [ ] T029 [BE] **Depende de REV-01 PR 1 y T028.** Implementar `backend/src/platform5e/infrastructure/adapters/generation_regeneration_adapter.py` sobre `resource_regeneration_port.py`, y en `main.py` reemplazar con él el adaptador síncrono provisional de Revisión. Caso GEN-C7.
  - `request_regeneration` llama a `StartRegeneration`.
  - `get_regeneration` traduce los estados: `queued` → `pending`, `running` → `running`, `succeeded` → `succeeded`, y `failed` o `interrupted` → `failed` con `reason`.
  - Devuelve `new_resource_ids`.
- [ ] T030 [E2E] **Depende de T029.** Probar la regeneración en `backend/tests/e2e/test_generation_requests_api.py` por la ruta de Revisión `POST /api/v1/units/{unitId}/resources/{resourceId}/regenerations`. Caso GEN-C7.
  - **Éxito:** el recurso anterior queda `descartado`.
  - **Repetición:** no crea otro pedido ni recursos.
  - **Edición durante el pedido:** conserva los dos recursos.
  - **Fallo:** no toca el recurso anterior.
- [ ] T031 [BE] **Depende de MAT-01 retrieval_mode.** Mapear en `material_evidence_adapter.py` el modo que informa el recuperador, quitar `None` del tipo en `evidence_provider_port.py` y guardar `retrieval_mode` en el pedido. Caso GEN-C9.
- [ ] T032 [E2E] **Depende de T031.** Con `EMBEDDINGS_ENABLED=false`, comprobar `retrievalMode = bm25_fallback` y que `steps[].generator.fallback` solo refleja el respaldo de redacción. Caso GEN-C9.
- [ ] T033 [BE] **Depende de MAT-01 retrieval_mode (filtro por docente).** Agregar una prueba de integración con dos docentes en `backend/tests/integration/test_generation_evidence_isolation.py`: la recuperación híbrida de un docente no devuelve fragmentos del otro, aunque compartan `unit_id` en los datos de prueba. Constitución IV.

## 5. Frontend

- [ ] T034 [FE] **Depende de CC-01 httpClient.** Acordar con CC-01, en un PR coordinado fuera de `src/features/generation`, la ampliación de `src/shared/api/httpClient.ts`. Casos GEN-C4 y GEN-C5.
  - Parámetro opcional de cabeceras.
  - Acceso al código de estado de la respuesta.
  - `ApiError` con `status` y `code`.
  - Las llamadas existentes no cambian.
- [ ] T035 [FE] Crear `src/features/generation/model/generationRequest.ts`. Casos GEN-C2, GEN-C3 y GEN-C8.
  - Tipos escritos a mano según `docs/api/openapi.json`: `RequestStatus`, `StepStatus`, `StartGenerationRequest`, `GenerationRequestStatus` y `GenerationStep`.
  - Funciones `isTerminal`, `stepLabel` y `verificationLabel` (`current` → vigente, `pending` → pendiente).
  - Pruebas en `src/features/generation/model/generationRequest.test.ts`.
- [ ] T036 [FE] **Depende de T034.** Crear `src/features/generation/api/generationApi.ts` sobre `request` de `src/shared/api/httpClient.ts`. Casos GEN-C4 y GEN-C5.
  - `startGenerationRequest(token, key, body)` devuelve `{ request, created }` según `202` o `200`.
  - `getGenerationRequest(token, id)`.
  - `listGenerationRequests(token, unitId, active)`.
  - Pruebas en `src/features/generation/api/generationApi.test.ts`, como `coursesApi.test.ts`.
- [ ] T037 [FE] **Depende de T036.** Crear `src/features/generation/hooks/useStartGeneration.ts`. Casos GEN-C4, GEN-C5 y GEN-C6.
  - Crea la clave con `crypto.randomUUID()` y guarda `{ key, payload, requestId }` en `sessionStorage` bajo `generation:{unitId}` antes de enviar.
  - Si falla la red, reintenta con la misma clave.
  - Muestra el `message` de `409 IDEMPOTENCY_KEY_REUSED` y ofrece un pedido nuevo con otra clave.
  - Muestra `429` y `400 NO_PROCESSED_MATERIAL`, con un enlace a la pestaña Material.
- [ ] T038 [FE] **Depende de T036.** Crear `src/features/generation/hooks/useGenerationRequest.ts`. Casos GEN-C2 y GEN-C4.
  - Consulta cada 2 s, con espera creciente hasta 10 s, y se detiene en un estado final.
  - Al montar, recupera el `requestId` guardado o, si no hay ninguno, consulta `listGenerationRequests(…, active = true)`.
  - Ante un `404`, limpia `sessionStorage`.
- [ ] T039 [FE] Crear `src/features/generation/components/GenerationForm.tsx`. Casos GEN-C1 y GEN-C2.
  - Selector de modo individual o secuencia.
  - Tipos tomados de `GET /api/v1/resource-types`, con un tipo en el modo individual y hasta 8 en la secuencia.
  - `quantity` de 1 a 5, común a todos los tipos.
  - Resultado de aprendizaje opcional, entre los de la unidad.
- [ ] T040 [FE] Crear `src/features/generation/components/GenerationProgress.tsx`. Casos GEN-C2, GEN-C3, GEN-C6 y GEN-C8.
  - Muestra los pasos en orden 5E con el estado que informa el servidor.
  - Los recursos de cada paso aparecen con su estado de verificación y un enlace a Revisión.
  - Los rechazos aparecen con su motivo.
  - Muestra `failure.message` cuando el pedido falla.
  - El estado `interrupted` ofrece crear un pedido nuevo.
- [ ] T041 [FE] Crear `src/features/generation/components/FallbackNotices.tsx`, con avisos distintos para `retrievalMode = bm25_fallback` y para `generator.fallback`. Con `retrievalMode = null` no muestra aviso de búsqueda. Los datos reales dependen de T031. Caso GEN-C9.
- [ ] T042 [FE] **Depende de T037 y T038.** Reemplazar el marcador `src/features/generation/pages/GenerationPage.tsx`. Casos GEN-C1 a GEN-C6.
  - Usa `course`, `unit`, `token` y `onSessionExpired` del contexto de `UnitLayout`.
  - Compone el formulario, el progreso y los avisos.
  - Estilos en `src/features/generation/generation.css`.
  - Pasa `npm run lint` y `npm test`.
- [ ] T043 [E2E] **Depende de T042 y T024.** Recorrer en el navegador el [recorrido de interfaz](quickstart.md#recorrido-en-interfaz) y adjuntar la evidencia. Casos GEN-C2, GEN-C4 y GEN-C9.
  - Recargar a mitad de una secuencia y recuperar su progreso.
  - Cortar la red al enviar y reintentar sin duplicar el pedido.
  - Distinguir los avisos de respaldo.

## 6. Carga, retirada y cierre

- [ ] T044 [E2E] Medir la carga ([V11](quickstart.md#v11--carga)): 5 secuencias de 8 × 5 con `LLM_PROVIDER=gemini` y con `rules`.
  - Registrar aquí p50, p95, llamadas al modelo por paso y pedidos con `DEADLINE_EXCEEDED`.
  - Si el p95 con Gemini supera 10 min, bajar el tope a 20 recursos por pedido en `spec.md`, `research.md` (R4) y T018.
- [ ] T045 [BE] Migrar los consumidores de la ruta antigua:
  - `backend/evaluation/collect_samples.py` pasa a `POST /api/v1/generation-requests` con consulta hasta el estado final.
  - `backend/scripts/export_contracts.py` exporta `StartGenerationRequest` en lugar de `GenerationRequest`. Actualizar `docs/api/contracts/generation-request.v1.json`.
- [ ] T046 [BE] **Depende de T045.** Retirar la ruta y el servicio antiguos.
  - Quitar `POST /api/v1/generations` y el modo demostración.
  - Eliminar lo que quede de `generation_service.py` y `generation_repository_port.py`.
  - Conservar la lectura de `GET /api/v1/generations/{id}` sobre `generaciones_demo` para el historial.
  - Exportar OpenAPI de nuevo, como en T021.
- [ ] T047 [BE] Coordinar con CC-01 el borrado de los pedidos de las unidades de un curso eliminado, en `gen_generation_requests` y en cascada en los pasos, dentro de la tarea T008 de [CC-01](../003-cuentas-y-cursos/tasks.md).
- [ ] T048 [BE] Proponer a CC-01 un paso en `.github/workflows/backend-ci.yml` que compare la exportación de OpenAPI con `docs/api/openapi.json`. Constitución II.
- [ ] T049 [E2E] Enlazar en este archivo la evidencia de cada caso, de GEN-C1 a GEN-C9, y de los criterios de éxito de la ficha: orden de etapas, recuperación, resultados parciales, no duplicación, aislamiento, huella y verificación en cada recurso, y regeneración fallida que conserva el anterior.

## Dependencias y trabajo en paralelo

- Las tareas T001 a T004 son independientes entre sí. T005 y T006 pueden avanzar al mismo tiempo que ellas.
- T008 depende de T005 y T007. T010 y T011 dependen de T006 y pueden hacerse en paralelo.
- T015 a T017 dependen de T002, T005, T006 y T013. T019 depende de T015 a T018. T020 depende de T008 a T011 y de T019.
- El frontend puede empezar T035, T039, T040 y T041 contra el contrato del paso 3, sin esperar el backend. T036 a T038 y T042 esperan a T034.
- Bloqueadas por equipos externos:
  - **REV-01 PR 1:** T025 a T030.
  - **CC-01 httpClient:** T034, y en cadena T036 a T038, T042 y T043.
  - **MAT-01 retrieval_mode:** T031 a T033.
- El backend no se integra a `main` sin T026, para que ningún recurso llegue a Revisión sin `verification` ni copia histórica completa.
