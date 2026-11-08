"""
HU-016: cada afirmación se contrasta con la evidencia recuperada (C01) y lo que no tiene respaldo se rechaza con su
motivo (C02), lo que alimenta el indicador I21 (tasa de alucinación).
"""

from __future__ import annotations

import pytest

from platform5e.application.services.generation.prompt_drafting import (
    build_generation_context,
    normalize_generated_resources,
)
from platform5e.domain.generation.errors import GenerationError
from platform5e.domain.generation.grounding import (
    check_claim,
    claim_support,
    hallucination_rate,
    verify_citations,
)
from tests.unit.test_generation_with_material import (
    MOCK_COURSE,
    MOCK_FRAGMENTS,
    MOCK_ITEM,
    MOCK_UNIT,
    MockGenerator,
    build_service_setup,
    make_request_dict,
)

TCP = "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable."
UDP = "El protocolo UDP no establece conexión y es más rápido."
FRAGMENTS = {"f1": TCP, "f2": UDP}
INVENTED = "El protocolo SCTP reemplazó a TCP en todos los navegadores modernos"


# --- C01: contrastar cada afirmación con la evidencia ---------------------------------------------------------


def test_support_counts_the_claim_words_found_in_the_evidence():
    assert claim_support("TCP garantiza una entrega confiable", [TCP]) == 1.0
    assert claim_support("TCP garantiza la entrega", [UDP]) == 0.0
    # Misma raíz o mismas seis primeras letras: «confiable» / «confiabilidad», «conexión» / «conexiones».
    assert claim_support("La confiabilidad de las conexiones TCP", [TCP]) == 1.0
    assert 0 < claim_support(INVENTED, [TCP]) < 0.6


def test_a_claim_with_support_in_its_cited_fragment_is_kept():
    check = check_claim("TCP garantiza una entrega confiable", ["f1"], FRAGMENTS)
    assert check.supported and check.fragment_ids == ["f1"] and not check.corrected


def test_a_claim_citing_the_wrong_fragment_is_moved_to_the_one_that_supports_it():
    check = check_claim("TCP garantiza una entrega confiable", ["f2"], FRAGMENTS)
    assert check.supported and check.corrected and check.fragment_ids == ["f1"]


def test_a_claim_without_support_in_any_retrieved_fragment_is_rejected_with_its_reason():
    check = check_claim(INVENTED, ["f1"], FRAGMENTS)
    assert not check.supported
    assert "de sus palabras aparece en los fragmentos citados" in check.reason and "mínimo 60 %" in check.reason


def test_a_claim_too_short_to_check_is_rejected():
    check = check_claim("TCP", ["f1"], FRAGMENTS)
    assert not check.supported and "demasiado breve" in check.reason


def test_the_threshold_is_the_evidence_threshold_of_the_request():
    claim = "TCP garantiza la entrega de segmentos"  # 3 de 4 palabras: 75 %
    assert check_claim(claim, ["f1"], FRAGMENTS, threshold=0.6).supported
    assert not check_claim(claim, ["f1"], FRAGMENTS, threshold=0.9).supported


# --- C02: rechazar lo que no tiene respaldo, con su motivo -----------------------------------------------------


def test_a_resource_keeps_its_supported_claims_and_records_the_removed_ones():
    citations = [
        {"claim": "TCP garantiza una entrega confiable", "fragmentIds": ["f1"]},
        {"claim": "UDP no establece conexión y es más rápido", "fragmentIds": ["f2"]},
        {"claim": INVENTED, "fragmentIds": ["f1"]},
    ]
    result = verify_citations(citations, FRAGMENTS)
    assert result.accepted and len(result.supported) == 2
    summary = result.summary()
    assert summary["checkedClaims"] == 3 and summary["supportedClaims"] == 2
    assert summary["removedClaims"][0]["claim"] == INVENTED and summary["removedClaims"][0]["reason"]


def test_a_resource_is_rejected_when_less_than_half_of_its_claims_have_support():
    citations = [
        {"claim": "TCP garantiza una entrega confiable", "fragmentIds": ["f1"]},
        {"claim": INVENTED, "fragmentIds": ["f1"]},
        {"claim": "El protocolo QUIC usa cifrado obligatorio siempre", "fragmentIds": ["f2"]},
    ]
    result = verify_citations(citations, FRAGMENTS)
    assert not result.accepted
    assert result.rejection_reason("Ítem") == (
        f"«Ítem»: 2 de 3 afirmaciones sin respaldo en el material (p. ej. «{INVENTED}»)."
    )
    assert verify_citations([], FRAGMENTS).rejection_reason("Ítem") == "«Ítem» no cita ninguna afirmación del material."


