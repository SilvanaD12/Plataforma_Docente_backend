"""Pruebas unitarias de los errores del módulo de Revisión (domain/review/errors.py)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from platform5e.domain.review.errors import (
    MATERIAL_STATE_CODES,
    RegenerationFailedError,
)
from platform5e.infrastructure.http.error_handlers import domain_error_handler


def test_material_state_codes_includes_plan_evidence_stale():
    assert "PLAN_EVIDENCE_STALE" in MATERIAL_STATE_CODES


@pytest.mark.asyncio
async def test_regeneration_failed_error_with_plan_evidence_stale_gives_409_and_preserves_details():
    stale_details = [
        {
            "documentId": "doc-api-1",
            "documentName": "protocolos_tcp_udp.pdf",
            "missingFragmentIds": ["frag-1a2b", "frag-3c4d"],
        }
    ]
    error = RegenerationFailedError(
        reason="El material del plan cambió. Crea un plan nuevo.",
        code="PLAN_EVIDENCE_STALE",
        details=stale_details,
    )

    assert error.status_code == 409
    assert error.code == "PLAN_EVIDENCE_STALE"
    assert error.details == stale_details

    # Comprobación de serialización uniforme mediante domain_error_handler
    response = await domain_error_handler(MagicMock(), error)
    assert response.status_code == 409
    payload = json.loads(response.body)
    assert payload == {
        "error": {
            "code": "PLAN_EVIDENCE_STALE",
            "message": "El material del plan cambió. Crea un plan nuevo.",
            "details": stale_details,
        }
    }


@pytest.mark.asyncio
async def test_regeneration_failed_error_without_details_does_not_include_details_key():
    error = RegenerationFailedError(
        reason="No hay material procesado en la unidad.",
        code="NO_PROCESSED_MATERIAL",
    )

    assert error.status_code == 409
    assert error.code == "NO_PROCESSED_MATERIAL"
    assert not hasattr(error, "details")

    # Comprobación de serialización uniforme: sin la clave 'details'
    response = await domain_error_handler(MagicMock(), error)
    assert response.status_code == 409
    payload = json.loads(response.body)
    assert "details" not in payload["error"]
    assert payload == {
        "error": {
            "code": "NO_PROCESSED_MATERIAL",
            "message": "No hay material procesado en la unidad.",
        }
    }
