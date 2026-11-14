"""
Adaptador HTTP del pedido de generación en segundo plano (GEN-01): inicio con clave de idempotencia, consulta del
estado por paso y listado de los pedidos de una unidad. Contrato: specs/002-generacion-multiple/contracts.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import JSONResponse

from platform5e.application.services.accounts.account_service import AccountService
from platform5e.application.use_cases.generation.get_generation_evidence import GetGenerationEvidence
from platform5e.application.use_cases.generation.get_generation_request import (
    GenerationRequestView,
    GetGenerationRequest,
)
from platform5e.application.use_cases.generation.interpret_generation_request import (
    InterpretGenerationCommand,
    InterpretGenerationRequest as InterpretGenerationUseCase,
)
from platform5e.application.use_cases.generation.start_generation_request import (
    StartGenerationCommand,
)
from platform5e.application.use_cases.generation.start_generation_request import (
    StartGenerationRequest as StartGenerationUseCase,
)
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_request import (
    IDEMPOTENCY_KEY_PATTERN,
    GenerationMode,
    GenerationRequest,
    GenerationStep as DomainStep,
    Problem as DomainProblem,
)
from platform5e.infrastructure.http.dependencies import current_teacher_dependency
from platform5e.infrastructure.http.error_handlers import error_json
from platform5e.infrastructure.http.schemas.common import error_responses
from platform5e.infrastructure.http.schemas.generation_requests import (
    GenerationEvidence,
    GenerationInterpretation,
    GenerationRequestStatus,
    GenerationRequestSummary,
    InterpretGenerationRequest,
    StartGenerationRequest,
)
from platform5e.infrastructure.http.schemas.generations import GeneratorInfo

BASE_PATH = "/api/v1/generation-requests"
RETRY_AFTER_SECONDS = 30
IDEMPOTENCY_KEY_DESCRIPTION = (
    "Stable client key, unique per teacher: 8 to 128 letters, digits, `-` or `_`. Reuse it when retrying the same "
    "request. Without it the API answers 400 IDEMPOTENCY_KEY_REQUIRED; with another format, 422 INVALID_PARAMETERS."
)

# Estado HTTP de cada código de GenerationError; los demás responden 400.
ERROR_STATUS: dict[str, int] = {
    GenerationErrorCode.UNIT_NOT_FOUND: 404,
    GenerationErrorCode.GENERATION_REQUEST_NOT_FOUND: 404,
    GenerationErrorCode.IDEMPOTENCY_KEY_REUSED: 409,
    GenerationErrorCode.INVALID_PARAMETERS: 422,
    GenerationErrorCode.RESOURCE_TYPE_NOT_IN_MODALITY: 422,
    GenerationErrorCode.TOO_MANY_ACTIVE_REQUESTS: 429,
    GenerationErrorCode.EVIDENCE_UNAVAILABLE: 503,
    # Regeneración: hoy solo llegan por la ruta de Revisión, que decide su propio estado; aquí quedan coherentes.
    GenerationErrorCode.REGENERATION_PARAMETERS_MISSING: 422,
    GenerationErrorCode.REGENERATION_TARGET_INVALID: 422,
    GenerationErrorCode.REGENERATION_ATTEMPTS_EXHAUSTED: 409,
}


def generation_error_response(error: GenerationError) -> JSONResponse:
    """Traduce un error del pedido de generación al JSON común, con el estado del contrato."""
    status_code = ERROR_STATUS.get(error.code, 400)
    response = error_json(status_code, str(error.code), error.message)
    if status_code == 429:
        response.headers["Retry-After"] = str(RETRY_AFTER_SECONDS)
    return response


def _problem(problem: DomainProblem | None) -> dict[str, str] | None:
    return None if problem is None else {"code": str(problem.code), "message": problem.message}


def summary_payload(request: GenerationRequest) -> dict[str, Any]:
    return {
        "id": request.id,
        "mode": str(request.mode),
        "unitId": request.unit_id,
        "status": str(request.status),
        "resourceTypes": list(request.parameters.resource_types),
        "createdAt": request.created_at,
        "finishedAt": request.finished_at,
    }


def _step_payload(step: DomainStep, view: GenerationRequestView | None) -> dict[str, Any]:
    resources = view.resources_by_step.get(step.position, ()) if view is not None else ()
    return {
        "position": step.position,
        "stage": step.stage,
        "resourceType": step.resource_type,
        "agent": step.agent,
        "status": str(step.status),
        "resourceIds": list(step.resource_ids),
        "resources": [
            {"id": r.id, "title": r.title, "verificationStatus": r.verification_status} for r in resources
        ],
        "rejections": [
            {"title": r["title"], "reason": r["reason"], "kind": r.get("kind", "grounding")} for r in step.rejections
        ],
        "generator": step.generator,
        "grounding": step.grounding,
        "distractorReliability": step.distractor_reliability,
        "error": _problem(step.error),
        "startedAt": step.started_at,
        "finishedAt": step.finished_at,
    }


def status_payload(request: GenerationRequest, view: GenerationRequestView | None = None) -> dict[str, Any]:
    """El pedido en la forma de `GenerationRequestStatus` (camelCase)."""
    parameters = request.parameters.to_payload()
    # La respuesta conserva la forma del cuerpo (research R11): una lista de 0 o 1 modalidad.
    modality = parameters.pop("modality")
    parameters["modalities"] = [modality] if modality else []
    return {
        **summary_payload(request),
        "parameters": parameters,
        "retrievalMode": request.retrieval_mode,
        "regeneration": request.regeneration.to_payload() if request.regeneration else None,
        "failure": _problem(request.failure),
        "startedAt": request.started_at,
        "steps": [_step_payload(step, view) for step in request.steps],
    }


def _validated(payload: dict[str, Any]) -> dict[str, Any]:
    return GenerationRequestStatus.model_validate(payload).model_dump(by_alias=True, mode="json")


def create_generation_interpretation_router(
    interpreter: InterpretGenerationUseCase,
    account_service: AccountService,
) -> APIRouter:
    router = APIRouter()
    current_teacher = current_teacher_dependency(account_service)

    @router.post(
        f"{BASE_PATH}/interpret",
        tags=["generations"],
        operation_id="interpretGenerationRequest",
        summary="Interpret a generation request",
        response_model=GenerationInterpretation,
        response_model_exclude_unset=True,
        responses=error_responses(401, 404, 422),
    )
    def interpret_generation_request(
        body: InterpretGenerationRequest,
        teacher_id: str = Depends(current_teacher),
    ) -> GenerationInterpretation | JSONResponse:
        command = InterpretGenerationCommand(
            teacher_id=teacher_id,
            unit_id=body.unit_id,
            message=body.message,
        )
        try:
            result = interpreter.execute(command)
        except GenerationError as error:
            return generation_error_response(error)
        return GenerationInterpretation.model_validate(result)

    return router


def create_generation_requests_router(
    start_generation: StartGenerationUseCase,
    get_generation: GetGenerationRequest,
    account_service: AccountService,
    generator_info: dict[str, Any],
    get_evidence: GetGenerationEvidence,
) -> APIRouter:
    router = APIRouter()
    current_teacher = current_teacher_dependency(account_service)

    start_responses: dict[int | str, dict[str, Any]] = {
        **error_responses(400, 401, 404, 409, 422, 429, 503),
        202: {
            "description": "Request accepted and queued.",
            "headers": {"Location": {"schema": {"type": "string"}, "description": "URL of the request status."}},
        },
        200: {
            "model": GenerationRequestStatus,
            "description": "Same key and same body. The request already exists and is returned in its current state.",
        },
    }
    start_responses[429]["headers"] = {
        "Retry-After": {"schema": {"type": "integer"}, "description": "Suggested seconds before retrying."}
    }

    @router.post(
        BASE_PATH,
        tags=["generations"],
        status_code=status.HTTP_202_ACCEPTED,
        response_model=GenerationRequestStatus,
        summary="Start a generation request",
        responses=start_responses,
    )
    def start_generation_request(
        body: StartGenerationRequest,
        # Opcional en el esquema para responder 400 IDEMPOTENCY_KEY_REQUIRED (no 422) si falta; el patrón da 422.
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
            pattern=IDEMPOTENCY_KEY_PATTERN.pattern,
            description=IDEMPOTENCY_KEY_DESCRIPTION,
            examples=["3f6c2a1e-8b4d-4d7a-9a51-0c2f8e1b7d10"],
        ),
        teacher_id: str = Depends(current_teacher),
    ) -> Any:
        """Validates the unit ownership, the outcome and that the unit has processed material, saves the request
        and runs it in the background (202 with `Location`). Poll `GET /generation-requests/{requestId}` for the
        status of each step.

        The client sends a stable `Idempotency-Key`, unique per teacher. Repeating the same key with the same body
        (mode, unit and parameters) returns the existing request (200) without applying the other rules again;
        using it with a different body returns 409 IDEMPOTENCY_KEY_REUSED. Without processed material the request
        is rejected (400 NO_PROCESSED_MATERIAL), and a teacher with 2 active requests gets 429 with `Retry-After`.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X POST "$BASE_URL/api/v1/generation-requests" -H "Authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen)" -H 'Content-Type: application/json' --data '{"mode":"sequence","unitId":"unidad-1","resourceTypes":["pregunta_detonante","item_opcion_multiple"],"quantity":1}'
        ```

        Replace unidad-1 with a unit containing processed material. Expected 202; repeat with the same key to get 200."""
        command = StartGenerationCommand(
            teacher_id=teacher_id,
            unit_id=body.unit_id,
            mode=GenerationMode(body.mode),
            idempotency_key=idempotency_key,
            parameters=body.to_parameters(),
        )
        try:
            result = start_generation.execute(command)
        except GenerationError as error:
            return generation_error_response(error)
        payload = _validated(status_payload(result.request))
        if not result.created:
            return JSONResponse(status_code=status.HTTP_200_OK, content=payload)
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=payload,
            headers={"Location": f"{BASE_PATH}/{result.request.id}"},
        )

    @router.get(
        BASE_PATH,
        tags=["generations"],
        response_model=list[GenerationRequestSummary],
        summary="List my generation requests of a unit",
        responses=error_responses(401, 404, 422),
    )
    def list_generation_requests(
        unit_id: str = Query(alias="unitId", description="Unit of the teacher."),
        active: bool = Query(default=False, description="Only `queued` or `running` requests."),
        limit: int = Query(default=20, ge=1, le=50),
        teacher_id: str = Depends(current_teacher),
    ) -> Any:
        """Requests of the teacher in the unit, newest first. Used to recover a request after reloading when the
        client lost its id. A unit of another teacher answers 404 UNIT_NOT_FOUND, the same as a missing one.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/api/v1/generation-requests?unitId=unidad-1&active=true" -H "Authorization: Bearer $TOKEN"
        ```

        Replace unidad-1 with one of your units. Expected 200. See the response schema below for the returned fields."""
        try:
            requests = get_generation.list(teacher_id, unit_id, active, limit)
        except GenerationError as error:
            return generation_error_response(error)
        return [summary_payload(request) for request in requests]

    @router.get(
        f"{BASE_PATH}/{{request_id}}",
        tags=["generations"],
        response_model=GenerationRequestStatus,
        summary="Get the status of a generation request",
        responses=error_responses(401, 404),
    )
    def get_generation_request(request_id: str, teacher_id: str = Depends(current_teacher)) -> Any:
        """Returns the status of the request and of each step, in 5E order, as confirmed by the server: delivered
        resources, rejections with their reason, generator and fallback flags. Requests of other teachers answer
        404 GENERATION_REQUEST_NOT_FOUND, the same as missing ones.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/api/v1/generation-requests/${REQUEST_ID}" -H "Authorization: Bearer $TOKEN"
        ```

        Expected 200. Poll until `status` is `succeeded`, `partially_succeeded`, `failed` or `interrupted`."""
        try:
            view = get_generation.get(teacher_id, request_id)
        except GenerationError as error:
            return generation_error_response(error)
        return status_payload(view.request, view)

    @router.get(
        f"{BASE_PATH}/{{request_id}}/evidence",
        tags=["generations"],
        response_model=GenerationEvidence,
        summary="Get the evidence retrieved by a generation request",
        responses=error_responses(401, 404),
    )
    def get_generation_evidence(request_id: str, teacher_id: str = Depends(current_teacher)) -> Any:
        """Every chunk the request retrieved from the material and gave to the model, in retrieval order, not only
        the ones its resources cite. The Ragas evaluation uses it as the retrieved context (TA-010). A queued request
        answers 200 with no fragments. Requests of other teachers answer 404 GENERATION_REQUEST_NOT_FOUND, the same
        as missing ones.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/api/v1/generation-requests/${REQUEST_ID}/evidence" -H "Authorization: Bearer $TOKEN"
        ```

        Expected 200. See the response schema below for the returned fields."""
        try:
            evidence = get_evidence.execute(teacher_id, request_id)
        except GenerationError as error:
            return generation_error_response(error)
        return {
            "requestId": evidence.request_id,
            "retrievalMode": evidence.retrieval_mode,
            "limit": evidence.limit,
            "retrievedAt": evidence.retrieved_at,
            "fragments": list(evidence.fragments),
        }

    @router.get(
        "/api/v1/generator",
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
