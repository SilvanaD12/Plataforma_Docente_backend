"""TA-010 (T062): evidencia recuperada de un pedido, para la evaluación RAG (research R12).

Es todo lo que el pedido recuperó del material y entregó al modelo, en el orden de la recuperación, no solo lo que
citan los recursos.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.application.use_cases.generation.get_generation_evidence import GetGenerationEvidence
from platform5e.application.use_cases.generation.run_generation_request import RunGenerationRequest
from platform5e.application.use_cases.generation.start_generation_request import StartGenerationCommand
from platform5e.domain.generation.errors import GenerationError, GenerationErrorCode
from platform5e.domain.generation.generation_request import GenerationMode, GenerationParameters, RequestStatus
from platform5e.infrastructure.adapters.review_verification_adapter import ReviewVerificationAdapter
from tests.support.generation_fakes import FRAGMENTS
from tests.unit.test_kinesthetic_activity import _corpus_fragments
from tests.unit.test_start_regeneration import Setup

FRAGMENT_FIELDS = {"chunkId", "documentId", "documentName", "location", "text", "relevance", "sourceUrl", "license"}


@pytest.fixture
def setup(tmp_path) -> Setup:
    return Setup(tmp_path)


def _start(setup: Setup, *types: str, key: str = "clave-evidencia-1", **parameters) -> str:
    mode = GenerationMode.INDIVIDUAL if len(types) == 1 else GenerationMode.SEQUENCE
    return setup.use_case._start_generation.execute(
        StartGenerationCommand(
            "docente-a", "u1", mode, key, GenerationParameters(resource_types=types or ("explicacion",), **parameters)
        )
    ).request.id


def _run(setup: Setup, request_id: str) -> None:
    RunGenerationRequest(
        setup.repository, setup.membership, setup.evidence, setup.review, ReviewVerificationAdapter(),
        RuleBasedGenerator(), heartbeat_seconds=0,
    ).execute(request_id)


def test_a_queued_request_has_no_evidence_yet(setup):
    evidence = GetGenerationEvidence(setup.repository).execute("docente-a", _start(setup, top_k=10))
    assert evidence.fragments == () and evidence.retrieval_mode is None and evidence.retrieved_at is None
    assert evidence.limit == 10


@pytest.mark.parametrize(("top_k", "limit"), [(1, 3), (8, 8), (12, 12), (50, 12)])
def test_the_limit_is_the_one_the_request_used_to_retrieve(setup, top_k, limit):
    request_id = _start(setup, top_k=top_k, key=f"clave-evidencia-{top_k}")
    assert GetGenerationEvidence(setup.repository).execute("docente-a", request_id).limit == limit


def test_the_fragments_keep_the_retrieval_order_and_their_fields(setup):
    # La recuperación devolvió primero f2 y después f1: ese orden se conserva.
    setup.evidence.fragments = (FRAGMENTS[1], FRAGMENTS[0])
    setup.evidence.retrieval_mode = "hybrid"
    request_id = _start(setup, "pregunta_detonante")
    _run(setup, request_id)

    evidence = GetGenerationEvidence(setup.repository).execute("docente-a", request_id)
    assert evidence.request_id == request_id and evidence.retrieval_mode == "hybrid"
    assert [fragment["chunkId"] for fragment in evidence.fragments] == ["f2", "f1"]
    assert all(set(fragment) == FRAGMENT_FIELDS for fragment in evidence.fragments)  # sin retrievedAt
    stored = setup.repository.get("docente-a", request_id).evidence
    assert evidence.retrieved_at == stored[0]["retrievedAt"]
    assert evidence.fragments[0] == {key: value for key, value in stored[0].items() if key != "retrievedAt"}


def test_the_cited_fragments_are_a_subset_of_the_retrieved_ones(setup):
    setup.evidence.fragments = _corpus_fragments()
    request_id = _start(setup, "pregunta_detonante", "explicacion")
    _run(setup, request_id)
    assert setup.repository.get("docente-a", request_id).status in {
        RequestStatus.SUCCEEDED, RequestStatus.PARTIALLY_SUCCEEDED,
    }

    evidence = GetGenerationEvidence(setup.repository).execute("docente-a", request_id)
    retrieved = [fragment["chunkId"] for fragment in evidence.fragments]
    assert len(retrieved) == len(setup.evidence.fragments)
    assert retrieved == [fragment.chunk_id for fragment in setup.evidence.fragments]
    cited = {item["id"] for resource in setup.review.all() for item in resource["evidence"]}
    assert cited and cited <= set(retrieved)


def test_another_teacher_or_a_missing_request_is_not_found(setup):
    request_id = _start(setup)
    use_case = GetGenerationEvidence(setup.repository)
    for teacher_id, wanted in [("docente-b", request_id), ("docente-a", "gen-req-no-existe")]:
        with pytest.raises(GenerationError) as missing:
            use_case.execute(teacher_id, wanted)
        assert missing.value.code == GenerationErrorCode.GENERATION_REQUEST_NOT_FOUND
        assert missing.value.message == "El pedido de generación no existe."


def test_the_fragments_cannot_be_changed_through_the_result(setup):
    setup.evidence.fragments = (replace(FRAGMENTS[0]),)
    request_id = _start(setup, "pregunta_detonante")
    _run(setup, request_id)
    use_case = GetGenerationEvidence(setup.repository)
    first = use_case.execute("docente-a", request_id)
    first.fragments[0]["text"] = "cambiado"
    assert use_case.execute("docente-a", request_id).fragments[0]["text"] == FRAGMENTS[0].text
