# Guía de validación · REV-01 Revisión y exportación

Esta guía sirve para comprobar que el módulo cumple la ficha (T062). Los detalles de los campos están en
[data-model.md](data-model.md) y en [contracts/review-export.openapi.yaml](contracts/review-export.openapi.yaml). El
recorrido en el navegador es T060, en [tasks.md](tasks.md).

## Requisitos

- Python 3.12 y el entorno de `backend/.venv` (ver la guía común de arranque), con `psycopg` para PostgreSQL.
- Backend local en el puerto 8000 con SQLite (`DATABASE_URL` sin definir), desde `backend/`:
  `.\.venv\Scripts\python.exe -m uvicorn platform5e.main:app --port 8000`
- Dos cuentas de prueba (A y B), un curso con una unidad, un TXT procesado y un pedido de generación
  (`POST /api/v1/generation-requests`, con `Idempotency-Key`) con `explicacion` e `item_opcion_multiple`. Para
  REV-C8 con archivo hace falta la generación multimedia activa (configuración de IA de Yan); sin ella, se valida con
  pruebas unitarias con dobles.

## Pruebas automáticas con SQLite (desde `backend/`)

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit tests/architecture tests/integration -q
.\.venv\Scripts\python.exe -m pytest tests/e2e -q
.\.venv\Scripts\python.exe scripts/export_openapi.py   # solo si cambia la API; revisar el diff de docs/api/openapi.json
```

Resultado esperado: todo pasa, y `tests/architecture` confirma que `domain/review/` no importa de `application/` ni de
`infrastructure/`.

| Archivo de prueba | Casos |
|---|---|
| `tests/unit/test_content_fingerprint.py` | REV-C2, C4, C5 |
| `tests/unit/test_resource_verification.py` | REV-C1, C3, C10, C11 y REV-R6, R11 |
| `tests/unit/test_accounts_and_review.py` | REV-C1, C3, C5, C14 |
| `tests/unit/test_legacy_stored_data.py` | REV-R11 (recursos antiguos, D7) |
| `tests/unit/test_edited_media.py`, `tests/unit/test_media_change.py` | REV-C8 |
| `tests/unit/test_media_cleanup.py` | REV-C8: archivo sin referencia tras el 409 (T063) |
| `tests/unit/test_export_eligibility.py`, `tests/unit/test_export_unit_resources.py` | REV-C7 |
| `tests/unit/test_download_history.py` | REV-C9 |
| `tests/unit/test_resource_regeneration.py`, `tests/unit/test_background_regeneration.py` | REV-C12, C13 y D10 en segundo plano |
| `tests/unit/test_regenerated_resource_missing.py` | REV-C13: el recurso nuevo ya no existe |
| `tests/integration/test_regeneration_concurrency.py`, `tests/integration/test_regeneration_late_running_answer.py` | REV-C12: pedidos simultáneos, respuestas tardías e intentos terminados (T066, T067) |
| `tests/integration/test_course_download_retention.py` | REV-C9 al borrar un curso |
| `tests/e2e/test_accounts_and_review_api.py` | REV-C1, C3, C11, C12, C13, C14 y aislamiento A/B |
| `tests/e2e/test_exports_api.py` | REV-C7, C9 |
| `tests/e2e/test_generation_requests_api.py` (las de regeneración) | REV-C12, C13 con el adaptador de Generación, incluida una respuesta `running` |

## Pruebas e2e con PostgreSQL en una base desechable

**Cuidado.** Antes de cada prueba, `tests/e2e/conftest.py` ejecuta `DROP SCHEMA public CASCADE` sobre
`E2E_DATABASE_URL` y no comprueba que la base sea local. Nunca pongas ahí la URL de Render ni la de Neon de
producción. La opción recomendada es un contenedor local, que no comparte nada con Render.

**Opción A (recomendada): Docker local.** Es la misma imagen que usa la CI (`pgvector/pgvector:pg16`). Con Docker
Desktop abierto, desde `backend/`:

```powershell
docker run --name rev01-pg -e POSTGRES_USER=platform -e POSTGRES_PASSWORD=platform -e POSTGRES_DB=platform5e -p 55432:5432 -d pgvector/pgvector:pg16
docker exec rev01-pg pg_isready -U platform    # repetir hasta «accepting connections»
$env:E2E_DATABASE_URL = "postgresql+psycopg://platform:platform@localhost:55432/platform5e"
.\.venv\Scripts\python.exe -m pytest tests/e2e -q
Remove-Item Env:E2E_DATABASE_URL
docker rm -f rev01-pg
```

El puerto 55432 evita chocar con un PostgreSQL instalado en la máquina. El servidor de cada prueba aplica las
migraciones de `backend/database/migrations` al arrancar, igual que en Render. `Remove-Item Env:E2E_DATABASE_URL`
evita que una corrida posterior en la misma consola use esa base sin querer.

**Opción B: rama de Neon.** Solo con una rama creada para esto (por ejemplo, `rev01-e2e`), nunca la principal. Las
pruebas borran todo su esquema `public`. La URL de la rama tiene una contraseña: no la guardes en archivos del
repositorio ni la pegues en el registro de avance. Al terminar, borra la rama desde Neon. Crearla es de Sergio, o con
su acuerdo.

## Recorrido manual en `/docs`

Usa los IDs del registro de avance. En cada paso, la columna «Esperado» es lo que debe pasar.

| # | Acción | Esperado |
|---|---|---|
| 1 | `GET /units/{u}/resources` con A | Cada recurso trae `version` y `verification` (D7: los recursos sin verificación se actualizan al leerlos). |
| 2 | `PUT` de la explicación cambiando solo espacios o `bodyHtml`, con `expectedVersion` | 200. `verification.fingerprint` igual que antes y `version + 1` (REV-C2). |
| 3 | `PUT` cambiando una afirmación por una sin respaldo | 200. `verification.status = insufficient` con motivo, y aprobación bloqueada (REV-C1, C3). |
| 4 | Repetir el `PUT` con el `expectedVersion` anterior | 409 `VERSION_CONFLICT`. El recurso no cambia (REV-C14). |
| 5 | Aprobar un recurso vigente y luego editar su contenido | El recurso vuelve a `pendiente` con `reviewReset: true` (REV-C1). |
| 5b | `POST /documents/{id}/process` del material de la unidad y luego `GET /units/{u}/resources` | `evidence`, `verification` y `version` del recurso quedan iguales, y sigue aprobable (REV-C6). |
| 6 | Ítem: reordenar las opciones | Misma huella. Cambiar el texto de la opción correcta da otra huella y una nueva verificación (REV-C2). |
| 7 | `POST /units/{u}/exports` con recursos aprobados y no vigentes | El archivo solo incluye los vigentes. Sin elegibles, 422 `NO_APPROVED_RESOURCES` con `details` por motivo (REV-C7). |
| 8 | Abrir el archivo exportado | No aparecen recursos pendientes ni insuficientes. |
| 9 | `POST …/resources/{r}/regenerations` con `expectedVersion` | 200 con `status: succeeded` o `running`. Con `running`, `GET …/resources/{r}/regeneration` hasta que termine. El anterior pasa a descartado con motivo `regenerado` (REV-C12). |
| 10 | Repetir el paso 9 con la misma versión | El mismo resultado, sin un recurso nuevo (REV-C12). |
| 11 | Regenerar en una unidad sin material procesado | 409 `NO_PROCESSED_MATERIAL`; el anterior no cambia (REV-C13). |
| 12 | `GET /api/v1/downloads`, borrar el curso y repetir | El historial sigue mostrando fecha, formato, archivo, curso y unidad (REV-C9). |
| 13 | Con B: `GET`, `PUT`, `POST …/verification`, `POST …/regenerations`, `GET …/regeneration` y `POST …/exports` sobre la unidad de A | 404 `UNIT_NOT_FOUND`, sin datos de A. `GET /api/v1/downloads` de B no muestra las descargas de A. |

Anota cada resultado (estado HTTP y lo observado, sin tokens) en el registro de avance y en el PR.
