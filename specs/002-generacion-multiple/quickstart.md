# Guía de validación de GEN-01

[Plan](plan.md) · [Contrato](contracts/generation-requests.openapi.yaml) · [Modelo de datos](data-model.md)

Esta guía describe cómo comprobar los casos GEN-C1 a GEN-C9 una vez implementado el plan. No contiene código de implementación.

## Preparación

```bash
cd backend
python -m pip install -e ".[dev]"
export LLM_PROVIDER=rules              # validación determinista; repetir V11 con gemini
export GENERATION_MAX_WORKERS=2
uvicorn platform5e.main:app --port 8000
```

Variables de los ejemplos: `BASE_URL=http://localhost:8000`, `TOKEN` (de `POST /api/v1/sessions`) y `UNIT_ID`, una unidad con un documento en estado `procesado`. Para crearla se puede reutilizar `_unit_with_material` de `tests/e2e/test_sequence_api.py`.

## Pruebas automáticas

```bash
pytest tests/unit -k "generation or sequence or evidence or verification"
pytest tests/integration -k "generation_request"   # repositorio, unicidad de clave y barrido de arranque
pytest tests/e2e/test_sequence_api.py tests/e2e/test_generation_requests_api.py
pytest tests/architecture
python scripts/export_openapi.py && git diff --exit-code ../docs/api/openapi.json
```

El último comando falla si el contrato exportado no coincide con el que está en el repositorio (Constitución II). La CI hace la misma comparación en el paso «OpenAPI export matches docs/api/openapi.json» de `.github/workflows/backend-ci.yml` (T048), antes de las pruebas; ejecutarlo antes de abrir el PR evita que la CI falle por esto.

## Escenarios

