"""
Caso de uso GEN-P1 (T008): crea el plan de generación de una unidad, de forma síncrona
(specs/006-plan-de-generacion, research R1 y R3; PLAN-C1 a PLAN-C3).

Valida la clave y la unidad; si la clave ya tiene un plan, lo devuelve (o informa el conflicto) sin aplicar las demás
reglas, como GEN-01. Si no, valida los tipos pedidos, recupera la evidencia una sola vez y la congela, comprueba que
trate el tema de las indicaciones (QA-05), pide los referentes, las tipologías anteriores y los conceptos de las unidades anteriores (R11), arma el plan con la IA o
con reglas y lo guarda en borrador, aunque tenga problemas. Solo depende de puertos y del dominio.

GEN-P2 (research R2): `create_implicit` arma con las mismas reglas el plan de un pedido con el cuerpo anterior, sin
intervención del docente: `origin: implicit`, guardado ya aprobado. Si el plan tiene problemas no se aprueba y el
pedido se rechaza con PLAN_INVALID y cada problema.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from uuid import uuid4

from platform5e.application.ports.outbound.evidence_provider_port import (
    EvidenceProviderPort,
    EvidenceQuery,
    NoProcessedMaterial,
)
from platform5e.application.ports.outbound.generation_plan_repository_port import (
    GenerationPlanRepositoryPort,
    PlanKeyTaken,
)
from platform5e.application.ports.outbound.previous_unit_concepts_port import PreviousUnitConceptsPort
from platform5e.application.ports.outbound.referents_port import ReferentsPort
from platform5e.application.ports.outbound.resource_catalog_port import ResourceCatalogPort
from platform5e.application.ports.outbound.session_typology_port import SessionTypologyPort
from platform5e.application.ports.outbound.unit_membership_port import UnitMembershipPort
from platform5e.application.services.generation.plan_drafting import GenerationPlanner
from platform5e.application.services.generation.step_drafting import evidence_query_text
from platform5e.application.services.provider_errors import redact_secrets
from platform5e.application.use_cases.generation.get_generation_plan import PlanView, plan_view, utc_now
from platform5e.application.use_cases.generation.run_generation_request import off_topic_message
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_plan import (
    MAX_ITEM_QUANTITY,
    MAX_PLAN_TYPES,
    MAX_TOP_K,
    MIN_ITEM_QUANTITY,
    MIN_TOP_K,
    GenerationPlan,
    PlanEvidence,
    PlanFragment,
    PlanInputs,
    PlanInvalid,
    PlanStatus,
    Referent,
    SessionContext,
)
from platform5e.domain.generation.generation_request import validate_idempotency_key
from platform5e.domain.generation.topic_coverage import DEFAULT_COVERAGE_THRESHOLD, assess_topic_coverage

logger = logging.getLogger(__name__)

ORIGIN_TEACHER: str = "teacher"
ORIGIN_IMPLICIT: str = "implicit"
SAME_TYPOLOGY_WARNING: str = "SAME_TYPOLOGY_AS_LAST_SESSION"
MAX_PREVIOUS_TYPOLOGIES: int = 3
MAX_PREVIOUS_UNIT_CONCEPTS: int = 30
UNIT_NOT_FOUND_MESSAGE: str = "La unidad no existe o no pertenece a tus cursos."
INVALID_OUTCOME_MESSAGE: str = "El resultado de aprendizaje no pertenece a la unidad."
KEY_REUSED_MESSAGE: str = (
    "Ya usaste esta clave para un plan con otros datos. Recarga la página y vuelve a intentarlo."
)
NO_TYPES_MESSAGE: str = "Elige al menos un tipo de recurso."
TOO_MANY_TYPES_MESSAGE: str = f"Elige hasta {MAX_PLAN_TYPES} tipos de recurso distintos."
UNKNOWN_TYPES_MESSAGE: str = "Estos tipos de recurso no están en el catálogo: {types}."
REPEATED_TYPES_MESSAGE: str = "Cada tipo de recurso va una sola vez; indica la cantidad en ese tipo: {types}."
QUANTITY_MESSAGE: str = f"La cantidad de cada tipo debe estar entre {MIN_ITEM_QUANTITY} y {MAX_ITEM_QUANTITY}."
OUTSIDE_MODALITY_MESSAGE: str = (
    "Estos tipos de recurso no pertenecen a la modalidad {modality}: {names}. Quítalos o elige otra modalidad."
)


def plan_payload_hash(unit_id: str, inputs: PlanInputs) -> str:
    """SHA-256 del JSON canónico de la unidad y las entradas normalizadas: claves ordenadas y sin espacios."""
    canonical = json.dumps({"unitId": unit_id, "inputs": inputs.to_payload()}, sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def within_evidence(referents: tuple[Referent, ...], evidence: PlanEvidence) -> tuple[Referent, ...]:
    """T023 (research R10): deja en cada referente solo los fragmentos de la evidencia congelada del plan, en su
    orden. Un referente que se queda sin ninguno se conserva con la lista vacía: se muestra, pero no se cita. No es
    un problema de validación."""
    frozen = {fragment.id for fragment in evidence.fragments}
    return tuple(
        replace(referent, fragment_ids=tuple(i for i in referent.fragment_ids if i in frozen))
        for referent in referents
    )


@dataclass(frozen=True)
class CreatePlanCommand:
    teacher_id: str
    unit_id: str
    idempotency_key: str | None
    inputs: PlanInputs


@dataclass(frozen=True)
class CreatePlanResult:
    """`created` es False cuando la clave ya tenía un plan con el mismo contenido (se devuelve ese plan)."""

    view: PlanView
    created: bool


class CreateGenerationPlan:
    def __init__(
        self,
        membership: UnitMembershipPort,
        evidence: EvidenceProviderPort,
        referents: ReferentsPort,
        typologies: SessionTypologyPort,
        catalog: ResourceCatalogPort,
        planner: GenerationPlanner,
        repository: GenerationPlanRepositoryPort,
        clock: Callable[[], str] = utc_now,
        new_id: Callable[[], str] = lambda: f"gen-plan-{uuid4()}",
        topic_coverage_threshold: float = DEFAULT_COVERAGE_THRESHOLD,
        previous_units: PreviousUnitConceptsPort | None = None,
    ) -> None:
        self._membership = membership
        self._evidence = evidence
        self._referents = referents
        self._typologies = typologies
        self._catalog = catalog
        self._planner = planner
        self._repository = repository
        self._clock = clock
        self._new_id = new_id
        self._topic_coverage_threshold = topic_coverage_threshold
        self._previous_units = previous_units

    def execute(self, command: CreatePlanCommand) -> CreatePlanResult:
        return self._create(command, ORIGIN_TEACHER)

    def create_implicit(self, command: CreatePlanCommand) -> GenerationPlan:
        """GEN-P2: el plan implícito de un pedido sin plan, ya aprobado. La misma clave devuelve el plan existente."""
        result = self._create(command, ORIGIN_IMPLICIT)
        if not result.created:
            return result.view.plan
        if result.view.problems:
            raise PlanInvalid(result.view.problems)
        return result.view.plan

    def _create(self, command: CreatePlanCommand, origin: str) -> CreatePlanResult:
        # 1. Clave del plan.
        key = validate_idempotency_key(command.idempotency_key)

        # 2. Pertenencia: una unidad ajena y una inexistente dan la misma respuesta.
        unit = self._membership.get_unit_context(command.teacher_id, command.unit_id)
        if unit is None:
            raise GenerationError(GenerationErrorCode.UNIT_NOT_FOUND, UNIT_NOT_FOUND_MESSAGE)

        # 3. Misma clave: mismo contenido → el plan existente; otro contenido → conflicto.
        inputs = command.inputs
        content_hash = plan_payload_hash(command.unit_id, inputs)
        existing = self._repository.find_by_key(command.teacher_id, key)
        if existing is not None:
            return self._replay(existing, content_hash)

        # 4. Resultado de aprendizaje y tipos pedidos.
        if inputs.outcome_id and inputs.outcome_id not in {outcome.id for outcome in unit.outcomes}:
            raise GenerationError(GenerationErrorCode.INVALID_OUTCOME, INVALID_OUTCOME_MESSAGE)
        self._check_types(inputs)

        # 5. Sin material procesado no hay plan (GEN-C6).
        if not self._evidence.has_processed_material(command.teacher_id, command.unit_id):
            raise NoProcessedMaterial()

        # 6. Una sola recuperación, que queda congelada en el plan (research R3).
        outcome_texts = [o.text for o in unit.outcomes if not inputs.outcome_id or o.id == inputs.outcome_id]
        retrieval = self._evidence.retrieve(EvidenceQuery(
            teacher_id=command.teacher_id,
            unit_id=command.unit_id,
            query=evidence_query_text(unit.unit_title, outcome_texts, inputs.instructions, inputs.competency),
            limit=max(MIN_TOP_K, min(inputs.top_k, MAX_TOP_K)),
        ))
        evidence = PlanEvidence(retrieval.retrieval_mode, self._clock(), tuple(
            PlanFragment(f.chunk_id, f.document_id, f.document_name, f.location, f.text, f.relevance, f.source_url,
                         f.license)
            for f in retrieval.fragments
        ))

        # 7. QA-05: la evidencia debe tratar el tema de las indicaciones; si no, no se crea el plan.
        coverage = assess_topic_coverage(
            inputs.instructions, [fragment.text for fragment in evidence.fragments], self._topic_coverage_threshold
        )
        if not coverage.accepted:
            raise GenerationError(GenerationErrorCode.INSUFFICIENT_EVIDENCE, off_topic_message(coverage))

        # 8. Referentes (MAT-P2) y tipologías anteriores (CUR-P3). Si fallan, el plan se arma sin ellos. Los
        # fragmentos de cada referente se limitan a la evidencia congelada, sea cual sea el adaptador.
        referents = within_evidence(self._optional(
            lambda: tuple(self._referents.referents_for(
                command.teacher_id, command.unit_id, inputs.instructions, evidence.fragments)),
            "los referentes",
        ), evidence)
        previous = self._optional(
            lambda: tuple(self._typologies.previous_typologies(
                command.teacher_id, command.unit_id, MAX_PREVIOUS_TYPOLOGIES))[:MAX_PREVIOUS_TYPOLOGIES],
            "las tipologías anteriores",
        )
        # R11 (PLAN-C16): los conceptos de las unidades anteriores del curso, congelados como las tipologías.
        previous_units = self._optional(
            lambda: self._previous_unit_concepts(command.teacher_id, command.unit_id),
            "los conceptos de las unidades anteriores",
        )
        session_context = SessionContext(previous, previous_units)

        # 9. El plan, con la IA o con reglas, y sus avisos.
        # T029: el resultado elegido ancla los conceptos del plan (sin elegir, ninguno).
        chosen = next(
            (f"{o.code}: {o.text}" for o in unit.outcomes if inputs.outcome_id and o.id == inputs.outcome_id), ""
        )
        items, generator = self._planner.draft(inputs, evidence, referents, session_context, unit.unit_title, chosen)
        requested = {requested.type for requested in inputs.resource_types}
        warnings = (SAME_TYPOLOGY_WARNING,) if previous and set(previous[0].resource_types) == requested else ()

        # 10. Se guarda en borrador, aunque tenga problemas. Si otro envío con la misma clave ganó, se aplica la regla 3.
        #     El plan implícito (GEN-P2) se guarda aprobado si no tiene problemas.
        now = self._clock()
        plan = GenerationPlan(
            id=self._new_id(), teacher_id=command.teacher_id, unit_id=command.unit_id, idempotency_key=key,
            payload_hash=content_hash, version=1, status=PlanStatus.DRAFT, origin=origin, inputs=inputs,
            evidence=evidence, referents=referents, session_context=session_context, items=items, warnings=warnings,
            generator=generator, used_by_request_id=None, created_at=now, updated_at=now,
        )
        if origin == ORIGIN_IMPLICIT and not plan_view(plan, self._catalog).problems:
            plan = replace(plan, status=PlanStatus.APPROVED, approved_at=now)
        try:
            created = self._repository.create(plan)
        except PlanKeyTaken as taken:
            return self._replay(taken.existing, content_hash)
        return CreatePlanResult(view=plan_view(created, self._catalog), created=True)

    def _check_types(self, inputs: PlanInputs) -> None:
        requested = [r.type for r in inputs.resource_types]
        if not requested:
            raise GenerationError(GenerationErrorCode.INVALID_PARAMETERS, NO_TYPES_MESSAGE)
        entries = {entry.id: entry for entry in self._catalog.entries() if entry.active}
        unknown = list(dict.fromkeys(t for t in requested if t not in entries))
        if unknown:
            raise GenerationError(
                GenerationErrorCode.INVALID_PARAMETERS, UNKNOWN_TYPES_MESSAGE.format(types=", ".join(unknown)))
        repeated = list(dict.fromkeys(t for t in requested if requested.count(t) > 1))
        if repeated:
            names = ", ".join(entries[t].name for t in repeated)
            raise GenerationError(GenerationErrorCode.INVALID_PARAMETERS, REPEATED_TYPES_MESSAGE.format(types=names))
        if len(requested) > MAX_PLAN_TYPES:
            raise GenerationError(GenerationErrorCode.INVALID_PARAMETERS, TOO_MANY_TYPES_MESSAGE)
        if any(r.quantity is not None and not MIN_ITEM_QUANTITY <= r.quantity <= MAX_ITEM_QUANTITY
               for r in inputs.resource_types):
            raise GenerationError(GenerationErrorCode.INVALID_PARAMETERS, QUANTITY_MESSAGE)
        if inputs.modality is not None:
            outside = [t for t in requested if inputs.modality not in entries[t].modalities]
            if outside:
                names = ", ".join(entries[t].name for t in outside)
                raise GenerationError(
                    GenerationErrorCode.RESOURCE_TYPE_NOT_IN_MODALITY,
                    OUTSIDE_MODALITY_MESSAGE.format(modality=inputs.modality, names=names),
                )

    def _previous_unit_concepts(self, teacher_id: str, unit_id: str) -> tuple:
        if self._previous_units is None:
            return ()
        units = tuple(self._previous_units.previous_unit_concepts(teacher_id, unit_id, MAX_PREVIOUS_UNIT_CONCEPTS))
        # El tope vale aunque el adaptador devuelva más.
        kept, total = [], 0
        for unit in units:
            room = MAX_PREVIOUS_UNIT_CONCEPTS - total
            if room <= 0:
                break
            if unit.concepts[:room]:
                kept.append(replace(unit, concepts=unit.concepts[:room]))
                total += len(unit.concepts[:room])
        return tuple(kept)

    @staticmethod
    def _optional(read: Callable[[], tuple], what: str) -> tuple:
        try:
            return read()
        except Exception as error:  # el contexto es opcional: el plan se arma igual
            logger.warning("No se pudieron leer %s del plan: %s", what, redact_secrets(str(error))[:300])
            return ()

    def _replay(self, existing: GenerationPlan, content_hash: str) -> CreatePlanResult:
        if existing.payload_hash != content_hash:
            raise GenerationError(GenerationErrorCode.IDEMPOTENCY_KEY_REUSED, KEY_REUSED_MESSAGE)
        return CreatePlanResult(view=plan_view(existing, self._catalog), created=False)
