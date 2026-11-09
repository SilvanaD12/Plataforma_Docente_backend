"""GEN-01 (T025): el adaptador de verificación delega en las funciones de REV-01 sin copiar sus reglas. Caso GEN-C8."""

from __future__ import annotations

from typing import Any

from platform5e.application.ports.outbound.resource_verification_port import ResourceVerificationPort
from platform5e.domain.generation import grounding
from platform5e.domain.review.content_fingerprint import content_fingerprint
from platform5e.domain.review.resource_verification import referenced_fragment_ids, verify_resource
from platform5e.infrastructure.adapters.review_verification_adapter import ReviewVerificationAdapter

TEXT = "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable."
RESOURCE: dict[str, Any] = {
    "type": "pregunta_detonante",
    "title": "Entrega confiable",
    "body": "¿Por qué TCP garantiza una entrega confiable?",
    "version": 1,
    "citations": [{"claim": TEXT, "fragmentIds": ["f1"]}],
    "options": [{"id": "a", "text": "Porque", "isCorrect": True, "sourceFragmentIds": ["f2", "f1"]}],
    "structure": {"guidedSteps": [{"title": "Paso", "fragmentIds": ["f3"]}]},
    "evidence": [{"id": "f1", "text": TEXT}],
}


def test_the_adapter_implements_the_port():
    adapter: ResourceVerificationPort = ReviewVerificationAdapter()
    assert isinstance(adapter, ReviewVerificationAdapter)


def test_ids_and_fingerprint_are_the_ones_of_review():
    adapter = ReviewVerificationAdapter()
    assert adapter.referenced_fragment_ids(RESOURCE) == referenced_fragment_ids(RESOURCE) == ["f1", "f2", "f3"]
    assert adapter.fingerprint(RESOURCE) == content_fingerprint(RESOURCE)
    assert adapter.fingerprint(RESOURCE).startswith("sha256:")


def test_verify_uses_review_rules_and_the_current_rule_version(monkeypatch):
    adapter = ReviewVerificationAdapter()
    result = adapter.verify(RESOURCE, 0.6)
    expected = verify_resource(RESOURCE, 0.6, grounding.VERIFICATION_RULE_VERSION)
    assert {k: v for k, v in result.items() if k != "checkedAt"} == {
        k: v for k, v in expected.items() if k != "checkedAt"
    }
    # f2 y f3 no están en la copia: la regla de Revisión lo deja pendiente y sin reintento.
    assert (result["status"], result["retryAvailable"], result["verifiedVersion"]) == ("pending", False, 1)

    monkeypatch.setattr(grounding, "VERIFICATION_RULE_VERSION", 7)
    assert adapter.verify(RESOURCE, 0.6)["ruleVersion"] == 7


def test_verify_does_not_modify_the_resource():
    resource = {**RESOURCE, "evidence": [dict(item) for item in RESOURCE["evidence"]]}
    before = repr(resource)
    ReviewVerificationAdapter().verify(resource, 0.6)
    assert repr(resource) == before
