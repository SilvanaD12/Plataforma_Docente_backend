"""Pruebas del historial y re-descarga de paquetes exportados (HU-010)."""

from __future__ import annotations

import pytest

from platform5e.application.services.review.resource_review_service import ResourceReviewService
from platform5e.domain.accounts.teacher_account import AccountConfigurationError


class FakeReviewRepository:
    def __init__(self, downloads: list[dict] | None = None) -> None:
        self.downloads = list(downloads or [])

    def get_downloads(self, teacher_id: str, unit_id: str) -> list[dict]:
        return [d for d in self.downloads if d.get("unitId") == unit_id]

    def save_download(self, teacher_id: str, unit_id: str, download_record: dict) -> None:
        self.downloads.append(download_record)

    def delete_downloads(self, teacher_id: str, unit_id: str) -> None:
        self.downloads = [d for d in self.downloads if d.get("unitId") != unit_id]


class FakeTeacherRepository:
    def get_courses(self, teacher_id: str) -> list[dict]:
        if teacher_id != "docente-1":
            return []
        return [{"id": "c1", "units": [{"id": "u1", "title": "Unidad 1"}]}]


def test_get_download_record_returns_existing_record() -> None:
    repo = FakeReviewRepository([
        {"id": "descarga-abc", "unitId": "u1", "format": "scorm_zip", "fileName": "paquete.zip", "createdAt": "2026-10-26T00:00:00Z"}
    ])
    service = ResourceReviewService(FakeTeacherRepository(), repo)

    record = service.get_download_record("docente-1", "u1", "descarga-abc")

    assert record["id"] == "descarga-abc"
    assert record["format"] == "scorm_zip"


def test_get_download_record_raises_404_when_missing() -> None:
    service = ResourceReviewService(FakeTeacherRepository(), FakeReviewRepository())

    with pytest.raises(AccountConfigurationError) as exc_info:
        service.get_download_record("docente-1", "u1", "descarga-inexistente")

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "DOWNLOAD_NOT_FOUND"


def test_get_download_record_raises_404_when_teacher_has_no_unit_access() -> None:
    repo = FakeReviewRepository([{"id": "d1", "unitId": "u1"}])
    service = ResourceReviewService(FakeTeacherRepository(), repo)

    with pytest.raises(AccountConfigurationError) as exc_info:
        service.get_download_record("otro-docente", "u1", "d1")

    assert exc_info.value.status_code == 404