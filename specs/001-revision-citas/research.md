# Investigación y decisiones · REV-01 Revisión y exportación

**Fecha** 2026-11-08 · **Base revisada** `main` en `821b27c` (incluye Cuentas y cursos) · **Ficha** `spec.md`

Cada decisión indica qué se eligió, por qué y qué alternativas se descartaron. Las rutas son relativas a
`backend/src/platform5e/`, salvo `database/`, `tests/` y `docs/`.

## Hallazgos de la revisión del código

| # | Hallazgo | Dónde | Consecuencia para el plan |
|---|---|---|---|
| H1 | Los recursos no tienen versión. El PUT sobrescribe sin control de concurrencia. | `sqlalchemy_resource_repository.save_resources` usa `session.merge` | REV-C14 y REV-R12 necesitan una versión con guardado condicional (D3). |
| H2 | El resultado guardado (`grounding`) no tiene huella, versión de la regla, estado ni versión verificada. | `generation_service._build_resource_dict` | Se agrega el bloque `verification` (D2). Confirmado en la Fase 0 con datos reales. |
| H3 | La copia histórica (`evidence`) no guarda la fecha de recuperación. | `generation_service._save_for_review` | Se agrega `retrievedAt`, que admite `null` (desconocida). Lo llena Generación (Yan), con el dato que entrega Material (Sergio). |
| H4 | La verificación de Generación está mezclada con el borrador del modelo y no se puede llamar desde Revisión. | `prompt_drafting.py:500-652` | Se crea una función de dominio que repite la misma regla sobre la copia histórica (D4). |
| H5 | Al borrar un curso se borran también sus descargas. | `sqlalchemy_account_repository.delete_course`, tabla `DownloadORM` en el bucle | Contradice REV-R9 y el acuerdo con CC-01. Se quita `DownloadORM` del borrado (D8). Hay que avisar a Silvana. |
| H6 | El historial se consulta por unidad y exige acceso a la unidad. Tras borrar el curso devolvería 404. | `resource_review_service.get_downloads_history` | Nueva consulta por docente con nombres de curso y unidad guardados en el registro (D8). |
| H7 | La redescarga `GET /units/{id}/downloads/{download_id}` vuelve a exportar el estado actual. | `routers/downloads.py:42-78` | Se retira: queda fuera del alcance y no devuelve el archivo original. |
| H8 | El registro de descarga tiene dos caminos: el automático de la exportación y un `POST` manual. | `export_unit_resources.py:66` y `routers/downloads.py:80` | Se deja solo el automático. El documento de unidad ya se construye en el backend (`UnitDocumentExporter`). |
| H9 | Cualquier cambio de `structure` invalida la imagen o el audio. | `resource_review_service.py:148` | Se compara solo el campo con que se generó: `prompt` o `script` normalizado (D9). |
| H10 | Tras invalidar el archivo, la aprobación sigue permitida (se aprueba con el respaldo). | `test_edited_media.py:99` | REV-C8 exige bloquearla. Esa prueba cambia (D9). |
| H11 | Los contratos `docs/api/contracts/resource-*.v1.json` describen otro modelo (snake_case, `quoted_text`, `similarity_score` coseno) que no coincide con el recurso guardado (`title`, `body`, `options`, `structure`, `citations`). | `docs/api/contracts/` | La huella se define sobre el modelo real guardado y expuesto en OpenAPI (D1). Los JSON antiguos no se modifican en esta entrega. |
| H12 | En SQLite las migraciones SQL no se aplican: las tablas se crean con `create(checkfirst=True)`, que no agrega columnas a tablas existentes. | `database.py`, `sqlalchemy_account_repository.py:151` | La nueva columna `version` necesita un ajuste para SQLite además de la migración de PostgreSQL (D3). |
| H13 | `citation.py` describe `similarity_score` como similitud coseno, pero la verificación es por palabras. | `infrastructure/http/schemas/citation.py` | Se corrige la descripción. |
| H14 | En el frontend, `UnitLayout` y `UnitContext` estaban solo en `feat/cuentas-y-cursos` (PR 2). **Resuelto:** los PR #1 y #2 ya se integraron en `main` (`616390a`), que incluye `UnitLayout`, `UnitContext` y las pestañas. Desde `d9d4f7d` («feat: preparar las pestañas de cada unidad»), la unidad tiene las rutas hijas `material`, `generation`, `review` y `export`, con pestañas `NavLink`, y las páginas marcador `src/features/review/pages/ReviewPage.tsx` y `src/features/export/pages/ExportPage.tsx` (`UnitModulePlaceholder`). | `Plataforma_Docente_frontend`: `src/app/App.tsx`, `src/features/units/pages/UnitLayout.tsx`, `src/shared/types/courses.ts` | La rama del frontend de REV-01 se crea desde `main` actualizado. Las rutas y las pestañas ya las resolvió CC-01: REV-01 reemplaza el contenido de los dos marcadores (D12). |

