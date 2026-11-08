"""
Adaptador HTTP del historial de descargas de cada unidad
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status

from platform5e.application.services.accounts.account_service import AccountService
from platform5e.application.services.review.resource_review_service import ResourceReviewService
from platform5e.application.use_cases.export.export_unit_resources import ExportUnitResourcesUseCase
from platform5e.domain.accounts.teacher_account import AccountConfigurationError
from platform5e.infrastructure.http.dependencies import current_teacher_dependency
from platform5e.infrastructure.http.schemas.common import error_responses
from platform5e.infrastructure.http.schemas.downloads import DownloadInput, DownloadResponse


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


def create_downloads_router(
    review_service: ResourceReviewService,
    account_service: AccountService,
    export_use_case: ExportUnitResourcesUseCase | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/units/{unit_id}/downloads", tags=["downloads"])
    current_teacher = current_teacher_dependency(account_service)

    @router.get("", response_model=list[DownloadResponse], summary="List the downloads of a unit", responses=error_responses(401, 404))
    def list_downloads(unit_id: str, teacher_id: str = Depends(current_teacher)) -> list[dict[str, Any]]:
        """The last 50 downloads, newest first.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/api/v1/units/${UNIT_ID}/downloads" -H "Authorization: Bearer $TOKEN"
        ```

        Expected 200. See the response schema below for the returned fields."""
        return review_service.get_downloads_history(teacher_id, unit_id)

    @router.get(
        "/{download_id}",
        summary="Re-download an exported package",
        response_class=Response,
        responses={
            200: {
                "content": {"application/zip": {}, "application/xml": {}, "text/html": {}},
                "description": "The re-downloaded file; its name comes in Content-Disposition.",
            },
            **error_responses(401, 404, 422),
        },
    )
    def redownload_package(
        unit_id: str,
        download_id: str,
        teacher_id: str = Depends(current_teacher),
    ) -> Response:
        """Re-downloads an exported package recorded in the unit's download history (HU-010 C02).

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -X GET "$BASE_URL/api/v1/units/${UNIT_ID}/downloads/${DOWNLOAD_ID}" -H "Authorization: Bearer $TOKEN" -D respuesta-headers.txt --output paquete.zip
        ```

        Expected 200 for an existing history entry and resources compatible with its format. The returned MIME type determines the file extension."""
        if export_use_case is None:
            raise AccountConfigurationError("SERVICE_UNAVAILABLE", "Export service not configured.", 500)

        record = review_service.get_download_record(teacher_id, unit_id, download_id)
        exported = export_use_case.execute(teacher_id, unit_id, record["format"])
        return Response(
            exported.content,
            media_type=exported.media_type,
            headers={"Content-Disposition": f'attachment; filename="{exported.file_name}"'},
        )

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        response_model=DownloadResponse,
        summary="Record a download",
        responses=error_responses(401, 404, 422),
    )
    def register_download(unit_id: str, body: DownloadInput, teacher_id: str = Depends(current_teacher)) -> dict[str, Any]:
        """Records a file built in the browser (the unit document). Exports built by the backend record themselves.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X POST "$BASE_URL/api/v1/units/${UNIT_ID}/downloads" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' --data '{"format":"documento","fileName":"red-301-unidad-1-documento.html","resourceCount":1}'
        ```

        Replace unidad-1 through UNIT_ID. This registers browser-built document metadata; it does not generate a package. Expected 201."""
        return review_service.register_download(teacher_id, unit_id, body.model_dump(by_alias=True))

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