def test_hallucination_rate_is_unsupported_over_checked_claims():
    assert hallucination_rate(40, 1) == 0.025
    assert hallucination_rate(0, 0) is None


def context(**overrides):
    return build_generation_context(MOCK_COURSE, MOCK_UNIT, make_request_dict(**overrides), MOCK_FRAGMENTS, {})


def test_normalization_drops_unsupported_resources_and_reports_why():
    invented = {**MOCK_ITEM, "titulo": "Inventado", "citas": [{"afirmacion": INVENTED, "fragmentos": ["F1", "F2"]}]}
    rejections: list[dict] = []
    resources = normalize_generated_resources({"recursos": [invented]}, context(), rejections)
    assert resources == []
    assert rejections[0]["title"] == "Inventado" and "sin respaldo en el material" in rejections[0]["reason"]
    assert rejections[0]["grounding"]["checkedClaims"] == 1 and rejections[0]["grounding"]["supportedClaims"] == 0


def test_the_service_reports_the_grounding_of_the_request_with_i21():
    mixed = {
        **MOCK_ITEM,
        "citas": [
            {"afirmacion": "TCP garantiza una entrega confiable", "fragmentos": ["F1", "F2"]},
            {"afirmacion": "UDP no establece conexión y es más rápido", "fragmentos": ["F1", "F2"]},
            {"afirmacion": INVENTED, "fragmentos": ["F1"]},
        ],
    }
    invented = {**MOCK_ITEM, "titulo": "Inventado", "citas": [{"afirmacion": INVENTED, "fragmentos": ["F1"]}]}
    service, _ = build_service_setup(MockGenerator({"recursos": [invented, mixed]}))
    result = service.generate(make_request_dict(quantity=2), "docente")

    [resource] = result["resources"]
    assert [c["claim"] for c in resource["citations"]] == [
        "TCP garantiza una entrega confiable",
        "UDP no establece conexión y es más rápido",
    ]
    assert resource["grounding"]["removedClaims"][0]["claim"] == INVENTED
    report = result["grounding"]
    assert (report["checkedClaims"], report["supportedClaims"], report["unsupportedClaims"]) == (4, 2, 2)
    assert report["hallucinationRate"] == 0.5
    assert report["rejectedResources"][0]["title"] == "Inventado"
    assert "Se quitaron 2 afirmación(es) sin respaldo en el material y se rechazaron 1 recurso(s)." in result["notice"]


def test_when_nothing_has_support_the_service_refuses_and_explains_why():
    invented = {**MOCK_ITEM, "titulo": "Inventado", "citas": [{"afirmacion": INVENTED, "fragmentos": ["F1"]}]}
    service, repo = build_service_setup(MockGenerator({"recursos": [invented]}))
    with pytest.raises(GenerationError) as error:
        service.generate(make_request_dict(), "docente")
    assert error.value.code == "INSUFFICIENT_EVIDENCE"
    assert "Motivo: «Inventado»: 1 de 1 afirmaciones sin respaldo en el material" in error.value.message
    assert repo.saved_results == []


class ByTypeGenerator(MockGenerator):
    """Devuelve una respuesta distinta según el tipo pedido, para probar la secuencia."""

    def __init__(self, by_type):
        super().__init__({})
        self.by_type = by_type

    def generate(self, context):
        self.captured_contexts.append(context)
        return {"recursos": [self.by_type[context["solicitud"]["tipo"]]]}


def test_in_a_sequence_each_agent_reports_what_it_rejected_for_lack_of_support():
    trigger = {"titulo": "Inventado", "contenido": "¿Y si...?", "citas": [{"afirmacion": INVENTED, "fragmentos": ["F1"]}]}
    explanation = {
        "titulo": "TCP y UDP",
        "contenido": "TCP es confiable; UDP es más rápido.",
        "citas": [{"afirmacion": "UDP no establece conexión y es más rápido", "fragmentos": ["F1", "F2"]}],
    }
    service, _ = build_service_setup(
        ByTypeGenerator({"pregunta_detonante": trigger, "explicacion": explanation})
    )
    result = service.generate_sequence(
        make_request_dict(resourceTypes=["pregunta_detonante", "explicacion"], stage=None, resourceType=None),
        "docente",
    )
    engage, explain = result["sequence"]
    assert engage["generated"] == 0 and "sin respaldo en el material" in engage["rejected"][0]
    assert explain["generated"] == 1 and explain["rejected"] == []
    assert result["grounding"]["rejectedResources"][0]["title"] == "Inventado"
    assert result["grounding"]["hallucinationRate"] == 0.5