## D1. Huella del contenido verificable (REV-R1, REV-R2 · REV-C2, C4, C5)

**Decisión.** Se crea `domain/review/content_fingerprint.py` con dos funciones puras:
`normalize_verifiable_content(resource) -> dict` y `content_fingerprint(resource) -> str`. La huella es
`"sha256:" + hex` del JSON canónico (`sort_keys=True`, `ensure_ascii=False`, separadores compactos) del contenido
normalizado. El texto se normaliza a Unicode NFC, con los espacios colapsados y sin espacios al inicio ni al final.
Se conservan las mayúsculas, porque pueden cambiar el sentido de una sigla.

| Entra en la huella | Fuera de la huella |
|---|---|
| `type` | `id`, `title`, `status`, `edited`, fechas, `version` |
| `body` normalizado como lista de párrafos (los separa una línea en blanco), porque `verify_statements` verifica por párrafo | `bodyHtml`: solo formato visual. Las líneas en blanco de más y los espacios repetidos |
| `citations`: cada `claim` normalizado con sus `fragmentIds` ordenados, y la lista ordenada | `media`, `evidence`, `params`, `grounding`, `verification`, `agent`, `generator*` |
| `options`, **ordenadas por `id`**: `id`, `text`, `isCorrect`, `feedback` y `sourceFragmentIds` ordenados (fuentes vinculadas, REV-R6) | En cada opción: `decision`, `discardReason`, `edited`, `misconception`, `reliabilityWarning` |
| `structure`: la salida de `normalize_structure(type, structure)`, que ya limpia espacios y conserva el orden de las listas | En `structure` de la imagen: `alt` |

**Por qué.**
- Ordenar las opciones por su `id` estable hace que reordenarlas no cambie la huella (REV-C2).
- Incluir `text` e `isCorrect` hace que cambiar la respuesta correcta o el texto de un distractor sí la cambie (REV-C2 y REV-C4).
- Excluir `decision` deja que cambiar solo la decisión sobre un distractor aplique las reglas de aprobación sin volver a verificar (REV-C4).
- `title` se excluye porque ninguna regla de `grounding.py` lo verifica.
- `alt` de la imagen se excluye porque es texto de accesibilidad: no afirma nada y `grounding.py` no lo verifica. Si entrara, corregirlo devolvería a revisión un recurso aprobado (D5) sin que cambie ningún contenido verificable. `prompt` y `caption` sí entran.
- En `structure`, el orden de pasos y secuencias sí es contenido, y por eso se respeta.
- Reutilizar `normalize_structure` evita una segunda normalización por tipo (tabla de reutilización).

**Alternativas descartadas.**
- Usar los JSON de `docs/api/contracts/`: no describen el recurso real (H11).
- Calcular la huella sobre el recurso completo: un cambio visual o de decisión la invalidaría.
- Normalizar en minúsculas: confundiría siglas.

## D2. Resultado de verificación asociado a la huella (REV-R4, REV-R5 · REV-C5, C10)

**Decisión.** Cada recurso guarda un bloque `verification`, descrito en [data-model.md](data-model.md):
`status` (`current` · `insufficient` · `pending`), `reason`, `fingerprint`, `verifiedVersion`,
`evidenceThreshold`, `ruleVersion`, `checkedAt`, `retryAvailable` y `summary`. `summary` tiene la forma actual de
`grounding` y se mantiene por compatibilidad. Una verificación **solo cuenta** si `verification.fingerprint` coincide
con la huella actual del recurso. Esa comparación resuelve REV-C5: un resultado de otra versión no habilita nada.

Los valores técnicos del estado van en inglés, como pide la guía para los valores nuevos, y la interfaz los muestra en
español: vigente, insuficiente y pendiente. Así no se confunden con el estado de revisión `pendiente` del recurso.

**`VERIFICATION_RULE_VERSION`.** Se agrega a `domain/generation/grounding.py` con el valor `1`. Se incrementa cuando
cambia un umbral o mínimo de ese archivo. Sin edición no se recalcula (REV-C10). Al recalcular tras una edición, si el
estado cambia y la regla guardada es otra, el motivo lo indica: «la regla de verificación cambió (v1 → v2)».

