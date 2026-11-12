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

    def save_resource_if_version(self, teacher_id, unit_id, resource, expected_version, increment=True):
        if self.by_id.get(resource["id"], {}).get("version", 1) != expected_version:
            return False
        self.by_id[resource["id"]] = {**resource, "version": expected_version + 1 if increment else expected_version}
        return True

    def save_download(self, teacher_id, unit_id, record):
        self.downloads.append(record)


class Media:
    def __init__(self):
        self.files = {"media-old": ({"id": "media-old", "fileName": "r1.mp3", "mimeType": "audio/mpeg"}, b"ID3old")}

    def save_media(self, teacher_id, media, content):
        self.files[media["id"]] = (dict(media), content)

    def get_media(self, teacher_id, media_id):
        return self.files.get(media_id)

    def delete_media(self, teacher_id, media_id):
        self.files.pop(media_id, None)


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
        # REV-01: afirmación y copia histórica que la respalda, como en los recursos de Generación.
        "citations": [{"claim": "El protocolo TCP confirma la entrega de los datos.", "fragmentIds": ["frag-audio"]}],
        "evidence": [{"id": "frag-audio", "text": "El protocolo TCP confirma la entrega de los datos al receptor.",
                      "location": "página 1", "documentId": "d1", "documentName": "redes.pdf"}],
    }


def setup():
    resources, media = Resources([audio_resource()]), Media()
    return ResourceReviewService(Teachers(), resources), resources, media


def review(service, **changes):
    version = service.get_resource("ana", "u1", "r1").get("version", 1)
    return service.update_resource("ana", "u1", "r1", {"title": "Resumen", "body": "Escucha el resumen.", "status": "pendiente",
                                                       "expectedVersion": version, **changes})


def scorm(resources, media):
    exported = ExportUnitResourcesUseCase(Teachers(), resources, [ScormPackageExporter()], media).execute("ana", "u1", "scorm_zip")
    return zipfile.ZipFile(io.BytesIO(exported.content))


def test_editing_the_script_drops_the_old_audio_everywhere():
    service, resources, media = setup()
    edited = review(service, structure={"script": NEW_SCRIPT})
    assert edited["media"]["status"] == "fallback" and "Cambiaste el guion" in edited["media"]["note"]
    assert edited["media"]["invalidated"] is True

    # REV-C8 (D9, opción A): la aprobación se bloquea hasta generar el archivo de nuevo.
    with pytest.raises(AccountConfigurationError) as blocked:
        review(service, status="aprobado")
    assert blocked.value.code == "APPROVAL_BLOCKED" and "genera" in blocked.value.message.lower()

    # Aunque estuviera aprobado de antes, un recurso con el archivo invalidado no entra en una exportación nueva.
    resources.by_id["r1"]["status"] = "aprobado"
    with pytest.raises(AccountConfigurationError) as excluded:
        scorm(resources, media)
    assert excluded.value.code == "NO_APPROVED_RESOURCES"
    assert excluded.value.details == [{"reason": "media_invalidated", "count": 1}]


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


# --------------------------------------------------------------------------- REV-01 · bloque e) (REV-C8 · REV-R8)

IMAGE_STRUCTURE = {
    "prompt": "Ilustración didáctica de un segmento TCP que confirma la entrega de los datos.",
    "alt": "Ilustración sobre la entrega de datos",
    "caption": "El protocolo TCP confirma la entrega de los datos.",
}


def image_resource() -> dict[str, Any]:
    return {
        "id": "img1", "unitId": "u1", "type": "imagen_ilustrativa", "stage": "explore", "format": "image",
        "status": "pendiente", "title": "Imagen", "body": "Observa la imagen.", "options": None,
        "createdAt": "2026-10-18T10:00", "structure": dict(IMAGE_STRUCTURE),
        "media": {"status": "ready", "id": "media-img", "mimeType": "image/png", "fileName": "img1.png"},
        "citations": [{"claim": "El protocolo TCP confirma la entrega de los datos.", "fragmentIds": ["frag-img"]}],
        "evidence": [{"id": "frag-img", "text": "El protocolo TCP confirma la entrega de los datos al receptor.",
                      "location": "página 1", "documentId": "d1", "documentName": "redes.pdf"}],
    }


def edit_image(**structure_changes: str) -> dict[str, Any]:
    resources = Resources([image_resource()])
    service = ResourceReviewService(Teachers(), resources)
    version = service.get_resource("ana", "u1", "img1").get("version", 1)
    return service.update_resource("ana", "u1", "img1", {
        "title": "Imagen", "body": "Observa la imagen.", "status": "pendiente", "expectedVersion": version,
        "structure": {**IMAGE_STRUCTURE, **structure_changes},
    })


