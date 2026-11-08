"""Catálogo público de los recursos admitidos por el backend."""
from fastapi import APIRouter

from platform5e.application.use_cases.catalog.list_resource_types import ListResourceTypesUseCase
from platform5e.infrastructure.http.schemas.catalog import ResourceTypeResponse


def create_catalog_router(use_case: ListResourceTypesUseCase) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["catalog"])

    @router.get(
        "/resource-types",
        response_model=list[ResourceTypeResponse],
        summary="List supported resource types in teaching order",
    )
    def list_resource_types():
        """Public metadata only: no teacher data, session or external AI calls.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/api/v1/resource-types"
        ```

        Expected 200. See the response schema below for the returned fields."""
        return use_case.execute()

    return router
