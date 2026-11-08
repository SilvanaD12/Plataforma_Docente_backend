"""Caso de uso de exportación con puertos falsos: solo lo aprobado, el formato pedido y el registro en el historial."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from platform5e.application.ports.outbound.unit_exporter_port import ExportedFile
from platform5e.application.use_cases.export.export_unit_resources import ExportUnitResourcesUseCase
from platform5e.domain.accounts.teacher_account import AccountConfigurationError

COURSE = {"id": "c1", "code": "RED-301", "units": [{"id": "u1", "number": 1, "title": "Transporte"}]}


class FakeTeacherRepository:
    def get_courses(self, teacher_id: str) -> list[dict[str, Any]]:
        return [COURSE] if teacher_id == "ana" else []


class FakeReviewRepository:
    def __init__(self, resources: list[dict[str, Any]]) -> None:
        self.resources = resources
        self.downloads: list[dict[str, Any]] = []

    def get_resources_by_unit(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        return [r for r in self.resources if r["unitId"] == unit_id]

    def save_download(self, teacher_id: str, unit_id: str, download_record: dict[str, Any]) -> None:
        self.downloads.append(download_record)


class FakeExporter:
    format = "fake"

    def __init__(self) -> None:
        self.received: list[Mapping] = []

    def supports(self, resource: Mapping) -> bool:
        return bool(resource.get("options"))

    def export(self, resources: Sequence[Mapping], course: Mapping, unit: Mapping) -> ExportedFile:
        self.received = list(resources)
        return ExportedFile(f"{course['code']}-{unit['number']}.fake", "text/plain", b"ok")


def resource(resource_id: str, status: str, options: list | None = None) -> dict[str, Any]:
    return {"id": resource_id, "unitId": "u1", "status": status, "options": options}


def build(resources: list[dict[str, Any]]) -> tuple[ExportUnitResourcesUseCase, FakeReviewRepository, FakeExporter]:
    review, exporter = FakeReviewRepository(resources), FakeExporter()
    return ExportUnitResourcesUseCase(FakeTeacherRepository(), review, [exporter]), review, exporter


def test_exports_only_approved_supported_resources_and_records_the_download():
    use_case, review, exporter = build(
        [resource("a", "aprobado", [{}]), resource("b", "pendiente", [{}]), resource("c", "aprobado")]
    )
    exported = use_case.execute("ana", "u1", "fake")
    assert exported.file_name == "RED-301-1.fake" and use_case.formats == ["fake"]
    assert [r["id"] for r in exporter.received] == ["a"]
    assert review.downloads[0]["format"] == "fake" and review.downloads[0]["resourceCount"] == 1


@pytest.mark.parametrize(
    "teacher,unit,export_format,resources,code",
    [
        ("otra", "u1", "fake", [resource("a", "aprobado", [{}])], "UNIT_NOT_FOUND"),
        ("ana", "u1", "pdf", [resource("a", "aprobado", [{}])], "INVALID_FORMAT"),
        ("ana", "u1", "fake", [resource("a", "pendiente", [{}])], "NO_APPROVED_RESOURCES"),
    ],
)
def test_rejects_foreign_units_unknown_formats_and_nothing_approved(teacher, unit, export_format, resources, code):
    use_case, review, _ = build(resources)
    with pytest.raises(AccountConfigurationError) as error:
        use_case.execute(teacher, unit, export_format)
    assert error.value.code == code and review.downloads == []
