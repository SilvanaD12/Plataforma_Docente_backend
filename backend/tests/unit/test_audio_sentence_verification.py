"""QA-11 · Verificación frase por frase de guiones de audio (audio_detonante y podcast_resumen).

Cada frase del guion se contrasta con los fragmentos citados y recuperados.
Un guion con al menos una frase sin respaldo queda `insufficient` con el motivo que nombra la frase.
Los audios aprobados antes del cambio se reverifican al leerlos (verificación heredada).
"""

from __future__ import annotations

from typing import Any
import pytest

from platform5e.application.services.review.legacy_verification import upgrade_resource_verification
from platform5e.domain.generation.grounding import VERIFICATION_RULE_VERSION
from platform5e.domain.review.resource_verification import CURRENT, INSUFFICIENT, verify_resource
from tests.unit.test_legacy_stored_data import StoredResources

FRAGMENT_ID = "frag-audio-1"
EVIDENCE_TEXT = (
    "El protocolo TCP confirma la entrega de los datos al receptor. Retransmite los paquetes perdidos. "
    "El protocolo UDP envía datagramas sin confirmación previa y ofrece menor latencia para aplicaciones en tiempo real."
)
CLAIM_TEXT = "El protocolo TCP confirma la entrega de los datos al receptor."
UNSUPPORTED_SENTENCE = "Los satélites geoestacionarios orbitan sobre el ecuador terrestre a gran altura."


def make_audio_resource(
    resource_type: str = "audio_detonante",
    script: str = "El protocolo TCP confirma la entrega de los datos. Retransmite los paquetes perdidos.",
    **overrides: Any,
) -> dict[str, Any]:
    resource = {
        "id": "rec-audio-1",
        "unitId": "u1",
        "type": resource_type,
        "format": "audio",
        "version": 1,
        "title": "Cápsula de transporte",
        "body": "Escucha la cápsula sobre TCP y UDP.",
        "structure": {"script": script},
        "options": None,
        "citations": [{"claim": CLAIM_TEXT, "fragmentIds": [FRAGMENT_ID]}],
        "evidence": [
            {
                "id": FRAGMENT_ID,
                "text": EVIDENCE_TEXT,
                "location": "sección 1",
                "documentId": "doc-1",
                "documentName": "redes.txt",
                "retrievedAt": None,
            }
        ],
        "params": {"evidenceThreshold": 0.6},
    }
    resource.update(overrides)
    return resource


# --------------------------------------------------------------------------- Verificación de guion respaldado vs insuficiente


@pytest.mark.parametrize("audio_type", ["audio_detonante", "podcast_resumen"])
def test_audio_script_with_all_sentences_supported_is_current(audio_type):
    resource = make_audio_resource(
        resource_type=audio_type,
        script="El protocolo TCP confirma la entrega de los datos. UDP ofrece menor latencia para aplicaciones en tiempo real.",
    )
    result = verify_resource(resource, threshold=0.6, rule_version=VERIFICATION_RULE_VERSION)

    assert result["status"] == CURRENT
    assert result["reason"] is None
    assert result["ruleVersion"] == VERIFICATION_RULE_VERSION
    assert result["summary"]["scriptThreshold"] == 0.6
    assert result["summary"]["checkedSentences"] == 2
    assert result["summary"]["supportedSentences"] == 2
    assert result["summary"]["unsupportedSentences"] == []


@pytest.mark.parametrize("audio_type", ["audio_detonante", "podcast_resumen"])
def test_audio_script_with_unsupported_sentence_is_insufficient_with_reason(audio_type):
    resource = make_audio_resource(
        resource_type=audio_type,
        title="Audio de prueba",
        script=f"El protocolo TCP confirma la entrega de los datos. {UNSUPPORTED_SENTENCE}",
    )
    result = verify_resource(resource, threshold=0.6, rule_version=VERIFICATION_RULE_VERSION)

    assert result["status"] == INSUFFICIENT
    assert "Audio de prueba" in result["reason"]
    assert UNSUPPORTED_SENTENCE in result["reason"]
    assert "no tiene respaldo en el material" in result["reason"]
    assert result["summary"]["checkedSentences"] == 2
    assert result["summary"]["supportedSentences"] == 1
    assert len(result["summary"]["unsupportedSentences"]) == 1
    assert result["summary"]["unsupportedSentences"][0]["text"] == UNSUPPORTED_SENTENCE


def test_audio_without_script_is_insufficient():
    resource = make_audio_resource(script="")
    resource["structure"] = {}
    resource["body"] = ""
    result = verify_resource(resource, threshold=0.6, rule_version=VERIFICATION_RULE_VERSION)

    assert result["status"] == INSUFFICIENT
    assert "no tiene guion" in result["reason"].lower()


def test_short_intro_or_transition_sentences_do_not_cause_failure():
    # Frases de transición con menos palabras útiles que MIN_CLAIM_TERMS no se consideran afirmaciones no respaldadas
    resource = make_audio_resource(
        script="¡Hola! El protocolo TCP confirma la entrega de los datos al receptor. ¡Atención! UDP ofrece menor latencia."
    )
    result = verify_resource(resource, threshold=0.6, rule_version=VERIFICATION_RULE_VERSION)

    assert result["status"] == CURRENT
    assert result["reason"] is None
    assert result["summary"]["supportedSentences"] == 2


