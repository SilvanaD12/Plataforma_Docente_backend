"""REV-01 · Huella del contenido verificable (REV-R1, REV-R2 · REV-C2, C4, C5).

La huella cambia solo cuando cambia lo que la verificación contrasta con la evidencia: el cuerpo, las afirmaciones y
sus fragmentos, las alternativas y los campos de la estructura. Los cambios visuales, los metadatos de revisión y el
orden de alternativas con identificadores estables la conservan.
"""

from __future__ import annotations

import copy
import re
from typing import Any

import pytest

from platform5e.domain.review.content_fingerprint import content_fingerprint, normalize_verifiable_content

FRAGMENT_A = "frag-48d6fc446d5b412d"
FRAGMENT_B = "frag-6d792e371d524a21"


def explanation() -> dict[str, Any]:
    return {
        "id": "rec-explicacion",
        "type": "explicacion",
        "format": "text",
        "title": "Capa de transporte: explicación del material",
        "body": "Los dos protocolos principales de esta capa en Internet son TCP y UDP.\n\n"
        "UDP tiene menor latencia que TCP porque no espera confirmaciones ni retransmite datos.",
        "bodyHtml": None,
        "structure": None,
        "options": None,
        "citations": [
            {"claim": "Los dos protocolos principales de esta capa en Internet son TCP y UDP.", "fragmentIds": [FRAGMENT_A]},
            {"claim": "UDP tiene menor latencia que TCP porque no espera confirmaciones ni retransmite datos.", "fragmentIds": [FRAGMENT_B]},
        ],
        "status": "pendiente",
        "edited": False,
        "createdAt": "2026-11-08T15:23:06+00:00",
        "updatedAt": "2026-11-08T15:23:06+00:00",
        "evidence": [{"id": FRAGMENT_A, "text": "Texto A"}, {"id": FRAGMENT_B, "text": "Texto B"}],
        "grounding": {"threshold": 0.6, "checkedClaims": 2, "supportedClaims": 2},
        "media": None,
    }


def multiple_choice() -> dict[str, Any]:
    def option(letter: str, text: str, correct: bool, decision: str = "pendiente") -> dict[str, Any]:
        return {
            "id": f"rec-item:{letter}",
            "text": text,
            "isCorrect": correct,
            "feedback": f"Retroalimentación de {text}.",
            "sourceFragmentIds": [FRAGMENT_A],
            "decision": decision,
            "discardReason": None,
            "edited": False,
            "misconception": None if correct else f"Confunde {text} con capa de transporte.",
            "reliabilityWarning": None,
        }

    return {
        "id": "rec-item",
        "type": "item_opcion_multiple",
        "format": "text",
        "title": "Concepto clave 1: Capa de transporte",
        "body": "Según el material, ¿qué término completa la afirmación?\n\n«La ________ ofrece comunicación de extremo a extremo.»",
        "structure": None,
        "options": [
            option("a", "capa de transporte", True),
            option("b", "TCP", False),
            option("c", "UDP", False),
            option("d", "SYN", False),
        ],
        "citations": [{"claim": "La capa de transporte ofrece comunicación de extremo a extremo.", "fragmentIds": [FRAGMENT_A]}],
        "status": "pendiente",
    }


def image() -> dict[str, Any]:
    return {
        "id": "rec-imagen",
        "type": "imagen_ilustrativa",
        "format": "image",
        "title": "Imagen para observar: capa de transporte",
        "body": "Observa la imagen y responde.",
        "structure": {
            "prompt": "Ilustración didáctica de la comunicación de extremo a extremo entre procesos.",
            "alt": "Ilustración sobre capa de transporte",
            "caption": "La capa de transporte ofrece comunicación de extremo a extremo entre procesos.",
        },
        "options": None,
        "citations": [{"claim": "La capa de transporte ofrece comunicación de extremo a extremo.", "fragmentIds": [FRAGMENT_A]}],
        "media": {"status": "fallback", "note": "Sin imagen generada."},
        "status": "pendiente",
    }


