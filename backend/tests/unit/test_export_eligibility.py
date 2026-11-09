"""REV-01 · Filtro común de exportación (REV-R7 · REV-C7, C10).

Un recurso entra en una exportación nueva solo si está aprobado, tiene una verificación vigente para su contenido
actual y no tiene un archivo multimedia invalidado. La versión de la regla no participa.
"""

from __future__ import annotations

from typing import Any

import pytest

from platform5e.domain.generation.grounding import VERIFICATION_RULE_VERSION
from platform5e.domain.review.export_eligibility import export_ineligibility
from platform5e.domain.review.resource_verification import verify_resource

EVIDENCE = "El protocolo TCP confirma la entrega de los datos al receptor."


def approved(**overrides: Any) -> dict[str, Any]:
    resource = {
        "id": "r1",
        "status": "aprobado",
        "body": "¿Qué protocolo confirma la entrega?",
        "citations": [{"claim": "El protocolo TCP confirma la entrega de los datos.", "fragmentIds": ["f1"]}],
        "evidence": [{"id": "f1", "text": EVIDENCE}],
        "options": None,
        **overrides,
    }
    resource["verification"] = verify_resource(resource, threshold=0.6, rule_version=VERIFICATION_RULE_VERSION)
    return resource


def test_an_approved_resource_with_a_current_verification_is_eligible():
    assert export_ineligibility(approved()) is None


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        pytest.param(lambda r: r.update(status="pendiente"), "not_approved", id="pendiente"),
        pytest.param(lambda r: r.update(status="descartado"), "not_approved", id="descartado"),
        pytest.param(lambda r: r.pop("verification"), "verification_missing", id="sin-verificacion"),
        pytest.param(lambda r: r.update(body="Otro enunciado."), "verification_outdated", id="otra-huella"),
        pytest.param(lambda r: r["verification"].update(status="insufficient"), "verification_insufficient", id="insuficiente"),
        pytest.param(lambda r: r["verification"].update(status="pending"), "verification_pending", id="pendiente-de-comprobar"),
        pytest.param(lambda r: r.update(media={"status": "fallback", "invalidated": True}), "media_invalidated", id="multimedia"),
    ],
)
def test_each_reason_for_leaving_a_resource_out(change, reason):
    """REV-C7: el archivo incluye solo los recursos aprobados y con comprobación vigente."""
    resource = approved()
    change(resource)
    assert export_ineligibility(resource) == reason


def test_approval_is_checked_before_verification():
    resource = approved(status="pendiente")
    resource["verification"]["status"] = "insufficient"
    assert export_ineligibility(resource) == "not_approved"


def test_the_rule_version_does_not_take_part():
    """REV-C10: si cambia la regla y el recurso no se edita, sigue exportable."""
    resource = approved()
    resource["verification"]["ruleVersion"] = VERIFICATION_RULE_VERSION + 5
    assert export_ineligibility(resource) is None


def test_the_english_approved_status_is_also_accepted():
    """El caso de uso ya aceptaba `approved` para cuando los valores guardados se migren al inglés."""
    assert export_ineligibility(approved(status="approved")) is None
