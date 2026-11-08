"""
REV-01 · Verificación de los recursos que todavía no tienen resultado guardado (decisión D7, regla de REV-R11).

Los recursos guardados antes de REV-01, y los que Generación crea mientras no guarde `verification`, se verifican la
primera vez que se leen, con el umbral guardado o con `DEFAULT_THRESHOLD`:

- un recurso aprobado con resultado vigente sigue aprobado;
- uno aprobado con resultado insuficiente o pendiente vuelve a revisión;
- sin copia histórica, o con un fragmento referenciado sin texto, queda pendiente y solo se puede regenerar.

La actualización no cambia el contenido, así que se guarda **sin incrementar la versión**: el docente que tenía el
recurso abierto no recibe un conflicto falso. Si entre la lectura y la escritura hubo un guardado, se descarta sin
error y se repite en la próxima lectura.

Esta función la usan la revisión y, en el bloque d), la exportación. El script único para Neon (opción B de D7) sigue
pendiente de acuerdo con Material y evidencia.
"""

from __future__ import annotations

from typing import Any

from platform5e.application.ports.outbound.resource_repository_port import ResourceReviewRepositoryPort
from platform5e.domain.generation import grounding
from platform5e.domain.review.resource_verification import CURRENT, stored_threshold, verify_resource

APPROVED = "aprobado"
PENDING_REVIEW = "pendiente"


def upgrade_resource_verification(
    repository: ResourceReviewRepositoryPort, teacher_id: str, unit_id: str, resource: dict[str, Any]
) -> dict[str, Any]:
    """Devuelve el recurso con su verificación. Si ya la tenía, lo devuelve sin cambios."""
    if isinstance(resource.get("verification"), dict):
        return resource
    upgraded = {**resource, "version": resource.get("version", 1)}
    # REV-R11: la falta de fecha de recuperación no invalida la copia; se registra como desconocida (`null`).
    if isinstance(resource.get("evidence"), list):
        upgraded["evidence"] = [
            {"retrievedAt": None, **fragment} if isinstance(fragment, dict) else fragment
            for fragment in resource["evidence"]
        ]
    upgraded["verification"] = verify_resource(upgraded, stored_threshold(resource), grounding.VERIFICATION_RULE_VERSION)
    if upgraded.get("status") == APPROVED and upgraded["verification"]["status"] != CURRENT:
        upgraded["status"] = PENDING_REVIEW
        upgraded["decidedAt"] = None
    saved = repository.save_resource_if_version(teacher_id, unit_id, upgraded, upgraded["version"], increment=False)
    return upgraded if saved else resource
