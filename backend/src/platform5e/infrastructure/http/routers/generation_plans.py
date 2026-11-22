"""
Adaptador HTTP del plan de generación (GEN-P1): crear, listar, leer, editar y aprobar.
Contrato: specs/006-plan-de-generacion/contracts/generation-plans.openapi.yaml.

`validation` y `doesNotCover` se calculan en cada respuesta. Un plan ajeno responde igual que uno inexistente.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query, status
from fastapi.responses import JSONResponse

from platform5e.application.services.accounts.account_service import AccountService
from platform5e.application.use_cases.generation.approve_generation_plan import ApproveGenerationPlan as ApproveUseCase
from platform5e.application.use_cases.generation.create_generation_plan import (
    CreateGenerationPlan as CreateUseCase,
    CreatePlanCommand,
)
from platform5e.application.use_cases.generation.get_generation_plan import GetGenerationPlan, PlanView
from platform5e.application.use_cases.generation.update_generation_plan import (
    EditedItem,
    UpdateGenerationPlan as UpdateUseCase,
)
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_plan import PlanInvalid, PlanStatus
from platform5e.domain.generation.generation_request import IDEMPOTENCY_KEY_PATTERN
from platform5e.domain.generation.plan_validation import does_not_cover
from platform5e.infrastructure.http.dependencies import current_teacher_dependency
from platform5e.infrastructure.http.error_handlers import error_json
from platform5e.infrastructure.http.schemas.common import ERROR_DESCRIPTIONS, ErrorResponse, error_responses
from platform5e.infrastructure.http.schemas.generation_plans import (
    ApproveGenerationPlan,
    CreateGenerationPlan,
    GenerationPlan,
    PlanStatus as PlanStatusField,
    UpdateGenerationPlan,
)

BASE_PATH = "/api/v1/generation-plans"
TAG = "generation-plans"
IDEMPOTENCY_KEY_DESCRIPTION = (
    "Stable client key, unique per teacher: 8 to 128 letters, digits, `-` or `_`, as in GEN-01. Reuse it when "
    "retrying the same plan. Without it the API answers 400 IDEMPOTENCY_KEY_REQUIRED."
)

# Estado HTTP de cada código de GenerationError; los demás responden 400.
ERROR_STATUS: dict[str, int] = {
    GenerationErrorCode.UNIT_NOT_FOUND: 404,
    GenerationErrorCode.PLAN_NOT_FOUND: 404,
    GenerationErrorCode.IDEMPOTENCY_KEY_REUSED: 409,
    GenerationErrorCode.PLAN_VERSION_CONFLICT: 409,
    GenerationErrorCode.PLAN_ALREADY_USED: 409,
    GenerationErrorCode.INVALID_PARAMETERS: 422,
    GenerationErrorCode.RESOURCE_TYPE_NOT_IN_MODALITY: 422,
    GenerationErrorCode.INSUFFICIENT_EVIDENCE: 422,
    GenerationErrorCode.PLAN_INVALID: 422,
    GenerationErrorCode.EVIDENCE_UNAVAILABLE: 503,
}


def plan_error_response(error: GenerationError) -> JSONResponse:
    """Traduce un error del plan al JSON común. PLAN_INVALID lleva cada problema en `details`."""
    details = [problem.to_payload() for problem in error.problems] if isinstance(error, PlanInvalid) else None
    return error_json(ERROR_STATUS.get(error.code, 400), str(error.code), error.message, details)


def plan_payload(view: PlanView) -> dict[str, Any]:
    """El plan en la forma de `GenerationPlan` (camelCase), con `doesNotCover` y `validation` calculados."""
    plan = view.plan
    return {
        "id": plan.id,
        "version": plan.version,
        "status": str(plan.status),
        "origin": plan.origin,
        "unitId": plan.unit_id,
        "inputs": plan.inputs.to_payload(),
        "evidence": plan.evidence.to_payload(),
        "referents": [referent.to_payload() for referent in plan.referents],
        "sessionContext": plan.session_context.to_payload(),
        "items": [
            {**item.to_payload(), "doesNotCover": does_not_cover(plan.items, item.position)} for item in plan.items
        ],
        "validation": {"valid": not view.problems, "problems": [p.to_payload() for p in view.problems]},
        "warnings": list(plan.warnings),
        "generator": dict(plan.generator),
        "usedByRequestId": plan.used_by_request_id,
        "createdAt": plan.created_at,
        "updatedAt": plan.updated_at,
        "approvedAt": plan.approved_at,
        "usedAt": plan.used_at,
    }


def _validated(view: PlanView) -> dict[str, Any]:
    return GenerationPlan.model_validate(plan_payload(view)).model_dump(by_alias=True, mode="json")


def create_generation_plans_router(
    create_plan: CreateUseCase,
    get_plan: GetGenerationPlan,
    update_plan: UpdateUseCase,
    approve_plan: ApproveUseCase,
    account_service: AccountService,
) -> APIRouter:
    router = APIRouter()
    current_teacher = current_teacher_dependency(account_service)

    create_responses: dict[int | str, dict[str, Any]] = {
        **error_responses(400, 401, 404, 409, 422, 429, 503),
        201: {"model": GenerationPlan, "description": "Plan created in `draft`."},
        200: {"model": GenerationPlan,
              "description": "The same key and body were already used; the existing plan is returned."},
    }
    create_responses[400]["description"] = "`NO_PROCESSED_MATERIAL`, `INVALID_OUTCOME` or `IDEMPOTENCY_KEY_REQUIRED`."
    create_responses[404]["description"] = "`UNIT_NOT_FOUND`: missing or belongs to another teacher."
    create_responses[409]["description"] = (
        "`IDEMPOTENCY_KEY_REUSED`: the key was already used by this teacher with a different body."
    )
    create_responses[422]["description"] = (
        "`INVALID_PARAMETERS` (type, range, unknown or repeated type), `RESOURCE_TYPE_NOT_IN_MODALITY`, or "
        "`INSUFFICIENT_EVIDENCE`: the unit material does not cover the topic of the instructions; the message names "
        "what is missing. No plan is created."
    )
    create_responses[429] = {
        "model": ErrorResponse,
        "description": "Per-IP limit of costly routes, with `Retry-After`.",
        "headers": {"Retry-After": {"schema": {"type": "integer"}, "description": "Seconds before retrying."}},
    }
    plan_not_found = {"model": ErrorResponse,
                      "description": "`PLAN_NOT_FOUND`: missing or belongs to another teacher. Both answers are "
                                     "identical."}
    plan_conflict = {"model": ErrorResponse,
                     "description": "`PLAN_VERSION_CONFLICT`: `expectedVersion` is not the current version. "
                                    "`PLAN_ALREADY_USED`: the plan already started a generation request."}

    @router.post(
        BASE_PATH,
        tags=[TAG],
        operation_id="createGenerationPlan",
        status_code=status.HTTP_201_CREATED,
        response_model=GenerationPlan,
        summary="Create a generation plan (synchronous)",
        responses=create_responses,
    )
    def create_generation_plan(
        body: CreateGenerationPlan,
        # Opcional en el esquema para responder 400 IDEMPOTENCY_KEY_REQUIRED (no 422) si falta.
        idempotency_key: str | None = Header(
            default=None,
            alias="Idempotency-Key",
            pattern=IDEMPOTENCY_KEY_PATTERN.pattern,
            description=IDEMPOTENCY_KEY_DESCRIPTION,
            examples=["3f6c2a1e-8b4d-4d7a-9a51-0c2f8e1b7d10"],
        ),
        teacher_id: str = Depends(current_teacher),
    ) -> Any:
        """Retrieves the unit evidence once and freezes it in the plan, adds the referents and the previous
        typologies, drafts the plan with one AI call (within the per-call deadline) or with the rule-based planner,
        and validates it. If the AI fails, times out or returns an invalid plan, the rule-based planner drafts it and
        `generator.fallbackReason` says why. The plan is saved in `draft` even with problems; see `validation`.

        Same `Idempotency-Key` with the same body returns the existing plan (200); with another body, 409.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X POST "$BASE_URL/api/v1/generation-plans" -H "Authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen)" -H 'Content-Type: application/json' --data '{"unitId":"unidad-1","instructions":"Diferencias entre TCP y UDP","resourceTypes":[{"type":"pregunta_detonante","quantity":1},{"type":"explicacion"}]}'
        ```

        Replace unidad-1 with a unit containing processed material. Expected 201; repeat with the same key to get
        200."""
        command = CreatePlanCommand(
            teacher_id=teacher_id, unit_id=body.unit_id, idempotency_key=idempotency_key, inputs=body.to_inputs()
        )
        try:
            result = create_plan.execute(command)
        except GenerationError as error:
            return plan_error_response(error)
        payload = _validated(result.view)
        if not result.created:
            return JSONResponse(status_code=status.HTTP_200_OK, content=payload)
        return JSONResponse(status_code=status.HTTP_201_CREATED, content=payload,
                            headers={"Location": f"{BASE_PATH}/{result.view.plan.id}"})

    @router.get(
        BASE_PATH,
        tags=[TAG],
        operation_id="listGenerationPlans",
        response_model=list[GenerationPlan],
        summary="List the teacher's plans of a unit",
        responses={**error_responses(401, 422),
                   404: {"model": ErrorResponse, "description": "`UNIT_NOT_FOUND`: missing or another teacher's."}},
    )
    def list_generation_plans(
        unit_id: str = Query(alias="unitId", description="Unit of the teacher."),
        plan_status: PlanStatusField | None = Query(default=None, alias="status", description="Only this status."),
        limit: int = Query(default=5, ge=1, le=20),
        teacher_id: str = Depends(current_teacher),
    ) -> Any:
        """Plans of the teacher in the unit, most recently updated first (empty list if none). Used to recover the
        last plan after a reload. A unit of another teacher answers 404 UNIT_NOT_FOUND, the same as a missing one.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/api/v1/generation-plans?unitId=unidad-1&status=draft" -H "Authorization: Bearer $TOKEN"
        ```

        Replace unidad-1 with one of your units. Expected 200."""
        try:
            views = get_plan.list(teacher_id, unit_id, PlanStatus(plan_status) if plan_status else None, limit)
        except GenerationError as error:
            return plan_error_response(error)
        return [_validated(view) for view in views]

    @router.get(
        f"{BASE_PATH}/{{plan_id}}",
        tags=[TAG],
        operation_id="getGenerationPlan",
        response_model=GenerationPlan,
        summary="Get a plan",
        responses={**error_responses(401), 404: plan_not_found},
    )
    def get_generation_plan(plan_id: str, teacher_id: str = Depends(current_teacher)) -> Any:
        """Returns the plan, with `validation` and `doesNotCover` computed on read. Plans of other teachers answer
        404 PLAN_NOT_FOUND, the same as missing ones.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/api/v1/generation-plans/${PLAN_ID}" -H "Authorization: Bearer $TOKEN"
        ```

        Expected 200."""
        try:
            view = get_plan.get(teacher_id, plan_id)
        except GenerationError as error:
            return plan_error_response(error)
        return _validated(view)

    @router.put(
        f"{BASE_PATH}/{{plan_id}}",
        tags=[TAG],
        operation_id="updateGenerationPlan",
        response_model=GenerationPlan,
        summary="Save the teacher's edits",
        responses={**error_responses(401, 422), 404: plan_not_found, 409: plan_conflict},
    )
    def update_generation_plan(
        plan_id: str, body: UpdateGenerationPlan, teacher_id: str = Depends(current_teacher)
    ) -> Any:
        """Replaces the items. The stage of each item comes from the catalog and `doesNotCover` is computed. The
        plan goes back to `draft` and its `version` increases. An invalid plan is saved anyway, with its problems in
        `validation`, so the teacher does not lose work; it cannot be approved until it is valid. `inputs` and
        `evidence` do not change: to change the topic or the types, create a new plan. A type that is not in the
        catalog answers 422 INVALID_PARAMETERS.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X PUT "$BASE_URL/api/v1/generation-plans/${PLAN_ID}" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' --data '{"expectedVersion":1,"items":[{"resourceType":"explicacion","quantity":1,"purpose":"Explicar TCP","covers":["control de flujo"],"fragmentIds":["frag-1"]}]}'
        ```

        Expected 200. Check `validation`."""
        items = [EditedItem(i.resource_type, i.quantity, i.purpose, i.covers, i.fragment_ids) for i in body.items]
        try:
            view = update_plan.execute(teacher_id, plan_id, body.expected_version, items)
        except GenerationError as error:
            return plan_error_response(error)
        return _validated(view)

    @router.post(
        f"{BASE_PATH}/{{plan_id}}/approve",
        tags=[TAG],
        operation_id="approveGenerationPlan",
        response_model=GenerationPlan,
        summary="Approve a valid plan",
        responses={
            **error_responses(401), 404: plan_not_found, 409: plan_conflict,
            422: {"model": ErrorResponse, "description": "`PLAN_INVALID`: `details` lists every `PlanProblem`. "
                                                         + ERROR_DESCRIPTIONS[422]},
        },
    )
    def approve_generation_plan(
        plan_id: str, body: ApproveGenerationPlan, teacher_id: str = Depends(current_teacher)
    ) -> Any:
        """Approves the plan in its current version if it has no problems; the version does not change. Approving
        an already approved plan with its current version returns it unchanged. Generation (next step) always starts
        from an approved plan.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X POST "$BASE_URL/api/v1/generation-plans/${PLAN_ID}/approve" -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' --data '{"expectedVersion":1}'
        ```

        Expected 200 with `status: approved`, or 422 PLAN_INVALID with the problems in `details`."""
        try:
            view = approve_plan.execute(teacher_id, plan_id, body.expected_version)
        except GenerationError as error:
            return plan_error_response(error)
        return _validated(view)

    return router
