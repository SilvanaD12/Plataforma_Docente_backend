# Tareas de Revisión y exportación (REV-01)

[Ficha REV-01](spec.md) · [Plan](plan.md) · [Decisiones](research.md) · [Modelo de datos](data-model.md) · [Contrato](contracts/review-export.openapi.yaml) · [Validación](quickstart.md)

## Cómo leer las tareas

Formato: `- [ ] Txxx [P] [BE|FE|E2E] [USn] Descripción`.

| Marca | Significado |
|---|---|
| `[P]` | Se puede hacer en paralelo: otro archivo y sin dependencias pendientes |
| `[BE]` | Repositorio `Plataforma_Docente_backend`. Rutas relativas a la raíz del repositorio; el código está en `backend/src/platform5e/`. |
| `[FE]` | Repositorio `Plataforma_Docente_frontend`, en la rama `feat/revision-y-exportacion` |
| `[E2E]` | Recorrido en el navegador con backend y frontend locales. Se documenta con capturas y estados HTTP. |
| `[US1]` | Historia 1 · Editar un recurso sin perder el control del respaldo (REV-C1 a C6, C10, C11, C14) |
| `[US2]` | Historia 2 · Regenerar un recurso sin perder el anterior (REV-C12, C13) |
| `[US3]` | Historia 3 · Exportar solo lo verificado y consultar lo descargado (REV-C7, C8, C9) |

