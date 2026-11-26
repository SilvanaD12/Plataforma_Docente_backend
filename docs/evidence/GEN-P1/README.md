# GEN-P1 · Tiempo de creación del plan (T020, V9)

Evidencia de [T020](../../../specs/006-plan-de-generacion/tasks.md) y de [V9 en quickstart](../../../specs/006-plan-de-generacion/quickstart.md#v9--tiempos): cuánto tarda `POST /api/v1/generation-plans` con el planificador por reglas.

## Entorno

- Backend local (`http://127.0.0.1:8000`) con SQLite y `LLM_PROVIDER=rules`, sin ninguna clave de API.
- Corpus de T067 (`backend/evaluation/corpus_t067`) procesado en la unidad de la cuenta de medición.
- Secuencia de V1: `pregunta_detonante` × 1, `explicacion` con cantidad libre e `item_opcion_multiple` × 2.
- Corrida del 25/11/2026 (`runId` 20261125T235326).

## Comando

Desde `backend/`, con el backend en marcha:

```bash
export EVAL_EMAIL=... EVAL_PASSWORD=...
.venv/bin/python scripts/measure_plan_latency.py --api http://127.0.0.1:8000   # 20 planes seguidos
```

El script crea 20 planes seguidos, cada uno con su propia clave de idempotencia, y no los aprueba ni genera. Solo corre contra un backend local.

## Resultado

| Métrica | Valor |
| --- | --- |
| Planes creados | 20 de 20 (0 fallidos, 0 con problemas de validación) |
| `POST /generation-plans` p50 | 34,4 ms |
| `POST /generation-plans` p95 | 40,8 ms |
| `POST /generation-plans` máximo | 49,1 ms |
| Planificador | reglas 20, IA 0 |
| Meta de V9 con reglas (p95 < 1 s) | **Cumplida** |

Datos: [`plan-latency-rules.json`](plan-latency-rules.json), copia de `backend/evaluation/results/plan-latency-rules-20261125T235327.json` con la ruta del corpus relativa al repositorio. No guarda el token, la contraseña ni el correo.

## Gemini (opcional, sin medir)

La parte de V9 con Gemini (p95 < 30 s) es opcional y no se midió, para no gastar créditos del proveedor. Para medirla: el mismo comando con el backend en `LLM_PROVIDER=gemini` y `LLM_MODEL=gemini-3.5-flash-lite`, con la clave local y nunca en Render.
