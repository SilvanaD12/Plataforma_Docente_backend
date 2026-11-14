"""GEN-01 (T073, seguimiento): cuando el texto de Gemini no es JSON válido, el error dice por qué.

Con gemini-3.5-flash-lite, la actividad kinestésica y la imagen ilustrativa terminaban con «La respuesta del modelo no
es JSON válido.» tras dos llamadas de unos 115 s. La hipótesis es que el modelo repite texto hasta el límite de tokens
y el JSON queda cortado. El mensaje (que llega a `fallbackReason`) agrega finishReason, los tokens de la respuesta y
su largo, y el registro guarda el comienzo y el final del texto. Sin red: respuestas HTTP falsas.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest

from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.application.services.generation.step_drafting import draft_resources
from platform5e.infrastructure.llm.gemini_language_model import RETRY_PROMPT_SUFFIX, GeminiLanguageModel
from tests.unit.test_kinesthetic_activity import context

API_KEY = "clave-de-prueba-secreta"
# Un recurso que se repite hasta cortarse: el JSON no cierra.
LOOPING_TEXT = '{"recursos": [{"titulo": "Paso", "contenido": "' + "Formen grupos y repitan. " * 7200


def gemini_answer(text: str, finish_reason: str | None = None, tokens: int | None = None) -> dict[str, Any]:
    candidate: dict[str, Any] = {"content": {"parts": [{"text": text}]}}
    if finish_reason:
        candidate["finishReason"] = finish_reason
    answer: dict[str, Any] = {"candidates": [candidate]}
    if tokens is not None:
        answer["usageMetadata"] = {"promptTokenCount": 1200, "candidatesTokenCount": tokens}
    return answer


class FakeGemini:
    """Responde cada llamada con la siguiente respuesta de la lista y guarda los prompts recibidos."""

    def __init__(self, *answers: dict[str, Any]) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.prompts.append(json.loads(request.content)["contents"][0]["parts"][0]["text"])
        return httpx.Response(200, json=self.answers.pop(0))

    def model(self) -> GeminiLanguageModel:
        return GeminiLanguageModel("gemini", API_KEY, model="gemini-3.5-flash-lite",
                                   client=httpx.Client(transport=httpx.MockTransport(self)))


def characters(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def test_truncated_json_reports_finish_reason_tokens_and_length(caplog):
    fake = FakeGemini(gemini_answer(LOOPING_TEXT, "MAX_TOKENS", 65536), gemini_answer(LOOPING_TEXT, "MAX_TOKENS", 65536))
    with caplog.at_level(logging.WARNING), pytest.raises(ValueError) as invalid:
        fake.model().generate(context())
    assert str(invalid.value) == (
        f"La respuesta del modelo no es JSON válido (finishReason MAX_TOKENS, 65 536 tokens, "
        f"{characters(len(LOOPING_TEXT))} caracteres)."
    )
    assert len(fake.prompts) == 2 and fake.prompts[1].endswith(RETRY_PROMPT_SUFFIX)

    # Cada intento inválido queda en el registro con el comienzo y el final del texto, sin la clave ni el prompt.
    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 2
    assert all(LOOPING_TEXT[:300] in message and LOOPING_TEXT[-300:] in message for message in warnings)
    assert "intento 1 de 2" in warnings[0] and "intento 2 de 2" in warnings[1]
    assert not any(API_KEY in message or "FRAGMENTOS DEL MATERIAL" in message for message in warnings)


def test_when_both_calls_fail_the_last_one_is_reported():
    fake = FakeGemini(gemini_answer(LOOPING_TEXT, "MAX_TOKENS", 65536), gemini_answer('{"recursos": [', "STOP", 9))
    with pytest.raises(ValueError) as invalid:
        fake.model().generate(context())
    assert str(invalid.value) == "La respuesta del modelo no es JSON válido (finishReason STOP, 9 tokens, 14 caracteres)."


def test_without_finish_reason_or_usage_the_message_is_still_clear():
    fake = FakeGemini(gemini_answer("no es json"), gemini_answer("tampoco es json"))
    with pytest.raises(ValueError) as invalid:
        fake.model().generate(context())
    assert str(invalid.value) == "La respuesta del modelo no es JSON válido (15 caracteres)."


def test_an_empty_answer_keeps_its_message_with_the_finish_reason():
    fake = FakeGemini(gemini_answer("", "SAFETY"), gemini_answer("", "SAFETY"))
    with pytest.raises(ValueError) as invalid:
        fake.model().generate(context())
    assert str(invalid.value) == "La respuesta del modelo está vacía (finishReason SAFETY, 0 caracteres)."


def test_valid_json_is_unaffected(caplog):
    valid = {"recursos": [{"titulo": "Actividad", "contenido": "Hagan los pasos.", "citas": [], "alternativas": []}]}
    fake = FakeGemini(gemini_answer(json.dumps(valid), "STOP", 40))
    with caplog.at_level(logging.WARNING):
        assert fake.model().generate(context()) == valid
    assert len(fake.prompts) == 1 and not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_retry_that_returns_valid_json_still_succeeds():
    valid = {"recursos": []}
    fake = FakeGemini(gemini_answer(LOOPING_TEXT, "MAX_TOKENS", 65536), gemini_answer(json.dumps(valid), "STOP", 5))
    assert fake.model().generate(context()) == valid and len(fake.prompts) == 2


def test_the_detailed_message_reaches_the_fallback_reason():
    fake = FakeGemini(gemini_answer(LOOPING_TEXT, "MAX_TOKENS", 65536), gemini_answer(LOOPING_TEXT, "MAX_TOKENS", 65536))
    _, generator, warning = draft_resources(context(), fake.model(), RuleBasedGenerator(), [])
    assert isinstance(generator, RuleBasedGenerator)
    assert warning == (
        "Gemini · gemini-3.5-flash-lite no respondió (La respuesta del modelo no es JSON válido (finishReason "
        f"MAX_TOKENS, 65 536 tokens, {characters(len(LOOPING_TEXT))} caracteres).). Se usó el generador por reglas."
    )