@pytest.mark.parametrize("field", ["alt", "caption"])
def test_changing_only_the_alt_text_or_the_caption_keeps_the_generated_image(field):
    """REV-C8: si cambian solo `alt` o `caption`, el archivo se conserva."""
    edited = edit_image(**{field: "Texto corregido por el docente para la imagen."})
    assert edited["media"]["status"] == "ready" and edited["media"]["id"] == "media-img"
    assert edited["structure"][field] == "Texto corregido por el docente para la imagen."


def test_changing_the_prompt_drops_the_generated_image():
    """REV-C8: si cambia el `prompt` normalizado, el archivo deja de usarse y se muestra la descripción."""
    edited = edit_image(prompt="Ilustración de un datagrama UDP que viaja sin confirmación de entrega.")
    assert edited["media"]["status"] == "fallback" and "Cambiaste la descripción" in edited["media"]["note"]
    assert edited["media"]["invalidated"] is True


@pytest.mark.parametrize("field", ["alt", "caption"])
def test_changing_alt_or_caption_does_not_mark_the_file_as_invalidated(field):
    assert not edit_image(**{field: "Texto corregido."})["media"].get("invalidated")


class FailingVoice(Voice):
    def synthesize_speech(self, script):
        raise RuntimeError("servicio de voz sin cuota")


def test_a_failed_generation_keeps_the_file_invalidated_and_approval_blocked():
    """Si «Generar de nuevo» falla, el recurso sigue con el respaldo y la aprobación sigue bloqueada."""
    service, resources, media = setup()
    review(service, structure={"script": NEW_SCRIPT})
    regenerated = RegenerateResourceMediaUseCase(service, resources, FailingVoice(), media).execute("ana", "u1", "r1")
    assert regenerated["media"]["status"] == "fallback" and regenerated["media"]["invalidated"] is True
    with pytest.raises(AccountConfigurationError) as blocked:
        review(service, status="aprobado")
    assert blocked.value.code == "APPROVAL_BLOCKED"


def test_the_invalidated_file_is_a_pedagogical_blocker_with_its_reason():
    resource = {**audio_resource(), "media": {"status": "fallback", "note": "Cambiaste el guion.", "invalidated": True}}
    assert validate_approval_blockers(resource)[-1] == (
        "Cambiaste el guion o la descripción: genera el archivo de nuevo para poder aprobar."
    )


def test_a_prompt_that_only_differs_in_spaces_keeps_the_generated_image():
    edited = edit_image(prompt="  " + IMAGE_STRUCTURE["prompt"].replace(" ", "   ") + "  ")
    assert edited["media"]["status"] == "ready"


class VoiceWhileTheTeacherEdits(Voice):
    """Mientras genera el audio, el docente guarda en otra pestaña un guion distinto (la versión avanza)."""

    def __init__(self, service):
        super().__init__()
        self._service = service

    def synthesize_speech(self, script):
        review(self._service, structure={"script": EDITED_MEANWHILE})
        return super().synthesize_speech(script)


EDITED_MEANWHILE = "Guion guardado mientras se generaba el audio: TCP confirma la entrega y UDP no lo hace, por eso es más rápido."


def test_generating_again_does_not_overwrite_an_edit_saved_meanwhile():
    """Revisión de Silvana (PR #13): el resultado se guarda solo si la versión de partida sigue vigente."""
    service, resources, media = setup()
    review(service, structure={"script": NEW_SCRIPT})
    started = service.get_resource("ana", "u1", "r1")["version"]
    with pytest.raises(AccountConfigurationError) as error:
        RegenerateResourceMediaUseCase(service, resources, VoiceWhileTheTeacherEdits(service), media).execute("ana", "u1", "r1")
    assert error.value.code == "VERSION_CONFLICT" and error.value.status_code == 409
    stored = resources.by_id["r1"]
    assert stored["version"] == started + 1
    assert stored["structure"]["script"] == EDITED_MEANWHILE
    assert stored["media"]["status"] == "fallback" and stored["media"]["invalidated"] is True


def test_generating_again_without_edits_meanwhile_keeps_the_version():
    service, resources, media = setup()
    review(service, structure={"script": NEW_SCRIPT})
    started = service.get_resource("ana", "u1", "r1")["version"]
    regenerated = RegenerateResourceMediaUseCase(service, resources, Voice(), media).execute("ana", "u1", "r1")
    assert regenerated["media"]["status"] == "ready"
    assert resources.by_id["r1"]["version"] == started and resources.by_id["r1"]["media"]["status"] == "ready"
