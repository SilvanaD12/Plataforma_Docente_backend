"""
Errores y datos de generación independientes del transporte HTTP y de la persistencia.
"""

from __future__ import annotations

from enum import StrEnum

from platform5e.domain.shared.errors import DomainError


class GenerationError(DomainError):
    """Error producido durante el flujo de generación del modelo pedagógico 5E."""

    def __init__(self, code: str, message: str) -> None:
        self.code: str = code
        self.message: str = message
        super().__init__(message)


class GenerationErrorCode(StrEnum):
    """Códigos estables del pedido de generación en segundo plano (GEN-01).

    Son valores de `GenerationError.code`; el adaptador HTTP decide el estado de cada uno según el contrato OpenAPI.
    Como `StrEnum`, cada miembro se compara y se serializa igual que su texto.
    """

    # Validación del pedido
    INVALID_PARAMETERS = "INVALID_PARAMETERS"
    INVALID_SEQUENCE = "INVALID_SEQUENCE"
    INVALID_OUTCOME = "INVALID_OUTCOME"
    IDEMPOTENCY_KEY_REQUIRED = "IDEMPOTENCY_KEY_REQUIRED"
    IDEMPOTENCY_KEY_REUSED = "IDEMPOTENCY_KEY_REUSED"
    NO_PROCESSED_MATERIAL = "NO_PROCESSED_MATERIAL"
    RESOURCE_TYPE_NOT_IN_MODALITY = "RESOURCE_TYPE_NOT_IN_MODALITY"  # 422 (HU-024)
    # No encontrados (también cuando la entidad es de otro docente)
    GENERATION_REQUEST_NOT_FOUND = "GENERATION_REQUEST_NOT_FOUND"
    UNIT_NOT_FOUND = "UNIT_NOT_FOUND"
    # Límites y ejecución
    TOO_MANY_ACTIVE_REQUESTS = "TOO_MANY_ACTIVE_REQUESTS"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    REQUEST_INTERRUPTED = "REQUEST_INTERRUPTED"
    GENERATION_FAILED = "GENERATION_FAILED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    # Regeneración (los lanza StartRegeneration; Revisión decide el estado HTTP de su ruta). REGENERATION_UNAVAILABLE
    # ya no es de Generación: queda solo para el 503 propio de Revisión («la regeneración no está disponible»).
    REGENERATION_PARAMETERS_MISSING = "REGENERATION_PARAMETERS_MISSING"  # 422: sin `params` o sin `resourceType`
    REGENERATION_TARGET_INVALID = "REGENERATION_TARGET_INVALID"  # 422: id o versión del recurso no válidos
    REGENERATION_ATTEMPTS_EXHAUSTED = "REGENERATION_ATTEMPTS_EXHAUSTED"  # 409: se agotaron los intentos de la versión
    # Plan de generación (GEN-P1, specs/006-plan-de-generacion)
    PLAN_NOT_FOUND = "PLAN_NOT_FOUND"  # 404: no existe o es de otro docente
    PLAN_VERSION_CONFLICT = "PLAN_VERSION_CONFLICT"  # 409: expectedVersion o planVersion no es la actual
    PLAN_ALREADY_USED = "PLAN_ALREADY_USED"  # 409: el plan ya inició un pedido de generación
    PLAN_INVALID = "PLAN_INVALID"  # 422: se intentó aprobar un plan con problemas de validación
    PLAN_NOT_APPROVED = "PLAN_NOT_APPROVED"  # 422: se intentó usar un plan en borrador (GEN-P2)
    PLAN_EVIDENCE_STALE = "PLAN_EVIDENCE_STALE"  # 409: un fragmento del plan ya no existe en la unidad (GEN-P2)
    PLAN_REQUIRED = "PLAN_REQUIRED"  # 422: pedido sin plan con GENERATION_REQUIRE_PLAN=true (GEN-P2)