def ordering() -> dict[str, Any]:
    return {
        "id": "rec-orden",
        "type": "ordenar_pasos",
        "format": "interactive",
        "title": "Ordena el acuerdo en tres pasos",
        "body": "Ordena los pasos del establecimiento de conexión de TCP.",
        "structure": {"sequence": ["El cliente envía SYN.", "El servidor responde SYN-ACK.", "El cliente confirma con ACK."]},
        "options": None,
        "citations": [{"claim": "TCP establece la conexión mediante un acuerdo en tres pasos.", "fragmentIds": [FRAGMENT_A]}],
        "status": "pendiente",
    }


def changed(resource: dict[str, Any], change) -> dict[str, Any]:
    edited = copy.deepcopy(resource)
    change(edited)
    return edited


def test_fingerprint_is_a_sha256_digest():
    fingerprint = content_fingerprint(explanation())
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint)
    assert content_fingerprint(explanation()) == fingerprint  # determinista


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda r: r.update(body="  Los dos protocolos principales   de esta capa en Internet son TCP y UDP.\n\n\n"
                                        "UDP tiene menor latencia que TCP porque no espera confirmaciones ni retransmite datos.  "),
                     id="espacios-equivalentes"),
        pytest.param(lambda r: r.update(bodyHtml="<p><strong>Los dos protocolos</strong> principales…</p>"), id="formato-html"),
        pytest.param(lambda r: r.update(title="Otro título"), id="titulo"),
        pytest.param(lambda r: r.update(status="aprobado", edited=True, updatedAt="2026-11-09T10:00:00+00:00"), id="metadatos-de-revision"),
        pytest.param(lambda r: r.update(media={"status": "ready", "id": "media-1"}), id="multimedia"),
        pytest.param(lambda r: r.update(evidence=[], grounding=None, verification={"status": "current"}), id="evidencia-y-resultados"),
        pytest.param(lambda r: r["citations"].reverse(), id="orden-de-las-citas"),
    ],
)
def test_visual_changes_and_internal_metadata_keep_the_fingerprint(change):
    """REV-R2: formato, espacios equivalentes y metadatos internos no cambian la huella."""
    original = explanation()
    assert content_fingerprint(changed(original, change)) == content_fingerprint(original)


def test_reordering_options_with_stable_ids_keeps_the_fingerprint():
    """REV-C2: reordenar las alternativas con los mismos identificadores conserva la huella."""
    original = multiple_choice()
    assert content_fingerprint(changed(original, lambda r: r["options"].reverse())) == content_fingerprint(original)


def test_changing_only_a_distractor_decision_keeps_the_fingerprint():
    """REV-C4: cambiar solo la decisión de revisión de un distractor no exige verificar de nuevo."""
    original = multiple_choice()

    def decide(resource):
        resource["options"][1].update(decision="descartado", discardReason="sin_sentido", edited=True)
        resource["options"][2].update(decision="aceptado", reliabilityWarning="Otro aviso.")

    assert content_fingerprint(changed(original, decide)) == content_fingerprint(original)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda r: r["options"][0].update(text="capa de red"), id="texto-de-la-respuesta-correcta"),
        pytest.param(lambda r: (r["options"][0].update(isCorrect=False), r["options"][1].update(isCorrect=True)),
                     id="otra-respuesta-correcta"),
        pytest.param(lambda r: r["options"][1].update(text="IP"), id="texto-de-un-distractor"),
        pytest.param(lambda r: r["options"][2].update(feedback="Otra explicación."), id="feedback"),
        pytest.param(lambda r: r.update(body="Según el material, ¿qué capa ofrece comunicación de extremo a extremo?"), id="enunciado"),
        pytest.param(lambda r: r["citations"][0].update(claim="La capa de red enruta paquetes."), id="afirmacion"),
    ],
)
def test_content_changes_alter_the_fingerprint(change):
    """REV-C2 y REV-C4: la respuesta correcta, los distractores, las explicaciones y el enunciado son verificables."""
    original = multiple_choice()
    assert content_fingerprint(changed(original, change)) != content_fingerprint(original)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param(lambda r: r["citations"][0].update(fragmentIds=[FRAGMENT_B]), id="fragmentos-de-una-cita"),
        pytest.param(lambda r: r["options"][1].update(sourceFragmentIds=[FRAGMENT_B]), id="fragmentos-de-una-alternativa"),
    ],
)
def test_changing_linked_fragments_alters_the_fingerprint(change):
    """REV-R6: las fuentes vinculadas son los fragmentIds que referencia el recurso."""
    original = multiple_choice()
    assert content_fingerprint(changed(original, change)) != content_fingerprint(original)


