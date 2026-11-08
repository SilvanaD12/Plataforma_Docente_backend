# Plan de implementación: Revisión y exportación (REV-01)

[Ficha REV-01](spec.md) · [Decisiones](research.md) · [Modelo de datos](data-model.md) · [Contrato](contracts/review-export.openapi.yaml) · [Validación](quickstart.md) · [Tareas](tasks.md)

**Rama**: `feat/revision-y-exportacion` en el backend y en el frontend · **Fecha**: 2026-11-08
**Entrada**: ficha REV-01 v2, tabla de reutilización y datos reales de la Fase 0 (backend local en `821b27c`)

## Resumen

Revisión verifica cada edición contra la copia histórica guardada en el recurso, con la misma regla de
`grounding.py` que usa Generación y sin consultar servicios externos. El resultado queda ligado a una **huella del
contenido verificable**, y la aprobación y la exportación solo cuentan si esa huella sigue vigente. Además:

- los guardados con una versión obsoleta se rechazan con conflicto;
- la exportación aplica un filtro común a los tres formatos;
- el historial de descargas se consulta por docente y sobrevive al borrado del curso;
- la imagen o el audio se invalidan solo cuando cambia su `prompt` o su `script`.

En el frontend, las pestañas Revisión y Exportación de la unidad muestran:

- el estado de verificación y su motivo;
- «Reintentar comprobación»;
- el aviso de conflicto de versión;
- el motivo cuando no hay recursos elegibles;
- el historial por docente.

La regeneración depende del contrato con Generación y va en el último bloque. Todo el módulo, backend y frontend, se
especifica y planifica en esta carpeta (`specs/README.md`).

## Contexto técnico

**Lenguaje y versión**: Python 3.12 en el backend (CI y local; `pyproject.toml` admite ≥ 3.11). En el frontend, TypeScript 5.6, React 18.3, React Router 6.30 y Node.js 22.
**Dependencias principales**: FastAPI, Pydantic v2, SQLAlchemy 2 y psycopg 3. En el frontend, Vite 5 y Vitest 3. No se agregan dependencias: la huella usa `hashlib`, `json` y `unicodedata`.
**Almacenamiento**: SQLite en local y en CI e2e, y PostgreSQL con pgvector en CI e2e y en Neon. Los recursos y las descargas se guardan como JSON en `datos`. Solo se agrega la columna `ep002_recursos.version`.
**Pruebas**: pytest en el backend, con `tests/unit`, `tests/architecture`, `tests/integration` y `tests/e2e` (servidor real en SQLite y PostgreSQL). En el frontend, Vitest con `npm run lint`, `npm test` y `npm run build`. Los recorridos `[E2E]` se hacen en el navegador.
**Plataforma**: backend en Render (Linux) y frontend en Vercel.
**Tipo de proyecto**: aplicación web con dos repositorios (`Plataforma_Docente_backend` y `Plataforma_Docente_frontend`) y una sola especificación.
**Metas de rendimiento**: la ficha no fija ninguna. La comprobación al guardar es local, por palabras y sobre unos pocos fragmentos, sin red.
**Restricciones**:
- La comprobación al guardar, al reintentar y al migrar no consulta servicios externos.
- No se cambia la regla de `grounding.py` ni de `distractor_reliability.py`.
- Los nombres de Python van en inglés (`tests/architecture/test_english_names.py`).
- El mecanismo de migraciones SQL al iniciar no se cambia sin acuerdo con Sergio.

**Escala y alcance**: decenas de docentes y cientos de recursos por unidad. Son 14 casos (REV-C1 a C14) y 12 requisitos (REV-R1 a R12).

No quedan puntos «NEEDS CLARIFICATION». Los dos «por definir» de la ficha se resuelven en D1 (campos de la huella)
y en [contracts/](contracts/review-export.openapi.yaml) (nombres de campos, con `retrievedAt` que admite `null`).

## Comprobación de la constitución

*Antes de la Fase 0 y repetida después del diseño.*

