"""
Adaptador HTTP de la generación de recursos (HU-053, EN-006): RAG sobre el material de la unidad.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from platform5e.application.services.accounts.account_service import AccountService
from platform5e.application.services.generation.generation_service import GenerationService
from platform5e.domain.generation.errors import GenerationError
from platform5e.domain.shared.errors import PersistenceUnavailableError
from platform5e.infrastructure.http.dependencies import current_teacher_dependency, extract_authorization_header
from platform5e.infrastructure.http.error_handlers import error_json
from platform5e.infrastructure.http.schemas.common import error_responses
from platform5e.infrastructure.http.schemas.generations import (
    GenerationRequest,
    GenerationRequestRecord,
    GenerationResult,
    GeneratorInfo,
)


def create_generations_router(
    generation_service: GenerationService,
    account_service: AccountService,
    generator_info: dict[str, Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    current_teacher = current_teacher_dependency(account_service)

    @router.post(
        "/generations",
        tags=["generations"],
        response_model=GenerationResult,
        summary="Generate resources from the unit material",
        responses=error_responses(400, 401, 404, 422, 503),
    )
    def generate_resources(
        body: GenerationRequest, authorization: str | None = Depends(extract_authorization_header)
    ) -> Any:
        """Retrieves the most relevant chunks of the unit (BM25) and drafts the resources with the active generator.

        Only resources whose claims cite valid chunks are kept; they are saved as `pendiente` for the teacher's review.
        If the AI fails, the rule-based generator answers and `generator.fallback` is true. Without material the
        request is rejected (400 NO_PROCESSED_MATERIAL) instead of inventing content.

        With `resourceTypes`, the request becomes a class sequence (HU-003): each type goes to the agent of its 5E
        stage, in the order of the class; all agents share the same evidence and see what the previous ones wrote.
        A resource too similar to another one of the sequence is asked again once and, if it still repeats, rejected.
        Each resource records its `agent`, and `sequence` reports what every agent generated or rejected.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X POST "$BASE_URL/api/v1/generations" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' --data '{"unitId":"unidad-1","stage":"explain","resourceType":"glosario","quantity":1,"difficulty":"intermedia"}'
        ```

        Replace unidad-1 with a unit containing processed material. Expected 200; returned resources await review."""
        try:
            teacher_id = account_service.authenticate_token(authorization) if authorization else None
            if teacher_id:
                account_service.get_unit(teacher_id, body.unit_id)
            return generation_service.generate(body.to_domain(), teacher_id)
        except GenerationError as error:
            return error_json(400, error.code, error.message)
        except PersistenceUnavailableError:
            return error_json(
                503,
                "PERSISTENCE_UNAVAILABLE",
                "No se pudo guardar la solicitud. Comprueba la conexión de la base de datos.",
            )

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
        try:
            account_service.verify_generation_ownership(generation_id, authorization)
            return generation_service.get_by_id(generation_id)
        except GenerationError as error:
            return error_json(404, error.code, error.message)

    @router.get(
        "/generator",
        response_model=GeneratorInfo,
        summary="Get the active generator",
        tags=["system"],
    )
    def get_generator() -> dict[str, Any]:
        """Says whether resources are drafted by a language model (and which one) or by the rule-based generator.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/api/v1/generator"
        ```

        Expected 200. See the response schema below for the returned fields."""
        return generator_info

    return router
