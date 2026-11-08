"""
Adaptador HTTP del historial de descargas de cada unidad
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status

from platform5e.application.services.accounts.account_service import AccountService
from platform5e.application.services.review.resource_review_service import ResourceReviewService
from platform5e.infrastructure.http.dependencies import current_teacher_dependency
from platform5e.infrastructure.http.schemas.common import error_responses
from platform5e.infrastructure.http.schemas.downloads import DownloadResponse


def create_teacher_downloads_router(review_service: ResourceReviewService, account_service: AccountService) -> APIRouter:
    """REV-01 · Historial de descargas del docente, que se conserva al borrar el curso (REV-R9)."""
    router = APIRouter(prefix="/api/v1/downloads", tags=["downloads"])
    current_teacher = current_teacher_dependency(account_service)

    @router.get("", response_model=list[DownloadResponse], summary="List my downloads", responses=error_responses(401))
    def list_teacher_downloads(teacher_id: str = Depends(current_teacher)) -> list[dict[str, Any]]:
        """Downloads of the signed-in teacher, newest first, limited to the last 50 (there is no paging yet). Each
        record keeps the date, format, file name, course and unit, also after the course is deleted. Only the record
        is kept, not the exported file. Records saved before REV-01 may come without course and unit names.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/api/v1/downloads" -H "Authorization: Bearer $TOKEN"
        ```

        Expected 200. See the response schema below for the returned fields."""
        return review_service.get_teacher_downloads(teacher_id)

    return router


def create_downloads_router(review_service: ResourceReviewService, account_service: AccountService) -> APIRouter:
    router = APIRouter(prefix="/api/v1/units/{unit_id}/downloads", tags=["downloads"])
    current_teacher = current_teacher_dependency(account_service)

    @router.get("", response_model=list[DownloadResponse], summary="List the downloads of a unit", responses=error_responses(401, 404))
    def list_downloads(unit_id: str, teacher_id: str = Depends(current_teacher)) -> list[dict[str, Any]]:
        """The last 50 downloads of the unit, newest first (there is no paging yet). Exports record themselves once
        per file; GET /api/v1/downloads lists the whole history of the teacher, also after a course is deleted.

        REV-01 removed `POST /units/{unit_id}/downloads` (it duplicated the record that every export already saves)
        and `GET /units/{unit_id}/downloads/{download_id}` (re-downloading is out of scope and that route exported the
        current state, not the original file).

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/api/v1/units/${UNIT_ID}/downloads" -H "Authorization: Bearer $TOKEN"
        ```

        Expected 200. See the response schema below for the returned fields."""
        return review_service.get_downloads_history(teacher_id, unit_id)

    @router.delete(
        "",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Clear the download history",
        responses=error_responses(401, 404),
    )
    def clear_downloads(unit_id: str, teacher_id: str = Depends(current_teacher)) -> Response:
        """Deletes the history of the unit. The files already downloaded are not affected.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X DELETE "$BASE_URL/api/v1/units/${UNIT_ID}/downloads" -H "Authorization: Bearer $TOKEN"
        ```

        Deletes the download history of the unit. Expected 204 with an empty body."""
        review_service.clear_downloads_history(teacher_id, unit_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