| Principio | Cómo lo cumple el plan | Estado |
|---|---|---|
| I. Arquitectura hexagonal | La huella, la verificación, la elegibilidad y el cambio de multimedia son funciones puras en `domain/review/`. Los servicios de `application/` usan puertos: el repositorio ampliado y el nuevo puerto de regeneración. SQLAlchemy y HTTP quedan en `infrastructure/`, y la composición en `main.py`. Revisión no importa el servicio de Generación. En el frontend, el módulo vive en `src/features/review` y `src/features/export`, y el cliente HTTP compartido en `src/shared`. | Cumple |
| II. Contrato OpenAPI | Los cambios están en [contracts/](contracts/review-export.openapi.yaml). `docs/api/openapi.json` se regenera en cada bloque con cambios de API. El cliente del frontend se adapta en las tareas `[FE]` de esta misma carpeta, y los PR de ambos repositorios se enlazan. El cambio incompatible del PUT se integra coordinado (ver «Orden de entrega»). | Cumple, con aviso a Silvana |
| III. Evidencia y aprobación | Se verifica al guardar con la copia histórica. La aprobación y la exportación exigen una verificación `current` con la huella vigente. Se conserva el vínculo con la copia (REV-R6 y REV-C6). Los distractores siguen `assess_distractor`. | Cumple |
| IV. Aislamiento por docente y unidad | Toda operación nueva pasa por `_verify_unit_access` o filtra por `teacher_id`. El historial por docente no expone datos de otro docente. Las pruebas e2e incluyen la cuenta B. | Cumple |
| V. Pruebas y entrega por módulo | En cada bloque, las pruebas van primero y luego la implementación, con un commit por bloque y dos PR de backend (a-c y d-f) enlazados con sus PR de frontend. Hay e2e en SQLite y PostgreSQL en CI, y dos recorridos `[E2E]` en el navegador. | Cumple |

**Después del diseño.** Sin violaciones. Hay un único desvío de la tabla de reutilización: se crean
`domain/review/resource_verification.py`, `export_eligibility.py` y `media_change.py`. Así la regla vive en el
dominio y no en el servicio (Principio I). Queda registrado en «Seguimiento de complejidad».

## Estructura del proyecto

### Documentación (esta ficha)

```text
specs/001-revision-citas/
├── spec.md
├── plan.md              # este archivo
├── research.md          # decisiones D1 a D12 y hallazgos H1 a H14
├── data-model.md        # recurso, verificación, descarga y puertos
├── quickstart.md        # validación automática y recorrido manual
├── contracts/
│   └── review-export.openapi.yaml
└── tasks.md             # tareas [BE], [FE] y [E2E] (/speckit-tasks)
```

### Código fuente del backend (`Plataforma_Docente_backend/backend/`)

Rutas relativas a `backend/src/platform5e/`. Leyenda: **C** crear · **A** ajustar · **R** reutilizar sin cambio de lógica · **X** retirar.

```text
domain/
├── review/                                   C  paquete nuevo (de Revisión)
│   ├── __init__.py                           C
│   ├── content_fingerprint.py                C  D1 · normalización por tipo y huella sha256 (compartida con Generación)
│   ├── resource_verification.py              C  D4 · verify_resource sobre la copia histórica
│   ├── export_eligibility.py                 C  D6 · motivo de no elegibilidad
│   └── media_change.py                       C  D9 · media_source_changed (prompt o script)
└── generation/
    ├── grounding.py                          A  solo agrega VERIFICATION_RULE_VERSION = 1
    ├── distractor_reliability.py             R
    └── resource_formats.py                   R  normalize_structure y structure_problems
application/
├── ports/outbound/
│   ├── resource_repository_port.py           A  save_resource_if_version(…, increment), get_downloads_by_teacher
│   ├── resource_regeneration_port.py         C  D10 · pendiente de acuerdo con Yan
│   └── unit_exporter_port.py                 R
├── services/review/resource_review_service.py  A  update_resource (versión, huella, reverificación, reviewReset,
│                                                  multimedia), validate_approval_blockers, retry_verification,
│                                                  regenerate_resource, historial por docente
├── services/review/legacy_verification.py   C  D7 · upgrade_resource_verification, compartida por el
│                                                servicio de revisión y el caso de uso de exportación
├── services/media/media_attachment.py        R  fallback_media y EDITED_NOTES
├── use_cases/media/regenerate_resource_media.py  A  limpiar media.invalidated al generar de nuevo
└── use_cases/export/export_unit_resources.py A  filtro común y registro con curso y unidad
infrastructure/
├── persistence/repositories/
│   ├── sqlalchemy_resource_repository.py     A  columna version, UPDATE condicional, columna en SQLite, consulta por docente
│   └── sqlalchemy_account_repository.py      A  módulo CC-01: TeacherResourceORM.version; delete_course conserva
│                                                DownloadORM. Lo hace Silvana, o Juan con su aprobación en el PR
│                                                (T008 de CC-01). El borrado de media_assets es de CC-01.
├── http/routers/resources.py                 A  PUT con expectedVersion; POST …/verification; POST …/regenerations
├── http/routers/downloads.py                 A/X  GET /api/v1/downloads; X GET /{download_id}; X POST manual
├── http/routers/exports.py                   R  documentar details del 422
├── http/schemas/resources.py                 A  VerificationResult, version, retrievedAt, invalidated, reviewReset
├── http/schemas/citation.py                  A  corregir la descripción de similarity_score
├── http/schemas/downloads.py                 A  courseId, courseName, unitName, unitNumber; quitar DownloadInput
├── exporters/                                R  Moodle XML, SCORM y documento de unidad
└── (adaptador de regeneración)               C  D10 · delega en Generación (bloque f)
main.py                                       A  inyectar el puerto de regeneración
database/migrations/20261108000001_resource_version.sql   C  D3 · ADD COLUMN IF NOT EXISTS version
scripts/upgrade_resource_verification.py      C  solo si Sergio elige la opción B de D7
docs/api/openapi.json                         A  regenerado en cada bloque con cambios de API

tests/
├── unit/test_content_fingerprint.py          C  a)
├── unit/test_resource_verification.py        C  b) c) e)
├── unit/test_accounts_and_review.py          A  b) c), incluido el reproceso del material (REV-C6)
├── unit/test_export_unit_resources.py        A  d)
├── unit/test_download_history.py             A  d) quitar la redescarga y agregar el historial por docente
├── unit/test_edited_media.py                 A  e) ajustar la prueba de H10
├── unit/test_legacy_stored_data.py           A  e) recursos antiguos según REV-R11
├── unit/test_resource_regeneration.py        C  f)
├── e2e/test_accounts_and_review_api.py       A  b) c) d), incluido el reproceso del material (REV-C6)
├── e2e/test_exports_api.py                   A  d)
└── test_grounding.py, test_distractor_reliability.py, pruebas de exportadores   R  deben seguir pasando
```

