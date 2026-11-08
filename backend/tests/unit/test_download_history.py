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


# --------------------------------------------------------------------------- REV-01 · historial por docente (REV-C9)

class TeacherDownloadsRepository:
    """Registros de descarga por docente, como la tabla `ep002_descargas`."""

    def __init__(self, records: dict[str, list[dict]]) -> None:
        self.records = records

    def get_downloads_by_teacher(self, teacher_id: str) -> list[dict]:
        return list(self.records.get(teacher_id, []))


class TeacherCourses:
    def __init__(self, courses: dict[str, list[dict]]) -> None:
        self.courses = courses

    def get_courses(self, teacher_id: str) -> list[dict]:
        return self.courses.get(teacher_id, [])


def download(download_id: str, created_at: str, **names) -> dict:
    return {"id": download_id, "unitId": "u1", "format": "scorm_zip", "fileName": f"{download_id}.zip",
            "resourceCount": 1, "createdAt": created_at, **names}


NAMES = {"courseId": "c1", "courseName": "Redes", "unitName": "Transporte", "unitNumber": 1}
REDES = [{"id": "c1", "name": "Redes", "units": [{"id": "u1", "number": 1, "title": "Transporte"}]}]


def test_the_history_lists_the_teacher_downloads_newest_first():
    records = {"ana": [download("d1", "2026-11-08T10:00:00Z", **NAMES), download("d2", "2026-11-08T12:00:00Z", **NAMES)]}
    service = ResourceReviewService(TeacherCourses({"ana": REDES}), TeacherDownloadsRepository(records))
    assert [d["id"] for d in service.get_teacher_downloads("ana")] == ["d2", "d1"]


def test_the_history_survives_the_deletion_of_the_course():
    """REV-C9: sin el curso, el docente sigue viendo fecha, formato, archivo, curso y unidad."""
    records = {"ana": [download("d1", "2026-11-08T10:00:00Z", **NAMES)]}
    service = ResourceReviewService(TeacherCourses({}), TeacherDownloadsRepository(records))
    [record] = service.get_teacher_downloads("ana")
    assert {k: record[k] for k in ("createdAt", "format", "fileName", "courseName", "unitName", "unitNumber")} == {
        "createdAt": "2026-11-08T10:00:00Z", "format": "scorm_zip", "fileName": "d1.zip",
        "courseName": "Redes", "unitName": "Transporte", "unitNumber": 1,
    }


def test_another_teacher_never_sees_the_history():
    records = {"ana": [download("d1", "2026-11-08T10:00:00Z", **NAMES)]}
    service = ResourceReviewService(TeacherCourses({"ana": REDES}), TeacherDownloadsRepository(records))
    assert service.get_teacher_downloads("beto") == []


def test_old_records_without_names_take_them_from_the_current_course_when_it_still_exists():
    records = {"ana": [download("d1", "2026-11-08T10:00:00Z"), download("d2", "2026-11-08T11:00:00Z") | {"unitId": "u9"}]}
    service = ResourceReviewService(TeacherCourses({"ana": REDES}), TeacherDownloadsRepository(records))
    by_id = {d["id"]: d for d in service.get_teacher_downloads("ana")}
    assert {k: by_id["d1"][k] for k in ("courseId", "courseName", "unitName", "unitNumber")} == NAMES
    # La unidad ya no existe: el registro queda sin nombres y la interfaz muestra «Curso eliminado».
    assert by_id["d2"].get("courseName") is None and by_id["d2"].get("unitName") is None


def test_the_history_is_limited_to_the_latest_records():
    records = {"ana": [download(f"d{i:03}", f"2026-11-08T10:{i % 60:02}:{i // 60:02}Z", **NAMES) for i in range(80)]}
    service = ResourceReviewService(TeacherCourses({"ana": REDES}), TeacherDownloadsRepository(records))
    assert len(service.get_teacher_downloads("ana")) == 50