"""REV-01 · T063: «Generar de nuevo» no deja archivos sin referencia.

Si el docente guarda otra versión mientras se genera el archivo, el resultado no se guarda (409 VERSION_CONFLICT,
revisión de Silvana en el PR #13). El archivo recién generado ya estaba guardado y ningún recurso lo usa: se borra con
`MediaRepositoryPort.delete_media`. El archivo anterior del recurso no se toca.
"""

from __future__ import annotations

import logging

import pytest

from platform5e.application.use_cases.media.regenerate_resource_media import RegenerateResourceMediaUseCase
from platform5e.domain.accounts.teacher_account import AccountConfigurationError
from tests.unit.test_edited_media import NEW_SCRIPT, Media, Voice, VoiceWhileTheTeacherEdits, review, setup


class MediaWithDelete(Media):
    """El doble de `test_edited_media.py` con el borrado del puerto, que registra lo que se borra."""

    def __init__(self) -> None:
        super().__init__()
        self.deleted: list[str] = []

    def delete_media(self, teacher_id, media_id):
        self.deleted.append(media_id)
        self.files.pop(media_id, None)


class BrokenDelete(MediaWithDelete):
    def delete_media(self, teacher_id, media_id):
        super().delete_media(teacher_id, media_id)
        raise OSError("el almacenamiento no respondió")


def _generate_while_the_teacher_edits(media: MediaWithDelete):
    service, resources, _ = setup()
    review(service, structure={"script": NEW_SCRIPT})
    use_case = RegenerateResourceMediaUseCase(service, resources, VoiceWhileTheTeacherEdits(service), media)
    with pytest.raises(AccountConfigurationError) as error:
        use_case.execute("ana", "u1", "r1")
    return error.value, resources


def test_a_file_generated_for_an_outdated_version_is_deleted():
    media = MediaWithDelete()
    error, resources = _generate_while_the_teacher_edits(media)
    assert error.code == "VERSION_CONFLICT" and error.status_code == 409
    assert len(media.deleted) == 1 and media.deleted[0].startswith("media-")
    assert set(media.files) == {"media-old"}, "quedó guardado un archivo que ningún recurso usa"
    assert resources.by_id["r1"]["media"].get("id") != media.deleted[0]


def test_if_deleting_the_unused_file_fails_the_answer_is_still_the_version_conflict(caplog):
    media = BrokenDelete()
    with caplog.at_level(logging.WARNING, logger="platform5e.media"):
        error, _ = _generate_while_the_teacher_edits(media)
    assert error.code == "VERSION_CONFLICT" and error.status_code == 409
    # El registro lleva solo el id del archivo y el error, sin datos del docente.
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert media.deleted[0] in logged and "el almacenamiento no respondió" in logged
    assert "ana" not in logged


def test_a_file_saved_with_the_resource_is_not_deleted():
    service, resources, _ = setup()
    media = MediaWithDelete()
    review(service, structure={"script": NEW_SCRIPT})
    regenerated = RegenerateResourceMediaUseCase(service, resources, Voice(), media).execute("ana", "u1", "r1")
    assert media.deleted == [] and regenerated["media"]["id"] in media.files
