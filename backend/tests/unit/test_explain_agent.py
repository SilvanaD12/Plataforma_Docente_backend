"""
HU-049 (Sprint 1, solo texto): el agente de Explicar redacta la explicación y el glosario, y cada párrafo de su
contenido se contrasta con el material (C02). Lo que no tiene respaldo se quita con su motivo y, si queda menos de la
mitad, el recurso se rechaza. El recurso multimedia (C01) queda para el Sprint 2.
"""

from __future__ import annotations

import pytest

from platform5e.application.services.generation.prompt_drafting import (
    build_generation_context,
    build_prompt_instructions,
    normalize_generated_resources,
)
from platform5e.domain.generation.errors import GenerationError
from platform5e.domain.generation.grounding import (
    check_statement,
    split_statements,
    verify_statements,
)
from tests.unit.test_generation_with_material import (
    MOCK_COURSE,
    MOCK_FRAGMENTS,
    MOCK_UNIT,
    MockGenerator,
    build_service_setup,
    make_request_dict,
)

TCP = "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable."
UDP = "El protocolo UDP no establece conexión y es más rápido."
FRAGMENTS = {"f1": TCP, "f2": UDP}

TCP_PARAGRAPH = "El protocolo TCP es orientado a la conexión: garantiza una entrega confiable de los datos."
UDP_PARAGRAPH = "Por otro lado, el protocolo UDP no establece conexión y por eso es más rápido."
BOTH_PARAGRAPH = "TCP es confiable mientras que UDP es más rápido porque no establece conexión."
INVENTED_PARAGRAPH = "El protocolo SCTP reemplazó a TCP en todos los navegadores modernos desde 2015."
CITATIONS = [
    {"afirmacion": "TCP garantiza una entrega confiable", "fragmentos": ["F1"]},
    {"afirmacion": "UDP no establece conexión y es más rápido", "fragmentos": ["F2"]},
]


def explanation(*paragraphs: str, title: str = "TCP y UDP") -> dict:
    return {"titulo": title, "contenido": "\n\n".join(paragraphs), "citas": CITATIONS, "alternativas": []}


def context(resource_type: str = "explicacion", **overrides):
    request = make_request_dict(**{"stage": "explain", "resourceType": resource_type, **overrides})
    return build_generation_context(MOCK_COURSE, MOCK_UNIT, request, MOCK_FRAGMENTS, {})


# --- Separar el contenido ----------------------------------------------------------------------------------------


def test_the_explanation_is_split_by_paragraphs_and_the_glossary_by_entries():
    assert split_statements("Uno.\nsigue.\n\nDos.", "paragraph") == ["Uno.\nsigue.", "Dos."]
    assert split_statements("Uno.\nDos.", "paragraph") == ["Uno.", "Dos."]  # sin líneas en blanco: una por línea
    assert split_statements("TCP: uno.\n\nUDP: dos.\n", "line") == ["TCP: uno.", "UDP: dos."]


def test_only_the_explanation_and_the_glossary_are_checked_paragraph_by_paragraph():
    assert verify_statements("Texto", "pregunta_detonante", FRAGMENTS) is None
    assert verify_statements(TCP_PARAGRAPH, "explicacion", FRAGMENTS) is not None
    assert verify_statements(TCP_PARAGRAPH, "glosario", FRAGMENTS) is not None


# --- C02: cada párrafo se contrasta con el material y cita su fragmento --------------------------------------------


def test_each_paragraph_is_linked_to_the_chunks_that_support_it():
    assert check_statement(TCP_PARAGRAPH, FRAGMENTS, 0.5).fragment_ids == ["f1"]
    assert check_statement(UDP_PARAGRAPH, FRAGMENTS, 0.5).fragment_ids == ["f2"]
    # Un párrafo que resume dos fragmentos se enlaza con los dos.
    both = check_statement(BOTH_PARAGRAPH, FRAGMENTS, 0.5)
    assert both.supported and sorted(both.fragment_ids) == ["f1", "f2"]


def test_a_paragraph_without_support_in_the_material_is_marked_with_its_reason():
    check = check_statement(INVENTED_PARAGRAPH, FRAGMENTS, 0.5)
    assert not check.supported
    assert "de sus palabras aparece en el material" in check.reason and "mínimo 50 %" in check.reason


def test_headings_and_short_transitions_are_not_checked_and_are_kept():
    check = check_statement("En resumen", FRAGMENTS, 0.5)
    assert check.supported and not check.checked


def test_a_paragraph_needs_ten_points_less_than_a_cited_claim():
    result = verify_statements(TCP_PARAGRAPH, "explicacion", FRAGMENTS, threshold=0.6)
    assert result.threshold == pytest.approx(0.5)
    assert verify_statements(TCP_PARAGRAPH, "explicacion", FRAGMENTS, threshold=0.9).threshold == pytest.approx(0.8)


