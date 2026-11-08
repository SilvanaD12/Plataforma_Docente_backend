"""
Adaptador HTTP de la exportación en el backend: POST /api/v1/units/{unit_id}/exports devuelve el archivo.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from platform5e.application.services.accounts.account_service import AccountService
from platform5e.application.use_cases.export.export_unit_resources import ExportUnitResourcesUseCase
from platform5e.infrastructure.http.dependencies import current_teacher_dependency
from platform5e.infrastructure.http.schemas.common import error_responses
from platform5e.infrastructure.http.schemas.downloads import ExportRequest


def create_exports_router(use_case: ExportUnitResourcesUseCase, account_service: AccountService) -> APIRouter:
    router = APIRouter(prefix="/api/v1/units", tags=["exports"])
    current_teacher = current_teacher_dependency(account_service)

    @router.post(
        "/{unit_id}/exports",
        summary="Export the approved resources of a unit",
        response_class=Response,
        responses={
            200: {
                "content": {"application/zip": {}, "application/xml": {}, "text/html": {}},
                "description": "The file to download; its name comes in Content-Disposition.",
            },
            **error_responses(401, 404, 422),
        },
    )
    def export_unit(unit_id: str, body: ExportRequest, teacher_id: str = Depends(current_teacher)) -> Response:
        """Builds the file in the backend from the approved resources (fixed templates, never written by the AI),
        records the download in the unit history and returns the file.

        - `scorm_zip`: SCORM 1.2 package for Chamilo, one page per resource in 5E order; questions are graded.
        - `moodle_xml`: Moodle question bank with the multiple-choice items.
        - `documento`: printable HTML document of the approved unit resources, with evidence.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -X POST "$BASE_URL/api/v1/units/${UNIT_ID}/exports" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' --data '{"format":"scorm_zip","resourceIds":[]}' -D respuesta-headers.txt --output unidad-scorm.zip
        ```

        Expected 200 when the unit has approved resources. An empty resourceIds selects every approved resource compatible with scorm_zip."""
        exported = use_case.execute(teacher_id, unit_id, body.format, body.resource_ids)
        return Response(
            exported.content,
            media_type=exported.media_type,
            headers={"Content-Disposition": f'attachment; filename="{exported.file_name}"'},
        )

    return router
