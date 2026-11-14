"""Las imágenes de imagen_ilustrativa salían con texto escrito («Step 1», «RULES»…) aunque la descripción pide «sin
texto escrito». La instrucción fija se agrega solo al pedido que se envía al modelo de imágenes: la descripción
guardada (structure.prompt), el texto alternativo, la leyenda, la huella y el audio no cambian.

Sin red: Gemini se reemplaza por un transporte HTTP falso que guarda cada cuerpo enviado.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest

from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.application.services.media.media_attachment import generate_media
from platform5e.application.use_cases.generation.run_generation_request import RunGenerationRequest
from platform5e.application.use_cases.generation.start_generation_request import StartGenerationCommand
from platform5e.application.use_cases.media.regenerate_resource_media import RegenerateResourceMediaUseCase
from platform5e.application.services.review.resource_review_service import ResourceReviewService
from platform5e.domain.generation.generation_request import GenerationMode, GenerationParameters
from platform5e.domain.review.content_fingerprint import content_fingerprint
from platform5e.infrastructure.adapters.review_verification_adapter import ReviewVerificationAdapter
from platform5e.infrastructure.llm.gemini_media_generator import NO_TEXT_IN_IMAGE_INSTRUCTION, GeminiMediaGenerator
from tests.unit.test_edited_media import IMAGE_STRUCTURE, Media, Resources, Teachers, image_resource
from tests.unit.test_kinesthetic_activity import _corpus_fragments
from tests.unit.test_start_regeneration import Setup

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200
PCM = b"\x00\x01" * 24000
# Huella del recurso de imagen de test_edited_media calculada antes de este cambio: la instrucción no la toca.
IMAGE_FINGERPRINT = "sha256:1c6106ec662c66f9b860c8715b8edd76364a3b24f65b44cd7ebb17ef75b7896e"


class FakeGemini:
    """Transporte HTTP falso: guarda cada cuerpo enviado y responde una imagen o un audio."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.bodies.append(body)
        if body["response_format"]["type"] == "image":
            content = {"type": "image", "mime_type": "image/png", "data": base64.b64encode(PNG).decode()}
        else:
            content = {"type": "audio", "mime_type": "audio/l16; rate=24000", "data": base64.b64encode(PCM).decode()}
        return httpx.Response(200, json={"steps": [{"content": [content]}]})

    def generator(self) -> GeminiMediaGenerator:
        return GeminiMediaGenerator("clave", client=httpx.Client(transport=httpx.MockTransport(self)))

    def image_texts(self) -> list[str]:
        return [body["input"][0]["text"] for body in self.bodies if body["response_format"]["type"] == "image"]


def test_the_instruction_forbids_any_text_and_names_what_to_use_instead():
    instruction = NO_TEXT_IN_IMAGE_INSTRUCTION.lower()
    for word in ("text", "letters", "numbers", "words", "labels", "captions", "logos", "watermarks"):
        assert word in instruction
    for word in ("shapes", "objects", "people", "colors", "arrows"):
        assert word in instruction


def test_the_image_request_sends_the_stored_prompt_plus_the_instruction():
    gemini = FakeGemini()
    gemini.generator().generate_image("Una red de computadoras")
    [body] = gemini.bodies
    assert body == {
        "model": "gemini-3.1-flash-lite-image",
        "input": [{"type": "text", "text": f"Una red de computadoras\n\n{NO_TEXT_IN_IMAGE_INSTRUCTION}"}],
        "response_format": {"type": "image", "mime_type": "image/jpeg", "aspect_ratio": "16:9", "image_size": "1K"},
    }


def test_the_speech_request_is_unchanged():
    gemini = FakeGemini()
    gemini.generator().synthesize_speech("Hola, clase.")
    [body] = gemini.bodies
    assert body == {
        "model": "gemini-3.8-flash-tts",
        "input": [{"type": "user_input", "content": [{"type": "text", "text": "Hola, clase."}]}],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": "Kore"}]},
    }
    assert NO_TEXT_IN_IMAGE_INSTRUCTION not in json.dumps(body)


def test_generating_the_image_keeps_the_stored_structure_and_the_fingerprint():
    resource = image_resource()
    assert content_fingerprint(resource) == IMAGE_FINGERPRINT
    gemini = FakeGemini()
    pending = generate_media(resource, gemini.generator())
    assert pending is not None and pending.content == PNG
    assert resource["structure"] == IMAGE_STRUCTURE
    assert gemini.image_texts() == [f"{IMAGE_STRUCTURE['prompt']}\n\n{NO_TEXT_IN_IMAGE_INSTRUCTION}"]
    assert content_fingerprint(resource) == IMAGE_FINGERPRINT


def test_generate_again_sends_the_instruction_and_saves_the_prompt_as_it_was():
    resources, media, gemini = Resources([image_resource()]), Media(), FakeGemini()
    service = ResourceReviewService(Teachers(), resources)
    regenerated = RegenerateResourceMediaUseCase(service, resources, gemini.generator(), media).execute(
        "ana", "u1", "img1"
    )
    assert gemini.image_texts() == [f"{IMAGE_STRUCTURE['prompt']}\n\n{NO_TEXT_IN_IMAGE_INSTRUCTION}"]
    assert regenerated["media"]["status"] == "ready"
    assert regenerated["structure"] == IMAGE_STRUCTURE == resources.by_id["img1"]["structure"]
    assert content_fingerprint(resources.by_id["img1"]) == IMAGE_FINGERPRINT


@pytest.fixture
def setup(tmp_path) -> Setup:
    return Setup(tmp_path)


def test_a_generation_request_sends_the_instruction_and_stores_the_prompt_unchanged(setup):
    setup.evidence.fragments = _corpus_fragments()
    request_id = setup.use_case._start_generation.execute(
        StartGenerationCommand(
            "docente-a", "u1", GenerationMode.INDIVIDUAL, "clave-imagen-sin-texto",
            GenerationParameters(resource_types=("imagen_ilustrativa",)),
        )
    ).request.id
    gemini, media = FakeGemini(), Media()
    RunGenerationRequest(
        setup.repository, setup.membership, setup.evidence, setup.review, ReviewVerificationAdapter(),
        RuleBasedGenerator(), media_generator=gemini.generator(), media_repository=media, heartbeat_seconds=0,
    ).execute(request_id)

    stored = [resource for resource in setup.review.all() if resource["type"] == "imagen_ilustrativa"]
    assert stored and len(gemini.image_texts()) == len(stored)
    for resource, sent in zip(stored, gemini.image_texts()):
        prompt = resource["structure"]["prompt"]
        assert NO_TEXT_IN_IMAGE_INSTRUCTION not in prompt
        assert sent == f"{prompt}\n\n{NO_TEXT_IN_IMAGE_INSTRUCTION}"
        assert resource["media"]["status"] == "ready"
        # La huella guardada al verificar sigue siendo la del contenido guardado.
        assert resource["verification"]["fingerprint"] == content_fingerprint(resource)