### Código fuente del frontend (`Plataforma_Docente_frontend/`)

**Rama.** `feat/revision-y-exportacion`, creada desde `main` actualizado (`616390a` o posterior), que ya integra los
PR #1 y #2 con `UnitContext` (H14). Las rutas `review` y `export` de la unidad, sus pestañas y las páginas
marcador `ReviewPage` y `ExportPage` ya existen desde `d9d4f7d` (CC-01): REV-01 reemplaza el contenido de esos
marcadores y no toca `src/app/App.tsx`. **Código anterior.**
`Yansete/plataforma-5e-frontend@feca57c`, carpetas `src/features/review` y `src/features/export`, que se adaptan
según los casos REV y no se copian completas.

```text
src/
├── shared/api/httpClient.ts                  R  request y ApiError
├── shared/types/courses.ts                   R  Course, Unit y UnitContext
├── features/review/
│   ├── api/reviewApi.ts                      C  listar, guardar (PUT con expectedVersion), reintentar y regenerar
│   ├── model/resource.ts                     C  Resource, VerificationResult y etiquetas vigente, insuficiente y pendiente
│   ├── components/VerificationBadge.tsx      C  estado y motivo; «Reintentar comprobación» o aviso de regenerar
│   ├── components/ResourceEditor.tsx         C  edición de texto, opciones y estructura; envía la version leída
│   ├── pages/ReviewPage.tsx                  A  reemplaza el marcador de CC-01; lee { course, unit } con useOutletContext<UnitContext>()
│   └── *.test.ts(x)                          C  Vitest: cliente, etiquetas, 409 VERSION_CONFLICT, reviewReset
└── features/export/
    ├── api/exportApi.ts                      C  exportar (descarga del archivo) e historial por docente
    ├── pages/ExportPage.tsx                  A  reemplaza el marcador de CC-01: formatos, motivo sin elegibles (details del 422) e historial
    └── *.test.ts(x)                          C  Vitest: motivos del 422 e historial con «Curso eliminado»
```

**Comportamiento en la interfaz.**

| Situación | Qué ve el docente | Casos |
|---|---|---|
| Recurso con verificación `current`, `insufficient` o `pending` | Una insignia con el estado en español y su `reason` | REV-C3, C11 |
| `pending` con `retryAvailable` | Botón «Reintentar comprobación» (`POST …/verification` con `expectedVersion`) | REV-C3 |
| `pending` sin `retryAvailable` | Aviso «Regenera el recurso» y botón de regenerar, activo después del bloque f) | REV-C3, C12 |
| Guardado con 409 `VERSION_CONFLICT` | Mensaje para recargar. No se pierde lo que escribió hasta que confirme la recarga | REV-C14 |
| PUT con `reviewReset: true` | Aviso de que el recurso volvió a revisión y necesita una nueva aprobación | REV-C1 |
| Aprobación bloqueada | Los `approvalBlockers` del servidor, sin reglas duplicadas en el cliente | REV-C3, C8 |
| 422 `NO_APPROVED_RESOURCES` | El motivo, con cuántos recursos quedaron fuera por cada causa | REV-C7 |
| Historial | Fecha, formato, archivo, curso y unidad desde `GET /api/v1/downloads`, con las **50 descargas más recientes**; «Curso eliminado» si falta el nombre | REV-C9 |

**Comprobación.** Desde la raíz del frontend: `npm ci`, `npm run lint`, `npm test` y `npm run build`, con el
backend local en el puerto 8000 y `VITE_API_URL` vacío.