def test_unsupported_paragraphs_are_removed_from_the_content_and_recorded():
    body = "\n\n".join([TCP_PARAGRAPH, INVENTED_PARAGRAPH, UDP_PARAGRAPH])
    result = verify_statements(body, "explicacion", FRAGMENTS)
    assert result.accepted
    assert result.kept_body() == f"{TCP_PARAGRAPH}\n\n{UDP_PARAGRAPH}"
    summary = result.summary()
    assert (summary["checkedParagraphs"], summary["supportedParagraphs"]) == (3, 2)
    assert summary["paragraphSources"] == [["f1"], ["f2"]]
    assert summary["removedParagraphs"][0]["text"] == INVENTED_PARAGRAPH


def test_a_resource_with_less_than_half_of_its_paragraphs_supported_is_rejected():
    other = "El protocolo QUIC usa cifrado obligatorio en todos los servidores web."
    result = verify_statements("\n\n".join([TCP_PARAGRAPH, INVENTED_PARAGRAPH, other]), "explicacion", FRAGMENTS)
    assert not result.accepted
    assert result.rejection_reason("TCP y UDP") == (
        f"«TCP y UDP»: 2 de 3 párrafos sin respaldo en el material (p. ej. «{INVENTED_PARAGRAPH}»)."
    )


def test_each_glossary_entry_is_checked_on_its_own():
    glossary = "\n".join([
        "TCP: protocolo orientado a la conexión que garantiza una entrega confiable.",
        "UDP: protocolo que no establece conexión y es más rápido.",
        "SCTP: protocolo que reemplazó a TCP en los navegadores modernos desde 2015.",
    ])
    result = verify_statements(glossary, "glosario", FRAGMENTS)
    assert result.accepted and len(result.unsupported) == 1
    assert result.kept_body().split("\n") == glossary.split("\n")[:2]


# --- Integración con la normalización y el servicio ------------------------------------------------------------


def test_normalization_keeps_the_supported_paragraphs_and_stores_their_sources():
    rejections: list[dict] = []
    payload = {"recursos": [explanation(TCP_PARAGRAPH, INVENTED_PARAGRAPH, UDP_PARAGRAPH)]}
    [resource] = normalize_generated_resources(payload, context(), rejections)
    assert resource["contenido"] == f"{TCP_PARAGRAPH}\n\n{UDP_PARAGRAPH}"
    assert resource["verificacion"]["paragraphSources"] == [["f1"], ["f2"]]
    assert resource["verificacion"]["removedParagraphs"][0]["text"] == INVENTED_PARAGRAPH
    assert resource["verificacion"]["checkedClaims"] == 2  # la verificación de HU-016 sigue igual
    assert rejections == []


def test_normalization_rejects_an_invented_explanation_and_reports_why():
    rejections: list[dict] = []
    other = "El protocolo QUIC usa cifrado obligatorio en todos los servidores web."
    payload = {"recursos": [explanation(INVENTED_PARAGRAPH, other, title="Inventada")]}
    assert normalize_generated_resources(payload, context(), rejections) == []
    assert rejections[0]["title"] == "Inventada" and "párrafos sin respaldo" in rejections[0]["reason"]
    assert rejections[0]["grounding"]["checkedParagraphs"] == 2


def test_other_resource_types_keep_their_content_unchanged():
    trigger = {**explanation(TCP_PARAGRAPH, INVENTED_PARAGRAPH), "titulo": "Pregunta"}
    [resource] = normalize_generated_resources({"recursos": [trigger]}, context("pregunta_detonante", stage="engage"))
    assert INVENTED_PARAGRAPH in resource["contenido"] and "checkedParagraphs" not in resource["verificacion"]


def test_the_prompt_asks_for_paragraphs_and_glossary_entries_taken_from_the_material():
    _, explain_prompt = build_prompt_instructions(context())
    assert "separados por una línea en blanco" in explain_prompt and "solo información del material" in explain_prompt
    _, glossary_prompt = build_prompt_instructions(context("glosario"))
    assert "«Término: definición»" in glossary_prompt


def test_the_service_reports_the_removed_paragraphs():
    generator = MockGenerator({"recursos": [explanation(TCP_PARAGRAPH, INVENTED_PARAGRAPH, UDP_PARAGRAPH)]})
    service, _ = build_service_setup(generator)
    result = service.generate(make_request_dict(stage="explain", resourceType="explicacion"), "docente")

    [resource] = result["resources"]
    assert resource["body"] == f"{TCP_PARAGRAPH}\n\n{UDP_PARAGRAPH}"
    assert resource["grounding"]["removedParagraphs"][0]["text"] == INVENTED_PARAGRAPH
    assert result["grounding"]["unsupportedParagraphs"] == 1
    assert "Se quitaron 1 párrafo(s) sin respaldo en el material." in result["notice"]


def test_when_the_whole_explanation_is_invented_the_service_refuses_and_explains_why():
    other = "El protocolo QUIC usa cifrado obligatorio en todos los servidores web."
    generator = MockGenerator({"recursos": [explanation(INVENTED_PARAGRAPH, other, title="Inventada")]})
    service, repo = build_service_setup(generator)
    with pytest.raises(GenerationError) as error:
        service.generate(make_request_dict(stage="explain", resourceType="explicacion"), "docente")
    assert error.value.code == "INSUFFICIENT_EVIDENCE"
    assert "Motivo: «Inventada»: 2 de 2 párrafos sin respaldo en el material" in error.value.message
    assert repo.saved_results == []
