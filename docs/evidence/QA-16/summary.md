# Evidencia QA-16 · Protección contra denegación de servicio

- **Tarea:** QA-16 (`[BE] Sergio`)
- **Atributo ISO/IEC 25010:** Fiabilidad (Disponibilidad y Tolerancia a fallos)
- **Medidas ISO/IEC 25023:** RAv-1-G, RFt-1-G ($X = A / B$)
- **Fecha de medición:** 2026-11-19

## 1. Controles implementados

- **`IpRateLimitMiddleware`** (`backend/src/platform5e/infrastructure/http/security.py`): límite deslizante por IP cliente (resolviendo `X-Forwarded-For` únicamente desde `TRUSTED_PROXIES`) en las 7 rutas costosas (`POST /api/v1/generation-requests`, `POST /api/v1/generation-requests/interpret`, `POST /api/v1/documents`, `POST /api/v1/documents/from-topic`, `POST /api/v1/documents/{document_id}/process`, `POST /api/v1/units/{unit_id}/exports` y `POST /api/v1/units/{unit_id}/resources/{resource_id}/regenerations`). Responde `429 Too Many Requests` con encabezado `Retry-After` y código `RATE_LIMIT_EXCEEDED`. Configurable mediante `EXPENSIVE_RATE_LIMIT_MAX_REQUESTS` (defecto: `60`) y `EXPENSIVE_RATE_LIMIT_WINDOW_SECONDS` (defecto: `60`).
- **`PayloadSizeLimitMiddleware`** (`backend/src/platform5e/infrastructure/http/security.py`): middleware ASGI puro que inspecciona `Content-Length` antes de leer el cuerpo (y controla el stream entrante) devolviendo `413 Payload Too Large` (`PAYLOAD_TOO_LARGE`) cuando se superan `25 MB` (`MAX_UPLOAD_BODY_BYTES`) en `POST /api/v1/documents` o `1 MB` (`MAX_JSON_BODY_BYTES`) en rutas JSON.

## 2. Pruebas E2E (`pytest-qa16.txt`)

Comando ejecutado:

```bash
python -m pytest backend/tests/e2e/test_rate_limit_and_body_size.py -v
```
