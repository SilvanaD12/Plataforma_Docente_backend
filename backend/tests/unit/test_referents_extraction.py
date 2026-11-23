"""Pruebas unitarias para MAT-P2 (Pedido P7 / GEN-P1): extracción, persistencia y aislamiento de referentes."""

from __future__ import annotations

import json
from collections.abc import Sequence

import httpx

from platform5e.application.services.materials.referent_service import ReferentService
from platform5e.domain.generation.generation_plan import PlanFragment, Referent
from platform5e.infrastructure.llm.gemini_referent_extractor import GeminiReferentExtractor


class _InMemoryReferentRepo:
    def __init__(self) -> None:
        self.storage: dict[tuple[str, str], list[Referent]] = {}

    def replace_unit_referents(
        self,
        teacher_id: str,
        unit_id: str,
        referents: Sequence[Referent],
        document_id: str | None = None,
    ) -> None:
        self.storage[(teacher_id, unit_id)] = list(referents)

    def get_unit_referents(self, teacher_id: str, unit_id: str) -> list[Referent]:
        return list(self.storage.get((teacher_id, unit_id), []))


def _sample_fragments() -> list[PlanFragment]:
    return [
        PlanFragment(
            id="frag-001",
            document_id="doc-1",
            document_name="teoria_aprendizaje.pdf",
            location="p. 2",
            text="Según Rodger Bybee, el modelo de indagación estructura la secuencia didáctica en fases.",
            relevance=0.92,
            source_url=None,
            license=None,
        )
    ]


def test_gemini_referent_extractor_parses_valid_referents_and_filters_unknown_fragments() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "referents": [
                                            {
                                                "name": "Rodger W. Bybee",
                                                "description": "Autor principal del enfoque de indagación científica.",
                                                "fragmentIds": ["frag-001", "frag-inexistente"],
                                            }
                                        ]
                                    }
                                )
                            }
                        ]
                    }
                }
            ]
        }
        return httpx.Response(200, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    extractor = GeminiReferentExtractor(api_key="test-key", client=client)

    referents = extractor.extract_referents("Indagación científica", _sample_fragments())
    assert len(referents) == 1
    assert referents[0].name == "Rodger W. Bybee"
    assert referents[0].fragment_ids == ("frag-001",)


def test_gemini_referent_extractor_returns_empty_list_when_no_authors_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = {"candidates": [{"content": {"parts": [{"text": '{"referents": []}'}]}}]}
        return httpx.Response(200, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    extractor = GeminiReferentExtractor(api_key="test-key", client=client)

    referents = extractor.extract_referents("Manual técnico sin autores", _sample_fragments())
    assert referents == []


def test_referent_service_stores_and_isolates_by_teacher_and_unit() -> None:
    repo = _InMemoryReferentRepo()

    class _FakeExtractor:
        def extract_referents(self, topic: str, fragments: Sequence[PlanFragment]) -> list[Referent]:
            return [Referent(name="Leslie Lamport", description="Consenso distribuido", fragment_ids=("frag-001",))]

    service = ReferentService(repository=repo, extractor=_FakeExtractor())
    stored = service.extract_and_store_for_unit(
        teacher_id="docente-a",
        unit_id="unidad-1",
        topic="Sistemas Distribuidos",
        fragments=_sample_fragments(),
        document_id="doc-1",
    )

    assert len(stored) == 1
    assert service.referents_for("docente-a", "unidad-1", "Sistemas Distribuidos", ()) == tuple(stored)
    # Otro docente o unidad no ve los referentes de docente-a
    assert service.referents_for("docente-b", "unidad-1", "Sistemas Distribuidos", ()) == ()