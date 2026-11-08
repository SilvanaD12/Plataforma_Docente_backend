# Modelo de datos · REV-01 Revisión y exportación

Los recursos y las descargas se guardan como JSON en la columna `datos` de `ep002_recursos` y `ep002_descargas`. Este
documento describe los campos **nuevos o que cambian**. Los demás campos del recurso siguen como en
`ResourceResponse` (`infrastructure/http/schemas/resources.py`). Las decisiones se justifican en
[research.md](research.md).

## Recurso (`ep002_recursos`)

### Columnas

| Columna | Tipo | Cambio | Uso |
|---|---|---|---|
| `id`, `docente`, `unidad`, `creado`, `datos` | — | sin cambios | — |
| `version` | `INTEGER NOT NULL DEFAULT 1` | **nueva** | Guardado condicional (REV-R12). Se incrementa en cada guardado. |

### Campos nuevos en el JSON

| Campo | Tipo | Regla |
|---|---|---|
| `version` | entero ≥ 1 | Copia de la columna. Se devuelve en la API para que el cliente la envíe como `expectedVersion`. |
| `verification` | objeto `VerificationResult` | Resultado de la última comprobación. Obligatorio después de la actualización de D7. |
| `media.invalidated` | booleano | `true` cuando se descartó un archivo por cambiar `prompt` o `script`. Bloquea la aprobación hasta generarlo de nuevo. |
| `evidence[].retrievedAt` | texto ISO 8601 o `null` | Fecha de recuperación del fragmento. `null` = desconocida (recursos migrados). |

### `VerificationResult`

| Campo | Tipo | Regla |
|---|---|---|
| `status` | `current` · `insufficient` · `pending` | En pantalla: vigente, insuficiente y pendiente. |
| `reason` | texto o `null` | Motivo en español. Obligatorio si `status` ≠ `current`. |
| `fingerprint` | texto `sha256:<hex>` | Huella del contenido verificado. La verificación cuenta solo si es igual a la huella actual. |
| `verifiedVersion` | entero | `version` del recurso al verificar. Sirve como trazabilidad. |
| `evidenceThreshold` | número de 0 a 1 | Umbral del pedido original. Se reutiliza en cada nueva comprobación. |
| `ruleVersion` | entero | `VERIFICATION_RULE_VERSION` con que se verificó. |
| `checkedAt` | texto ISO 8601 | Fecha de la comprobación. |
| `retryAvailable` | booleano | `true` solo si `status = pending` y la copia histórica está completa. |
| `summary` | objeto | La misma forma de `ResourceGrounding`: afirmaciones, párrafos y elementos verificados, corregidos o quitados. |

### Normalización para la huella

Las reglas completas están en la decisión D1 de [research.md](research.md#d1-huella-del-contenido-verificable-rev-r1-rev-r2--rev-c2-c4-c5).

| Tipo de recurso | Campos de `structure` que entran |
|---|---|
| Texto (`explicacion`, `glosario`, `item_opcion_multiple`, …) | Ninguno. Entran `body`, `citations` y `options`. |
| `imagen_ilustrativa` (imagen) | `prompt` y `caption`. `alt` no entra: es texto de accesibilidad y no se verifica (D1) |
| `audio_detonante` (audio) | `script` |
| Visuales e interactivos (`mapa_conceptual`, `infografia`, `diagrama_proceso`, `exploracion_guiada`, `reto_prediccion`, `caso_aplicado`, `ordenar_pasos`, `emparejamiento`, `verdadero_falso`, `completar_espacios`) | Toda la salida de `normalize_structure`, incluidos los `fragmentIds` de pasos, predicciones y criterios, en su orden |

### Estados de revisión y de verificación

```text
Estado de revisión (status)        Verificación (verification.status)
  pendiente ──aprobar──► aprobado    current ◄──editar (respaldo suficiente)── cualquiera
      ▲                     │        insufficient ◄──editar (sin respaldo)
      └──editar contenido───┘        pending ◄──copia incompleta o error
  pendiente / aprobado ──► descartado     pending ──reintentar (copia completa)──► current | insufficient
```

**Transiciones del estado de revisión**

- Aprobar exige no tener bloqueos. Entre ellos, `verification.status = current` con la huella vigente y que no haya `media.invalidated`.
- Un guardado que cambia la huella de un recurso `aprobado` lo deja `pendiente` (`reviewReset: true`).
- La regeneración exitosa descarta el anterior con `discardReason = regenerado`, solo si su `version` no cambió.

**Transiciones de la verificación**

- Sin edición, la verificación no se recalcula, aunque cambie `VERIFICATION_RULE_VERSION`.
- Una edición que no cambia la huella conserva la verificación (REV-C2).
- Reintentar solo es posible si `status = pending` y `retryAvailable = true`. No cambia la `version`: el contenido es el mismo, y así una pestaña abierta no recibe un conflicto falso. Igual exige `expectedVersion`.

## Registro de descarga (`ep002_descargas`)

| Campo del JSON | Cambio | Regla |
|---|---|---|
| `id`, `unitId`, `format`, `fileName`, `resourceCount`, `createdAt` | sin cambios | — |
| `courseId` | **nuevo** | Identificador del curso al exportar. |
| `courseName` | **nuevo** | Nombre del curso al exportar. Se conserva tras borrar el curso. |
| `unitName` | **nuevo** | Título de la unidad al exportar. |
| `unitNumber` | **nuevo** | Número de la unidad. |

- Los registros solo se crean desde `ExportUnitResourcesUseCase`: un registro por archivo generado.
- Borrar un curso **no** borra sus registros. Solo se guarda el registro, no el archivo.
- Los registros anteriores sin nombres se muestran con `courseName = null`, y la interfaz indica «Curso eliminado».

## Puerto de persistencia (`ResourceReviewRepositoryPort`)

| Operación | Cambio |
|---|---|
| `save_resource_if_version(teacher_id, unit_id, resource, expected_version, increment=True) -> bool` | **nueva**. Devuelve `False` si la versión ya no es la vigente. Con `increment=False`, que usa la actualización de recursos antiguos (D7), guarda sin cambiar `version`. |
| `get_downloads_by_teacher(teacher_id) -> list[dict]` | **nueva** |
| `save_resources(...)` | Se conserva para Generación, que crea recursos con `version = 1`. |
| `get_downloads(teacher_id, unit_id)` | Se conserva para el filtro por unidad. |

## Puerto de regeneración (`ResourceRegenerationPort`), pendiente de acuerdo con Yan

| Operación | Entrada | Salida |
|---|---|---|
| `request_regeneration` | `teacher_id` y el recurso, con `id`, `version` y `params` | `RegenerationOutcome(ok: bool, new_resource_ids: list[str], reason: str \| None)` |
