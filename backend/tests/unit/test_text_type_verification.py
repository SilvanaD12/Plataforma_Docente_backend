"""GEN-P2 (T015) y CUR-P2: tipos de texto del catálogo, con su extensión y su modo de verificación
(specs/006-plan-de-generacion, research R6).

- `lengthHint` válido o ausente (nunca es regla de rechazo).
- `strict`: cada párrafo se contrasta como en `explicacion`; un tipo cuya evidencia no tiene lo que necesita no se
  redacta (por ejemplo, la frase célebre sin una cita textual en el material).
- `framed`: las oraciones de ambientación no necesitan cita, pero cada oración sobre un concepto sí, y hacen falta al
  menos 2 con respaldo.
"""

from __future__ import annotations

import pytest

from platform5e.domain.generation.grounding import verify_framed, verify_statements
from platform5e.domain.generation.text_types import (
    LengthHint,
    evidence_gap,
    length_hint_from,
    literal_quotes,
    verification_mode,
)

FRAGMENTS = {
    "f1": "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable de los datos.",
    "f2": "El control de flujo de TCP evita que el emisor sature al receptor con demasiados segmentos.",
    "f3": "La retransmisión de TCP reenvía los segmentos que no recibieron confirmación del receptor.",
}
CONCEPTS = ("control de flujo", "retransmisión")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"minWords": 40, "maxWords": 120}, LengthHint(40, 120)),
        ({"minWords": 20, "maxWords": 20}, LengthHint(20, 20)),
        ({"minWords": 600, "maxWords": 600}, LengthHint(600, 600)),
        (None, None),
        ({"minWords": 19, "maxWords": 120}, None),
        ({"minWords": 40, "maxWords": 601}, None),
        ({"minWords": 130, "maxWords": 120}, None),
        ({"minWords": "40", "maxWords": 120}, None),
        ({"minWords": True, "maxWords": 120}, None),
        ({"minWords": 40.5, "maxWords": 120}, None),
        ({"maxWords": 120}, None),
        ("40-120", None),
    ],
)
def test_a_length_hint_is_used_only_when_it_follows_the_catalog_rules(raw, expected):
    assert length_hint_from(raw) == expected


def test_the_length_hint_is_prompt_guidance():
    assert LengthHint(40, 120).instruction() == "Extensión: entre 40 y 120 palabras."


@pytest.mark.parametrize(("raw", "mode"), [("strict", "strict"), ("framed", "framed"), ("otro", None), (None, None)])
def test_only_the_two_verification_modes_are_known(raw, mode):
    assert verification_mode(raw) == mode


def test_literal_quotes_need_quotation_marks_and_at_least_four_words():
    text = ('Tanenbaum escribió: «Lo bueno de los estándares es que hay muchos para elegir». '
            'El término "socket" es breve. Y dijo “una red es un conjunto de computadoras conectadas”.')
    assert literal_quotes(text) == [
        "Lo bueno de los estándares es que hay muchos para elegir",
        "una red es un conjunto de computadoras conectadas",
    ]


def test_the_quote_type_without_a_literal_quote_in_the_evidence_is_not_drafted():
    reason = evidence_gap("frase_celebre_comentada", "strict", CONCEPTS, list(FRAGMENTS.values()))
    assert reason == "El material no tiene una cita textual para este tema."
    quoted = [*FRAGMENTS.values(), "Cerf afirmó: «el control de flujo es la cortesía de la red entre equipos»."]
    assert evidence_gap("frase_celebre_comentada", "strict", CONCEPTS, quoted) is None


def test_a_strict_type_needs_evidence_about_its_concepts_and_a_framed_type_does_not():
    other = ("enrutamiento dinámico",)
    reason = evidence_gap("resumen_ideas_clave", "strict", other, list(FRAGMENTS.values()))
    assert reason == "El material no trata «enrutamiento dinámico»: este tipo solo usa lo que dice el material."
    assert evidence_gap("resumen_ideas_clave", "strict", CONCEPTS, list(FRAGMENTS.values())) is None
    assert evidence_gap("historia_corta", "framed", other, list(FRAGMENTS.values())) is None


def test_a_strict_type_is_checked_paragraph_by_paragraph_like_the_explanation():
    body = (f"{FRAGMENTS['f2']}\n\n{FRAGMENTS['f3']}\n\n"
            "Los satélites geoestacionarios orbitan sobre el ecuador a gran altura sobre la Tierra.")
    result = verify_statements(body, "resumen_ideas_clave", FRAGMENTS, mode="paragraph")
    assert result is not None and result.accepted
    assert result.kept_body() == f"{FRAGMENTS['f2']}\n\n{FRAGMENTS['f3']}"
    assert verify_statements(body, "resumen_ideas_clave", FRAGMENTS) is None  # sin modo, un tipo nuevo no se contrasta


def test_framed_accepts_scene_setting_sentences_without_citations():
    body = ("Ana y Luis preparan la red del laboratorio antes de la feria escolar del viernes. "
            f"{FRAGMENTS['f2']} {FRAGMENTS['f3']}")
    result = verify_framed(body, CONCEPTS, FRAGMENTS)
    assert result.accepted
    summary = result.summary()
    assert summary["conceptStatements"] == 2 and summary["supportedConceptStatements"] == 2
    assert summary["framingSentences"] == 1 and summary["unsupportedStatements"] == []


def test_framed_needs_at_least_two_supported_concept_statements():
    body = f"Ana y Luis preparan la red del laboratorio antes de la feria escolar. {FRAGMENTS['f2']}"
    result = verify_framed(body, CONCEPTS, FRAGMENTS)
    assert not result.accepted
    assert result.rejection_reason("Historia") == (
        "«Historia»: solo 1 afirmación sobre los conceptos se apoya en el material; este tipo necesita al menos 2.")


def test_framed_rejects_an_unsupported_statement_about_a_concept():
    body = (f"{FRAGMENTS['f2']} {FRAGMENTS['f3']} "
            "La retransmisión ocurre siempre cada cinco minutos en las redes de los satélites geoestacionarios.")
    result = verify_framed(body, CONCEPTS, FRAGMENTS)
    assert not result.accepted
    assert result.rejection_reason("Historia").startswith(
        "«Historia»: una afirmación sobre los conceptos no se apoya en el material (")


def test_framed_does_not_check_the_question_for_the_student():
    body = (f"{FRAGMENTS['f2']} {FRAGMENTS['f3']} "
            "¿Qué relación encuentras entre la situación y el control de flujo?")
    result = verify_framed(body, CONCEPTS, FRAGMENTS)
    assert result.accepted and result.summary()["framingSentences"] == 1