def test_audio_with_only_empty_or_trivial_sentences_is_insufficient():
    resource = make_audio_resource(script="¡Hola! ¡Gracias!")
    result = verify_resource(resource, threshold=0.6, rule_version=VERIFICATION_RULE_VERSION)

    assert result["status"] == INSUFFICIENT
    assert "afirmaciones suficientes" in result["reason"].lower()


# --------------------------------------------------------------------------- Reverificación al leer (verificación heredada)


def test_reading_approved_audio_with_older_rule_version_and_unsupported_sentence_drops_to_pending():
    # Audio aprobado bajo ruleVersion 1 con una frase que no tiene respaldo en el material
    resource = make_audio_resource(
        status="aprobado",
        decidedAt="2026-11-10T12:00:00",
        script=f"El protocolo TCP confirma la entrega de los datos. {UNSUPPORTED_SENTENCE}",
        verification={
            "status": "current",
            "reason": None,
            "ruleVersion": 1,
            "evidenceThreshold": 0.6,
            "verifiedVersion": 1,
            "fingerprint": "sha256:abc123",
            "checkedAt": "2026-11-10T12:00:00",
            "retryAvailable": False,
            "summary": {"checkedClaims": 1, "supportedClaims": 1},
        },
    )
    repo = StoredResources(resource)
    upgraded = upgrade_resource_verification(repo, "docente-1", "u1", resource)

    assert upgraded["status"] == "pendiente"
    assert upgraded["decidedAt"] is None
    assert upgraded["verification"]["status"] == INSUFFICIENT
    assert upgraded["verification"]["ruleVersion"] == VERIFICATION_RULE_VERSION
    assert "La regla de verificación cambió (v1 → v2)." in upgraded["verification"]["reason"]
    assert UNSUPPORTED_SENTENCE in upgraded["verification"]["reason"]
    # Se guardó en el repositorio sin incrementar la versión
    assert repo.saves == [(1, False)]


def test_reading_approved_audio_with_older_rule_version_and_supported_sentences_stays_approved():
    # Audio aprobado bajo ruleVersion 1 donde todas las frases están respaldadas
    resource = make_audio_resource(
        status="aprobado",
        decidedAt="2026-11-10T12:00:00",
        script="El protocolo TCP confirma la entrega de los datos al receptor. Retransmite los paquetes perdidos.",
        verification={
            "status": "current",
            "reason": None,
            "ruleVersion": 1,
            "evidenceThreshold": 0.6,
            "verifiedVersion": 1,
            "fingerprint": "sha256:abc123",
            "checkedAt": "2026-11-10T12:00:00",
            "retryAvailable": False,
            "summary": {"checkedClaims": 1, "supportedClaims": 1},
        },
    )
    repo = StoredResources(resource)
    upgraded = upgrade_resource_verification(repo, "docente-1", "u1", resource)

    assert upgraded["status"] == "aprobado"
    assert upgraded["decidedAt"] == "2026-11-10T12:00:00"
    assert upgraded["verification"]["status"] == CURRENT
    assert upgraded["verification"]["ruleVersion"] == VERIFICATION_RULE_VERSION
    assert upgraded["verification"]["reason"] is None
    assert repo.saves == [(1, False)]


def test_reading_already_upgraded_audio_does_not_save_again():
    # Audio con ruleVersion 2 actual ya no se vuelve a verificar ni a guardar
    resource = make_audio_resource(
        status="aprobado",
        decidedAt="2026-11-10T12:00:00",
        script="El protocolo TCP confirma la entrega de los datos.",
        verification={
            "status": "current",
            "reason": None,
            "ruleVersion": VERIFICATION_RULE_VERSION,
            "evidenceThreshold": 0.6,
            "verifiedVersion": 1,
            "fingerprint": "sha256:abc123",
            "checkedAt": "2026-11-15T12:00:00",
            "retryAvailable": False,
            "summary": {"scriptThreshold": 0.6, "checkedSentences": 1, "supportedSentences": 1},
        },
    )
    repo = StoredResources(resource)
    upgraded = upgrade_resource_verification(repo, "docente-1", "u1", resource)

    assert upgraded is resource
    assert repo.saves == []


def test_reading_non_audio_resource_with_older_rule_version_retains_its_result():
    # Un recurso no audio (p. ej. explicación) conserva su resultado bajo la regla con que fue creado
    non_audio = {
        "id": "rec-exp-1",
        "unitId": "u1",
        "type": "explicacion",
        "status": "aprobado",
        "decidedAt": "2026-11-10T12:00:00",
        "body": "Texto de explicación.",
        "citations": [{"claim": CLAIM_TEXT, "fragmentIds": [FRAGMENT_ID]}],
        "evidence": [{"id": FRAGMENT_ID, "text": EVIDENCE_TEXT}],
        "verification": {
            "status": "current",
            "reason": None,
            "ruleVersion": 1,
            "evidenceThreshold": 0.6,
            "verifiedVersion": 1,
            "fingerprint": "sha256:exp123",
            "checkedAt": "2026-11-10T12:00:00",
            "retryAvailable": False,
        },
    }
    repo = StoredResources(non_audio)
    upgraded = upgrade_resource_verification(repo, "docente-1", "u1", non_audio)

    assert upgraded is non_audio
    assert upgraded["verification"]["ruleVersion"] == 1
    assert repo.saves == []
