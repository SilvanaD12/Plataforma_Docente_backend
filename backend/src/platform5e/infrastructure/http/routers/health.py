"""
Comprobación de salud para Render (Health Check Path: /health).
"""

from __future__ import annotations

from fastapi import APIRouter

from platform5e.infrastructure.http.schemas.health import HealthResponse


def create_health_router() -> APIRouter:
    router = APIRouter(tags=["system"])

    @router.get("/health", response_model=HealthResponse, summary="Check that the API is up")
    @router.get("/salud", include_in_schema=False)  # ruta anterior: Render la usa hasta cambiar su Health Check Path
    def check_health() -> dict[str, str]:
        """Answers without touching the database, so Render can wake the service up quickly.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/health"
        ```

        Expected 200. See the response schema below for the returned fields."""
        return {"status": "ok"}

    return router