**Alternativas descartadas.**
- Asociar el resultado al número `version` del recurso: este cambia también con ediciones que no tocan contenido verificable, y obligaría a recalcular sin motivo (contradice REV-C2).
- Reemplazar `grounding`: lo leen el frontend y el cálculo de I21. Se conserva.

## D3. Versión del recurso y conflicto (REV-R12 · REV-C14)

**Decisión.**
- Nueva columna `version INTEGER NOT NULL DEFAULT 1` en `ep002_recursos`, también reflejada en el JSON como `version`.
- El PUT exige `expectedVersion`.
- El repositorio guarda con `UPDATE … SET datos = :d, version = version + 1 WHERE id = :id AND docente = :t AND version = :expected`. Si no actualiza ninguna fila, el servicio responde **409 `VERSION_CONFLICT`** sin modificar nada.
- En PostgreSQL, la columna se crea con la migración `database/migrations/20261108000001_resource_version.sql` (`ADD COLUMN IF NOT EXISTS`).
- En SQLite, el adaptador de recursos agrega la columna si falta, con una comprobación de `inspect` al iniciar. Así se conservan las bases locales existentes (H12).

**Por qué.** El UPDATE condicional es atómico en los dos motores y no depende de funciones JSON propias de cada
dialecto.

**Alternativas descartadas.**
- Guardar la versión solo en el JSON y comparar en Python: dos guardados simultáneos podrían pasar la comprobación a la vez.
- `SELECT … FOR UPDATE`: no existe en SQLite.
- Borrar `demo.db`: perdería los datos de prueba de cada integrante.

## D4. Verificación local al guardar, reintentar y migrar (REV-R3, R5, R6, R11 · REV-C1, C3, C11)

**Decisión.** Nueva función de dominio `domain/review/resource_verification.py · verify_resource(resource,
threshold, rule_version)`, que devuelve el bloque `verification`. Usa **solo** `resource["evidence"]` (la copia
histórica) y las funciones de `grounding.py` y `distractor_reliability.py`, sin cambiar su regla:

1. **Integridad de la copia.** Reúne los fragmentos referenciados por `citations[].fragmentIds`,
   `options[].sourceFragmentIds` y `structure.*[].fragmentIds`. Si falta la copia, o falta el texto de algún fragmento
   referenciado, el resultado es `pending` con `retryAvailable = false` y el motivo «regenera el recurso» (REV-R6).
2. `verify_citations(citations, fragments, threshold)`. Si no queda `accepted`, el resultado es `insufficient`.
3. `verify_statements(body, type, …)` para `explicacion` y `glosario`. Si no queda `accepted`, el resultado es `insufficient`.
4. `link_step_sources`, `link_prediction_sources` o `link_criterion_sources` según el tipo. Si quedan menos elementos que `MIN_ITEMS`, el resultado es `insufficient`.
5. Distractores con texto editado: `assess_distractor`. Si la evidencia muestra el distractor como correcto, se llena su `reliabilityWarning` (REV-C4). No es un bloqueo nuevo: el docente decide con las reglas de aprobación vigentes.
6. Si los pasos anteriores pasan, el resultado es `current`. Si ocurre una excepción inesperada, el resultado es `pending` con `retryAvailable = true` y el motivo «no se pudo completar».

**Umbral.** Se usa el primero que exista: `verification.evidenceThreshold`, `grounding.threshold`,
`params.evidenceThreshold` o `DEFAULT_THRESHOLD`.

**Dónde se usa.**
- `update_resource`: solo si cambió la huella (REV-C1, REV-C2).
- «Reintentar comprobación»: solo si el estado es `pending` y `retryAvailable` (REV-C3).
- Actualización de recursos antiguos (D7).

**Por qué en el dominio.** La regla es pura y la necesitan tres casos de uso. La tabla de reutilización no la
listaba. Se agrega aquí, y su archivo de pruebas, como «Crear».

**Alternativa descartada.** Llamar a `prompt_drafting`: pertenece a Generación, mezcla el borrador del modelo y
consulta lo recuperado, no la copia (H4).

## D4b. Reproceso del material (REV-C6 · REV-R6)

**Qué significa «cambian las fuentes vinculadas» (REV-R6).** Que cambian los `fragmentIds` que referencia el recurso
en `citations`, `options` o `structure`. Esos identificadores entran en la huella (D1), así que un cambio así produce
una nueva comprobación al guardar.

