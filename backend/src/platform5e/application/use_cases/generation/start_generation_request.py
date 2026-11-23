"""
Caso de uso GEN-01 (T015): inicia un pedido de generación individual o de secuencia en segundo plano.

Valida la clave y la unidad; si la clave ya tiene un pedido, lo devuelve (o informa el conflicto) sin aplicar las demás
reglas. Si no, valida el resultado de aprendizaje, el plan de pasos y el material; el repositorio comprueba el límite de
pedidos activos y guarda el pedido de forma atómica, y el caso de uso lo encola. Solo depende de puertos y del dominio.

GEN-P2 (specs/006-plan-de-generacion, research R2):
- `execute_planned` inicia el pedido desde un plan aprobado (`{planId, planVersion}`): un paso por ítem, el modo que
  sale del plan y la evidencia vigente (si falta un fragmento citado, `409 PLAN_EVIDENCE_STALE` con cada documento).
  El plan pasa a usado en la misma transacción que el alta del pedido.
- El cuerpo anterior crea un plan implícito aprobado y genera desde él, si hay con qué armarlo (`implicit_plans`).
  Sin `implicit_plans` (GENERATION_IMPLICIT_PLAN=false, solo para medir la línea base de P4) se redacta como antes de
  GEN-P1. Con `require_plan` (GENERATION_REQUIRE_PLAN=true) se rechaza con `422 PLAN_REQUIRED`, antes que todo lo
  demás: tiene prioridad sobre el interruptor del plan implícito.
- La regeneración de un recurso que nació de un plan lee su ítem sin escribir el plan y comprueba la evidencia vigente
  de los fragmentos de ese ítem. Sin colaboradores del plan, el caso de uso funciona como en GEN-01.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from platform5e.application.ports.outbound.evidence_provider_port import (
    EvidenceProviderPort,
    NoProcessedMaterial,
)
from platform5e.application.ports.outbound.generation_job_runner_port import GenerationJobRunnerPort
from platform5e.application.ports.outbound.generation_plan_repository_port import GenerationPlanRepositoryPort
from platform5e.application.ports.outbound.generation_request_repository_port import (
    ActiveRequestLimitReached,
    GenerationRequestRepositoryPort,
    IdempotencyKeyTaken,
    PlanClaim,
    PlanClaimLost,
    UnitNoLongerOwned,
)
from platform5e.application.ports.outbound.session_typology_port import SessionTypologyPort
from platform5e.application.ports.outbound.unit_membership_port import UnitMembershipPort
from platform5e.application.use_cases.generation.create_generation_plan import CreatePlanCommand
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_plan import (
    ALREADY_USED_MESSAGE,
    NOT_APPROVED_MESSAGE,
    VERSION_CONFLICT_MESSAGE,
    GenerationPlan,
    PlanInputs,
    PlanStatus,
    RequestedType,
    mark_plan_used,
)
from platform5e.domain.generation.generation_request import (
    GenerationMode,
    GenerationParameters,
    GenerationRequest,
    GenerationStep,
    PlanReference,
    RegenerationTarget,
    payload_hash,
    validate_idempotency_key,
)
from platform5e.domain.generation.planned_request import (
    PLAN_REQUIRED_MESSAGE,
    PlanEvidenceStale,
    plan_fragment_ids,
    plan_mode,
    plan_parameters_quantity,
    planned_steps,
    stale_documents,
)
from platform5e.domain.generation.resource_catalog import RESOURCE_TYPES
from platform5e.domain.generation.resource_formats import types_outside_modality
from platform5e.domain.generation.sequence import PlannedStep, SequenceError, plan_steps

logger = logging.getLogger("platform5e.generation.start")

MAX_ACTIVE_REQUESTS: int = 2
UNIT_NOT_FOUND_MESSAGE: str = "La unidad no existe o no pertenece a tus cursos."
INVALID_OUTCOME_MESSAGE: str = "El resultado de aprendizaje no pertenece a la unidad."
KEY_REUSED_MESSAGE: str = (
    "Ya usaste esta clave para un pedido con otros datos. Recarga la página y vuelve a enviar el pedido."
)
TOO_MANY_ACTIVE_MESSAGE: str = (
    f"Ya tienes {MAX_ACTIVE_REQUESTS} pedidos de generación en curso. Espera a que termine alguno y vuelve a "
    "intentarlo."
)


TYPE_NAMES: dict[str, str] = {entry.id: entry.name for entry in RESOURCE_TYPES}
PLAN_NOT_FOUND_MESSAGE: str = "El plan no existe."
PLAN_ITEM_MISSING_MESSAGE: str = "El recurso no se puede regenerar desde su plan: el ítem ya no está en el plan."
IMPLICIT_KEY_PREFIX: str = "implicit-"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _outside_modality_message(modality: str, outside: list[str]) -> str:
    names = ", ".join(TYPE_NAMES.get(resource_type, resource_type) for resource_type in outside)
    return (
        f"Estos tipos de recurso no pertenecen a la modalidad {modality}: {names}. "
        "Quítalos o elige otra modalidad."
    )


@dataclass(frozen=True)
class PlannedRegeneration:
    """GEN-P2: el ítem del plan del que nació el recurso que se regenera (`params.planId`, `params.planItemPosition`)."""

    plan_id: str
    item_position: int


@dataclass(frozen=True)
class StartGenerationCommand:
    teacher_id: str
    unit_id: str
    mode: GenerationMode
    idempotency_key: str | None
    parameters: GenerationParameters
    regeneration: RegenerationTarget | None = None
    planned_regeneration: PlannedRegeneration | None = None


@dataclass(frozen=True)
class StartPlannedGenerationCommand:
    """GEN-P2: cuerpo `{planId, planVersion}` de POST /generation-requests."""

    teacher_id: str
    plan_id: str
    plan_version: int
    idempotency_key: str | None


class ImplicitPlanCreator(Protocol):
    """Arma y aprueba el plan implícito de un pedido sin plan (CreateGenerationPlan.create_implicit)."""

    def create_implicit(self, command: CreatePlanCommand) -> GenerationPlan: ...


def implicit_plan_key(request_key: str) -> str:
    """La clave del plan implícito: sale de la del pedido, así repetir el envío reutiliza el mismo plan."""
    return IMPLICIT_KEY_PREFIX + hashlib.sha256(request_key.encode("utf-8")).hexdigest()[:48]


@dataclass(frozen=True)
class StartGenerationResult:
    """`created` es False cuando la clave ya tenía un pedido con el mismo contenido (se devuelve ese pedido)."""

    request: GenerationRequest
    created: bool


class StartGenerationRequest:
    """Inicia un pedido (GEN-R1, GEN-R3, GEN-R5)."""

    def __init__(
        self,
        membership: UnitMembershipPort,
        evidence: EvidenceProviderPort,
        repository: GenerationRequestRepositoryPort,
        runner: GenerationJobRunnerPort,
        clock: Callable[[], str] = _utc_now,
        new_id: Callable[[], str] = lambda: f"gen-req-{uuid4()}",
        plans: GenerationPlanRepositoryPort | None = None,
        implicit_plans: ImplicitPlanCreator | None = None,
        require_plan: bool = False,
        typologies: SessionTypologyPort | None = None,
    ) -> None:
        self._membership = membership
        self._evidence = evidence
        self._repository = repository
        self._runner = runner
        self._clock = clock
        self._new_id = new_id
        self._plans = plans
        self._implicit_plans = implicit_plans
        self._require_plan = require_plan
        self._typologies = typologies

    def execute(self, command: StartGenerationCommand) -> StartGenerationResult:
        # 1. Clave del pedido.
        key = validate_idempotency_key(command.idempotency_key)
        # GEN-P2: sin plan, el cuerpo anterior solo se acepta mientras GENERATION_REQUIRE_PLAN=false. La regeneración
        # no es un pedido del docente: rehace un recurso con sus datos guardados.
        if self._require_plan and command.mode != GenerationMode.REGENERATION:
            raise GenerationError(GenerationErrorCode.PLAN_REQUIRED, PLAN_REQUIRED_MESSAGE)

        # 2. Pertenencia: una unidad ajena y una inexistente dan la misma respuesta.
        unit = self._membership.get_unit_context(command.teacher_id, command.unit_id)
        if unit is None:
            raise GenerationError(GenerationErrorCode.UNIT_NOT_FOUND, UNIT_NOT_FOUND_MESSAGE)

        # 3. Misma clave: mismo contenido → el pedido existente; otro contenido → conflicto (GEN-C4, GEN-C5).
        #    Un pedido ya aceptado se devuelve sin aplicar las demás reglas, aunque la unidad haya cambiado después.
        content_hash = payload_hash(command.mode, command.unit_id, command.parameters, command.regeneration)
        existing = self._repository.find_by_key(command.teacher_id, key)
        if existing is not None:
            return self._replay(existing, content_hash)

        # 4. Resultado de aprendizaje de la unidad.
        outcome_id = command.parameters.outcome_id
        if outcome_id and outcome_id not in {outcome.id for outcome in unit.outcomes}:
            raise GenerationError(GenerationErrorCode.INVALID_OUTCOME, INVALID_OUTCOME_MESSAGE)

        # 5. Plan de pasos en orden 5E. La regeneración desde un plan (GEN-P2) toma su paso del ítem del plan, que
        #    puede ser un tipo nuevo del catálogo de Cursos (CUR-P2).
        from_plan_item = command.planned_regeneration is not None and self._plans is not None
        try:
            planned = [] if from_plan_item else plan_steps(
                command.mode, list(command.parameters.resource_types), command.parameters.quantity
            )
        except SequenceError as error:
            raise GenerationError(GenerationErrorCode.INVALID_SEQUENCE, str(error)) from error

        # 5b. HU-024: con modalidad, todos los tipos deben pertenecer a ella. La regeneración no la comprueba: rehace un
        #     recurso que ya existe, con su propio tipo (research R11).
        modality = command.parameters.modality
        if modality is not None and command.mode != GenerationMode.REGENERATION:
            outside = types_outside_modality(modality, command.parameters.resource_types)
            if outside:
                raise GenerationError(
                    GenerationErrorCode.RESOURCE_TYPE_NOT_IN_MODALITY, _outside_modality_message(modality, outside)
                )

        # 6. Sin material procesado no se crea el pedido (GEN-C6).
        if not self._evidence.has_processed_material(command.teacher_id, command.unit_id):
            raise NoProcessedMaterial()

        # GEN-P2: la regeneración de un recurso que nació de un plan lee su ítem; el cuerpo anterior crea un plan
        # implícito y genera desde él (research R2).
        if from_plan_item:
            return self._start_planned_regeneration(command, key, content_hash)
        if command.mode != GenerationMode.REGENERATION and self._implicit_plans is not None:
            return self._start_from_implicit_plan(command, key, content_hash, planned)

        # 7 y 8. Límite de pedidos activos por docente y registro, en una sola operación atómica del repositorio
        #    (research R4): dos envíos simultáneos no pueden superar el límite. Si otro envío con la misma clave ganó
        #    la carrera, se aplica la regla 3. Con el bloqueo del docente tomado se vuelve a comprobar la unidad: si
        #    el curso se borró después del paso 2, el pedido no se guarda (T047).
        request = GenerationRequest(
            id=self._new_id(),
            teacher_id=command.teacher_id,
            unit_id=command.unit_id,
            mode=command.mode,
            idempotency_key=key,
            payload_hash=content_hash,
            # Se guardan los tipos sin repetir y en el orden de la clase; el hash usa el orden recibido.
            parameters=replace(command.parameters, resource_types=tuple(p.resource_type for p in planned)),
            created_at=self._clock(),
            steps=tuple(GenerationStep.from_plan(p) for p in planned),
            regeneration=command.regeneration,
        )
        try:
            created = self._repository.create_within_limit(
                request, MAX_ACTIVE_REQUESTS, unit_still_owned=lambda: self._unit_still_owned(command)
            )
        except IdempotencyKeyTaken as taken:
            return self._replay(taken.existing, content_hash)
        except UnitNoLongerOwned:
            raise GenerationError(GenerationErrorCode.UNIT_NOT_FOUND, UNIT_NOT_FOUND_MESSAGE) from None
        except ActiveRequestLimitReached:
            raise GenerationError(GenerationErrorCode.TOO_MANY_ACTIVE_REQUESTS, TOO_MANY_ACTIVE_MESSAGE) from None
        self._runner.submit(created.id)
        return StartGenerationResult(request=created, created=True)

    # GEN-P2 · Pedido desde el plan

    def execute_planned(self, command: StartPlannedGenerationCommand) -> StartGenerationResult:
        """Inicia el pedido desde un plan aprobado. Mismas reglas de clave, pertenencia y cupo que GEN-01."""
        key = validate_idempotency_key(command.idempotency_key)
        plan = self._read_plan(command.teacher_id, command.plan_id)
        if self._membership.get_unit_context(command.teacher_id, plan.unit_id) is None:
            raise GenerationError(GenerationErrorCode.UNIT_NOT_FOUND, UNIT_NOT_FOUND_MESSAGE)
        mode = plan_mode(plan.items)
        parameters = self._plan_parameters(plan)
        reference = PlanReference(plan.id, command.plan_version)
        content_hash = payload_hash(mode, plan.unit_id, parameters, plan=reference)
        existing = self._repository.find_by_key(command.teacher_id, key)
        if existing is not None:
            return self._replay(existing, content_hash)
        return self._start_from_plan(command.teacher_id, plan, command.plan_version, key, content_hash, mode,
                                     parameters)

    def _start_from_implicit_plan(
        self, command: StartGenerationCommand, key: str, content_hash: str, planned: list[PlannedStep]
    ) -> StartGenerationResult:
        """El cuerpo anterior: arma y aprueba el plan implícito con las mismas entradas y genera desde él. El pedido
        conserva el hash del cuerpo anterior, así el mismo envío devuelve el mismo pedido."""
        parameters = command.parameters
        types = [step.resource_type for step in planned]
        inputs = PlanInputs(
            instructions=parameters.instructions,
            audience=parameters.audience,
            competency=parameters.competency,
            outcome_id=parameters.outcome_id,
            modality=parameters.modality,
            resource_types=tuple(RequestedType(resource_type, parameters.quantity) for resource_type in types),
            difficulty=parameters.difficulty,
            option_count=parameters.option_count,
            evidence_threshold=parameters.evidence_threshold,
            top_k=max(3, min(parameters.top_k, 12)),
        )
        assert self._implicit_plans is not None
        plan = self._implicit_plans.create_implicit(
            CreatePlanCommand(command.teacher_id, command.unit_id, implicit_plan_key(key), inputs)
        )
        stored = replace(parameters, resource_types=tuple(types))
        return self._start_from_plan(command.teacher_id, plan, plan.version, key, content_hash, command.mode, stored)

    def _start_from_plan(
        self,
        teacher_id: str,
        plan: GenerationPlan,
        plan_version: int,
        key: str,
        content_hash: str,
        mode: GenerationMode,
        parameters: GenerationParameters,
    ) -> StartGenerationResult:
        request_id = self._new_id()
        now = self._clock()
        used = mark_plan_used(plan, plan_version, request_id, now)  # PLAN_ALREADY_USED, versión o borrador
        self._check_evidence(teacher_id, plan, plan_fragment_ids(plan.items))
        request = GenerationRequest(
            id=request_id,
            teacher_id=teacher_id,
            unit_id=plan.unit_id,
            mode=mode,
            idempotency_key=key,
            payload_hash=content_hash,
            parameters=parameters,
            created_at=now,
            steps=planned_steps(plan.items),
            plan=PlanReference(plan.id, plan.version),
        )
        result = self._create(request, teacher_id, plan.unit_id, PlanClaim(used, plan_version), plan)
        if result.created:
            self._record_typology(used)
        return result

    def _record_typology(self, used: GenerationPlan) -> None:
        """CUR-P3 (research R9): una sesión se cuenta cuando un plan pasa a usado. Si Cursos falla, el pedido sigue:
        la tipología es contexto para el plan siguiente, no una condición para generar."""
        if self._typologies is None:
            return
        try:
            self._typologies.record_typology(
                used.teacher_id, used.unit_id, used.id, [item.resource_type for item in used.items],
                used.used_at or self._clock(),
            )
        except Exception:
            logger.warning("No se pudo registrar la tipología del plan %s.", used.id, exc_info=True)

    def _start_planned_regeneration(
        self, command: StartGenerationCommand, key: str, content_hash: str
    ) -> StartGenerationResult:
        """Regenera un recurso desde su ítem: lee el plan sin escribirlo (un plan usado no responde
        PLAN_ALREADY_USED) y exige la evidencia vigente de los fragmentos de ese ítem."""
        assert command.planned_regeneration is not None
        plan = self._read_plan(command.teacher_id, command.planned_regeneration.plan_id)
        item = next((i for i in plan.items if i.position == command.planned_regeneration.item_position), None)
        if item is None:
            raise GenerationError(GenerationErrorCode.REGENERATION_PARAMETERS_MISSING, PLAN_ITEM_MISSING_MESSAGE)
        self._check_evidence(command.teacher_id, plan, list(item.fragment_ids))
        [step] = planned_steps((item,))
        request = GenerationRequest(
            id=self._new_id(),
            teacher_id=command.teacher_id,
            unit_id=command.unit_id,
            mode=command.mode,
            idempotency_key=key,
            payload_hash=content_hash,
            parameters=replace(command.parameters, resource_types=(item.resource_type,)),
            created_at=self._clock(),
            steps=(step,),
            regeneration=command.regeneration,
            plan=PlanReference(plan.id, plan.version),
        )
        return self._create(request, command.teacher_id, command.unit_id, None, None)

    def _create(
        self,
        request: GenerationRequest,
        teacher_id: str,
        unit_id: str,
        claim: PlanClaim | None,
        plan: GenerationPlan | None,
    ) -> StartGenerationResult:
        """Alta atómica con cupo (y, con plan, el plan pasa a usado en la misma transacción) y encolado."""
        try:
            created = self._repository.create_within_limit(
                request,
                MAX_ACTIVE_REQUESTS,
                unit_still_owned=lambda: self._membership.get_unit_context(teacher_id, unit_id) is not None,
                plan_claim=claim,
            )
        except IdempotencyKeyTaken as taken:
            return self._replay(taken.existing, request.payload_hash)
        except UnitNoLongerOwned:
            raise GenerationError(GenerationErrorCode.UNIT_NOT_FOUND, UNIT_NOT_FOUND_MESSAGE) from None
        except ActiveRequestLimitReached:
            raise GenerationError(GenerationErrorCode.TOO_MANY_ACTIVE_REQUESTS, TOO_MANY_ACTIVE_MESSAGE) from None
        except PlanClaimLost:
            raise self._lost_claim(teacher_id, plan, claim) from None
        self._runner.submit(created.id)
        return StartGenerationResult(request=created, created=True)

    def _lost_claim(self, teacher_id: str, plan: GenerationPlan | None, claim: PlanClaim | None) -> GenerationError:
        """Por qué el plan no pasó a usado: otro pedido lo usó, se editó o volvió a borrador."""
        current = self._plans.get(teacher_id, plan.id) if self._plans is not None and plan is not None else None
        if current is None:
            return GenerationError(GenerationErrorCode.PLAN_NOT_FOUND, PLAN_NOT_FOUND_MESSAGE)
        if current.status == PlanStatus.USED:
            return GenerationError(GenerationErrorCode.PLAN_ALREADY_USED, ALREADY_USED_MESSAGE)
        if claim is not None and current.version != claim.expected_version:
            return GenerationError(GenerationErrorCode.PLAN_VERSION_CONFLICT, VERSION_CONFLICT_MESSAGE)
        return GenerationError(GenerationErrorCode.PLAN_NOT_APPROVED, NOT_APPROVED_MESSAGE)

    def _read_plan(self, teacher_id: str, plan_id: str) -> GenerationPlan:
        plan = self._plans.get(teacher_id, plan_id) if self._plans is not None else None
        if plan is None:
            raise GenerationError(GenerationErrorCode.PLAN_NOT_FOUND, PLAN_NOT_FOUND_MESSAGE)
        return plan

    def _check_evidence(self, teacher_id: str, plan: GenerationPlan, fragment_ids: list[str]) -> None:
        """Evidencia vigente: cada fragmento citado sigue existiendo en la unidad; si no, PLAN_EVIDENCE_STALE."""
        existing = self._evidence.existing_fragment_ids(teacher_id, plan.unit_id, fragment_ids)
        details = stale_documents(plan.evidence, fragment_ids, set(existing))
        if details:
            raise PlanEvidenceStale(details)

    @staticmethod
    def _plan_parameters(plan: GenerationPlan) -> GenerationParameters:
        """Los parámetros del pedido salen de las entradas del plan; los tipos, de sus ítems."""
        inputs = plan.inputs
        return GenerationParameters(
            resource_types=tuple(item.resource_type for item in plan.items),
            quantity=plan_parameters_quantity(plan.items),
            outcome_id=inputs.outcome_id,
            difficulty=inputs.difficulty,
            option_count=inputs.option_count,
            top_k=inputs.top_k,
            evidence_threshold=inputs.evidence_threshold,
            instructions=inputs.instructions,
            audience=inputs.audience,
            competency=inputs.competency,
            modality=inputs.modality,
        )

    def _unit_still_owned(self, command: StartGenerationCommand) -> bool:
        return self._membership.get_unit_context(command.teacher_id, command.unit_id) is not None

    @staticmethod
    def _replay(existing: GenerationRequest, content_hash: str) -> StartGenerationResult:
        if existing.payload_hash != content_hash:
            raise GenerationError(GenerationErrorCode.IDEMPOTENCY_KEY_REUSED, KEY_REUSED_MESSAGE)
        return StartGenerationResult(request=existing, created=False)
