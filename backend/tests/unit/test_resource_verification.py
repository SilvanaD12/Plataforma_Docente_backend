"""REV-01 · Verificación local de un recurso contra su copia histórica (REV-R3, R4, R6 · REV-C1, C3, C4, C11).

`verify_resource` usa solo `resource["evidence"]` y las reglas de `grounding.py` y `distractor_reliability.py`: no
consulta el índice del material ni servicios externos.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from platform5e.domain.generation.grounding import DEFAULT_THRESHOLD, VERIFICATION_RULE_VERSION
from platform5e.domain.review import resource_verification
from platform5e.domain.review.content_fingerprint import content_fingerprint
from platform5e.domain.review.resource_verification import (
    assess_edited_distractors,
    stored_threshold,
    verify_resource,
)

FRAGMENT_A = "frag-48d6fc446d5b412d"
FRAGMENT_B = "frag-6d792e371d524a21"
TEXT_A = (
    "La capa de transporte ofrece comunicación de extremo a extremo entre procesos que se ejecutan en distintos "
    "equipos. Los dos protocolos principales de esta capa en Internet son TCP y UDP. El protocolo TCP está orientado "
    "a la conexión. Antes de enviar datos, TCP establece la conexión mediante un acuerdo en tres pasos: el cliente "
    "envía un segmento SYN, el servidor responde con SYN-ACK y el cliente confirma con ACK."
)
TEXT_B = (
    "UDP envía datagramas sin establecer una conexión previa y no garantiza la entrega. Su cabecera mide solo 8 "
    "bytes. UDP tiene menor latencia que TCP porque no espera confirmaciones ni retransmite datos."
)
UNSUPPORTED = "Los satélites geoestacionarios orbitan sobre el ecuador terrestre a gran altura."


def evidence(*fragments: tuple[str, str]) -> list[dict[str, Any]]:
    return [
        {"id": fragment_id, "text": text, "location": "sección 1", "documentId": "doc-1",
         "documentName": "material_tcp_udp.txt", "sourceUrl": None, "license": None, "retrievedAt": None}
        for fragment_id, text in fragments
    ]


def explanation(**overrides: Any) -> dict[str, Any]:
    resource = {
        "id": "rec-explicacion",
        "type": "explicacion",
        "format": "text",
        "version": 3,
        "body": "Los dos protocolos principales de esta capa en Internet son TCP y UDP.\n\n"
        "UDP tiene menor latencia que TCP porque no espera confirmaciones ni retransmite datos.",
        "structure": None,
        "options": None,
        "citations": [
            {"claim": "Los dos protocolos principales de esta capa en Internet son TCP y UDP.", "fragmentIds": [FRAGMENT_A]},
            {"claim": "UDP tiene menor latencia que TCP porque no espera confirmaciones ni retransmite datos.",
             "fragmentIds": [FRAGMENT_B]},
        ],
        "evidence": evidence((FRAGMENT_A, TEXT_A), (FRAGMENT_B, TEXT_B)),
        "grounding": {"threshold": 0.6, "checkedClaims": 2, "supportedClaims": 2},
        "params": {"evidenceThreshold": 0.6},
    }
    resource.update(overrides)
    return resource


def multiple_choice() -> dict[str, Any]:
    def option(letter: str, text: str, correct: bool) -> dict[str, Any]:
        return {"id": f"rec-item:{letter}", "text": text, "isCorrect": correct, "feedback": "",
                "sourceFragmentIds": [FRAGMENT_A], "decision": "pendiente", "reliabilityWarning": None}

    return {
        "id": "rec-item",
        "type": "item_opcion_multiple",
        "version": 1,
        "body": "Según el material, ¿qué protocolo está orientado a la conexión?",
        "options": [option("a", "TCP", True), option("b", "UDP", False), option("c", "SYN", False), option("d", "IP", False)],
        "citations": [{"claim": "El protocolo TCP está orientado a la conexión.", "fragmentIds": [FRAGMENT_A]}],
        "evidence": evidence((FRAGMENT_A, TEXT_A)),
        "grounding": {"threshold": 0.6},
    }


def guided_exploration(steps: int = 3) -> dict[str, Any]:
    texts = [
        ("Acuerdo inicial", "Observa cómo el cliente envía un segmento SYN.", "¿Qué envía el cliente al iniciar la conexión?"),
        ("Respuesta", "Observa cómo el servidor responde con SYN-ACK.", "¿Qué responde el servidor?"),
        ("Confirmación", "Observa cómo el cliente confirma con ACK.", "¿Con qué confirma el cliente la conexión?"),
    ]
    return {
        "id": "rec-guia",
        "type": "exploracion_guiada",
        "version": 1,
        "body": "Explora el acuerdo en tres pasos de TCP.",
        "options": None,
        "citations": [{"claim": "TCP establece la conexión mediante un acuerdo en tres pasos.", "fragmentIds": [FRAGMENT_A]}],
        "structure": {
            "guidedSteps": [
                {"title": title, "instruction": instruction, "question": question, "fragmentIds": [FRAGMENT_A]}
                for title, instruction, question in texts[:steps]
            ]
        },
        "evidence": evidence((FRAGMENT_A, TEXT_A)),
    }


def verify(resource: dict[str, Any]) -> dict[str, Any]:
    return verify_resource(resource, threshold=0.6, rule_version=VERIFICATION_RULE_VERSION)


# --------------------------------------------------------------------------- resultado vigente

def test_complete_copy_with_supported_claims_is_current():
    resource = explanation()
    result = verify(resource)
    assert result["status"] == "current" and result["reason"] is None
    assert result["fingerprint"] == content_fingerprint(resource)
    assert result["verifiedVersion"] == 3
    assert result["evidenceThreshold"] == 0.6 and result["ruleVersion"] == VERIFICATION_RULE_VERSION
    assert result["checkedAt"] and result["retryAvailable"] is False
    assert result["summary"]["checkedClaims"] == 2 and result["summary"]["supportedClaims"] == 2


def test_unknown_retrieval_date_does_not_invalidate_the_copy():
    """REV-R11: en recursos migrados la fecha de recuperación puede ser desconocida (`null`)."""
    resource = explanation()
    for fragment in resource["evidence"]:
        fragment["retrievedAt"] = None
    assert verify(resource)["status"] == "current"
    resource_without_field = explanation(evidence=[{k: v for k, v in f.items() if k != "retrievedAt"} for f in resource["evidence"]])
    assert verify(resource_without_field)["status"] == "current"


def test_verification_does_not_modify_the_resource():
    resource = explanation()
    before = copy.deepcopy(resource)
    verify(resource)
    assert resource == before


# --------------------------------------------------------------------------- respaldo insuficiente

def test_claim_without_support_is_insufficient_with_a_reason():
    """REV-C1: una afirmación editada que el material no respalda deja la verificación insuficiente."""
    resource = explanation(citations=[{"claim": UNSUPPORTED, "fragmentIds": [FRAGMENT_A]}])
    result = verify(resource)
    assert result["status"] == "insufficient"
    assert result["reason"] and result["retryAvailable"] is False
    assert result["summary"]["removedClaims"]


def test_explanation_paragraph_without_support_is_insufficient():
    """REV-C1: en la explicación también se contrasta cada párrafo del cuerpo."""
    resource = explanation(body=f"{UNSUPPORTED}\n\nLas órbitas bajas permiten fotografías satelitales de alta resolución.")
    result = verify(resource)
    assert result["status"] == "insufficient"
    assert result["summary"]["checkedParagraphs"] == 2 and result["summary"]["supportedParagraphs"] == 0


def test_guided_exploration_with_fewer_linked_steps_than_the_minimum_is_insufficient():
    assert verify(guided_exploration(steps=3))["status"] == "current"
    resource = guided_exploration(steps=3)
    resource["structure"]["guidedSteps"][2] = {
        "title": "Satélites", "instruction": UNSUPPORTED, "question": "¿A qué altura orbitan los satélites?",
        "fragmentIds": [FRAGMENT_A],
    }
    result = verify(resource)
    assert result["status"] == "insufficient" and "paso" in result["reason"]


# --------------------------------------------------------------------------- copia incompleta: pendiente sin reintento

@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda r: r.update(evidence=[]), id="sin-copia"),
        pytest.param(lambda r: r.pop("evidence"), id="sin-campo-evidence"),
        pytest.param(lambda r: r.update(evidence=evidence((FRAGMENT_A, TEXT_A))), id="falta-un-fragmento-citado"),
        pytest.param(lambda r: r["evidence"][1].update(text=""), id="fragmento-sin-texto"),
    ],
)
def test_incomplete_copy_is_pending_without_retry(change):
    """REV-R6 y REV-C3: sin copia, o con un fragmento referenciado sin texto, solo queda regenerar."""
    resource = explanation()
    change(resource)
    result = verify(resource)
    assert result["status"] == "pending" and result["retryAvailable"] is False
    assert "regenera" in result["reason"].lower()


def test_fragments_referenced_by_options_and_structure_must_be_in_the_copy():
    item = multiple_choice()
    item["options"][1]["sourceFragmentIds"] = [FRAGMENT_B]  # no está en la copia del ítem
    assert verify(item)["status"] == "pending"

    guide = guided_exploration()
    guide["structure"]["guidedSteps"][0]["fragmentIds"] = [FRAGMENT_B]
    assert verify(guide)["status"] == "pending"


def test_unexpected_error_is_pending_with_retry(monkeypatch):
    """REV-C3: si la comprobación no pudo completarse, se ofrece «Reintentar comprobación»."""
    def broken(*args, **kwargs):
        raise RuntimeError("fallo inesperado")

    monkeypatch.setattr(resource_verification, "verify_citations", broken)
    result = verify(explanation())
    assert result["status"] == "pending" and result["retryAvailable"] is True
    assert result["reason"]


# --------------------------------------------------------------------------- umbral guardado

@pytest.mark.parametrize(
    ("resource", "expected"),
    [
        pytest.param({"verification": {"evidenceThreshold": 0.7}, "grounding": {"threshold": 0.5}, "params": {"evidenceThreshold": 0.4}},
                     0.7, id="verificacion"),
        pytest.param({"grounding": {"threshold": 0.5}, "params": {"evidenceThreshold": 0.4}}, 0.5, id="grounding"),
        pytest.param({"grounding": None, "params": {"evidenceThreshold": 0.4}}, 0.4, id="pedido"),
        pytest.param({}, DEFAULT_THRESHOLD, id="por-defecto"),
    ],
)
def test_stored_threshold_priority(resource, expected):
    """REV-R3: se usa el umbral registrado en el resultado de verificación del recurso."""
    assert stored_threshold(resource) == expected


def test_the_threshold_decides_the_result():
    # Una afirmación con parte de sus palabras en el material: pasa con un umbral bajo y no con uno alto.
    resource = explanation(citations=[{"claim": "TCP y UDP orbitan satélites geoestacionarios lejanos.", "fragmentIds": [FRAGMENT_A]}],
                           body="Texto breve.")
    assert verify_resource(resource, threshold=0.3, rule_version=1)["status"] == "current"
    assert verify_resource(resource, threshold=0.9, rule_version=1)["status"] == "insufficient"


# --------------------------------------------------------------------------- fiabilidad de distractores (REV-C4)

def test_edited_distractor_that_the_evidence_shows_as_correct_gets_a_warning():
    # El material dice «Los dos protocolos principales de esta capa en Internet son TCP y UDP»: si el docente cambia un
    # distractor a «UDP», ese distractor también es correcto según la evidencia.
    item = multiple_choice()
    item["body"] = "Según el material, ¿cuál es uno de los dos protocolos principales de esta capa en Internet?"
    item["options"][1]["text"] = "UDP"
    warnings = assess_edited_distractors(item, edited_option_ids={"rec-item:b"})
    assert set(warnings) == {"rec-item:b"} and "material también lo presenta" in warnings["rec-item:b"]

    item["options"][1]["text"] = "DNS"  # no aparece en el material: es un distractor defendible
    assert assess_edited_distractors(item, edited_option_ids={"rec-item:b"}) == {"rec-item:b": None}


def test_only_edited_distractors_are_assessed_and_the_key_never_is():
    item = multiple_choice()
    warnings = assess_edited_distractors(item, edited_option_ids={"rec-item:a", "rec-item:c"})
    assert "rec-item:a" not in warnings
    assert warnings == {"rec-item:c": None}


def test_a_distractor_warning_does_not_change_the_verification_status():
    """REV-C4: el aviso de fiabilidad se muestra al docente; la aprobación sigue sus reglas vigentes."""
    item = multiple_choice()
    item["options"][1]["reliabilityWarning"] = "El material también lo presenta como respuesta."
    assert verify(item)["status"] == "current"
