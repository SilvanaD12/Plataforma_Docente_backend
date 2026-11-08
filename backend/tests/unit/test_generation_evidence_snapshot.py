"""GEN-R8 y GEN-C8 (T004): copia histórica de todos los fragmentos que referencia un recurso. Solo dominio."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from platform5e.domain.generation import evidence as evidence_module
from platform5e.domain.generation.evidence import EvidenceSnapshotItem, build_snapshot

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
