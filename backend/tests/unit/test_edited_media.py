"""Revisión de Silvana (PR #35): si el docente edita el guion o la descripción, el audio o la imagen anterior ya no
se usa en la revisión, la aprobación ni el SCORM, y se puede volver a generar."""

from __future__ import annotations

import io
import zipfile
from typing import Any

import pytest

from platform5e.application.ports.outbound.media_port import GeneratedMedia
from platform5e.application.services.review.resource_review_service import (
    ResourceReviewService,
    validate_approval_blockers,
)
from platform5e.application.use_cases.export.export_unit_resources import ExportUnitResourcesUseCase
from platform5e.application.use_cases.media.regenerate_resource_media import RegenerateResourceMediaUseCase
from platform5e.domain.accounts.teacher_account import AccountConfigurationError
from platform5e.infrastructure.exporters.scorm_package_exporter import ScormPackageExporter

COURSE = {"id": "c1", "code": "RED-301", "units": [{"id": "u1", "number": 1, "title": "Transporte"}]}
OLD_SCRIPT = "Escucha esta idea del material: el protocolo TCP confirma la entrega de los datos y retransmite lo que se pierde."
NEW_SCRIPT = "Guion editado por el docente: el protocolo UDP no confirma la entrega y por eso es más rápido en videollamadas."


class Teachers:
    def get_courses(self, teacher_id: str) -> list[dict[str, Any]]:
        return [COURSE]


class Resources:
    def __init__(self, resources: list[dict[str, Any]]) -> None:
        self.by_id = {r["id"]: r for r in resources}
        self.downloads: list[dict[str, Any]] = []

    def get_resource_by_id(self, teacher_id, resource_id):
        return self.by_id.get(resource_id)

    def get_resources_by_unit(self, teacher_id, unit_id):
        return [r for r in self.by_id.values() if r["unitId"] == unit_id]

    def save_resources(self, teacher_id, unit_id, resources):
        for resource in resources:
            self.by_id[resource["id"]] = resource

    def save_download(self, teacher_id, unit_id, record):
        self.downloads.append(record)


class Media:
    def __init__(self):
        self.files = {"media-old": ({"id": "media-old", "fileName": "r1.mp3", "mimeType": "audio/mpeg"}, b"ID3old")}

    def save_media(self, teacher_id, media, content):
        self.files[media["id"]] = (dict(media), content)

    def get_media(self, teacher_id, media_id):
        return self.files.get(media_id)


class Voice:
    description = "Voz de prueba"

    def __init__(self):
        self.scripts: list[str] = []

    def generate_image(self, prompt):
        raise AssertionError("no se pide imagen")

    def synthesize_speech(self, script):
        self.scripts.append(script)
        return GeneratedMedia(b"ID3new", "audio/mpeg", "mp3")


def audio_resource() -> dict[str, Any]:
    return {
        "id": "r1", "unitId": "u1", "type": "podcast_resumen", "stage": "explain", "format": "audio", "status": "pendiente",
        "title": "Resumen", "body": "Escucha el resumen.", "options": None, "createdAt": "2026-10-18T10:00",
        "structure": {"script": OLD_SCRIPT},
        "media": {"status": "ready", "id": "media-old", "mimeType": "audio/mpeg", "fileName": "r1.mp3"},
    }


def setup():
    resources, media = Resources([audio_resource()]), Media()
    return ResourceReviewService(Teachers(), resources), resources, media


def review(service, **changes):
    return service.update_resource("ana", "u1", "r1", {"title": "Resumen", "body": "Escucha el resumen.", "status": "pendiente", **changes})


def scorm(resources, media):
    exported = ExportUnitResourcesUseCase(Teachers(), resources, [ScormPackageExporter()], media).execute("ana", "u1", "scorm_zip")
    return zipfile.ZipFile(io.BytesIO(exported.content))


def test_editing_the_script_drops_the_old_audio_everywhere():
    service, resources, media = setup()
    edited = review(service, structure={"script": NEW_SCRIPT})
    assert edited["media"]["status"] == "fallback" and "Cambiaste el guion" in edited["media"]["note"]

    approved = review(service, status="aprobado")  # se puede aprobar: se escucha con la voz del navegador
    assert approved["status"] == "aprobado"
    archive = scorm(resources, media)
    page = next(archive.read(n).decode() for n in archive.namelist() if n.startswith("sco/"))
    assert not any(n.endswith(".mp3") for n in archive.namelist())
    assert NEW_SCRIPT in page and 'data-speak="script"' in page and OLD_SCRIPT not in page


def test_same_script_keeps_the_generated_audio():
    service, resources, media = setup()
    assert review(service, structure={"script": OLD_SCRIPT})["media"]["status"] == "ready"
    review(service, status="aprobado")
    assert scorm(resources, media).read("media/01.mp3") == b"ID3old"


def test_an_outdated_file_blocks_approval_and_is_never_exported():
    stale = {**audio_resource(), "media": {**audio_resource()["media"], "outdated": True}}
    assert validate_approval_blockers(stale)[-1].startswith("El archivo no coincide")
    resources, media = Resources([{**stale, "status": "aprobado"}]), Media()
    assert not any(n.endswith(".mp3") for n in scorm(resources, media).namelist())


def test_generate_again_uses_the_edited_script():
    service, resources, media = setup()
    review(service, structure={"script": NEW_SCRIPT})
    voice = Voice()
    regenerated = RegenerateResourceMediaUseCase(service, resources, voice, media).execute("ana", "u1", "r1")
    assert voice.scripts == [NEW_SCRIPT] and regenerated["media"]["status"] == "ready"
    assert media.files[regenerated["media"]["id"]][1] == b"ID3new"
    review(service, status="aprobado")
    assert scorm(resources, media).read("media/01.mp3") == b"ID3new"


@pytest.mark.parametrize("change,code", [
    ({"generator": None}, "MEDIA_GENERATION_DISABLED"),
    ({"status": "aprobado"}, "RESOURCE_NOT_PENDING"),
    ({"type": "glosario", "format": "text"}, "NO_MEDIA"),
])
def test_generate_again_needs_a_pending_media_resource_and_an_active_service(change, code):
    resource = {**audio_resource(), **{k: v for k, v in change.items() if k != "generator"}}
    resources, media = Resources([resource]), Media()
    service = ResourceReviewService(Teachers(), resources)
    generator = None if "generator" in change else Voice()
    with pytest.raises(AccountConfigurationError) as error:
        RegenerateResourceMediaUseCase(service, resources, generator, media).execute("ana", "u1", "r1")
    assert error.value.code == code
