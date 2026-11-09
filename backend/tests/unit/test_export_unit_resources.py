"""Caso de uso de exportación con puertos falsos: solo lo aprobado, el formato pedido y el registro en el historial."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from platform5e.application.ports.outbound.unit_exporter_port import ExportedFile
from platform5e.application.use_cases.export.export_unit_resources import ExportUnitResourcesUseCase
from platform5e.domain.accounts.teacher_account import AccountConfigurationError
from platform5e.domain.generation import grounding
from platform5e.domain.review.resource_verification import verify_resource

COURSE = {"id": "c1", "code": "RED-301", "units": [{"id": "u1", "number": 1, "title": "Transporte"}]}
EVIDENCE_TEXT = "El protocolo TCP confirma la entrega de los datos al receptor."


class FakeTeacherRepository:
    def get_courses(self, teacher_id: str) -> list[dict[str, Any]]:
        return [COURSE] if teacher_id == "ana" else []


class FakeReviewRepository:
    def __init__(self, resources: list[dict[str, Any]]) -> None:
        self.resources = resources
        self.downloads: list[dict[str, Any]] = []

    def get_resources_by_unit(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        return [r for r in self.resources if r["unitId"] == unit_id]

    # REV-01: los usa la verificación de los recursos sin `verification` antes de filtrar.
    def get_resource_by_id(self, teacher_id: str, resource_id: str) -> dict[str, Any] | None:
        return next((r for r in self.resources if r["id"] == resource_id), None)

    def save_resource_if_version(self, teacher_id, unit_id, resource, expected_version, increment=True) -> bool:
        for index, current in enumerate(self.resources):
            if current["id"] == resource["id"] and current.get("version", 1) == expected_version:
                self.resources[index] = {**resource, "version": expected_version + 1 if increment else expected_version}
                return True
        return False

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
    # REV-01: copia histórica, afirmación respaldada y verificación vigente, como los recursos de Generación.
    item = {
        "id": resource_id, "unitId": "u1", "status": status, "options": options, "version": 1,
        "citations": [{"claim": "El protocolo TCP confirma la entrega de los datos.", "fragmentIds": ["f1"]}],
        "evidence": [{"id": "f1", "text": EVIDENCE_TEXT}],
    }
    item["verification"] = verify_resource(item, threshold=0.6, rule_version=grounding.VERIFICATION_RULE_VERSION)
    return item


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


# --------------------------------------------------------------------------- REV-01 · bloque d) filtro común

NAMED_COURSE = {"id": "c1", "code": "RED-301", "name": "Redes", "units": [{"id": "u1", "number": 1, "title": "Transporte"}]}


class NamedTeacherRepository:
    def get_courses(self, teacher_id: str) -> list[dict[str, Any]]:
        return [NAMED_COURSE] if teacher_id == "ana" else []


def verified(resource_id: str, status: str = "aprobado", **overrides: Any) -> dict[str, Any]:
    """Un ítem con copia histórica y afirmación respaldada, verificado como vigente."""
    item = {
        "id": resource_id,
        "unitId": "u1",
        "status": status,
        "body": "¿Qué protocolo confirma la entrega?",
        "options": [{"id": f"{resource_id}:a", "text": "TCP", "isCorrect": True, "feedback": "", "sourceFragmentIds": ["f1"]}],
        "citations": [{"claim": "El protocolo TCP confirma la entrega de los datos.", "fragmentIds": ["f1"]}],
        "evidence": [{"id": "f1", "text": EVIDENCE_TEXT}],
        "version": 1,
        **overrides,
    }
    item["verification"] = verify_resource(item, threshold=0.6, rule_version=grounding.VERIFICATION_RULE_VERSION)
    return item


def build_named(resources: list[dict[str, Any]]):
    review, exporter = FakeReviewRepository(resources), FakeExporter()
    return ExportUnitResourcesUseCase(NamedTeacherRepository(), review, [exporter]), review, exporter


def test_approved_resources_without_a_current_verification_are_left_out():
    """REV-C7: el archivo incluye solo los aprobados con comprobación vigente y compatibles con el formato."""
    insufficient = verified("b")
    insufficient["verification"]["status"] = "insufficient"
    pending = verified("c")
    pending["verification"]["status"] = "pending"
    outdated = verified("d")
    outdated["body"] = "Enunciado editado después de verificar."
    use_case, review, exporter = build_named([verified("a"), insufficient, pending, outdated])
    use_case.execute("ana", "u1", "fake")
    assert [r["id"] for r in exporter.received] == ["a"]
    assert review.downloads[0]["resourceCount"] == 1


def test_without_eligible_resources_no_file_is_made_and_the_reasons_are_given():
    """REV-C7: si ninguno cumple, se informa el motivo y no se genera el archivo."""
    insufficient = verified("b")
    insufficient["verification"]["status"] = "insufficient"
    use_case, review, exporter = build_named([verified("a", status="pendiente"), insufficient, verified("c", options=None)])
    with pytest.raises(AccountConfigurationError) as error:
        use_case.execute("ana", "u1", "fake")
    assert error.value.code == "NO_APPROVED_RESOURCES" and error.value.status_code == 422
    assert error.value.details == [
        {"reason": "not_approved", "count": 1},
        {"reason": "unsupported_format", "count": 1},
        {"reason": "verification_insufficient", "count": 1},
    ]
    assert exporter.received == [] and review.downloads == []


def test_the_download_record_keeps_the_course_and_unit_names():
    """REV-C9 y REV-R9: el registro guarda curso y unidad para que el historial sobreviva al borrado del curso."""
    use_case, review, _ = build_named([verified("a")])
    use_case.execute("ana", "u1", "fake")
    assert len(review.downloads) == 1
    record = review.downloads[0]
    assert {k: record[k] for k in ("courseId", "courseName", "unitId", "unitName", "unitNumber", "format", "fileName")} == {
        "courseId": "c1", "courseName": "Redes", "unitId": "u1", "unitName": "Transporte", "unitNumber": 1,
        "format": "fake", "fileName": "RED-301-1.fake",
    }


def test_a_rule_change_does_not_remove_a_current_resource_from_exports(monkeypatch):
    """REV-C10: el recurso conserva su estado y sigue exportable si no se edita."""
    use_case, _, exporter = build_named([verified("a")])
    monkeypatch.setattr(grounding, "VERIFICATION_RULE_VERSION", grounding.VERIFICATION_RULE_VERSION + 1)
    use_case.execute("ana", "u1", "fake")
    assert [r["id"] for r in exporter.received] == ["a"]


def test_resources_without_verification_are_checked_before_exporting():
    """D7: un aprobado sin `verification` se verifica antes de filtrar; sin copia histórica queda fuera."""
    legacy_ok = {k: v for k, v in verified("a").items() if k != "verification"}
    legacy_without_copy = {k: v for k, v in verified("b").items() if k != "verification"} | {"evidence": []}
    use_case, review, exporter = build_named([legacy_ok, legacy_without_copy])
    use_case.execute("ana", "u1", "fake")
    assert [r["id"] for r in exporter.received] == ["a"]
    stored = {r["id"]: r for r in review.resources}
    assert stored["a"]["verification"]["status"] == "current" and stored["a"]["status"] == "aprobado"
    assert stored["b"]["verification"]["status"] == "pending" and stored["b"]["status"] == "pendiente"