| Id | Caso | Pasos | Resultado esperado |
| --- | --- | --- | --- |
| V1 | GEN-C1 | `POST /generation-requests` con `mode: individual` y `resourceTypes: [glosario]`, y después `GET` hasta un estado final. | `202` con `queued`; después, `succeeded` con un paso. Cada recurso en `GET /units/{UNIT_ID}/resources/{id}` tiene `verification.status` igual a `current` o `pending`, `verification.fingerprint` y `evidence`. |
| V2 | GEN-C2 | `mode: sequence` con `[item_opcion_multiple, pregunta_detonante]`. | Los `steps` llegan ordenados como `engage` y luego `evaluate`, y la evidencia es la misma para ambos (`evidence` única en el pedido). Mientras se ejecuta, `GET` muestra pasos `running` y `pending`. |
| V3 | GEN-C3 | Usar un generador falso de prueba que devuelva un paso sin citas válidas. | El pedido termina `partially_succeeded`. El paso rechazado trae `rejections[].reason` y el otro conserva sus recursos en revisión. |
| V4 | GEN-C4 | Repetir el mismo `POST` con la misma `Idempotency-Key`. Luego reiniciar uvicorn durante un pedido en curso. | La repetición responde `200` con el mismo `id` y el número de recursos de la unidad no cambia. Tras el reinicio, `GET` devuelve `interrupted` y los recursos ya entregados siguen en revisión. |
| V5 | GEN-C5 | Con un segundo docente, consultar el `id` del primero. Con el primer docente, repetir la clave cambiando `quantity`. | La consulta ajena responde `404 GENERATION_REQUEST_NOT_FOUND` y la clave reutilizada responde `409 IDEMPOTENCY_KEY_REUSED`. |
| V6 | GEN-C6 | Hacer el `POST` sobre una unidad sin material procesado. Después, usar un generador falso que falle en todos los pasos. | El primero responde `400 NO_PROCESSED_MATERIAL` y no crea ningún pedido. El segundo termina `failed` con `failure.message` y sigue consultable. |
| V7 | GEN-C7 | Desde Revisión, `POST /units/{UNIT_ID}/resources/{id}/regenerations` con la `expectedVersion` actual; consultar hasta `succeeded`. Repetir la misma petición. Repetir editando el recurso mientras corre. | Los recursos nuevos traen `regeneratedFrom` y `verification`. La repetición no crea otro pedido ni recursos. Revisión descarta el anterior solo si su versión no cambió; si se editó, quedan los dos. Un pedido fallido no toca el anterior. |
| V8 | GEN-C8 | Usar un recurso de `exploracion_guiada`, `reto_prediccion` o `caso_aplicado` cuyo paso, predicción o criterio cite un fragmento que no está en la evidencia, incluido uno redactado por reglas. | `verification.status = pending`, con el motivo de copia incompleta y `retryAvailable = false`. Revisión rechaza aprobarlo y exportarlo. La copia `evidence` incluye los fragmentos de los pasos, predicciones y criterios presentes. |
| V9 | GEN-C9 | Ejecutar con `EMBEDDINGS_ENABLED=false`. | `retrievalMode = bm25_fallback`. `steps[].generator.fallback` sigue reflejando solo el respaldo de redacción. |
| V10 | Aislamiento (Constitución IV) | Dos docentes con unidades distintas. Pedido sobre la unidad ajena. | `404 UNIT_NOT_FOUND`, con el mismo cuerpo que una unidad inexistente. |
| V12 | GEN-C10 y GEN-C11 | Con `LLM_PROVIDER=rules`: (a) un `POST` por modalidad, con `modalities: [X]` y tipos de esa modalidad; (b) `modalities: [Textual]` con `imagen_ilustrativa`; (c) un `POST` sin `modalities`; (d) desde Revisión, regenerar una `imagen_ilustrativa` y un `audio_detonante` antiguos guardados con `modalities: ["Textual"]`; (e) `modalities: [Kinestésico]` con `actividad_kinestesica`, aprobarla y exportarla en SCORM y en el documento de la unidad. | (a) Cada pedido termina con `parameters.modalities = [X]` y sus recursos con `params.modality = X`. (b) `422 RESOURCE_TYPE_NOT_IN_MODALITY`; no se crea ningún pedido y el número de recursos de la unidad no cambia. (c) Se acepta como hoy, sin filtrar tipos, con `parameters.modalities = []`. (d) Las dos regeneraciones terminan `succeeded`. (e) El recurso trae al menos 3 `guidedSteps` citados, `materials`, `estimatedMinutes` y `space`, con `verification.status = current`; el documento de la unidad y el paquete SCORM muestran los materiales, el tiempo estimado y el espacio antes de los pasos, y SCORM, la casilla «Lo hicimos». |
| V13 | Evaluación RAG (TA-010) | Con `LLM_PROVIDER=rules`, una secuencia con `topK: 8`. Al terminar, `GET /generation-requests/{id}/evidence`; repetir con el token de otro docente y antes de que el pedido empiece (con `GENERATION_MAX_WORKERS=1` y otro pedido en curso). | `200` con `requestId`, `retrievalMode` igual al del pedido, `limit = 8`, `retrievedAt` y `fragments` en el orden de la recuperación; los fragmentos de `evidence` de cada recurso son parte de `fragments`. Otro docente: `404 GENERATION_REQUEST_NOT_FOUND`, igual que un pedido inexistente. En cola: `200` con `fragments: []` y `retrievedAt: null`. |

## V11 · Carga

Ejecutar 5 secuencias de 8 tipos × 5 recursos con `LLM_PROVIDER=gemini` y con `rules`, y registrar en `tasks.md` la duración de cada pedido (p50 y p95), las llamadas al modelo por paso y los pedidos que llegaron a `DEADLINE_EXCEEDED`. El criterio de aceptación de los límites está en [research R4](research.md#r4-límites-de-carga). Con 3 pedidos simultáneos del mismo docente, el tercero responde `429 TOO_MANY_ACTIVE_REQUESTS`.

## Recorrido en interfaz

En `Plataforma_Docente_frontend`, en la ruta `/courses/:courseId/units/:unitId/generation`:

1. Pedir una secuencia y recargar la página en mitad del proceso. El progreso se recupera y continúa con el estado del servidor.
2. Cortar la red con DevTools en modo offline justo al enviar y reintentar. Debe existir un solo pedido.
3. Comprobar que se distinguen los avisos de respaldo de búsqueda y de respaldo de redacción.
