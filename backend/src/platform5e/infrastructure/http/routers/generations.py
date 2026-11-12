"""
Historial de la generación síncrona retirada (GEN-01, T046).

`POST /api/v1/generations` se retiró: los pedidos nuevos usan routers/generation_requests.py. Quedan las lecturas del
historial guardado antes de GEN-01, que ahora es de Cuentas: `GET /api/v1/generations` (lista del docente) y
`GET /api/v1/generations/{id}`, con la misma comprobación de pertenencia y la misma respuesta.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from platform5e.application.services.accounts.account_service import AccountService
from platform5e.infrastructure.http.dependencies import current_teacher_dependency, extract_authorization_header
from platform5e.infrastructure.http.schemas.common import error_responses
from platform5e.infrastructure.http.schemas.generations import GenerationRequestRecord, GenerationResult


def create_generations_router(account_service: AccountService) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    current_teacher = current_teacher_dependency(account_service)

    @router.get(
        "/generations",
        tags=["generations"],
        response_model=list[GenerationRequestRecord],
        summary="List my generation requests",
        responses=error_responses(401),
    )
    def list_generation_requests(teacher_id: str = Depends(current_teacher)) -> list[dict[str, Any]]:
        """History of the teacher's requests, newest first.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/api/v1/generations" -H "Authorization: Bearer $TOKEN"
        ```

        Expected 200. See the response schema below for the returned fields."""
        return account_service.list_generation_requests(teacher_id)

    @router.get(
        "/generations/{generation_id}",
        tags=["generations"],
        response_model=GenerationResult,
        summary="Get a generation",
        responses=error_responses(401, 404),
    )
    def get_generation(
        generation_id: str, authorization: str | None = Depends(extract_authorization_header)
    ) -> Any:
        """Returns a saved generation exactly as it was answered. Generations of other teachers give 404.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/api/v1/generations/${GENERATION_ID}" -H "Authorization: Bearer $TOKEN"
        ```

        Expected 200. See the response schema below for the returned fields."""
        return account_service.get_generation(generation_id, authorization)

    return router