def test_structure_fragment_ids_are_part_of_the_fingerprint():
    """REV-R6: los fragmentos de pasos, predicciones y criterios también son fuentes vinculadas."""
    original = {
        "id": "rec-guia",
        "type": "exploracion_guiada",
        "body": "Explora el acuerdo en tres pasos.",
        "citations": [],
        "structure": {
            "guidedSteps": [
                {"title": f"Paso {n}", "instruction": f"Observa el segmento {n}.", "question": f"¿Qué indica el segmento {n}?",
                 "fragmentIds": [FRAGMENT_A]}
                for n in (1, 2, 3)
            ]
        },
    }
    edited = changed(original, lambda r: r["structure"]["guidedSteps"][0].update(fragmentIds=[FRAGMENT_B]))
    assert content_fingerprint(edited) != content_fingerprint(original)


@pytest.mark.parametrize(
    ("field", "value"),
    [("prompt", "Ilustración de un datagrama UDP."), ("caption", "UDP no garantiza la entrega.")],
)
def test_image_prompt_and_caption_alter_the_fingerprint(field, value):
    original = image()
    edited = changed(original, lambda r: r["structure"].update({field: value}))
    assert content_fingerprint(edited) != content_fingerprint(original)


def test_image_alt_text_is_not_part_of_the_fingerprint():
    """D1: `alt` es texto de accesibilidad; corregirlo no debe devolver a revisión un recurso aprobado."""
    original = image()
    edited = changed(original, lambda r: r["structure"].update(alt="Diagrama de dos computadoras conectadas"))
    assert content_fingerprint(edited) == content_fingerprint(original)
    assert "alt" not in (normalize_verifiable_content(original)["structure"] or {})


def test_order_of_steps_is_content():
    """En `ordenar_pasos` el orden de la secuencia es la respuesta: cambiarlo cambia la huella."""
    original = ordering()
    edited = changed(original, lambda r: r["structure"]["sequence"].reverse())
    assert content_fingerprint(edited) != content_fingerprint(original)


def test_incomplete_structure_still_has_a_stable_fingerprint():
    """Una estructura que todavía no alcanza el mínimo del tipo se puede guardar y debe tener una huella estable."""
    original = changed(ordering(), lambda r: r["structure"].update(sequence=["Solo un paso."]))
    assert content_fingerprint(original) == content_fingerprint(copy.deepcopy(original))
    assert content_fingerprint(original) != content_fingerprint(ordering())


def test_result_of_another_version_is_detected_by_its_fingerprint():
    """REV-C5: un resultado guardado con la huella de una versión anterior no corresponde a la versión actual."""
    previous = multiple_choice()
    stored_result = {"status": "current", "fingerprint": content_fingerprint(previous)}
    current = changed(previous, lambda r: r["options"][0].update(text="capa de red"))
    assert stored_result["fingerprint"] != content_fingerprint(current)


def test_normalized_content_lists_only_verifiable_fields():
    normalized = normalize_verifiable_content(multiple_choice())
    assert set(normalized) == {"type", "body", "citations", "options", "structure"}
    assert set(normalized["options"][0]) == {"id", "text", "isCorrect", "feedback", "sourceFragmentIds"}
    assert [option["id"] for option in normalized["options"]] == sorted(option["id"] for option in normalized["options"])
