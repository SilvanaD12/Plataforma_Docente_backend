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
| `claim_regeneration(teacher_id, unit_id, resource, expected_version) -> bool` | **nueva** (REV-C12). Reserva atómica del pedido de regeneración: `False` si la versión cambió o si esa versión ya está reservada. Guarda `resource` sin cambiar `version`. Columna `regeneration_claim` (migración `20261109000001_regeneration_claim.sql`). También guarda el `attemptId` del intento como vigente (columna `regeneration_attempt`, migración `20261111000001_regeneration_attempt.sql`). |
| `save_resource_if_attempt(teacher_id, unit_id, resource, expected_version, attempt_id, increment=False) -> bool` | **nueva** (REV-C12, revisión de Silvana en el PR #17). Como `save_resource_if_version`, pero también exige en el mismo `UPDATE` que `attempt_id` sea el intento vigente. La usan el registro del estado del pedido y el descarte del anterior, para que la respuesta tardía de un intento viejo no cambie nada del intento nuevo desde la misma versión. Además exige que el intento siga en `running` y guarda su estado nuevo (columna `regeneration_status`, migración `20261112000001_regeneration_status.sql`; `claim_regeneration` la deja en `running`): un intento que ya terminó no se reescribe, aunque llegue tarde otra consulta del mismo intento. |
| `release_regeneration(teacher_id, unit_id, resource_id, attempt_id) -> None` | **nueva**. Libera la reserva si la regeneración falló, solo si `attempt_id` sigue siendo el intento vigente. |
| `save_resources(...)` | Se conserva para Generación, que crea recursos con `version = 1`. |
| `get_downloads(teacher_id, unit_id)` | Se conserva para el filtro por unidad. |

## Puerto de regeneración (`ResourceRegenerationPort`), D10

Lo implementa el adaptador de Generación en segundo plano, `infrastructure/adapters/generation_regeneration_adapter.py` (T029 de GEN-01, PR #17), conectado en `main.py`.

| Operación | Entrada | Salida |
|---|---|---|
| `request_regeneration` | `teacher_id`, `resource_id`, `resource_version` y `params` (con `unitId`) | `RegenerationStatus(request_id, status, new_resource_ids, reason, code)`; `status`: `pending`, `running`, `succeeded` o `failed`; `code` solo en `failed` por los datos del docente (`None` si falló el proveedor) |
| `get_regeneration` | `teacher_id` y `request_id` | `RegenerationStatus` o `None` si no existe o es de otro docente. Revisión lo consulta desde `GET …/regeneration` mientras el pedido está en curso |

En el recurso anterior, Revisión guarda `regeneration: {fromVersion, requestId, status, newResourceIds, previousDiscarded}`. En cada recurso nuevo guarda `regeneratedFrom: {resourceId, version}`.

Si Generación responde `succeeded` pero ninguno de los recursos nuevos existe, Revisión registra `status: failed` con `code: REGENERATED_RESOURCE_NOT_FOUND` y libera la reserva; en el `POST` responde **409** (`MATERIAL_STATE_CODES` de `domain/review/errors.py`). Si existen algunos, `newResourceIds` guarda solo esos.
