"""Recursos multimodales e interactivos: catálogo por etapa, estructura, respaldo por reglas, medios y exportación."""
from __future__ import annotations

import base64
import io
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import httpx
import pytest

from platform5e.application.ports.outbound.media_port import GeneratedMedia
from platform5e.application.services.generation.generation_service import GenerationService
from platform5e.application.services.generation.prompt_drafting import (
    build_prompt_instructions,
    normalize_generated_resources,
    structure_from_model,
)
from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.domain.generation.resource_formats import (
    RESOURCE_CATALOG,
    normalize_structure,
    resource_format,
    structure_problems,
)
from platform5e.domain.materials.chunking import chunk_pages
from platform5e.infrastructure.exporters.scorm_package_exporter import ScormPackageExporter
from platform5e.infrastructure.exporters.unit_document_exporter import UnitDocumentExporter
from platform5e.infrastructure.exporters.visual_renderer import SvgVisualRenderer
from platform5e.infrastructure.llm.gemini_language_model import GEMINI_RESPONSE_SCHEMA, AIProviderError
from platform5e.infrastructure.llm.gemini_media_generator import GeminiMediaGenerator, pcm_to_wav
from platform5e.infrastructure.llm.language_model_factory import create_media_generator

CORPUS = Path(__file__).resolve().parents[2] / "evaluation" / "corpus" / "protocols.txt"
NS = {"cp": "http://www.imsproject.org/xsd/imscp_rootv1p1p2"}


def context_for(resource_type: str, quantity: int = 2) -> dict:
    chunks = chunk_pages([("1", CORPUS.read_text(encoding="utf-8"))])
    stage = RESOURCE_CATALOG[resource_type][0]
    return {
        "curso": {"nombre": "Redes", "sumilla": "", "logro": ""},
        "unidad": {"numero": 1, "titulo": "Protocolos de transporte", "resultados": []},
        "solicitud": {"etapa": stage, "tipo": resource_type, "cantidad": quantity, "dificultad": "intermedia",
                      "alternativas": 4, "indicaciones": "", "publico": "", "competencia": "", "modalidades": []},
        "fragmentos": [{"etiqueta": f"F{i + 1}", "id": f"c{i}", "ubicacion": "p. 1", "documento": "protocolos.txt",
                        "texto": c.get("text") or c.get("texto")} for i, c in enumerate(chunks)],
    }


def test_every_stage_offers_at_least_two_types_and_multimodal_options():
    by_stage: dict[str, set[str]] = {}
    for stage, kind in RESOURCE_CATALOG.values():
        by_stage.setdefault(stage, set()).add(kind)
    assert set(by_stage) == {"engage", "explore", "explain", "elaborate", "evaluate"}
    assert sum(1 for s, _ in RESOURCE_CATALOG.values() if s == "explain") >= 4
    assert {"audio", "image", "visual", "interactive"} <= {kind for kinds in by_stage.values() for kind in kinds}
    assert all(len(kinds) >= 2 for kinds in by_stage.values())  # cada etapa combina texto con otro formato


@pytest.mark.parametrize("resource_type", sorted(RESOURCE_CATALOG))
def test_rule_based_fallback_writes_every_type_with_citations_and_valid_structure(resource_type):
    context = context_for(resource_type)
    resources = normalize_generated_resources(RuleBasedGenerator().generate(context), context)
    assert resources, resource_type
    for resource in resources:
        assert resource["citas"] and resource["contenido"]
        if resource_format(resource_type) == "text":
            assert resource["estructura"] is None
        else:
            assert normalize_structure(resource_type, resource["estructura"]) == resource["estructura"]


def test_prompt_asks_for_the_structure_and_drops_the_text_only_rule_for_multimodal_types():
    system, user = build_prompt_instructions(context_for("mapa_conceptual"))
    assert '"nodos"' in user and "Genera solo texto" not in system
    system, _ = build_prompt_instructions(context_for("explicacion"))
    assert "Genera solo texto" in system
    assert "estructura" in GEMINI_RESPONSE_SCHEMA["properties"]["recursos"]["items"]["properties"]


