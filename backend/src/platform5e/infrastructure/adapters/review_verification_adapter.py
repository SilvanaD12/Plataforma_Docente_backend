"""
Adaptador de `ResourceVerificationPort` sobre las funciones de dominio de Revisión (REV-01).

Delega sin copiar reglas: `content_fingerprint`, `referenced_fragment_ids` y `verify_resource`, con
`VERIFICATION_RULE_VERSION` de `grounding.py`. Así Generación copia y verifica exactamente lo que Revisión exigirá.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from platform5e.application.ports.outbound.resource_verification_port import ResourceVerificationPort
from platform5e.domain.generation import grounding
from platform5e.domain.review.content_fingerprint import content_fingerprint
from platform5e.domain.review.resource_verification import referenced_fragment_ids, verify_resource


class ReviewVerificationAdapter(ResourceVerificationPort):
    """Verificación de Revisión para los recursos que crea Generación."""

    def referenced_fragment_ids(self, resource: Mapping[str, Any]) -> list[str]:
        return referenced_fragment_ids(dict(resource))

    def fingerprint(self, resource: Mapping[str, Any]) -> str:
        return content_fingerprint(dict(resource))

    def verify(self, resource: Mapping[str, Any], threshold: float) -> dict[str, Any]:
        # Se lee la versión de la regla al llamar, no al importar, para que un cambio de la regla se aplique siempre.
        return verify_resource(dict(resource), threshold, grounding.VERIFICATION_RULE_VERSION)
