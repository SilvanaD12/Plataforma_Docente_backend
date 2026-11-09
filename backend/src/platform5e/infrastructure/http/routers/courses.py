"""
Adaptador HTTP de cursos, unidades y resultados de aprendizaje (EP-002).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status

from platform5e.application.services.accounts.account_service import AccountService
from platform5e.infrastructure.http.dependencies import current_teacher_dependency
from platform5e.infrastructure.http.schemas.common import error_responses
from platform5e.infrastructure.http.schemas.courses import CourseInput, CourseResponse


def _to_service(body: CourseInput) -> dict[str, Any]:
    """El servicio recibe el curso con las claves del JSON (summary, learningGoal, units…)."""
    return body.model_dump(by_alias=True)


def create_courses_router(account_service: AccountService) -> APIRouter:
    router = APIRouter(prefix="/api/v1/courses", tags=["courses"])
    current_teacher = current_teacher_dependency(account_service)

    @router.get("", response_model=list[CourseResponse], summary="List my courses", responses=error_responses(401))
    def list_courses(teacher_id: str = Depends(current_teacher)) -> list[dict[str, Any]]:
        """Courses of the signed-in teacher with their units and learning outcomes.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/api/v1/courses" -H "Authorization: Bearer $TOKEN"
        ```

        Expected 200. See the response schema below for the returned fields."""
        return account_service.list_courses(teacher_id)

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        response_model=CourseResponse,
        summary="Create a course",
        responses=error_responses(400, 401, 409, 422),
    )
    def create_course(body: CourseInput, teacher_id: str = Depends(current_teacher)) -> dict[str, Any]:
        """Creates the course with at least one unit. The code is stored in uppercase and must be unique (409).

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X POST "$BASE_URL/api/v1/courses" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' --data '{"code":"RED-301","name":"Redes de computadoras","term":"2026-II","units":[{"title":"Capa de transporte","outcomes":[{"code":"RA1","text":"Distingue los protocolos TCP y UDP."}]}]}'
        ```

        Expected 201. Use a different code if RED-301 already exists for this teacher."""
        return account_service.save_course(teacher_id, _to_service(body))

    @router.put(
        "/{course_id}",
        response_model=CourseResponse,
        summary="Update a course",
        responses=error_responses(400, 401, 404, 409, 422),
    )
    def update_course(course_id: str, body: CourseInput, teacher_id: str = Depends(current_teacher)) -> dict[str, Any]:
        """Replaces the course data. Existing units must be sent back with their id; new units have none.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X PUT "$BASE_URL/api/v1/courses/${COURSE_ID}" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' --data '{"code":"RED-301","name":"Redes de computadoras","term":"2026-II","units":[{"title":"Capa de transporte","outcomes":[{"code":"RA1","text":"Distingue los protocolos TCP y UDP."}],"id":"unidad-1"}]}'
        ```

        Replace unidad-1 with an existing unit id. Copy existing unit and outcome ids from GET /courses before editing to preserve them. Expected 200."""
        return account_service.save_course(teacher_id, _to_service(body), course_id)

    @router.delete(
        "/{course_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Delete a course",
        responses=error_responses(401, 404),
    )
    def delete_course(course_id: str, teacher_id: str = Depends(current_teacher)) -> Response:
        """Deletes the course, its documents, chunks, resources and their media. Download records are retained.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X DELETE "$BASE_URL/api/v1/courses/${COURSE_ID}" -H "Authorization: Bearer $TOKEN"
        ```

        Expected 204 with an empty body."""
        account_service.delete_course(teacher_id, course_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