def test_model_structure_is_translated_and_validated():
    pairs = {"pares": [{"termino": t, "definicion": f"Definición de {t}"} for t in ("TCP", "UDP", "IP")]}
    assert structure_from_model("emparejamiento", pairs, "", "")["pairs"][0] == {"term": "TCP", "definition": "Definición de TCP"}
    assert structure_from_model("emparejamiento", {"pares": pairs["pares"][:2]}, "", "") is None  # muy pocos pares
    only_true = {"afirmaciones": [{"texto": f"A{i}", "verdadera": True} for i in range(4)]}
    assert structure_from_model("verdadero_falso", only_true, "", "") is None
    blanks = {"espacios": [{"oracion": "TCP garantiza la entrega.", "respuesta": "TCP"}, {"oracion": "El ___ es rápido.", "respuesta": "UDP"}]}
    assert [b["sentence"] for b in structure_from_model("completar_espacios", blanks, "", "")["blanks"]] == [
        "____ garantiza la entrega.", "El ____ es rápido."]
    assert structure_from_model("podcast_resumen", {}, "palabra " * 20, "")["script"].startswith("palabra")
    assert structure_problems("emparejamiento", {"pairs": []}) and not structure_problems("explicacion", None)


@pytest.mark.parametrize("resource_type", ["mapa_conceptual", "infografia", "diagrama_proceso", "imagen_ilustrativa"])
def test_graphics_are_well_formed_svg_with_escaped_text(resource_type):
    context = context_for(resource_type, 1)
    structure = normalize_generated_resources(RuleBasedGenerator().generate(context), context)[0]["estructura"]
    if resource_type == "mapa_conceptual":
        structure["nodes"][0]["label"] = "TCP <script>"
    svg = SvgVisualRenderer().render({"type": resource_type, "title": "Título & más", "structure": structure})
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg") and "<script" not in svg and "Título &amp; más" in svg


