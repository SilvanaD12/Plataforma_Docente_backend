"""Pruebas unitarias para MAT-P3 (Pedido P8): reintento acotado y aviso explícito ante fallo de IA."""

from __future__ import annotations

import pytest

from platform5e.application.use_cases.generation.run_generation_request import (
    AI_RETRY_FAILED_MESSAGE,
    _run_with_ai_retry,
)
from platform5e.infrastructure.llm.gemini_language_model import AIProviderError


def test_ai_retry_recovers_from_transient_error() -> None:
    calls = {"count": 0}

    def flaky_operation() -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise AIProviderError("timeout temporal", status_code=503, public_reason="el proveedor no respondió")
        return "ok"

    retries: list[int] = []
    result = _run_with_ai_retry(
        flaky_operation,
        max_retries=1,
        backoff_seconds=0.0,
        on_retry=lambda attempt, _exc: retries.append(attempt),
    )

    assert result == "ok"
    assert calls["count"] == 2
    assert retries == [1]


def test_ai_retry_raises_after_exhausting_attempts_without_leaking_secrets() -> None:
    def always_failing_operation() -> str:
        raise AIProviderError(
            "Gemini respondió 429 con api_key:AIzaSyDummySecretKey123456789012345",
            status_code=429,
            public_reason="límite de uso de Gemini alcanzado (429)",
        )

    with pytest.raises(AIProviderError) as exc_info:
        _run_with_ai_retry(always_failing_operation, max_retries=1, backoff_seconds=0.0)

    warning_message = f"{AI_RETRY_FAILED_MESSAGE} Motivo: {exc_info.value.public_reason}."
    assert "AIzaSy" not in warning_message
    assert "5E" not in warning_message
    assert "reintentar" in warning_message.lower()