"""Puertos falsos y datos de prueba para los casos de uso del pedido de generación (GEN-01). Sin red."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import create_engine

from platform5e.application.ports.outbound.evidence_provider_port import (
    EvidenceFragment,
    EvidenceQuery,
    EvidenceRetrieval,
    NoProcessedMaterial,
)
from platform5e.application.ports.outbound.unit_membership_port import OutcomeRef, UnitContext
from platform5e.infrastructure.persistence.repositories.sqlalchemy_generation_request_repository import (
    SQLAlchemyGenerationRequestRepository,
)

UNIT = UnitContext(
    course_id="c1",
    course_name="Redes",
    course_summary="Curso de redes.",
    learning_goal="Explica cómo se comunican los equipos.",
    unit_id="u1",
    unit_number=1,
    unit_title="Protocolos de transporte",
    outcomes=(OutcomeRef("ra-1", "RA1.1", "Distingue TCP y UDP"),),
)
FRAGMENTS = (
    EvidenceFragment(
        chunk_id="f1",
        document_id="doc1",
        document_name="apuntes.pdf",
        location="p. 1",
        text="El protocolo TCP es orientado a la conexión y garantiza una entrega confiable.",
        relevance=0.9,
        source_url=None,
        license=None,
    ),
    EvidenceFragment(
        chunk_id="f2",
        document_id="doc1",
        document_name="apuntes.pdf",
        location="p. 2",
        text="El protocolo UDP no establece conexión y es más rápido.",
        relevance=0.7,
        source_url=None,
        license=None,
    ),
)
INVENTED_RESOURCE = {
    "titulo": "Inventado",
    "contenido": "Los satélites geoestacionarios orbitan sobre el ecuador a gran altura.",
    "citas": [{"afirmacion": "Los satélites geoestacionarios orbitan sobre el ecuador", "fragmentos": ["F1"]}],
    "alternativas": [],
}


class FakeMembership:
    def __init__(self, units: dict[tuple[str, str], UnitContext] | None = None) -> None:
        self.units = units if units is not None else {("docente-a", "u1"): UNIT}

    def get_unit_context(self, teacher_id: str, unit_id: str) -> UnitContext | None:
        return self.units.get((teacher_id, unit_id))


class FakeEvidence:
    def __init__(
        self,
        fragments: tuple[EvidenceFragment, ...] = FRAGMENTS,
        material: bool = True,
        error: Exception | None = None,
    ) -> None:
        self.fragments = fragments
        self.material = material
        self.error = error
        self.queries: list[EvidenceQuery] = []

    def has_processed_material(self, teacher_id: str, unit_id: str) -> bool:
        return self.material

    def retrieve(self, query: EvidenceQuery) -> EvidenceRetrieval:
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        if not self.material:
            raise NoProcessedMaterial()
        return EvidenceRetrieval(fragments=self.fragments, retrieval_mode=None)


class FakeReviewRepository:
    def __init__(self) -> None:
        self.saved: dict[tuple[str, str], list[dict[str, Any]]] = {}

    def save_resources(self, teacher_id: str, unit_id: str, resources: list[dict[str, Any]]) -> None:
        self.saved.setdefault((teacher_id, unit_id), []).extend(resources)

    def get_resources_by_unit(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        return list(self.saved.get((teacher_id, unit_id), []))

    def delete_resource(self, teacher_id: str, resource_id: str) -> None:
        for (owner, unit_id), resources in self.saved.items():
            if owner == teacher_id:
                self.saved[(owner, unit_id)] = [r for r in resources if r.get("id") != resource_id]

    def all(self) -> list[dict[str, Any]]:
        return [resource for resources in self.saved.values() for resource in resources]


class FakeRunner:
    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, request_id: str) -> None:
        self.submitted.append(request_id)

    def shutdown(self, wait: bool) -> None: ...


class FailingGenerator:
    """Generador que siempre falla, como una IA que no responde."""

    description = "IA caída"
    uses_ai = True

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, context: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        raise TimeoutError("sin respuesta del proveedor")


def sqlite_repository(directory: Path) -> SQLAlchemyGenerationRequestRepository:
    bind = create_engine(f"sqlite:///{directory / 'generation.db'}", connect_args={"check_same_thread": False})
    return SQLAlchemyGenerationRequestRepository(bind)
