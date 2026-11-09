"""GEN-01 (T009 y T011): ejecutor en segundo plano y adaptador inicial de Material, con puertos falsos. Sin red y sin
base de datos. Las pruebas del adaptador de pertenencia (T010) están en test_unit_membership_adapter.py."""

from __future__ import annotations

import threading
from typing import Any

import pytest

from platform5e.application.ports.outbound.evidence_provider_port import (
    EvidenceQuery,
    EvidenceUnavailable,
    NoProcessedMaterial,
)
from platform5e.domain.generation.errors import GenerationErrorCode
from platform5e.domain.generation.generation_request import Problem, RequestStatus
from platform5e.infrastructure.adapters.material_evidence_adapter import MaterialEvidenceAdapter
from platform5e.infrastructure.jobs.thread_pool_generation_runner import ThreadPoolGenerationRunner
from platform5e.infrastructure.settings import (
    generation_max_workers,
    generation_request_deadline_seconds,
    generation_sweep_interval_seconds,
)

class FakeTeacherRepository:
    """Solo lo que usa el adaptador de Material: los documentos del docente."""

    def __init__(self, documents: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.documents = documents or {}

    def get_documents(self, teacher_id: str) -> list[dict[str, Any]]:
        return self.documents.get(teacher_id, [])


# T011 · Evidencia de Material


def chunk(chunk_id: str, document_id: str = "doc-1", unit_id: str = "u1") -> dict[str, Any]:
    # Misma forma que devuelve SQLAlchemyChunkRepository (claves en inglés y nombres anteriores).
    return {
        "id": chunk_id,
        "documentId": document_id,
        "document_id": document_id,
        "unitId": unit_id,
        "unit_id": unit_id,
        "location": f"p. {chunk_id[-1]}",
        "text": f"Texto de {chunk_id}.",
    }


class FakeChunkRepository:
    def __init__(self, chunks: dict[tuple[str, str], list[dict[str, Any]]]) -> None:
        self.chunks = chunks
        self.calls: list[tuple[str, str]] = []

    def get_chunks_by_unit(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        self.calls.append((teacher_id, unit_id))
        return [dict(c) for c in self.chunks.get((teacher_id, unit_id), [])]


class FakeRetriever:
    description = "búsqueda falsa"

    def __init__(
        self,
        extra_results: list[dict[str, Any]] | None = None,
        error: Exception | None = None,
        mode: str | None = "hybrid",
    ) -> None:
        self.extra_results = extra_results or []
        self.error = error
        self.mode = mode
        self.received: dict[str, Any] = {}

    def retrieve(self, query, chunks=None, top_k=5, unit_id=None, teacher_id=""):
        self.received = {"query": query, "chunks": chunks, "top_k": top_k, "unit_id": unit_id, "teacher_id": teacher_id}
        if self.error:
            raise self.error
        ranked = [{**c, "relevance": 1.0 - i * 0.25} for i, c in enumerate(reversed(chunks or []))]
        if self.mode is not None:  # como HybridEvidenceRetriever, que marca cada fragmento
            ranked = [{**c, "retrieval_mode": self.mode, "retrievalMode": self.mode} for c in ranked]
        return (self.extra_results + ranked)[:top_k]


DOCUMENTS = {
    "docente-a": [
        {"id": "doc-1", "unitId": "u1", "fileName": "apuntes.pdf", "origin": None},
        {
            "id": "doc-2",
            "unitId": "u1",
            "fileName": "Protocolo (Wikipedia).txt",
            "origin": {"url": "https://es.wikipedia.org/wiki/Protocolo", "license": "CC BY-SA 4.0"},
        },
        {"id": "doc-3", "unitId": "u2", "fileName": "otra-unidad.pdf"},
    ]
}


def make_adapter(retriever: FakeRetriever | None = None) -> tuple[MaterialEvidenceAdapter, FakeChunkRepository]:
    chunks = FakeChunkRepository(
        {
            ("docente-a", "u1"): [chunk("frag-1"), chunk("frag-2", "doc-2")],
            ("docente-b", "u1"): [chunk("frag-ajeno")],
        }
    )
    return MaterialEvidenceAdapter(chunks, retriever or FakeRetriever(), FakeTeacherRepository(DOCUMENTS)), chunks


def test_processed_material_is_checked_for_the_teacher_and_unit():
    adapter, chunks = make_adapter()
    assert adapter.has_processed_material("docente-a", "u1") is True
    assert adapter.has_processed_material("docente-a", "u2") is False
    assert adapter.has_processed_material("", "u1") is False
    assert ("", "u1") not in chunks.calls


def test_retrieve_passes_the_teacher_chunks_and_adds_provenance():
    retriever = FakeRetriever()
    adapter, chunks = make_adapter(retriever)
    retrieval = adapter.retrieve(EvidenceQuery("docente-a", "u1", "TCP y UDP", limit=5))

    assert chunks.calls == [("docente-a", "u1")]  # nunca get_chunks_by_unit("", …)
    assert [c["id"] for c in retriever.received["chunks"]] == ["frag-1", "frag-2"]
    assert (retriever.received["top_k"], retriever.received["unit_id"]) == (5, "u1")
    assert retriever.received["teacher_id"] == "docente-a"  # T031: la búsqueda vectorial filtra por docente
    assert retrieval.retrieval_mode == "hybrid"

    by_id = {f.chunk_id: f for f in retrieval.fragments}
    assert [f.chunk_id for f in retrieval.fragments] == ["frag-2", "frag-1"]  # orden del buscador
    assert (by_id["frag-1"].document_name, by_id["frag-1"].source_url, by_id["frag-1"].license) == (
        "apuntes.pdf",
        None,
        None,
    )
    assert by_id["frag-2"].source_url == "https://es.wikipedia.org/wiki/Protocolo"
    assert by_id["frag-2"].license == "CC BY-SA 4.0" and by_id["frag-2"].text == "Texto de frag-2."
    assert 0.0 <= by_id["frag-1"].relevance <= 1.0


def test_results_outside_the_teacher_chunks_are_dropped():
    """La búsqueda vectorial de hoy filtra solo por unidad: un fragmento de otro docente no se usa."""
    intruder = {**chunk("frag-ajeno"), "relevance": 0.99}
    adapter, _ = make_adapter(FakeRetriever(extra_results=[intruder]))
    retrieval = adapter.retrieve(EvidenceQuery("docente-a", "u1", "TCP", limit=5))
    assert "frag-ajeno" not in {f.chunk_id for f in retrieval.fragments}


@pytest.mark.parametrize("mode", ["hybrid", "bm25_fallback"])
def test_the_request_takes_the_retrieval_mode_of_the_fragments(mode):
    """T031: el modo del pedido es el que el buscador marcó en los fragmentos que se usan."""
    adapter, _ = make_adapter(FakeRetriever(mode=mode))
    assert adapter.retrieve(EvidenceQuery("docente-a", "u1", "TCP", limit=5)).retrieval_mode == mode


def test_the_retrieval_mode_is_none_without_fragments_or_an_unknown_mode(caplog):
    """T031: sin fragmentos no hay de dónde tomar el modo; un modo desconocido o ausente tampoco se inventa."""
    nothing, _ = make_adapter(FakeRetriever())
    empty = nothing.retrieve(EvidenceQuery("docente-a", "u1", "TCP", limit=0))
    assert empty.fragments == () and empty.retrieval_mode is None

    # Solo el fragmento ajeno trae modo, y se descarta: el modo sale de los fragmentos que se usan.
    intruder = {**chunk("frag-ajeno"), "relevance": 0.99, "retrieval_mode": "hybrid"}
    unmarked, _ = make_adapter(FakeRetriever(extra_results=[intruder], mode=None))
    with caplog.at_level("WARNING", logger="platform5e.generation.evidence"):
        retrieval = unmarked.retrieve(EvidenceQuery("docente-a", "u1", "TCP", limit=5))
    assert retrieval.fragments and retrieval.retrieval_mode is None
    assert "modo de recuperación" in caplog.text

    unknown, _ = make_adapter(FakeRetriever(mode="vector_only"))
    assert unknown.retrieve(EvidenceQuery("docente-a", "u1", "TCP", limit=5)).retrieval_mode is None


def test_retrieve_without_material_or_with_a_failing_search():
    adapter, _ = make_adapter()
    with pytest.raises(NoProcessedMaterial) as missing:
        adapter.retrieve(EvidenceQuery("docente-a", "u2", "TCP", limit=5))
    assert missing.value.code == GenerationErrorCode.NO_PROCESSED_MATERIAL

    failing, _ = make_adapter(FakeRetriever(error=TimeoutError("sin respuesta")))
    with pytest.raises(EvidenceUnavailable) as unavailable:
        failing.retrieve(EvidenceQuery("docente-a", "u1", "TCP", limit=5))
    assert unavailable.value.code == GenerationErrorCode.EVIDENCE_UNAVAILABLE
    assert "sin respuesta" not in unavailable.value.message  # el detalle técnico no llega al docente


# T009 · Ejecutor en segundo plano


class FakeRequestRepository:
    def __init__(self, fail_on_finish: bool = False) -> None:
        self.finished: list[tuple[str, RequestStatus, Problem | None]] = []
        self.fail_on_finish = fail_on_finish

    def finish(self, request_id: str, status: RequestStatus, failure: Problem | None) -> bool:
        if self.fail_on_finish:
            raise ConnectionError("base caída")
        self.finished.append((request_id, status, failure))
        return True

    def heartbeat(self, request_id: str) -> bool:
        return True


def test_the_runner_executes_requests_in_background_threads():
    executed: list[tuple[str, str]] = []
    repository = FakeRequestRepository()
    runner = ThreadPoolGenerationRunner(
        lambda request_id: executed.append((request_id, threading.current_thread().name)), repository, max_workers=2
    )
    with pytest.raises(RuntimeError):
        runner.submit("gen-req-antes")  # el lifespan todavía no lo inició
    runner.start()
    futures = [runner.submit(f"gen-req-{n}") for n in range(3)]
    for future in futures:
        future.result(timeout=5)
    runner.shutdown(wait=True)

    assert sorted(request_id for request_id, _ in executed) == ["gen-req-0", "gen-req-1", "gen-req-2"]
    assert all(name.startswith("generation") for _, name in executed)
    assert repository.finished == []
    with pytest.raises(RuntimeError):
        runner.submit("gen-req-tarde")


def test_an_unhandled_error_marks_the_request_failed_and_is_logged(caplog):
    repository = FakeRequestRepository()

    def explode(request_id: str) -> None:
        raise ValueError("detalle interno")

    runner = ThreadPoolGenerationRunner(explode, repository, max_workers=1)
    runner.start()
    with caplog.at_level("ERROR", logger="platform5e.generation.runner"):
        runner.submit("gen-req-1").result(timeout=5)
    runner.shutdown(wait=True)

    [(request_id, status, problem)] = repository.finished
    assert (request_id, status) == ("gen-req-1", RequestStatus.FAILED)
    assert problem.code == GenerationErrorCode.GENERATION_FAILED and "detalle interno" not in problem.message
    assert "gen-req-1" in caplog.text and "detalle interno" in caplog.text


def test_the_runner_survives_when_the_failure_cannot_be_saved(caplog):
    runner = ThreadPoolGenerationRunner(
        lambda request_id: (_ for _ in ()).throw(ValueError("x")), FakeRequestRepository(fail_on_finish=True), 1
    )
    runner.start()
    with caplog.at_level("ERROR", logger="platform5e.generation.runner"):
        runner.submit("gen-req-1").result(timeout=5)  # no propaga la excepción
    runner.shutdown(wait=True)
    assert "No se pudo marcar como fallido" in caplog.text


def test_generation_settings_have_safe_defaults():
    assert generation_max_workers({}) == 2
    assert generation_request_deadline_seconds({}) == 900
    assert generation_max_workers({"GENERATION_MAX_WORKERS": "4"}) == 4
    for invalid in ("0", "-1", "dos", ""):
        assert generation_max_workers({"GENERATION_MAX_WORKERS": invalid}) == 2
    assert generation_request_deadline_seconds({"GENERATION_REQUEST_DEADLINE_SECONDS": "60"}) == 60
    assert generation_sweep_interval_seconds({}) == 30
    assert generation_sweep_interval_seconds({"GENERATION_SWEEP_INTERVAL_SECONDS": "10"}) == 10
    assert generation_sweep_interval_seconds({"GENERATION_SWEEP_INTERVAL_SECONDS": "0"}) == 30