Las fases siguen los bloques del [plan](plan.md#orden-de-entrega). En cada bloque se escriben primero las pruebas y
se comprueba que fallan; después va la implementación. Comandos de comprobación del backend, desde `backend/`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit tests/architecture tests/integration -q
.\.venv\Scripts\python.exe -m pytest tests/e2e -q
.\.venv\Scripts\python.exe scripts/export_openapi.py   # si cambia la API
```

Comandos del frontend, desde su raíz: `npm ci`, `npm run lint`, `npm test` y `npm run build`.

Juan hace los commits, las ramas y los PR. Las tareas de cierre de cada bloque indican cuándo toca hacerlos.

## Fase 1 · Preparación

- [x] T001 [BE] Correr la línea base de pruebas del backend en `feat/revision-y-exportacion` (los tres comandos de arriba) y anotar el resultado en el registro de avance antes de cambiar código. Ruta: `backend/tests/`.
- [x] T002 [FE] Clonar `Plataforma_Docente_frontend` y crear la rama `feat/revision-y-exportacion` desde `main` actualizado (`git switch main`, `git pull --ff-only origin main`; `616390a` o posterior, con los PR #1 y #2 integrados, H14). Comprobar que existen `UnitLayout`, `ReviewPage` y `ExportPage`. Correr `npm ci`, `npm run lint`, `npm test` y `npm run build` como línea base. Ruta: `Plataforma_Docente_frontend/`.

## Fase 2 · Base compartida: bloque a) huella y versión de la regla

Bloquea a todas las historias. Casos REV-C2, C4, C5 · REV-R1, R2.

- [x] T003 [P] [BE] Crear `backend/tests/unit/test_content_fingerprint.py`. Debe probar:
  - Formato `sha256:<64 hex>`.
  - Espacios equivalentes, `bodyHtml`, `title`, `status`, `edited`, `media`, `evidence` y `grounding` no cambian la huella.
  - Reordenar `options` con los mismos `id` no la cambia (REV-C2).
  - Cambiar `decision` o `discardReason` de un distractor no la cambia (REV-C4).
  - Cambiar el texto de la opción correcta, el texto de un distractor, un `feedback`, un `claim` o `body` sí la cambia (REV-C2, C4).
  - Cambiar los `fragmentIds` referenciados en `citations`, `options` o `structure` también la cambia: son las fuentes vinculadas de REV-R6.
  - En la imagen, cambiar `prompt` o `caption` la cambia. Cambiar solo `alt` **no** la cambia (D1).
  - En `ordenar_pasos`, cambiar el orden de `sequence` la cambia.
  - Dos recursos con distinta huella permiten detectar un resultado de otra versión (REV-C5).
- [x] T004 [BE] Crear `backend/src/platform5e/domain/review/__init__.py` y `backend/src/platform5e/domain/review/content_fingerprint.py`, con `normalize_verifiable_content(resource) -> dict` y `content_fingerprint(resource) -> str`, según D1 de [research.md](research.md#d1-huella-del-contenido-verificable-rev-r1-rev-r2--rev-c2-c4-c5):
  - NFC y espacios colapsados; `body` como lista de párrafos.
  - Opciones ordenadas por `id`, con `id`, `text`, `isCorrect`, `feedback` y `sourceFragmentIds`.
  - Sin `alt` en la estructura de la imagen.
  - `citations` normalizadas y ordenadas.
  - `structure` pasada por `normalize_structure`.
  - JSON canónico y SHA-256.
  - Sin importar `application` ni `infrastructure`.
- [x] T005 [P] [BE] Agregar `VERIFICATION_RULE_VERSION: int = 1` en `backend/src/platform5e/domain/generation/grounding.py`, con un comentario que diga cuándo se incrementa. No cambiar ninguna otra regla del archivo, porque es compartido con Generación.
- [x] T006 [BE] Cierre del bloque a): correr las pruebas, comprobar que `test_grounding.py` y `test_distractor_reliability.py` siguen pasando sin cambios, anotar los resultados y hacer el **commit a)**. Ruta: `backend/tests/`.

## Fase 3 · Historia 1: editar sin perder el control del respaldo (prioridad 1)

**Objetivo.** Cada guardado verifica contra la copia histórica, rechaza versiones obsoletas y bloquea la aprobación
sin una verificación vigente.

**Prueba independiente.** Con la unidad de la Fase 0:
- un PUT con `expectedVersion` antiguo responde 409;
- editar una afirmación sin respaldo deja `insufficient` y bloquea la aprobación;
- reprocesar el material no cambia `evidence` ni `verification`.

### Bloque b) revalidar al guardar y conflicto de versión (REV-C1, C6, C14 · REV-R3, R4, R6, R12)

> **Dependencia con Yan, antes de empezar.** Enviar el mensaje 1 de [research.md](research.md#mensajes-para-el-grupo-antes-de-los-bloques-que-los-necesitan). Generación debe guardar `verification`, `version = 1` y `evidence[].retrievedAt` al crear. Mientras no lo haga, los recursos nuevos se cubren con T048.

- [x] T007 [P] [BE] [US1] Crear `backend/tests/unit/test_resource_verification.py` para `verify_resource`. Casos:
  - Copia completa y afirmaciones respaldadas: `current`.
  - Afirmación sin respaldo: `insufficient` con `reason` (REV-C1).
  - Copia ausente, o un fragmento referenciado sin texto: `pending` con `retryAvailable = false` y motivo de regenerar (REV-R6).
  - `explicacion` con un párrafo sin respaldo: `insufficient`.
  - `exploracion_guiada` con menos pasos enlazados que `MIN_ITEMS`: `insufficient`.
  - Distractor editado que la evidencia muestra como correcto: queda `reliabilityWarning`, pero el estado no cambia por eso (REV-C4).
  - Excepción interna: `pending` con `retryAvailable = true`.
  - Umbral tomado de `verification.evidenceThreshold`, luego `grounding.threshold`, luego `params.evidenceThreshold` y por último `DEFAULT_THRESHOLD`.
  - `evidence[].retrievedAt = null` no invalida la copia.
- [x] T008 [P] [BE] [US1] Ampliar `backend/tests/unit/test_accounts_and_review.py` con:
  - PUT sin cambio de huella: conserva `verification` y sube `version` (REV-C2).
  - Cambio de contenido: guarda una verificación nueva con la huella nueva (REV-C1).
  - Recurso `aprobado` con contenido editado: queda `pendiente` con `reviewReset = true` aunque pida `aprobado` (REV-C1).
  - `expectedVersion` distinto del vigente: 409 `VERSION_CONFLICT`, sin modificar ni el recurso ni su verificación (REV-C14).
  - Verificación con otra huella: no habilita aprobar (REV-C5).
  - Reprocesar el documento de la unidad: `evidence`, `verification` y `version` del recurso quedan iguales y la verificación sigue `current` (REV-C6).
- [x] T009 [P] [BE] [US1] Ampliar `backend/tests/e2e/test_accounts_and_review_api.py` con un servidor real:
  - Dos PUT con el mismo `expectedVersion`: el segundo responde 409 (REV-C14).
  - Editar una afirmación sin respaldo: `verification.status = insufficient` (REV-C1).
  - `POST /api/v1/documents/{id}/process` y luego `GET …/resources`: `evidence` y `verification` iguales (REV-C6).
  - La cuenta B recibe 404 en el PUT sobre la unidad de A.
- [x] T010 [BE] [US1] Crear `backend/src/platform5e/domain/review/resource_verification.py` con `verify_resource(resource, threshold, rule_version) -> dict`, según D4. Debe:
  - Usar solo `resource["evidence"]` y las funciones de `grounding.py` y `distractor_reliability.py`, sin cambiar sus reglas.
  - Devolver `status` (`current`, `insufficient` o `pending`), `reason` («Obligatorio si `status` ≠ `current`»), `fingerprint`, `verifiedVersion`, `evidenceThreshold`, `ruleVersion`, `checkedAt`, `retryAvailable` («`true` solo si `status = pending` y la copia histórica está completa») y `summary`.
- [x] T011 [P] [BE] [US1] Crear `backend/database/migrations/20261108000001_resource_version.sql` con `-- migrate:up`, que ejecuta `ALTER TABLE ep002_recursos ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;`, y `-- migrate:down`, que la quita. Probarla en la base desechable de CI con PostgreSQL. **Aviso a Sergio** para Neon (mensaje 2).
- [x] T012 [BE] [US1] Agregar `version = Column(Integer, nullable=False, default=1)` a `TeacherResourceORM` en `backend/src/platform5e/infrastructure/persistence/repositories/sqlalchemy_account_repository.py`. **El archivo es de CC-01:** solo se agrega la columna, y se avisa a Silvana en el PR.
- [x] T013 [BE] [US1] Agregar `save_resource_if_version(teacher_id, unit_id, resource, expected_version, increment=True) -> bool` en `backend/src/platform5e/application/ports/outbound/resource_repository_port.py`. Devuelve `False` si la versión ya no es la vigente.
- [x] T014 [BE] [US1] Implementar en `backend/src/platform5e/infrastructure/persistence/repositories/sqlalchemy_resource_repository.py`:
  - `save_resource_if_version` con `UPDATE … WHERE id AND docente AND version = :expected`, que suma 1 a `version` solo si `increment` es verdadero y copia `version` al JSON.
  - En SQLite, agregar la columna si falta, comprobándolo con `inspect` (H12).
  - Hacer que `save_resources` deje `version = 1` en los recursos nuevos.
- [x] T015 [BE] [US1] Ajustar `update_resource` en `backend/src/platform5e/application/services/review/resource_review_service.py`:
  - Exigir `expectedVersion`.
  - Comparar la huella nueva con `verification.fingerprint`. Si cambió, llamar `verify_resource` con el umbral guardado y `VERIFICATION_RULE_VERSION`; si no, conservar la verificación.
  - Si un recurso `aprobado` cambió su huella, dejarlo `pendiente` con `reviewReset = true`.
  - Guardar con `save_resource_if_version`. Si devuelve `False`, responder `AccountConfigurationError("VERSION_CONFLICT", "El recurso cambió en otra pestaña. Recárgalo antes de guardar.", 409)`.
- [x] T016 [P] [BE] [US1] Ajustar `backend/src/platform5e/infrastructure/http/schemas/resources.py`:
  - `ReviewedResourceInput.expected_version: int = Field(ge=1)`, obligatorio.
  - Nuevo esquema `VerificationResult`, con `status` como `Literal["current", "insufficient", "pending"]`.
  - `ResourceResponse` gana `version`, `verification` y `review_reset`.
  - `EvidenceResponse` gana `retrieved_at: str | None` («`null` = desconocida»).
  - Además, en `backend/src/platform5e/infrastructure/http/schemas/citation.py`, corregir la descripción de `similarity_score`: es una coincidencia de palabras, no similitud coseno (H13).
- [x] T017 [BE] [US1] Actualizar el PUT en `backend/src/platform5e/infrastructure/http/routers/resources.py`: la docstring con `expectedVersion`, el ejemplo cURL y el 409 `VERSION_CONFLICT`.
- [x] T018 [BE] [US1] Cierre del bloque b): correr las pruebas, ejecutar `scripts/export_openapi.py`, revisar el diff de `docs/api/openapi.json`, anotar los resultados y hacer el **commit b)**.

### Bloque c) bloqueos, estado con motivo y reintento (REV-C3, C10, C11 · REV-R5)

- [x] T019 [P] [BE] [US1] Ampliar `backend/tests/unit/test_accounts_and_review.py` con:
  - `validate_approval_blockers` con el motivo cuando falta `verification`, cuando la huella no coincide o cuando el estado es `insufficient` o `pending` (REV-C3).
  - Un recurso que llega `pending` desde Generación no se puede aprobar (REV-C11).
  - Reintento sobre `pending` con `retryAvailable` usa el `evidenceThreshold` guardado y la regla vigente, sin subir la versión del contenido.
  - Reintento sobre un recurso no `pending`: 409 `VERIFICATION_NOT_PENDING`.
  - Reintento con la copia incompleta: 409 `REGENERATION_REQUIRED`.
  - Cambiar `VERIFICATION_RULE_VERSION` sin editar conserva el estado (REV-C10).
  - Editar después de un cambio de regla, con un resultado distinto, deja un `reason` que menciona la regla anterior y la nueva (REV-C10).
- [x] T020 [P] [BE] [US1] Ampliar `backend/tests/e2e/test_accounts_and_review_api.py` con:
  - Aprobar después de una edición `insufficient`: 409 `APPROVAL_BLOCKED`, con el motivo de la verificación en `message` (REV-C3).
  - `POST …/verification` sobre un recurso `current`: 409 `VERIFICATION_NOT_PENDING`.
  - La cuenta B recibe 404 en `POST …/verification` sobre la unidad de A.
- [x] T021 [BE] [US1] En `backend/src/platform5e/application/services/review/resource_review_service.py`, conservar `validate_approval_blockers` y agregar `verification_blockers` (huella distinta, `insufficient` o `pending`, con su motivo; sin `verification`, ningún bloqueo: opción A) y `approval_blockers`, que junta las dos. La usan `update_resource`, después de calcular la verificación de la versión editada, y `ResourceResponse.approval_blockers`, que le pasa `verification` y `citations`.
- [x] T022 [BE] [US1] Agregar `retry_verification(teacher_id, unit_id, resource_id, expected_version)` en `backend/src/platform5e/application/services/review/resource_review_service.py`. Solo actúa si el estado es `pending` y `retryAvailable` es verdadero. Usa `verify_resource` con el umbral guardado y guarda con `save_resource_if_version`.
- [x] T023 [BE] [US1] En `verify_resource` (`backend/src/platform5e/domain/review/resource_verification.py`): si el resultado nuevo difiere del anterior y la `ruleVersion` guardada es otra, el motivo debe decir «la regla de verificación cambió (vN → vM)» (REV-C10).
- [x] T024 [BE] [US1] Agregar `POST /api/v1/units/{unit_id}/resources/{resource_id}/verification` en `backend/src/platform5e/infrastructure/http/routers/resources.py`. Recibe `{expectedVersion}` y documenta los errores 404 y 409 (`VERSION_CONFLICT`, `VERIFICATION_NOT_PENDING`, `REGENERATION_REQUIRED`), según [contracts/](contracts/review-export.openapi.yaml).
- [x] T025 [BE] [US1] Cierre del bloque c): correr las pruebas y `scripts/export_openapi.py`, y hacer el **commit c)** y el **PR 1** del backend. El PR debe:
  - enlazar la ficha y las tareas T003 a T025;
  - avisar del cambio incompatible del PUT;
  - enlazar el PR del frontend de T033.

  **No se integra ni se despliega en Render** hasta que el PR FE-1 esté listo (mensaje 3 a Silvana).

  **Hecho (2026-11-08):** el PR 1 es el [#6 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/6), con las correcciones de la revisión de Silvana (`becc1df` y `277ce9b`). Silvana lo integró en `main` (`5f5281b`) junto con el PR FE-1.

### FE-1 · Pestaña de revisión (REV-C1, C3, C11, C14)

> Las rutas `review` y `export` de la unidad, sus pestañas y las páginas marcador ya existen en `main` del frontend desde `d9d4f7d` (CC-01, integrado en `616390a`). Las tareas de FE-1 y FE-2 reemplazan el contenido de esos marcadores.

- [x] T026 [FE] [US1] **No aplica, resuelta por CC-01** en `d9d4f7d`: las rutas hijas `review` y `export` de `:courseId/units/:unitId` en `Plataforma_Docente_frontend/src/app/App.tsx` y sus pestañas en `src/features/units/pages/UnitLayout.tsx` ya existen. Solo comprobar en T002 que la rama del frontend las incluye.
- [x] T027 [P] [FE] [US1] Crear `Plataforma_Docente_frontend/src/features/review/api/reviewApi.test.ts` con Vitest:
  - el PUT envía `expectedVersion`;
  - un 409 `VERSION_CONFLICT` produce un error reconocible;
  - el reintento llama a `POST …/verification`;
  - la respuesta con `reviewReset` se expone al llamador.
- [x] T028 [P] [FE] [US1] Crear `Plataforma_Docente_frontend/src/features/review/model/resource.ts`, con los tipos `Resource` y `VerificationResult` según [data-model.md](data-model.md) y las etiquetas `current` → «Vigente», `insufficient` → «Insuficiente» y `pending` → «Pendiente», y su prueba `resource.test.ts`.
- [x] T029 [FE] [US1] Crear `Plataforma_Docente_frontend/src/features/review/api/reviewApi.ts` con `listResources`, `saveResource` (con `expectedVersion`) y `retryVerification`. Debe usar `request` y `ApiError` de `src/shared/api/httpClient.ts`. Adaptar lo que sirva de `Yansete/plataforma-5e-frontend@feca57c` (`src/features/review/api/reviewApi.ts`).
- [x] T030 [FE] [US1] Crear `Plataforma_Docente_frontend/src/features/review/components/VerificationBadge.tsx`, que muestra el estado en español y `reason`, el botón «Reintentar comprobación» si `retryAvailable` o el aviso «Regenera el recurso» si no. Incluir su prueba `VerificationBadge.test.tsx` (REV-C3, C11).
- [x] T031 [FE] [US1] Crear `Plataforma_Docente_frontend/src/features/review/components/ResourceEditor.tsx`. Edita título, cuerpo, opciones y estructura, guarda con la `version` leída y muestra los `approvalBlockers` del servidor sin repetir reglas. Ante un 409 `VERSION_CONFLICT`, pide recargar sin perder lo escrito hasta que el docente confirme (REV-C14). Con `reviewReset`, avisa que el recurso volvió a revisión (REV-C1).
- [x] T032 [FE] [US1] Reemplazar el marcador de `Plataforma_Docente_frontend/src/features/review/pages/ReviewPage.tsx` (hoy `UnitModulePlaceholder`), conservando el nombre `ReviewPage` y su exportación. Lee `const { course, unit } = useOutletContext<UnitContext>()`, lista los recursos de `unit.id` con carga, vacío y error, y usa `ResourceEditor` y `VerificationBadge`.
- [x] T033 [FE] [US1] Cierre de FE-1: con el backend local del PR 1, correr `npm run lint`, `npm test` y `npm run build`, revisar la pestaña en el navegador y abrir el **PR FE-1** enlazado al PR 1 del backend, con capturas. **Hecho (2026-11-08):** recorrido en el navegador correcto (pasos 1 a 8) y PR FE-1 abierto como [#4 del frontend](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/4), enlazado al [PR #6 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/6), con las correcciones de la revisión de Silvana. Silvana integró los dos en `main` (frontend `d4bfbbc`).

## Fase 4 · Historia 3: exportar solo lo verificado y consultar lo descargado (prioridad 3)

Va antes de la Historia 2, porque la Historia 2 depende del acuerdo con Yan.

**Objetivo.** Los tres formatos exportan solo recursos elegibles. El historial se consulta por docente y sobrevive al
borrado del curso. La multimedia se invalida solo por `prompt` o `script`.

**Prueba independiente.** Exportar una unidad con recursos aprobados vigentes y no vigentes; abrir el archivo;
borrar el curso y consultar `GET /api/v1/downloads`.

### Bloque d) filtro común de exportación y registro único por docente (REV-C7, C9 · REV-R7, R9)

> **Dependencia con Silvana, antes de T042.** El cambio en `delete_course` es de CC-01 (T008 de su ficha). Lo hace ella, o Juan con su aprobación en el PR. También se avisa del retiro de rutas y de la nueva ruta `GET /api/v1/downloads` (mensaje 4).

- [x] T034 [P] [BE] [US3] Ampliar `backend/tests/unit/test_export_unit_resources.py` con:
  - Un recurso aprobado con verificación `insufficient`, `pending` o de otra huella queda fuera del archivo (REV-C7).
  - Sin elegibles: 422 `NO_APPROVED_RESOURCES`, con `details` por motivo y sin generar el archivo.
  - El registro guarda `courseId`, `courseName`, `unitName` y `unitNumber`, y se crea una sola vez por exportación (REV-C9).
  - Cambiar `VERIFICATION_RULE_VERSION` no saca de la exportación a un recurso vigente (REV-C10).
- [x] T035 [P] [BE] [US3] **Hecho (2026-11-08), con el retiro de rutas aprobado por Silvana y Juan.** Antes, en parte: 5 pruebas del historial por docente agregadas; quitar las de redescarga queda para T041. Ajustar `backend/tests/unit/test_download_history.py`: quitar las pruebas de `get_download_record` (redescarga) y agregar el historial por docente, incluido después de borrar el curso. Debe mostrar fecha, formato, archivo, curso y unidad, y no mostrar registros de otro docente (REV-C9).
- [x] T036 [P] [BE] [US3] **Hecho (2026-11-08):** la conservación tras el borrado se probó después de integrar el PR #8 de CC-01 (`test_the_history_survives_the_deletion_of_the_course`). Ampliar `backend/tests/e2e/test_exports_api.py` con:
  - Exportar SCORM, Moodle XML y documento de unidad con un recurso aprobado vigente y otro no vigente, abrir cada archivo y comprobar que solo trae el vigente (REV-C7 · REV-R7).
  - Sin elegibles: 422 con `details`.
  - Después de `DELETE /api/v1/courses/{id}`, `GET /api/v1/downloads` sigue mostrando el registro con curso y unidad (REV-C9).
  - **Aislamiento (constitución IV):** con registros de A y de B, `GET /api/v1/downloads` con el token de B devuelve solo los suyos, sin ningún registro, curso ni unidad de A. B recibe 404 en `POST /units/{unidad de A}/exports`.
  - Las rutas retiradas `POST /units/{u}/downloads` y `GET /units/{u}/downloads/{id}` ya no existen.
- [x] T037 [BE] [US3] Crear `backend/src/platform5e/domain/review/export_eligibility.py` con `export_ineligibility(resource) -> str | None`, que devuelve un motivo técnico: `not_approved`, `verification_missing`, `verification_outdated`, `verification_insufficient`, `verification_pending` o `media_invalidated` (D6).
- [x] T038 [BE] [US3] Ajustar `backend/src/platform5e/application/use_cases/export/export_unit_resources.py`:
  - Aplicar `export_ineligibility` junto con `exporter.supports`.
  - Sin elegibles, responder 422 `NO_APPROVED_RESOURCES` con `details` del tipo `[{"reason": …, "count": …}]`.
  - Guardar en el registro `courseId`, `courseName`, `unitName` y `unitNumber`.
- [x] T039 [BE] [US3] Agregar `get_downloads_by_teacher(teacher_id)` en `backend/src/platform5e/application/ports/outbound/resource_repository_port.py` y en `backend/src/platform5e/infrastructure/persistence/repositories/sqlalchemy_resource_repository.py`, ordenado del más reciente al más antiguo.
- [x] T040 [BE] [US3] **Hecho (2026-11-08), con el retiro de rutas aprobado por Silvana y Juan.** Antes, en parte: `get_teacher_downloads` agregado (completa curso y unidad en registros antiguos si la unidad existe); quitar `get_download_record` y `register_download` va con T041. En `backend/src/platform5e/application/services/review/resource_review_service.py`, agregar `get_teacher_downloads(teacher_id)`, con un límite de `MAX_DOWNLOADS_HISTORY` y sin exigir acceso a la unidad, y quitar `get_download_record` y `register_download`.
- [x] T041 [BE] [US3] **Hecho (2026-11-08), con el retiro de rutas aprobado por Silvana y Juan.** Antes, en parte: `GET /api/v1/downloads` (router `create_teacher_downloads_router`, límite de 50) y los campos de curso y unidad en `DownloadResponse`, con su e2e de aislamiento en `test_exports_api.py`; el retiro de las dos rutas antiguas espera la respuesta de Silvana. Ajustar `backend/src/platform5e/infrastructure/http/routers/downloads.py` y `backend/src/platform5e/infrastructure/http/schemas/downloads.py`:
  - Agregar `GET /api/v1/downloads`.
  - Retirar `GET /units/{unit_id}/downloads/{download_id}` y `POST /units/{unit_id}/downloads`, y quitar `DownloadInput`.
  - `DownloadResponse` gana `course_id`, `course_name`, `unit_name` y `unit_number`, que pueden ser `null` en registros anteriores.
- [ ] T042 [BE] [US3] **CC-01:** en `backend/src/platform5e/infrastructure/persistence/repositories/sqlalchemy_account_repository.py`, quitar `DownloadORM` del bucle de `delete_course` (H5). Lo hace Silvana, o Juan con su aprobación en el PR. No tocar el borrado de `media_assets`, que también es de CC-01.
- [x] T043 [BE] [US3] Cierre del bloque d): documentar los `details` del 422 en `backend/src/platform5e/infrastructure/http/routers/exports.py`, correr las pruebas y `scripts/export_openapi.py`, y hacer el **commit d)**.

### Bloque e) multimedia por `prompt` o `script` y recursos antiguos (REV-C8 · REV-R8, R11)

> **Dependencias antes de empezar.**
> - **Sergio:** aprobar la migración para Neon y elegir la opción A (perezosa) o B (script) de D7 (mensaje 2).
> - **Equipo:** decidir qué pasa con el bloqueo multimedia si la generación de imágenes y voz está apagada (mensaje 5).

- [x] T044 [P] [BE] [US3] **Hecho (2026-11-08), con D9 opción A:** `test_editing_the_script_drops_the_old_audio_everywhere` ahora exige el bloqueo y la exclusión. Ajustar `backend/tests/unit/test_edited_media.py`:
  - Cambiar el `script` deja el respaldo con `media.invalidated = true` y **bloquea** la aprobación. Esto cambia la prueba actual `test_editing_the_script_drops_the_old_audio_everywhere`, según H10.
  - Cambiar el `prompt` de una imagen hace lo mismo.
  - Cambiar solo `alt` o `caption` conserva el archivo `ready`.
  - «Generar de nuevo» quita `invalidated` y permite aprobar.
  - El SCORM nunca incluye el archivo invalidado (REV-C8).
- [x] T045 [P] [BE] [US3] Ampliar `backend/tests/unit/test_legacy_stored_data.py` con recursos antiguos según REV-R11:
  - Copia completa y aprobado con resultado `current`: sigue `aprobado`.
  - Resultado `insufficient`: vuelve a `pendiente`.
  - Sin copia, o con un fragmento sin texto: `pending`, sin reintento y fuera de exportación.
  - Fragmento sin `retrievedAt`: queda `null`.
  - Umbral guardado o `DEFAULT_THRESHOLD`.
  - La actualización **no incrementa `version`**.
  - Si hubo un guardado concurrente, la actualización se descarta sin error.
- [x] T046 [BE] [US3] Crear `backend/src/platform5e/domain/review/media_change.py` con `media_source_changed(resource_type, old_structure, new_structure) -> bool`. Compara `prompt` para la imagen y `script` para el audio, normalizados con `normalize_structure` (D9).
- [x] T047 [BE] [US3] **Hecho (2026-11-08), con D9 opción A.** En `backend/src/platform5e/application/services/review/resource_review_service.py`:
  - Reemplazar la comparación de toda la estructura (hoy en la línea 148) por `media_source_changed`.
  - Al invalidar, dejar `fallback_media(..., EDITED_NOTES[...])` con `invalidated = true`.
  - En `validate_approval_blockers`, bloquear mientras `invalidated` esté presente.
- [ ] T048 [BE] [US3] **Adelantado en parte al bloque c):** ya existe `legacy_verification.py`, que se llama desde `list_resources` y `_get_resource_or_fail` con la regla de estado de REV-R11 e `increment=False`. Desde el bloque d) también la llama `ExportUnitResourcesUseCase` antes de filtrar. Falta solo el script de la opción B, si Sergio lo elige. Crear `backend/src/platform5e/application/services/review/legacy_verification.py` con `upgrade_resource_verification(repository, teacher_id, unit_id, resource) -> dict`, según D7. Recibe `ResourceReviewRepositoryPort`, guarda con `save_resource_if_version(..., increment=False)`, devuelve el recurso actualizado o el original si hubo un guardado concurrente, y no depende de `ResourceReviewService`.
  - **Opción A**, si Sergio la elige: llamarla para los recursos sin `verification` desde `list_resources` y `get_resource`, en `resource_review_service.py`, y desde `ExportUnitResourcesUseCase.execute`, en `export_unit_resources.py`, antes de aplicar el filtro.
  - **Opción B**: crear `backend/scripts/upgrade_resource_verification.py` con `--dry-run` y un informe por estado.
- [x] T049 [P] [BE] [US3] En `backend/src/platform5e/application/use_cases/media/regenerate_resource_media.py`, quitar `media.invalidated` cuando el archivo se genere bien. En `backend/src/platform5e/infrastructure/http/schemas/resources.py`, agregar `MediaResponse.invalidated: bool = False`.
- [ ] T050 [BE] [US3] Cierre del bloque e): correr las pruebas, incluida la de PostgreSQL con la migración aplicada, ejecutar `scripts/export_openapi.py` y hacer el **commit e)**.

## Fase 5 · Historia 2: regenerar sin perder el anterior (prioridad 2, dependiente de Yan)

**Objetivo.** Regenerar desde Revisión, descartando el anterior solo si sigue en la versión registrada.

**Prueba independiente.** Con un doble del puerto de regeneración: un éxito descarta el anterior, una edición durante
el pedido conserva ambos y un fallo deja el anterior igual.

> **Dependencia con Yan, antes de T052.** Acordar el contrato de GEN-R6: si el pedido es síncrono o en segundo plano, el nombre del puerto, el estado consultable y qué pasa si el recurso se edita durante el pedido (mensaje 1, D10). Sin ese acuerdo, esta fase no empieza.

- [x] T051 [P] [BE] [US2] **Hecho con la decisión provisional de D10 (2026-11-08), sin confirmación de Generación.** Crear `backend/tests/unit/test_resource_regeneration.py` con un doble de `ResourceRegenerationPort`:
  - Éxito con la versión intacta: el anterior queda `descartado` con `discardReason = "regenerado"` y el nuevo queda en revisión con huella y verificación (REV-C12).
  - Edición durante el pedido: ambos quedan en Revisión (REV-C12).
  - Fallo: el anterior no cambia y se devuelve el motivo (REV-C13).
  - La cuenta B recibe 404.
- [x] T052 [BE] [US2] Crear `backend/src/platform5e/application/ports/outbound/resource_regeneration_port.py` con `request_regeneration(teacher_id, resource) -> RegenerationOutcome(ok, new_resource_ids, reason)`, según el acuerdo con Yan.
- [x] T053 [BE] [US2] Crear el adaptador en `backend/src/platform5e/infrastructure/generation/generation_regeneration_adapter.py`, que delega en Generación con `params` y la evidencia vigente, e inyectarlo en `backend/src/platform5e/main.py`. Revisión no importa el servicio de Generación; `tests/architecture` lo comprueba.
- [x] T054 [BE] [US2] Agregar `regenerate_resource(teacher_id, unit_id, resource_id, expected_version)` en `backend/src/platform5e/application/services/review/resource_review_service.py`, y `POST /api/v1/units/{unit_id}/resources/{resource_id}/regenerations` con `RegenerationResponse` en `backend/src/platform5e/infrastructure/http/routers/resources.py` y en `schemas/resources.py`. Errores: 409 `VERSION_CONFLICT`; rechazos de Generación con su código (409 por el material, 422 por los parámetros guardados); 502 `REGENERATION_FAILED` solo para fallos del proveedor.
- [x] T055 [BE] [US2] Cierre del bloque f):
  - **Hecho (2026-11-08):** la e2e de regeneración con el servidor real (`test_regenerating_a_resource_from_review`: éxito, sin duplicados, fallo sin material y cuenta B con 404), `openapi.json` regenerado y D10 registrada como provisional. PR 2 abierto como [#13 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/13), enlazado al [PR #7 del frontend](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/7). D10 sigue pendiente de la confirmación de Yan.
  - **Pendiente del análisis (M3, constitución V):** cuando exista el contrato con Yan, agregar a `backend/tests/e2e/test_accounts_and_review_api.py` una prueba e2e de regeneración con el servidor real. Debe cubrir un éxito que descarta el anterior, un fallo que lo conserva y la cuenta B con 404 (REV-C12, C13).
  - Correr las pruebas y `scripts/export_openapi.py`, y hacer el **commit f)** y el **PR 2** del backend, enlazado con el PR FE-2 (T059).

## Fase 6 · FE-2: exportación, multimedia y regeneración (REV-C7, C8, C9, C12, C13)

- [x] T056 [P] [FE] [US3] Crear `Plataforma_Docente_frontend/src/features/export/api/exportApi.test.ts`:
  - el 422 `NO_APPROVED_RESOURCES` expone los motivos de `details`;
  - el historial de `GET /api/v1/downloads` muestra «Curso eliminado» cuando `courseName` es `null`.

  **Hecho (2026-11-08):** en la rama FE-2 (`4a34887`), con pruebas del modelo (`model/exportView.test.ts`), de la página y de `requestFile` en `src/shared/api/httpClient.test.ts`.
- [x] T057 [FE] [US3] Crear `Plataforma_Docente_frontend/src/features/export/api/exportApi.ts` (exportar con descarga del archivo, e historial por docente) y reemplazar el marcador de `src/features/export/pages/ExportPage.tsx` (hoy `UnitModulePlaceholder`), conservando el nombre `ExportPage` y su exportación. La página lee `useOutletContext<UnitContext>()`, ofrece los formatos, muestra el motivo sin elegibles y lista el historial con fecha, formato, archivo, curso y unidad (REV-C7, C9). Si el 422 llega sin `details`, se muestra el `message` de la API (acordado con Silvana el 2026-11-08). Adaptar lo que sirva de `feca57c` (`src/features/export`). **Hecho (2026-11-08):** en la rama FE-2 (`4a34887`): tres formatos, descarga con el nombre de `Content-Disposition` (`requestFile` en el cliente HTTP compartido), motivos de `details` o el `message` de la API, e historial del docente.
- [x] T058 [FE] [US2] Completar `Plataforma_Docente_frontend/src/features/review/pages/ReviewPage.tsx` y `components/ResourceEditor.tsx`:
  - **Pasa de FE-1 a FE-2 (acordado el 2026-11-08):** editar la `structure` de imagen, audio y actividades, y descartar con motivo (`discardReason`);
  - aviso de multimedia invalidada con el botón «Generar de nuevo» (REV-C8);
  - botón de regenerar con `expectedVersion`;
  - resultado con el anterior descartado o conservado (REV-C12);
  - motivo del fallo (REV-C13).

  **Hecho (2026-11-08):** en la rama FE-2, en cuatro commits: descarte con motivo y vuelta a revisión (`84a3f87`); editor de la estructura con los mínimos del backend (`0c7d3e6`); aviso de multimedia invalidada con «Generar de nuevo» (`c33cbc4`); y «Regenerar» con el resultado y el motivo del fallo (`439c971`). Las reglas están en `src/features/review/model/` con sus pruebas.
- [x] T059 [FE] Cierre de FE-2: correr `npm run lint`, `npm test` y `npm run build`, y abrir el **PR FE-2** enlazado al PR 2 del backend, con capturas. **Hecho (2026-11-08):** lint y build correctos y 166 pruebas; recorrido en el navegador con el backend del PR 2 (exportación con motivos, descargas e historial, descarte con motivo, estructura incompleta, regeneración y cuenta B sin acceso al historial de A). El aviso de multimedia invalidada no se pudo ver en local porque la generación de imágenes y voz no está activa; lo cubren las pruebas. PR FE-2 abierto como [#7 del frontend](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/7), enlazado al [PR #13 del backend](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/13).

## Fase 7 · Recorridos de extremo a extremo y cierre

- [ ] T060 [E2E] [US1] [US3] **Editar, verificar, aprobar y exportar en el navegador** con backend y frontend locales y la cuenta A:
  1. Abrir la pestaña Revisión de la unidad de prueba.
  2. Editar una afirmación para que no tenga respaldo y ver «Insuficiente» con su motivo y la aprobación bloqueada (REV-C1, C3).
  3. Corregir el texto y ver «Vigente».
  4. Guardar desde una segunda pestaña con la versión anterior y ver el aviso de conflicto (REV-C14).
  5. Aprobar.
  6. En Exportación, descargar SCORM y Moodle XML, abrir los archivos y confirmar que no incluyen recursos pendientes ni insuficientes (REV-C7).

  Registrar capturas y estados HTTP sin tokens. Depende de T033 y T059.
- [ ] T061 [E2E] [US3] **Borrar un curso y ver el historial:**
  1. Exportar desde un curso de prueba.
  2. Eliminar el curso desde la interfaz de CC-01.
  3. Abrir el historial y confirmar fecha, formato, archivo, curso y unidad (REV-C9).

  Depende de T042, de la tarea T009 de CC-01 (confirmación de borrado en la interfaz) y de T057.
- [ ] T062 [BE] Recorrer [quickstart.md](quickstart.md) completo, incluido el aislamiento con la cuenta B, y repetir `tests/e2e` con PostgreSQL (`E2E_DATABASE_URL` en una base desechable). Anotar todos los resultados en el registro de avance y en los PR.

### Seguimiento después de integrar los PR #13 (backend) y #7 (frontend)

Acordado con Silvana en la revisión de los PR (2026-11-09). Ninguna bloquea la integración.

- [ ] T063 [BE] **Limpiar el archivo multimedia sin referencia.** Si «Generar de nuevo» responde 409 `VERSION_CONFLICT` porque el docente guardó otra versión mientras tanto, el archivo recién generado queda guardado sin uso: `MediaRepositoryPort` no tiene forma de borrarlo. Agregar el borrado al puerto y al adaptador, o un barrido de archivos sin recurso, con su prueba.
- [ ] T064 [Yan] **Adaptador de regeneración en segundo plano (T029 de Generación).** Reemplaza en `main.py` el adaptador síncrono por el de Generación, sin tocar Revisión (D10). Revisión ya trata `pending` y `running` como «en curso», tiene `GET …/resources/{resource_id}/regeneration` y la revisión consulta ese estado, probado hoy solo con dobles. Ese PR debe agregar una prueba e2e con un pedido que pase por `running`.
- [ ] T065 [BE] **Publicación del PR #13 y del #7.** En Render, Juan comprueba que se aplicó la migración `20261109000001_regeneration_claim.sql` (columna `regeneration_claim` en `ep002_recursos`) y que `GET /api/v1/downloads` responde. Después, Yan comprueba «Mis descargas» en Vercel. Anotar los resultados, sin tokens, en el registro y en los PR.
- [x] T066 [BE] **Respuesta tardía de un intento viejo** (revisión de Silvana en el PR #17 de Yan; va antes del #17). Con el adaptador en segundo plano puede haber un intento fallido y otro nuevo desde la misma versión. El registro del estado, el descarte del anterior y la liberación de la reserva comparan el `attemptId` vigente en el mismo `UPDATE` (columna `regeneration_attempt`, migración `20261111000001_regeneration_attempt.sql`), con `save_resource_if_attempt` y `release_regeneration` por intento. Pruebas: `tests/unit/test_background_regeneration.py` y `tests/integration/test_regeneration_concurrency.py`, con `failed` y `succeeded` tardíos: el registro, la reserva y el recurso del intento nuevo quedan intactos. En Render hay que comprobar que se aplicó la migración, como en T065.
- [x] T067 [BE] **Escritura de `running` sobre un intento que ya terminó** (revisión de Silvana en el PR #17 de Yan; va antes del #17). Una consulta lee `running` y, antes de que escriba, otra consulta del mismo intento guarda `failed` y libera la reserva; como el `attemptId` es el mismo, T066 no lo impedía y el pedido siguiente respondía «en curso» sin crear uno nuevo. `save_resource_if_attempt` exige además en el mismo `UPDATE` que el intento siga en `running` (columna `regeneration_status`, migración `20261112000001_regeneration_status.sql`). Pruebas: `test_a_running_write_does_not_overwrite_the_same_attempt_once_it_failed` en `tests/unit/test_background_regeneration.py` y en `tests/integration/test_regeneration_concurrency.py`. En Render hay que comprobar que se aplicó la migración, como en T065.

## Dependencias y orden

```text
T001-T002 → Fase 2 (T003-T006) → Bloque b (T007-T018) → Bloque c (T019-T025) ─┬─► FE-1 (T027-T033; T026 no aplica)
                                                                              ├─► Bloque d (T034-T043) → Bloque e (T044-T050)
                                                                              └─► [Yan] Bloque f (T051-T055)
Bloque e + Bloque f → FE-2 (T056-T059) → E2E (T060-T061) → T062
```

| Depende de | Tareas | Motivo |
|---|---|---|
| Yan | Antes de T007; T052 a T055 | `verification` al crear y contrato de regeneración (GEN-R6) |
| Sergio | T011 en Neon; T048 | Migración y opción A o B de D7 |
| Silvana | T012 y T042 (archivo de CC-01); T025 (integración del PR 1); T061 (T009 de CC-01) | Ficha CC-01 y coordinación de despliegue |
| Equipo | T044 a T047 | Riesgo de D9 con la generación multimedia apagada |

## Paralelo dentro de cada bloque

- **Bloque a:** T003 y T005 a la vez. Después, T004.
- **Bloque b:** T007, T008, T009, T011 y T016 a la vez, porque son archivos distintos. Después, T010 → T013 → T014 → T015 → T017.
- **Bloque c:** T019 y T020 a la vez. Después, T021 a T024.
- **FE-1:** T027 y T028 a la vez. Después, T029 → T030 → T031 → T032.
- **Bloque d:** T034, T035 y T036 a la vez. Después, T037 → T038; T039 → T040 → T041; T042 con Silvana.
- **Bloque e:** T044, T045 y T049 a la vez. Después, T046 → T047 → T048.

## Estrategia de entrega

1. **Mínimo demostrable: la Historia 1 en el backend**, con los bloques a, b y c en el PR 1. Ya demuestra la verificación al guardar, el conflicto y los bloqueos con `/docs`.
2. **FE-1:** la Historia 1 en la interfaz. Se integra junto con el PR 1 por el cambio incompatible del PUT. Después se despliega en Render.
3. **Bloques d y e:** la Historia 3 en el backend. Los archivos excluyen lo no vigente y el historial sobrevive al borrado.
4. **Bloque f** cuando Yan cierre el contrato. Después, el PR 2 junto con FE-2.
5. **Recorridos `[E2E]`** y cierre con la evidencia en los PR.
