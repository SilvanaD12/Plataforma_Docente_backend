"""GEN-R8 y GEN-C8: copia histórica de todos los fragmentos que referencia un recurso.

T004 prueba el dominio. T027 prueba el pedido completo con el generador por reglas y el adaptador real de verificación
de Revisión: la copia y la verificación de las actividades con pasos, predicciones y criterios.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from platform5e.application.ports.outbound.evidence_provider_port import EvidenceFragment
from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.application.use_cases.generation.run_generation_request import RunGenerationRequest
from platform5e.application.use_cases.generation.start_generation_request import (
    StartGenerationCommand,
    StartGenerationRequest,
)
from platform5e.domain.generation import evidence as evidence_module
from platform5e.domain.generation.evidence import EvidenceSnapshotItem, build_snapshot
from platform5e.domain.generation.generation_request import GenerationMode, GenerationParameters, RequestStatus
from platform5e.infrastructure.adapters.review_verification_adapter import ReviewVerificationAdapter
from tests.support.generation_fakes import (
    FakeEvidence,
    FakeMembership,
    FakeReviewRepository,
    FakeRunner,
    sqlite_repository,
)

RETRIEVED_AT = "2026-11-10T12:00:00+00:00"

FRAGMENTS: list[dict[str, Any]] = [
    {
        "chunkId": f"frag-{n}",
        "documentId": "doc-1" if n < 5 else "doc-2",
        "documentName": "apuntes.pdf" if n < 5 else "Protocolo de transporte (Wikipedia)",
        "location": f"p. {n}",
        "text": f"Texto del fragmento {n}.",
        "relevance": 0.9,
        "sourceUrl": None if n < 5 else "https://es.wikipedia.org/wiki/Protocolo",
        "license": None if n < 5 else "CC BY-SA 4.0",
    }
    for n in range(1, 7)
]

# Un recurso que cita fragmentos desde todos los orígenes posibles.
RESOURCE: dict[str, Any] = {
    "citations": [{"claim": "…", "fragmentIds": ["frag-1"]}],
    "options": [{"text": "…", "sourceFragmentIds": ["frag-2", "frag-1"]}],
    "structure": {
        "guidedSteps": [{"title": "Paso 1", "fragmentIds": ["frag-3"]}],
        "predictions": [{"question": "¿…?", "fragmentIds": ["frag-4"]}],
        "criteria": [{"criterion": "Aplica…", "fragmentIds": ["frag-5", "frag-desaparecido"]}],
    },
}


def referenced_ids_of(resource: dict[str, Any]) -> list[str]:
    """Simula lo que entrega `referenced_fragment_ids` de Revisión por su puerto (no forma parte del dominio)."""
    ids = [f for c in resource.get("citations") or [] for f in c["fragmentIds"]]
    ids += [f for o in resource.get("options") or [] for f in o["sourceFragmentIds"]]
    for key in ("guidedSteps", "predictions", "criteria"):
        ids += [f for item in (resource.get("structure") or {}).get(key) or [] for f in item["fragmentIds"]]
    return ids


def test_the_snapshot_copies_fragments_from_citations_options_and_structure():
    snapshot = build_snapshot(referenced_ids_of(RESOURCE), FRAGMENTS, RETRIEVED_AT)

    # Sin repetir y en el orden de referencia: frag-1 aparece en una cita y en una alternativa.
    assert [item.id for item in snapshot.items] == ["frag-1", "frag-2", "frag-3", "frag-4", "frag-5"]
    assert snapshot.missing_ids == ("frag-desaparecido",)
    assert not snapshot.is_complete


def test_each_item_keeps_text_location_document_provenance_and_date():
    snapshot = build_snapshot(["frag-5"], FRAGMENTS, RETRIEVED_AT)
    assert snapshot.is_complete
    assert snapshot.items[0].to_dict() == {
        "id": "frag-5",
        "text": "Texto del fragmento 5.",
        "location": "p. 5",
        "documentId": "doc-2",
        "documentName": "Protocolo de transporte (Wikipedia)",
        "sourceUrl": "https://es.wikipedia.org/wiki/Protocolo",
        "license": "CC BY-SA 4.0",
        "retrievedAt": RETRIEVED_AT,
    }
    uploaded = build_snapshot(["frag-1"], FRAGMENTS, RETRIEVED_AT).items[0]
    assert (uploaded.source_url, uploaded.license) == (None, None)  # archivo subido por el docente


def test_structure_fragments_are_not_lost():
    """El ajuste conocido: antes solo se copiaban los fragmentos de citas y alternativas."""
    structure_only = {"structure": RESOURCE["structure"]}
    snapshot = build_snapshot(referenced_ids_of(structure_only), FRAGMENTS, RETRIEVED_AT)
    assert {item.id for item in snapshot.items} == {"frag-3", "frag-4", "frag-5"}


def test_a_fragment_without_text_counts_as_missing():
    """Igual que `incomplete_copy_reason` de Revisión: un fragmento vacío no sustenta la cita."""
    blank = [
        {**FRAGMENTS[0], "chunkId": "frag-empty", "text": ""},
        {**FRAGMENTS[0], "chunkId": "frag-spaces", "text": "  \n\t "},
        {**FRAGMENTS[0], "chunkId": "frag-none", "text": None},
        FRAGMENTS[1],
    ]
    snapshot = build_snapshot(["frag-empty", "frag-2", "frag-spaces", "frag-none"], blank, RETRIEVED_AT)
    assert [item.id for item in snapshot.items] == ["frag-2"]
    assert snapshot.missing_ids == ("frag-empty", "frag-spaces", "frag-none")
    assert not snapshot.is_complete


def test_fragments_with_the_generation_id_key_are_accepted():
    legacy = [{"id": "frag-9", "text": "Texto", "location": "p. 9", "documentId": "doc-1", "documentName": "a.pdf"}]
    item = build_snapshot(["frag-9"], legacy, RETRIEVED_AT).items[0]
    assert item == EvidenceSnapshotItem("frag-9", "Texto", "p. 9", "doc-1", "a.pdf", None, None, RETRIEVED_AT)


def test_a_resource_without_references_has_an_empty_complete_snapshot():
    snapshot = build_snapshot([], FRAGMENTS, RETRIEVED_AT)
    assert snapshot.items == () and snapshot.is_complete
    assert build_snapshot(["", None, "frag-1"], FRAGMENTS, RETRIEVED_AT).missing_ids == ()  # type: ignore[list-item]


def test_evidence_does_not_import_the_review_domain():
    tree = ast.parse(Path(evidence_module.__file__).read_text(encoding="utf-8"))
    imported = [
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ] + [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not [name for name in imported if "review" in name]


# T027 · Actividades redactadas por reglas, de punta a punta del caso de uso

MATERIAL = (
    "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable de los segmentos.",
    "El protocolo UDP no establece conexión y es más rápido, pero no garantiza la entrega.",
    "TCP usa un saludo de tres vías antes de enviar datos entre el cliente y el servidor.",
    "Las aplicaciones de video en vivo suelen usar UDP porque toleran la pérdida de algunos paquetes.",
    "El control de congestión de TCP reduce la velocidad de envío cuando la red se satura.",
)
ACTIVITY_ITEMS = {"exploracion_guiada": "guidedSteps", "reto_prediccion": "predictions", "caso_aplicado": "criteria"}
RAW_ITEMS = {"exploracion_guiada": "pasos_guiados", "reto_prediccion": "predicciones", "caso_aplicado": "criterios"}


def material_fragments(extra: tuple[EvidenceFragment, ...] = ()) -> tuple[EvidenceFragment, ...]:
    return tuple(
        EvidenceFragment(f"f{n}", "doc-1", "apuntes.pdf", f"p. {n}", text, 0.9 - n / 10, None, None)
        for n, text in enumerate(MATERIAL, start=1)
    ) + extra


class LastItemOnlyInStructure(RuleBasedGenerator):
    """Redacta por reglas y quita la última cita, de modo que el fragmento del último paso, predicción o criterio
    solo aparece en la estructura (el caso que antes se perdía de la copia)."""

    def generate(self, context: dict[str, Any]) -> dict[str, Any]:
        response = super().generate(context)
        for resource in response["recursos"]:
            resource["citas"] = resource["citas"][:-1]
        return response


class ReferencesABlankFragment(RuleBasedGenerator):
    """Redacta por reglas y agrega al primer elemento de la estructura un fragmento recuperado sin texto."""

    def __init__(self, resource_type: str, tag: str) -> None:
        super().__init__()
        self.resource_type, self.tag = resource_type, tag

    def generate(self, context: dict[str, Any]) -> dict[str, Any]:
        response = super().generate(context)
        for resource in response["recursos"]:
            first = resource["estructura"][RAW_ITEMS[self.resource_type]][0]
            first["fragmentos"] = [*first["fragmentos"], self.tag]
        return response


def run_activity(tmp_path, resource_type: str, generator, fragments) -> tuple[Any, list[dict[str, Any]]]:
    repository, membership, evidence = sqlite_repository(tmp_path), FakeMembership(), FakeEvidence(fragments)
    review = FakeReviewRepository()
    request_id = StartGenerationRequest(membership, evidence, repository, FakeRunner()).execute(
        StartGenerationCommand(
            "docente-a", "u1", GenerationMode.INDIVIDUAL, f"clave-{resource_type}", GenerationParameters((resource_type,))
        )
    ).request.id
    RunGenerationRequest(
        repository, membership, evidence, review, ReviewVerificationAdapter(), generator, generator, heartbeat_seconds=0
    ).execute(request_id)
    return repository.get("docente-a", request_id), review.all()


@pytest.mark.parametrize("resource_type", list(ACTIVITY_ITEMS))
def test_rule_based_activities_copy_the_fragments_of_their_items(tmp_path, resource_type):
    request, [resource] = run_activity(tmp_path, resource_type, LastItemOnlyInStructure(), material_fragments())

    items = resource["structure"][ACTIVITY_ITEMS[resource_type]]
    cited = {f for citation in resource["citations"] for f in citation["fragmentIds"]}
    item_ids = [f for item in items for f in item["fragmentIds"]]
    only_in_structure = [f for f in item_ids if f not in cited]
    copied = {item["id"]: item for item in resource["evidence"]}

    assert request.status == RequestStatus.SUCCEEDED and resource["generatorKind"] == "respaldo"
    assert only_in_structure, "la prueba necesita un fragmento citado solo por la estructura"
    assert set(item_ids) <= set(copied)  # pasos, predicciones o criterios
    assert all(copied[f]["text"] == MATERIAL[int(f[1:]) - 1] and copied[f]["retrievedAt"] for f in item_ids)
    assert resource["verification"]["status"] == "current" and resource["verification"]["retryAvailable"] is False


@pytest.mark.parametrize("resource_type", list(ACTIVITY_ITEMS))
def test_a_referenced_fragment_missing_from_the_copy_leaves_the_resource_pending(tmp_path, resource_type):
    """Un fragmento referenciado que llegó sin texto no se copia: Revisión no lo puede comprobar ni reintentar."""
    blank = EvidenceFragment("f6", "doc-1", "apuntes.pdf", "p. 6", "   ", 0.1, None, None)
    request, [resource] = run_activity(
        tmp_path, resource_type, ReferencesABlankFragment(resource_type, "F6"), material_fragments((blank,))
    )

    first_item = resource["structure"][ACTIVITY_ITEMS[resource_type]][0]
    verification = resource["verification"]
    assert request.status == RequestStatus.SUCCEEDED
    assert "f6" in first_item["fragmentIds"] and "f6" not in {item["id"] for item in resource["evidence"]}
    assert verification["status"] == "pending" and verification["retryAvailable"] is False
    assert "f6" in verification["reason"] and "regenera" in verification["reason"]