def gemini(handler) -> GeminiMediaGenerator:
    return GeminiMediaGenerator("clave", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_media_generator_reads_images_and_audio_from_the_interactions_api():
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 200
    pcm = b"\x00\x01" * 24000  # un segundo de audio

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path.endswith("/interactions") and request.headers["x-goog-api-key"] == "clave"
        if body["response_format"]["type"] == "image":
            return httpx.Response(200, json={"steps": [{"content": [{"type": "image", "mime_type": "image/png",
                                                                     "data": base64.b64encode(png).decode()}]}]})
        assert body["generation_config"]["speech_config"][0]["voice"] == "Kore"
        return httpx.Response(200, json={"steps": [{"content": [{"type": "audio", "mime_type": "audio/l16; rate=24000",
                                                                 "data": base64.b64encode(pcm).decode()}]}]})

    image = gemini(handler).generate_image("Una red")
    assert (image.mime_type, image.extension, image.content) == ("image/png", "png", png)
    audio = gemini(handler).synthesize_speech("Hola")
    assert audio.mime_type in ("audio/mpeg", "audio/wav") and len(audio.content) > 100


def test_media_generator_reports_quota_errors():
    generator = gemini(lambda request: httpx.Response(429, json={"error": {"message": "quota"}}))
    with pytest.raises(AIProviderError):
        generator.generate_image("x")


def test_media_generator_needs_gemini_and_can_be_turned_off():
    assert create_media_generator({"LLM_PROVIDER": "rules"}) is None
    assert create_media_generator({"LLM_PROVIDER": "gemini", "LLM_API_KEY": "k", "MEDIA_GENERATION_ENABLED": "false"}) is None
    assert create_media_generator({"LLM_PROVIDER": "gemini", "LLM_API_KEY": "k", "IMAGE_MODEL": "m"}).image_model == "m"


class FakeMediaGenerator:
    description = "Falso"

    def __init__(self, fail: bool = False):
        self.fail = fail

    def generate_image(self, prompt: str) -> GeneratedMedia:
        if self.fail:
            raise AIProviderError("sin cuota", 429)
        return GeneratedMedia(b"\x89PNGimagen", "image/png", "png")

    def synthesize_speech(self, script: str) -> GeneratedMedia:
        return GeneratedMedia(b"ID3audio", "audio/mpeg", "mp3")


class MemoryMediaRepository:
    def __init__(self):
        self.saved: dict[str, tuple[dict, bytes]] = {}

    def save_media(self, teacher_id, media, content):
        self.saved[media["id"]] = (dict(media), content)

    def get_media(self, teacher_id, media_id):
        return self.saved.get(media_id)


def test_generated_media_is_saved_or_falls_back_without_stopping_the_generation():
    repository = MemoryMediaRepository()
    service = GenerationService(repository=None, media_generator=FakeMediaGenerator(), media_repository=repository)
    audio = {"id": "r1", "format": "audio", "structure": {"script": "Hola"}}
    service._attach_media("t1", audio)
    assert audio["media"]["status"] == "ready" and repository.saved[audio["media"]["id"]][1] == b"ID3audio"

    failing = GenerationService(repository=None, media_generator=FakeMediaGenerator(fail=True), media_repository=repository)
    image = {"id": "r2", "format": "image", "structure": {"prompt": "Una red"}}
    failing._attach_media("t1", image)
    assert image["media"]["status"] == "fallback" and "sin cuota" in image["media"]["note"]

    text = {"id": "r3", "format": "text"}
    service._attach_media("t1", text)
    assert "media" not in text


def approved_resources() -> list[dict]:
    resources = []
    for n, resource_type in enumerate(["mapa_conceptual", "podcast_resumen", "emparejamiento", "verdadero_falso",
                                       "imagen_ilustrativa", "ordenar_pasos", "completar_espacios"]):
        context = context_for(resource_type, 1)
        generated = normalize_generated_resources(RuleBasedGenerator().generate(context), context)[0]
        resources.append({
            "id": f"r{n}", "type": resource_type, "stage": RESOURCE_CATALOG[resource_type][0], "status": "aprobado",
            "title": generated["titulo"], "body": generated["contenido"], "structure": generated["estructura"],
            "format": resource_format(resource_type), "createdAt": f"2026-10-17T10:0{n}", "options": None, "evidence": [],
        })
    resources[1]["mediaFile"] = {"fileName": "r1.mp3", "mimeType": "audio/mpeg", "content": b"ID3audio"}
    resources[0]["bodyHtml"] = "<h2>Mapa</h2><p>Lee <strong>desde el centro</strong>.</p><script>alert(1)</script>"
    return resources


def test_scorm_package_declares_every_file_with_graphics_audio_and_graded_activities():
    exported = ScormPackageExporter().export(approved_resources(), {"code": "RED-301"}, {"number": 1, "title": "Transporte"})
    archive = zipfile.ZipFile(io.BytesIO(exported.content))
    names = set(archive.namelist())
    root = ET.fromstring(archive.read("imsmanifest.xml"))
    declared = {f.get("href") for f in root.iter(f"{{{NS['cp']}}}file")}
    assert names - {"imsmanifest.xml"} == declared  # todo lo del paquete está en el manifiesto y existe
    assert "shared/activity.js" in names and archive.read(next(n for n in names if n.endswith(".mp3"))) == b"ID3audio"
    assert sum(n.endswith(".svg") for n in names) == 2  # mapa conceptual y tarjeta de la ilustración
    pages = {name: archive.read(name).decode() for name in names if name.startswith("sco/")}
    activity_pages = [p for p in pages.values() if 'data-kind="activity"' in p]
    assert len(activity_pages) == 4 and all('id="activity-data"' in p for p in activity_pages)
    assert any('<audio controls' in p for p in pages.values())
    concept_page = next(p for p in pages.values() if "Mapa" in p and "<h2>" in p)
    assert "<strong>desde el centro</strong>" in concept_page and "alert(1)" not in concept_page


def test_unit_document_embeds_graphics_and_prints_activities_with_an_answer_key():
    html = UnitDocumentExporter().export(approved_resources(), {"code": "RED-301"}, {"number": 1, "title": "T"}).content.decode()
    assert html.count("<svg") >= 2 and "Clave de respuestas" in html and "(V / F)" in html
    assert "Para aplicar" in html and "alert(1)" not in html