**Decisión.** Revisión no reacciona al reproceso. La copia histórica (`evidence`) y el bloque `verification` del
recurso no se modifican cuando Material reprocesa el documento (MAT-C5): el reproceso solo cambia el índice para
pedidos nuevos. Como la verificación depende de la huella y de la copia guardada, y no del índice vigente, sigue
`current` mientras el contenido del recurso no cambie.

**Prueba (bloque b).** Generar un recurso, reprocesar el documento de la unidad y comprobar que `evidence`,
`verification` y `version` quedan iguales, que el recurso sigue aprobable y que, al guardar sin cambiar el contenido,
la verificación se conserva. Esta prueba también protege el contrato con Material: si un cambio futuro reescribiera
la copia, fallaría.

## D5. Edición de un recurso aprobado y bloqueos (REV-C1, C3, C11 · REV-R5)

**Decisión.**
- Si un PUT cambia la huella de un recurso `aprobado`, el recurso queda `pendiente` aunque el cuerpo pida `aprobado`. La respuesta incluye `reviewReset: true`, y la nueva aprobación requiere otro guardado.
- `validate_approval_blockers` conserva sus reglas pedagógicas. Se agrega `verification_blockers`, que bloquea con su motivo cuando la huella de `verification` no coincide o cuando su estado no es `current`, y `approval_blockers`, que junta las dos y es la que usan el servicio y `ResourceResponse.approvalBlockers`.
- **Opción A (bloque c).** Sin `verification` no hay bloqueo que mostrar, por ejemplo en la respuesta de Generación: `update_resource` calcula la verificación de la versión editada **antes** de evaluar la aprobación, así que al aprobar siempre existe.
- El bloqueo multimedia de D9 también aplica.

## D6. Filtro común de exportación (REV-R7 · REV-C7)

**Decisión.** Nueva función de dominio `domain/review/export_eligibility.py · export_ineligibility(resource) -> str |
None`, que devuelve el motivo por el que el recurso no es elegible. Lo es si:
- su estado es aprobado;
- tiene `verification.status == current` con la huella vigente;
- no tiene multimedia invalidada.

`ExportUnitResourcesUseCase` la aplica junto con `exporter.supports`. Si no queda ninguno, responde **422
`NO_APPROVED_RESOURCES`**: se conserva el código que ya usa el frontend, con `details` agrupados por motivo. La
versión de la regla no participa (REV-C10).

## D7. Recursos antiguos sin verificación (REV-R11)

**Decisión.** Hay dos pasos:
1. **Esquema.** La migración SQL de D3 agrega `version`.
2. **Datos.** Para cada recurso sin bloque `verification` se calcula la huella y se ejecuta `verify_resource` con el umbral guardado o con `DEFAULT_THRESHOLD`. Los fragmentos sin `retrievedAt` quedan con `null` (desconocida).
   - Un recurso aprobado con resultado `current` sigue aprobado.
   - Con `insufficient` o `pending` vuelve a `pendiente`.
   - Sin copia histórica, o con un fragmento sin texto, queda `pending`, sin reintento y fuera de exportación. Solo puede regenerarse.

**La actualización no incrementa `version`.** No cambia el contenido, así que el docente que tenía abierto el recurso
no debe recibir un 409 falso al guardar. Se escribe con un guardado condicional que exige la versión leída y la deja
igual (`… SET datos = :d WHERE id = :id AND docente = :t AND version = :v`). Si entre la lectura y la escritura hubo
un guardado del docente, la actualización se descarta sin error y se repite en la siguiente lectura, porque el
recurso sigue sin `verification`. Esa operación del puerto es `save_resource_if_version(…, increment=False)`.

Mientras Generación no entregue el bloque `verification` (dependencia con Yan), esta misma vía cubre los recursos
recién creados.

**Dónde vive.** `application/services/review/legacy_verification.py · upgrade_resource_verification(repository,
teacher_id, unit_id, resource) -> dict`. Recibe el puerto `ResourceReviewRepositoryPort`, devuelve el recurso
actualizado y no depende del servicio de revisión. Así la pueden llamar `ResourceReviewService` y
`ExportUnitResourcesUseCase` sin que el caso de uso dependa del servicio.

**Dos opciones para decidir con Sergio.** Las dos usan esta misma función y las mismas pruebas. Solo cambia quién la
llama:

