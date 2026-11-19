# Backend · API REST de Platform 5E

FastAPI y SQLAlchemy con arquitectura hexagonal. Se despliega en Render (`rootDir: backend`) bajo el dominio personalizado `https://api.plataformadocente.dev` y usa PostgreSQL en Neon; en local usa SQLite si no se define `DATABASE_URL`.

## Despliegue en producción

- **Dominio de la API (Backend):** `https://api.plataformadocente.dev` (servicio Render)
  - Comprobación de salud: `GET https://api.plataformadocente.dev/health`
  - Documentación Swagger: `https://api.plataformadocente.dev/docs`
- **Dominio de la aplicación (Frontend):** `https://plataformadocente.dev` (Vercel, con redirección desde `https://www.plataformadocente.dev`)
- **Infraestructura:** Render (`rootDir: backend`) para la API, Neon para PostgreSQL con extensión `vector` (pgvector) y Vercel para el frontend.

## Ejecutar en local

~~~bash
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn platform5e.main:app --reload --port 8000
~~~

Swagger en http://localhost:8000/docs y ReDoc en http://localhost:8000/redoc. El contrato versionado está en [`../docs/api/openapi.json`](../docs/api/openapi.json).

## Pruebas

| Comando | Qué corre |
| --- | --- |
| `pytest` | Todo: unitarias, arquitectura, integración y punta a punta |
| `pytest tests/unit` | Dominio y casos de uso |
| `pytest tests/architecture` | Reglas de dependencias entre capas y nombres en inglés |
| `pytest tests/integration` | Repositorios y persistencia |
| `pytest tests/e2e` | API por HTTP con un servidor real (SQLite temporal, o `E2E_DATABASE_URL`) |

## Variables de entorno

Están descritas en [`.env.example`](.env.example). El backend no lee ese archivo: en local se exportan en la terminal y en producción se definen en Render.

## Base de datos local (PostgreSQL + pgvector)

~~~bash
cp .env.example .env
docker compose up -d --wait db
docker compose run --rm dbmate up
./database/verification/verify.sh
~~~

Detalles en [database/README.md](database/README.md).
