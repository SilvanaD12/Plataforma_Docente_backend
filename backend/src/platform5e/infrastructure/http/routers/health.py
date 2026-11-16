"""
Health-check routes for Render (Health Check Path: /health) and dependency diagnostics (EN-028).
"""

from __future__ import annotations

from fastapi import APIRouter
from starlette.responses import JSONResponse

from platform5e.application.use_cases.health.check_dependencies import CheckDependencies
from platform5e.infrastructure.http.schemas.health import (
    DependencyHealthResponse,
    HealthResponse,
)


def create_health_router(check_dependencies: CheckDependencies | None = None) -> APIRouter:
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

    @router.get(
        "/health/dependencies",
        response_model=DependencyHealthResponse,
        summary="Check external dependency health (database, Gemini, Wikipedia)",
        responses={
            503: {
                "model": DependencyHealthResponse,
                "description": "The database is unreachable.",
            }
        },
    )
    def check_dependency_health() -> JSONResponse:
        """Probes every external dependency in parallel with a 3 s timeout per probe.

        Returns 200 with `status: ok` or `status: degraded`.
        Returns 503 only when the database is unreachable.
        Results are cached for 30 s to prevent abuse.

        Example (Bash/cURL). Set BASE_URL to the API URL.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/health/dependencies"
        ```

        Expected 200 (or 503 if the database is down). See the response schema below."""
        if check_dependencies is None:
            return JSONResponse(
                content={"status": "ok", "checkedAt": "", "checks": []},
            )

        result = check_dependencies.execute()

        body = {
            "status": result.status,
            "checkedAt": result.checked_at,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "latencyMs": c.latency_ms,
                    "detail": c.detail,
                }
                for c in result.checks
            ],
        }

        status_code = 503 if result.database_down else 200
        return JSONResponse(content=body, status_code=status_code)

    return router