| | A. Actualización perezosa (propuesta) | B. Script único `scripts/upgrade_resource_verification.py` |
|---|---|---|
| Cuándo corre | Al leer un recurso sin `verification` en Revisión o en Exportación | Una vez, a mano, contra Neon u otra base, después de aplicar la migración SQL |
| Mecanismo de migraciones | No cambia: las migraciones SQL siguen igual al iniciar | No cambia: es un paso aparte que Sergio ejecuta y registra |
| Ventaja | No requiere una ventana de migración y cubre los recursos nuevos mientras Generación se adapta | Deja toda la base actualizada de una vez, con un informe de cuántos quedaron `current`, `insufficient` y `pending` |
| Costo | La primera lectura de cada recurso escribe una vez. La escritura queda fuera del camino crítico | Hay que ejecutarlo en cada entorno (local, CI de PostgreSQL y Neon) y conviene probarlo antes en una rama de Neon |
| Idempotencia | Sí: solo actúa si falta `verification` | Sí: el mismo criterio, con la opción `--dry-run` para ver el informe sin escribir |

Si Sergio elige B, A puede quedar activa solo como red de seguridad mientras Generación se adapta, o quitarse.

## D8. Historial por docente y registro único (REV-R9 · REV-C9)

**Decisión.**
- El registro de descarga guarda además `courseId`, `courseName`, `unitName` y `unitNumber`, tomados en el momento de exportar.
- Nueva ruta `GET /api/v1/downloads`, que consulta por `teacher_id` sin exigir acceso a la unidad.
- Se conserva `GET /units/{unit_id}/downloads`, que filtra el historial por docente y unidad.
- `delete_course` deja de borrar `DownloadORM` (H5). **Ese archivo es del módulo CC-01**
  (`sqlalchemy_account_repository.py`). El cambio lo hace Silvana, o Juan con su aprobación en el PR; corresponde a la
  tarea T008 de `specs/003-cuentas-y-cursos/tasks.md`. Revisión aporta la prueba del historial tras el borrado.
- El borrado de `media_assets` al eliminar un curso, que hoy no ocurre, también es de CC-01. Revisión no lo cambia y
  solo lo reporta.
- Se retiran `GET /units/{unit_id}/downloads/{download_id}` (H7) y `POST /units/{unit_id}/downloads` (H8).
- Los registros antiguos sin nombres muestran «Curso eliminado» o el identificador.

## D9. Multimedia editada (REV-R8 · REV-C8)

**Decisión.**
- Función pura `media_source_changed(type, old_structure, new_structure)`: compara `prompt` para la imagen y `script` para el audio, normalizados con `normalize_structure`.
- Si cambió y el archivo estaba `ready`, el recurso queda con el respaldo (`fallback_media(..., EDITED_NOTES)`) y `media.invalidated = true`.
- `validate_approval_blockers` bloquea si `invalidated` sigue presente; «Generar de nuevo» lo limpia.
- Si cambian solo `alt` o `caption`, se conserva el archivo. Cambiar `alt` no cambia la huella. Cambiar `caption` sí la cambia y produce una nueva comprobación, porque entra en la huella.

**Cambio de prueba existente.** `test_edited_media.py::test_editing_the_script_drops_the_old_audio_everywhere` hoy
aprueba con el respaldo. Cambia para exigir el bloqueo, como pide REV-C8.

**Riesgo para el equipo.** Si el servidor no tiene la generación multimedia activa (por ejemplo, en local o sin
claves), un recurso con archivo invalidado no podría aprobarse. Propuesta: el bloqueo indica
`MEDIA_GENERATION_DISABLED` y el docente puede regenerar el recurso. Hay que confirmarlo en el grupo antes del bloque e).

**Decisión del equipo (2026-11-08): opción A, como dice la ficha.** Un archivo invalidado (`media.invalidated`)
bloquea la aprobación y saca el recurso de las exportaciones nuevas hasta generarlo de nuevo, también cuando la
generación multimedia está apagada en el servidor. Si «Generar de nuevo» falla, la marca se conserva. **Cualquier
excepción para la demostración (por ejemplo, aprobar con el respaldo cuando no hay generación multimedia) requiere
acordarla en el equipo y actualizar antes la ficha (REV-C8 y REV-R8).**

## D10. Regeneración (REV-R10 · REV-C12, C13), dependiente de Yan