**Decisión de estructura.** Se usa la estructura existente: backend hexagonal y frontend por funcionalidades. Lo
único nuevo en el backend es el paquete `domain/review/`, cuyo responsable es Revisión.

## Orden de entrega

| Bloque | Contenido | Casos y requisitos | Depende de | Entrega |
|---|---|---|---|---|
| a) | `content_fingerprint.py`, `VERIFICATION_RULE_VERSION` y pruebas | REV-C2, C4, C5 · R1, R2 | — | commit |
| b) | `resource_verification.py`, columna `version`, PUT con `expectedVersion`, reverificación al guardar, `reviewReset` y prueba de reproceso del material | REV-C1, C6, C14 · R3, R4, R6, R12 | Aviso a Yan (`verification` al crear) | commit |
| c) | Bloqueos por verificación, estado con motivo, reintento y recursos pendientes desde Generación | REV-C3, C10, C11 · R5 | — | commit y **PR 1** del backend |
| FE-1 | `ReviewPage` con estados, reintento, conflicto y `reviewReset` (las rutas y pestañas ya las dejó CC-01 en `d9d4f7d`) | REV-C1, C3, C11, C14 | PR 1 del backend | **PR 1** del frontend |
| d) | `export_eligibility.py`, filtro común, registro único con curso y unidad, historial por docente y retiro de rutas | REV-C7, C9 · R7, R9 | Silvana: `delete_course` (CC-01, T008) y rutas | commit |
| e) | `media_change.py`, `media.invalidated` y actualización de recursos antiguos (REV-R11, opción A o B) | REV-C8 · R8, R11 | Sergio (migración y opción de D7) y equipo (riesgo de D9) | commit |
| f) | Puerto y adaptador de regeneración y ruta `…/regenerations` | REV-C12, C13 · R10 | Contrato con Yan (GEN-R6) | commit y **PR 2** del backend |
| FE-2 | `ExportPage` con motivo sin elegibles e historial; regeneración en `ReviewPage`; aviso de multimedia | REV-C7, C8, C9, C12, C13 | PR 2 del backend | **PR 2** del frontend |
| E2E | Dos recorridos en el navegador: editar, verificar, aprobar y exportar; y borrar un curso y ver el historial | REV-C1, C3, C7, C9 | FE-2 y CC-01 T008 | evidencia en los PR |

En cada bloque se escriben las pruebas primero, luego la implementación, y después se corren los comandos de
[quickstart.md](quickstart.md#pruebas-automáticas-desde-backend).

**El PR 1 del backend cambia el PUT de forma incompatible.** `expectedVersion` pasa a ser obligatorio, y un cliente
que no lo envía recibe 422. Por eso:
1. El PR 1 del backend se integra en `main` coordinado con el PR FE-1, que envía `expectedVersion`. Los dos se enlazan entre sí y se revisan juntos.
2. El despliegue en Render del commit que contiene el PR 1 se hace cuando el PR FE-1 esté listo para publicarse en Vercel. Hasta entonces, Render sigue en el commit anterior.
3. Silvana recibe el aviso antes de integrar (mensaje 3 de [research.md](research.md#mensajes-para-el-grupo-antes-de-los-bloques-que-los-necesitan)).

## Límites que no fija la ficha

- **Historial de descargas: 50 registros.** `GET /api/v1/downloads` y `GET /units/{unit_id}/downloads` devuelven las
  50 descargas más recientes (`MAX_DOWNLOADS_HISTORY`, que ya existía para el historial por unidad). Los registros más
  antiguos se conservan en la base, pero no se listan. Hoy no hay forma de pedir más. Si el equipo lo necesita, la
  opción simple es un parámetro `?limit=` con un máximo (por ejemplo, 200) o paginar con `?before=<createdAt>`.

## Seguimiento de complejidad

| Desvío | Por qué hace falta | Alternativa más simple descartada |
|---|---|---|
| Tres archivos de dominio que no estaban en la tabla (`resource_verification`, `export_eligibility`, `media_change`) | La misma regla la usan guardar, reintentar, migrar y exportar, y debe probarse sin base de datos | Dejarla en `resource_review_service.py`: mezclaría la regla con la coordinación y no la podría usar Exportación sin duplicarla |
| Ajuste de columna en SQLite dentro del adaptador | `create(checkfirst=True)` no agrega columnas a una tabla existente (H12) | Pedir que se borre `demo.db`: se pierden los datos de prueba |
| Cambio en `sqlalchemy_account_repository.delete_course`, archivo de CC-01 | REV-R9 exige conservar el historial, y hoy se borra (H5). Lo hace Silvana, o Juan con su aprobación | Copiar los registros a otra tabla antes de borrar: duplica datos sin necesidad |
