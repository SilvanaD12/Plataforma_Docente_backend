# Guía de validación · REV-01 Revisión y exportación

Esta guía sirve para comprobar que el módulo cumple la ficha. Los detalles de los campos están en
[data-model.md](data-model.md) y en [contracts/review-export.openapi.yaml](contracts/review-export.openapi.yaml).

## Requisitos

- Python 3.12 y el entorno de `backend/.venv` (ver la guía común de arranque).
- Backend local en el puerto 8000 con SQLite (`DATABASE_URL` sin definir):
  `.\.venv\Scripts\python.exe -m uvicorn platform5e.main:app --port 8000`
- Dos cuentas de prueba (A y B), un curso con una unidad, un TXT procesado y una generación con
  `explicacion`, `item_opcion_multiple`, `imagen_ilustrativa` y `audio_detonante`. Se preparan desde `/docs`.

## Pruebas automáticas (desde `backend/`)

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
| `tests/unit/test_edited_media.py` | REV-C8 |
| `tests/unit/test_export_unit_resources.py` | REV-C7 |
| `tests/unit/test_download_history.py` | REV-C9 |
| `tests/unit/test_resource_regeneration.py` | REV-C12, C13 |
| `tests/e2e/test_accounts_and_review_api.py` | REV-C1, C3, C11, C14 y aislamiento A/B |
| `tests/e2e/test_exports_api.py` | REV-C7, C9 |

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
| 9 | `GET /api/v1/downloads`, borrar el curso y repetir | El historial sigue mostrando fecha, formato, archivo, curso y unidad (REV-C9). |
| 10 | Con B: `GET`, `PUT`, `POST …/verification` y `POST …/exports` sobre la unidad de A | 404 `UNIT_NOT_FOUND`, sin datos de A. |

Los casos que necesitan multimedia real (REV-C8 con archivo) o regeneración (REV-C12 y C13) se validan con pruebas
unitarias con dobles. Con la configuración de IA de Yan, también se validan en el entorno compartido.
