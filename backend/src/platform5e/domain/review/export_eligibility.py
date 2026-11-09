"""
REV-01 · Filtro común de exportación (REV-R7 · REV-C7, C10).

Moodle XML, SCORM y el documento de unidad aplican el mismo criterio: un recurso entra en una exportación nueva solo
si está aprobado, tiene una verificación vigente para su contenido actual y no tiene un archivo multimedia invalidado.
La versión de la regla de verificación no participa: un recurso que no se edita sigue exportable aunque cambie.
"""

from __future__ import annotations

from typing import Any

from platform5e.domain.review.content_fingerprint import content_fingerprint
from platform5e.domain.review.resource_verification import CURRENT, INSUFFICIENT, PENDING

# Quitar "aprobado" cuando los valores guardados estén migrados al inglés.
APPROVED_STATUSES: frozenset[str] = frozenset({"approved", "aprobado"})

NOT_APPROVED = "not_approved"
VERIFICATION_MISSING = "verification_missing"
VERIFICATION_OUTDATED = "verification_outdated"
VERIFICATION_INSUFFICIENT = "verification_insufficient"
VERIFICATION_PENDING = "verification_pending"
MEDIA_INVALIDATED = "media_invalidated"


def export_ineligibility(resource: dict[str, Any]) -> str | None:
    """Motivo técnico por el que el recurso no entra en una exportación nueva, o None si es elegible."""
    if resource.get("status") not in APPROVED_STATUSES:
        return NOT_APPROVED
    verification = resource.get("verification")
    if not isinstance(verification, dict):
        return VERIFICATION_MISSING
    if verification.get("fingerprint") != content_fingerprint(resource):
        return VERIFICATION_OUTDATED
    if verification.get("status") == INSUFFICIENT:
        return VERIFICATION_INSUFFICIENT
    if verification.get("status") == PENDING or verification.get("status") != CURRENT:
        return VERIFICATION_PENDING
    if (resource.get("media") or {}).get("invalidated"):
        return MEDIA_INVALIDATED
    return None