**Decisión provisional.**
- Puerto de salida `application/ports/outbound/resource_regeneration_port.py`, con `request_regeneration(teacher_id, resource) -> RegenerationOutcome`. El resultado trae `ok`, `newResourceIds` y `reason`.
- El adaptador de infraestructura delega en Generación con `params` guardados y la evidencia vigente del material.
- Revisión registra la `version` del recurso al pedir la regeneración.
  - Si termina bien y la versión no cambió, pasa el recurso anterior a `descartado` con `discardReason = "regenerado"`, usando el guardado condicional.
  - Si el docente lo editó mientras tanto, no lo toca y ambos quedan en Revisión.
  - Si la regeneración falla, el anterior queda igual y se devuelve el motivo.
- Ruta: `POST /units/{unit_id}/resources/{resource_id}/regenerations` con `expectedVersion`.

**Pendiente con Yan.** Hay que definir si el pedido es síncrono, como hoy, o en segundo plano con estado consultable
(GEN-R6). También el nombre del puerto y qué pasa si el recurso se edita durante el pedido. El bloque f) no empieza
sin ese acuerdo.

## D12. Frontend en la misma carpeta de especificación

**Decisión.** Las tareas de frontend se planifican en esta carpeta, con la etiqueta `[FE]` (`specs/README.md`). Se
implementan en la rama del módulo del repositorio `Plataforma_Docente_frontend`.
- **Base.** La rama se crea desde `main` actualizado (`616390a` o posterior), que ya incluye `UnitContext` y las pestañas de la unidad (H14).
- **Pestañas.** Las rutas `review` y `export` y sus pestañas son de CC-01. REV-01 reemplaza el contenido de los marcadores `ReviewPage.tsx` y `ExportPage.tsx`, conserva sus nombres y exportaciones y no modifica `src/app/App.tsx`.
- **Contexto.** Las pestañas leen `const { course, unit } = useOutletContext<UnitContext>()`, como `UnitOverviewPage`, y usan `unit.id` en las llamadas.
- **Cliente HTTP.** Se reutiliza `request` y `ApiError` de `src/shared/api/httpClient.ts`.
- **Código anterior.** Se adapta de `Yansete/plataforma-5e-frontend@feca57c` (`src/features/review`, `src/features/export`).
- **Pruebas.** Con Vitest, ya configurado. El repositorio no tiene una herramienta de navegador automatizada, así que las tareas `[E2E]` se ejecutan en el navegador con backend local y se documentan con capturas y estados HTTP, como en CC-01.

## D11. Patrones que se usan

| Patrón | Dónde |
|---|---|
| Puertos y adaptadores | `ResourceReviewRepositoryPort` (ampliado), `ResourceRegenerationPort` (nuevo), `UnitExporterPort` (sin cambios) |
| Repositorio | `SQLAlchemyResourceRepository` con guardado condicional por versión |
| Inyección de dependencias en `main.py` | El servicio de revisión recibe el puerto de regeneración |
| Concurrencia optimista | `version` y `expectedVersion`, con respuesta 409 |
| Funciones de dominio puras | Huella, verificación, elegibilidad y cambio de multimedia, probadas sin base de datos |

## Mensajes para el grupo (antes de los bloques que los necesitan)

1. **Yan (antes de b y f).** Generación debe llamar `content_fingerprint` y `verify_resource` al crear, guardar `verification`, `version = 1` y `evidence[].retrievedAt`, y entregar `pending` cuando no pudo verificar. También hay que acordar el contrato de regeneración (D10).
2. **Sergio (antes de e).** Aprobar la migración SQL de `version` para Neon y elegir entre la actualización perezosa (A) y el script único `scripts/upgrade_resource_verification.py` (B) de D7. También, de dónde sale `retrievedAt` en la copia (H3).
3. **Silvana, PR 1 (antes de integrarlo).** El PUT de recursos pasa a exigir `expectedVersion` y deja de aceptar guardados sin él. El PR 1 del backend se integra en `main` coordinado con el PR del frontend que envía `expectedVersion`, y el despliegue de ese commit en Render espera a que el frontend esté listo en Vercel.
4. **Silvana, borrado y descargas (antes de d).** Quitar `DownloadORM` de `delete_course` (H5): lo hace ella, o Juan con su aprobación en el PR (T008 de CC-01). Además: se retiran `POST` y `GET /{download_id}` de descargas, y se agrega `GET /api/v1/downloads`. Las pestañas `review` y `export` ya están resueltas en `d9d4f7d`; no hace falta otro acuerdo de rutas (H14). El borrado de `media_assets` en `delete_course`, que hoy no ocurre, es de CC-01.
5. **Equipo (antes de e).** El riesgo de D9 cuando la generación multimedia está apagada.
