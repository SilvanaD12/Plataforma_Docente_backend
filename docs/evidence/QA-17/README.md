# QA-17 · Concurrencia y capacidad con Locust

Evidencia de la medición de QA-17 ([spec](../../../specs/005-atributos-calidad/spec.md), [plan](../../../specs/005-atributos-calidad/plan.md#qa-17--concurrencia-y-capacidad-con-locust)): escalones de 10, 25, 50 y 100 docentes simultáneos, 3 minutos cada uno, con `backend/performance/locust/locustfile.py`.

## Entorno

- Mac local, del 16/11 al 18/11/2026. Los cuatro escalones se corrieron seguidos el 18/11/2026, de 20:01 a 20:13 (hora de Lima). Los archivos de `docker stats` registran la hora en UTC (19/11, de 01:01 a 01:13).
- PostgreSQL 17 con pgvector en Docker (`backend/docker-compose.yml`, contenedor `backend-db-1`), en el puerto 5433 del equipo.
- Un solo proceso de `uvicorn`, fuera de Docker, con `LLM_PROVIDER=rules` (generador por reglas, sin Gemini), `EMBEDDINGS_ENABLED=false` (búsqueda `bm25_fallback`) y `GENERATION_MAX_WORKERS` por defecto (2).
- Locust 2.47.0 (extra `perf`), en el mismo equipo y desde una sola IP.
- El límite por IP de QA-16 todavía no está en `main`: QA-17 se midió antes de QA-16, sin ese límite.
- Sin ninguna clave de API. Las cuentas son de prueba, creadas por cada usuario virtual con un correo único.

## Comandos

Desde `backend/`, con `.env` copiado de `.env.example` (sin clave de API) y `POSTGRES_PORT=5433`:

```bash
docker compose up -d --wait db
docker compose run --rm dbmate up

# Terminal 1: backend
export DATABASE_URL='postgres://platform5e:cambiar-en-local@localhost:5433/platform5e?sslmode=disable'
export LLM_PROVIDER=rules EMBEDDINGS_ENABLED=false MEDIA_GENERATION_ENABLED=false TOPIC_SEARCH_ENABLED=false
unset LLM_API_KEY
.venv/bin/python -m uvicorn platform5e.main:create_application --factory --app-dir src --host 127.0.0.1 --port 8000
```

Terminal 2, desde la raíz del repositorio:

```bash
mkdir -p docs/evidence/QA-17
for users in 10 25 50 100; do
  ( while true; do date -u +%FT%TZ; docker stats --no-stream; sleep 30; done ) > docs/evidence/QA-17/docker-stats-${users}u.txt &
  STATS=$!
  backend/.venv/bin/locust -f backend/performance/locust/locustfile.py --host http://127.0.0.1:8000 \
    --headless -u ${users} -r 5 -t 3m \
    --html docs/evidence/QA-17/${users}u.html --csv docs/evidence/QA-17/${users}u
  kill $STATS
done
```

## Archivos

- `<N>u.html`: informe de Locust del escalón de N usuarios.
- `<N>u_stats.csv`, `<N>u_stats_history.csv`, `<N>u_failures.csv` y `<N>u_exceptions.csv`: estadísticas de Locust. Los archivos de fallos y de excepciones están vacíos en los cuatro escalones.
- `docker-stats-<N>u.txt`: `docker stats --no-stream` cada 30 s durante el escalón (6 muestras). La otra base que aparece, `plataforma-5e-taller-integrador-db-1`, es de otro proyecto del mismo equipo: no se usa.

## Qué se cuenta

La capacidad se calcula solo con las rutas reales que usa un docente:
- `GET /api/v1/courses`;
- `GET /api/v1/documents/search`;
- `POST /api/v1/generation-requests`;
- `GET /api/v1/generation-requests/[id]`.

Se excluyen dos tipos de filas:
- **«[preparación] …»** (cuenta, sesión, curso, subida y procesamiento del material): cada usuario las hace una sola vez al empezar, así que miden el alta de los usuarios, no la carga sostenida.
- **«[pedido completo] creado→final»**: mide el pedido de punta a punta, y su valor está acotado por el intervalo de consulta de 1 s (`LOCUST_POLL_SECONDS`). El generador por reglas termina antes de la primera consulta, así que esa fila mide sobre todo la espera del cliente, no el servidor. Se informa aparte.

## Resultados por escalón

Calculados con `<N>u_stats.csv` (las 4 rutas reales). p50 y p95 en ms. «p95 más alto» y «Máximo» son de esas 4 rutas. CPU y memoria son los picos de `backend-db-1` en `docker-stats-<N>u.txt`.

| Usuarios | Peticiones/s | `GET /courses` p50 / p95 | `GET /documents/search` p50 / p95 | `POST /generation-requests` p50 / p95 | `GET /generation-requests/[id]` p50 / p95 | p95 más alto | Máximo | Errores | CPU de la BD (pico) | Memoria de la BD (pico) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | 5,2 | 14 / 22 | 19 / 27 | 46 / 66 | 23 / 30 | 66 ms | 101 ms | 0 % (0 de 930) | 12,9 % | 44,5 MiB |
| 25 | 13,0 | 12 / 19 | 16 / 25 | 42 / 59 | 19 / 29 | 59 ms | 74 ms | 0 % (0 de 2330) | 9,0 % | 45,4 MiB |
| 50 | 25,8 | 11 / 19 | 15 / 24 | 37 / 53 | 17 / 28 | 53 ms | 96 ms | 0 % (0 de 4621) | 11,8 % | 48,8 MiB |
| 100 | 50,2 | 9 / 25 | 12 / 32 | 29 / 77 | 14 / 34 | 77 ms | 796 ms | 0 % (0 de 9028) | 14,5 % | 55,6 MiB |

El máximo de 796 ms con 100 usuarios es de un `POST /api/v1/generation-requests` (p99 150 ms, p99.9 790 ms): es un valor aislado. No hubo 429 de pedidos activos en ningún escalón: cada usuario espera su pedido antes de crear otro.

**Pedido de punta a punta** («[pedido completo] creado→final», p50, aparte de la capacidad): 1100 ms con 10 usuarios, 1100 ms con 25, 1100 ms con 50 y 1000 ms con 100. Son 110, 255, 587 y 1097 pedidos. Es casi todo el intervalo de consulta de 1 s.

## Medidas de ISO/IEC 25023

- **PCa-2-G, capacidad de acceso de usuarios.** Mayor número de usuarios con p95 < 1 s y errores < 1 % entre los escalones medidos: **≥ 100 usuarios** (no se alcanzó el límite; el punto de quiebre lo busca QA-18).
- **PTb-1-G, tiempo medio de respuesta.** Media de las 4 rutas reales con 100 usuarios, ponderada por peticiones: **17,8 ms**. En los otros escalones: 21,2 ms (10), 18,2 ms (25) y 17,0 ms (50).
- **PTb-5-G, rendimiento medio.** Peticiones por segundo de las rutas reales: **5,2 / 13,0 / 25,8 / 50,2** con 10, 25, 50 y 100 usuarios. Crece en proporción al número de usuarios, porque cada usuario espera entre 1 y 3 s entre tareas.

## Límites

- Un solo equipo local: Locust y el backend comparten la máquina, y la base es un contenedor local. No es Render ni Neon.
- Generador por reglas, sin Gemini. Los tiempos de generación con IA son otros y los limita QA-06 (60 s por llamada).
- Una sola IP. Se midió antes de QA-16: con el límite por IP, la misma corrida recibiría 429.
- La fila de punta a punta está acotada por la consulta cada 1 s.

Ningún archivo de esta carpeta contiene tokens, contraseñas ni claves de API. Las coincidencias de «password» y «tokens» en los `.html` son del JavaScript que trae Locust, no de datos de la corrida.
