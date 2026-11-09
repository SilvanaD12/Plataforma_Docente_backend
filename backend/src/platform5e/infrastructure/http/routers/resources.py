"""
Adaptador HTTP de la revisión docente de los recursos generados (HU-010).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status

from platform5e.application.services.accounts.account_service import AccountService
from platform5e.application.services.review.resource_review_service import ResourceReviewService
from platform5e.application.use_cases.media.get_resource_media import GetResourceMediaUseCase
from platform5e.application.use_cases.media.regenerate_resource_media import RegenerateResourceMediaUseCase
from platform5e.infrastructure.http.dependencies import current_teacher_dependency
from platform5e.infrastructure.http.schemas.common import error_responses
from platform5e.infrastructure.http.schemas.resources import (
    ResourceResponse,
    ReviewedResourceInput,
    UnitSummaryResponse,
    VerificationRetryInput,
)


def create_resources_router(
    review_service: ResourceReviewService,
    account_service: AccountService,
    media_use_case: GetResourceMediaUseCase,
    regenerate_media_use_case: RegenerateResourceMediaUseCase,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["resources"])
    current_teacher = current_teacher_dependency(account_service)

    @router.get(
        "/review-summary",
        response_model=list[UnitSummaryResponse],
        summary="Count approved and pending resources per unit",
        responses=error_responses(401),
    )
    def get_review_summary(teacher_id: str = Depends(current_teacher)) -> list[dict[str, Any]]:
        """One row per unit of the teacher's courses.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/api/v1/review-summary" -H "Authorization: Bearer $TOKEN"
        ```

        Expected 200. See the response schema below for the returned fields."""
        return review_service.get_summary(teacher_id)

    @router.get(
        "/units/{unit_id}/resources",
        response_model=list[ResourceResponse],
        summary="List the resources of a unit",
        responses=error_responses(401, 404),
    )
    def list_unit_resources(unit_id: str, teacher_id: str = Depends(current_teacher)) -> list[dict[str, Any]]:
        """Generated resources of the unit with their review, newest first.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/api/v1/units/${UNIT_ID}/resources" -H "Authorization: Bearer $TOKEN"
        ```

        Expected 200. See the response schema below for the returned fields."""
        return review_service.list_resources(teacher_id, unit_id)

    @router.put(
        "/units/{unit_id}/resources/{resource_id}",
        response_model=ResourceResponse,
        summary="Save the review of a resource",
        responses=error_responses(400, 401, 404, 409, 422),
    )
    def update_resource(
        unit_id: str, resource_id: str, body: ReviewedResourceInput, teacher_id: str = Depends(current_teacher)
    ) -> dict[str, Any]:
        """Saves edits and decisions. `aprobado` needs a key, no pending distractors and at least two accepted
        (409 APPROVAL_BLOCKED otherwise): the same rule the review screen shows.

        Send `expectedVersion` with the `version` you read. If the resource changed meanwhile (another tab), the save
        is rejected with 409 VERSION_CONFLICT and nothing changes: reload the resource. When the verifiable content
        changes, it is checked again against the stored evidence copy, without external services, and the result
        comes in `verification`. An approved resource whose content changed goes back to `pendiente`
        (`reviewReset: true`) and needs a new approval.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X PUT "$BASE_URL/api/v1/units/${UNIT_ID}/resources/${RESOURCE_ID}" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' --data '{"expectedVersion":1,"title":"Glosario de transporte","body":"TCP confirma la recepción de datos.","status":"pendiente","edited":true}'
        ```

        Use a resource in your unit; copy its actual title, content and version before saving. This example saves an edit as pendiente, not an approval. Expected 200."""
        return review_service.update_resource(
            teacher_id, unit_id, resource_id, body.model_dump(by_alias=True, exclude_unset=True)
        )

    @router.post(
        "/units/{unit_id}/resources/{resource_id}/verification",
        response_model=ResourceResponse,
        summary="Retry the verification of a pending resource",
        responses=error_responses(401, 404, 409, 422),
    )
    def retry_verification(
        unit_id: str, resource_id: str, body: VerificationRetryInput, teacher_id: str = Depends(current_teacher)
    ) -> dict[str, Any]:
        """«Reintentar comprobación» (REV-C3): checks the same version again with the current rule and the stored
        `evidenceThreshold`, using only the evidence copy saved in the resource (no external services). The version
        does not change.

        Only for `verification.status = pending` (409 VERIFICATION_NOT_PENDING). Without an evidence copy, or with a
        referenced chunk missing from it, the retry is not offered: regenerate the resource (409 REGENERATION_REQUIRED).
        An outdated `expectedVersion` returns 409 VERSION_CONFLICT.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X POST "$BASE_URL/api/v1/units/${UNIT_ID}/resources/${RESOURCE_ID}/verification" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' --data '{"expectedVersion":1}'
        ```

        Use a resource whose verification is pending and send its current version. Expected 200."""
        return review_service.retry_verification(teacher_id, unit_id, resource_id, body.expected_version)

    @router.get(
        "/units/{unit_id}/resources/{resource_id}/media",
        summary="Get the image, graphic or audio of a resource",
        response_class=Response,
        responses={
            200: {
                "content": {"image/svg+xml": {}, "image/png": {}, "image/jpeg": {}, "audio/mpeg": {}, "audio/wav": {}},
                "description": "The file. Graphics are drawn as SVG from the resource structure.",
            },
            **error_responses(401, 404),
        },
    )
    def get_resource_media(unit_id: str, resource_id: str, teacher_id: str = Depends(current_teacher)) -> Response:
        """Concept maps, infographics and process diagrams are drawn as SVG from their items. Illustrations and
        audio return the generated file; without one, an illustration returns a card with its description and an
        audio resource answers 404 NO_MEDIA (the review reads the script with the browser's voice).

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -X GET "$BASE_URL/api/v1/units/${UNIT_ID}/resources/${RESOURCE_ID}/media" -H "Authorization: Bearer $TOKEN" -D respuesta-headers.txt --output recurso.bin
        ```

        Expected 200 when media is available; its actual MIME type determines the file extension. An audio fallback without a file returns 404."""
        media = media_use_case.execute(teacher_id, unit_id, resource_id)
        return Response(
            media.content,
            media_type=media.media_type,
            headers={"Content-Disposition": f'inline; filename="{media.file_name}"', "Cache-Control": "private, max-age=60"},
        )

    @router.post(
        "/units/{unit_id}/resources/{resource_id}/media",
        response_model=ResourceResponse,
        summary="Generate the image or audio of a resource again",
        responses=error_responses(401, 404, 409, 422),
    )
    def regenerate_resource_media(unit_id: str, resource_id: str, teacher_id: str = Depends(current_teacher)) -> dict[str, Any]:
        """Generates the illustration or the audio again from the current description or script, for example after
        the teacher edited it. Only for resources under review (409 RESOURCE_NOT_PENDING) and when image and voice
        generation is active on the server (409 MEDIA_GENERATION_DISABLED). If the service fails, the resource keeps
        its fallback: the description card or the browser's voice.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X POST "$BASE_URL/api/v1/units/${UNIT_ID}/resources/${RESOURCE_ID}/media" -H "Authorization: Bearer $TOKEN"
        ```

        Expected 200 for a pending resource when media generation is enabled; otherwise the documented 409 applies."""
        return regenerate_media_use_case.execute(teacher_id, unit_id, resource_id)

    @router.delete(
        "/units/{unit_id}/resources/{resource_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Delete a resource",
        responses=error_responses(401, 404),
    )
    def delete_resource(unit_id: str, resource_id: str, teacher_id: str = Depends(current_teacher)) -> Response:
        """Deletes the resource from the unit.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X DELETE "$BASE_URL/api/v1/units/${UNIT_ID}/resources/${RESOURCE_ID}" -H "Authorization: Bearer $TOKEN"
        ```

        Deletes the selected resource. Expected 204 with an empty body."""
        review_service.delete_resource(teacher_id, unit_id, resource_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
