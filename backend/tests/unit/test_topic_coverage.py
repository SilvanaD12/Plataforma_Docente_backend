"""QA-05: antes de redactar se comprueba que la evidencia recuperada trata el tema que pidió el docente.

Con el material real de corpus_t067 (T068) y la búsqueda por palabras (BM25) del servidor, sin IA: C-06 (bases de
datos en una unidad de redes) se rechaza con el motivo; C-01 genera. Diseño y umbral en
specs/005-atributos-calidad/plan.md (QA-05).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from platform5e.application.ports.outbound.evidence_provider_port import (
    EvidenceFragment,
    EvidenceQuery,
    EvidenceRetrieval,
)
from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.application.use_cases.generation.run_generation_request import RunGenerationRequest, off_topic_message
from platform5e.application.use_cases.generation.start_generation_request import StartGenerationCommand
from platform5e.application.use_cases.generation.start_regeneration import StartRegenerationCommand
from platform5e.domain.generation.errors import GenerationErrorCode
from platform5e.domain.generation.generation_request import (
    GenerationMode,
    GenerationParameters,
    RequestStatus,
    StepStatus,
)
from platform5e.domain.generation.topic_coverage import (
    DEFAULT_COVERAGE_THRESHOLD,
    assess_topic_coverage,
    topic_phrases,
    topic_terms,
)
from platform5e.domain.materials.chunking import chunk_pages
from platform5e.domain.materials.text_analysis import retrieve_relevant_chunks
from platform5e.infrastructure.adapters.review_verification_adapter import ReviewVerificationAdapter
from platform5e.infrastructure.extraction.document_text_extractor import DocumentTextExtractor
from platform5e.infrastructure.settings import topic_coverage_threshold
from tests.support.generation_fakes import FakeEvidence
from tests.unit.test_start_regeneration import SAVED_PARAMS, Setup

EVALUATION = Path(__file__).resolve().parents[2] / "evaluation"
CASES = {case["id"]: case for case in json.loads((EVALUATION / "cases_t067.json").read_text(encoding="utf-8"))["cases"]}
C06_REASON = (
    "El material de la unidad no trata «llaves primarias, modelo relacional». Sube material sobre ese tema o cambia "
    "las indicaciones."
)


# Términos y frases del tema


def test_topic_terms_drop_stopwords_style_and_framing_words_and_remove_accents():
    assert topic_terms("¿Cómo se estructuran las tablas y llaves primarias en un modelo relacional?") == [
        "tablas", "llaves", "primarias", "modelo", "relacional",
    ]
    assert topic_terms("Explicación breve de la función del protocolo IP, con ejemplos para estudiantes.") == [
        "protocolo", "ip",
    ]
    assert topic_terms("Análisis de redes y ANÁLISIS de REDES") == ["analisis", "redes"]  # sin repetir


def test_style_only_instructions_have_no_topic():
    assert topic_terms("Usa ejemplos breves y un lenguaje sencillo para los estudiantes.") == []


def test_topic_phrases_join_terms_side_by_side_or_with_de():
    assert [p.text for p in topic_phrases("¿Qué diferencia existe entre TCP y UDP en la capa de transporte?")] == [
        "capa de transporte",
    ]
    assert [p.text for p in topic_phrases("Llaves primarias en un modelo relacional")] == [
        "llaves primarias", "modelo relacional",
    ]


# Cobertura


def test_coverage_counts_singular_and_plural_and_ignores_accents():
    coverage = assess_topic_coverage("Capas del modelo OSI y su relación", ["Las capa del Modelo OSI: relacion."])
    assert coverage.terms == ("capas", "modelo", "osi", "relacion") and coverage.coverage == 1.0


def test_a_phrase_found_in_the_evidence_accepts_low_coverage():
    """Las palabras de un escenario no están en el material aunque el tema sí (caso c04 de cases.json)."""
    fragment = ["Los protocolos de transporte entregan los datos entre procesos."]
    coverage = assess_topic_coverage("Caso de una empresa que elige el protocolo de transporte para transmitir en vivo.",
                                     fragment)
    assert coverage.coverage == pytest.approx(0.4) and [p.text for p in coverage.found_phrases] == [
        "protocolo de transporte",
    ]
    assert coverage.accepted


def test_low_coverage_without_any_phrase_is_rejected_and_names_what_is_missing():
    fragments = ["Las tablas de enrutamiento guardan las rutas.", "El modelo OSI tiene siete capas."]
    coverage = assess_topic_coverage(CASES["C-06"]["instructions"], fragments)
    assert coverage.found == ("tablas", "modelo") and coverage.coverage == pytest.approx(0.4)
    assert not coverage.accepted and coverage.missing_topic() == ["llaves primarias", "modelo relacional"]
    assert off_topic_message(coverage) == C06_REASON


def test_without_instructions_or_with_one_term_nothing_is_checked():
    for instructions in ("", "Usa un ejemplo de videollamadas.", "¿Cuáles son las características principales de UDP?"):
        coverage = assess_topic_coverage(instructions, ["Texto sin relación."])
        assert not coverage.checked and coverage.accepted


def test_a_threshold_of_zero_turns_the_check_off():
    assert assess_topic_coverage(CASES["C-06"]["instructions"], ["Nada que ver."], threshold=0).accepted


def test_the_missing_terms_keep_the_teacher_spelling():
    coverage = assess_topic_coverage("Normalización y álgebra relacional", ["Nada que ver."])
    assert coverage.missing_topic() == ["álgebra relacional", "normalización"]


# Configuración


@pytest.mark.parametrize(
    ("value", "expected"),
    [("", DEFAULT_COVERAGE_THRESHOLD), ("0.7", 0.7), ("0", 0.0), ("1", 1.0), ("-1", DEFAULT_COVERAGE_THRESHOLD),
     ("1.5", DEFAULT_COVERAGE_THRESHOLD), ("mucho", DEFAULT_COVERAGE_THRESHOLD)],
)
def test_the_threshold_setting(value, expected):
    assert topic_coverage_threshold({"TOPIC_COVERAGE_THRESHOLD": value}) == expected
    assert topic_coverage_threshold({}) == DEFAULT_COVERAGE_THRESHOLD


# El pedido, con el material real de T068 y la búsqueda BM25 del servidor


def _corpus_fragments(names: list[str]) -> list[dict]:
    extractor, chunks = DocumentTextExtractor(), []
    for name in names:
        path = EVALUATION / "corpus_t067" / name
        kind = path.suffix.lstrip(".").lower()
        for number, chunk in enumerate(chunk_pages(extractor.extract(kind, path.read_bytes()))):
            chunks.append({**chunk, "id": f"{path.stem}-{number}", "document": name})
    return chunks


class CorpusEvidence(FakeEvidence):
    """Recupera de verdad: los fragmentos del corpus, con la búsqueda por palabras del servidor (`bm25_fallback`)."""

    def __init__(self, names: list[str]) -> None:
        super().__init__(retrieval_mode="bm25_fallback")
        self.chunks = _corpus_fragments(names)

    def retrieve(self, query: EvidenceQuery) -> EvidenceRetrieval:
        self.queries.append(query)
        selected = retrieve_relevant_chunks(query.query, self.chunks, query.limit)
        fragments = tuple(
            EvidenceFragment(chunk_id=c["id"], document_id=c["document"], document_name=c["document"],
                             location=str(c.get("location") or "p. 1"), text=c["text"],
                             relevance=float(c["relevance"]), source_url=None, license=None)
            for c in selected
        )
        return EvidenceRetrieval(fragments=fragments, retrieval_mode=self.retrieval_mode)


@pytest.fixture
def setup(tmp_path) -> Setup:
    return Setup(tmp_path)


def run(setup: Setup, evidence: FakeEvidence, *types: str, instructions: str, key: str, **kwargs):
    setup.evidence = evidence
    setup.use_case._start_generation._evidence = evidence
    mode = GenerationMode.INDIVIDUAL if len(types) == 1 else GenerationMode.SEQUENCE
    request = setup.use_case._start_generation.execute(
        StartGenerationCommand("docente-a", "u1", mode, key,
                               GenerationParameters(resource_types=types, instructions=instructions, top_k=8))
    ).request
    RunGenerationRequest(setup.repository, setup.membership, evidence, setup.review, ReviewVerificationAdapter(),
                         RuleBasedGenerator(), heartbeat_seconds=0, **kwargs).execute(request.id)
    return setup.repository.get("docente-a", request.id)


def test_c06_is_rejected_before_drafting_with_the_reason(setup):
    evidence = CorpusEvidence(CASES["C-06"]["documents"])  # los 5 archivos de redes, sin el de bases de datos
    finished = run(setup, evidence, "explicacion", instructions=CASES["C-06"]["instructions"], key="clave-qa05-c06")
    assert finished.status == RequestStatus.FAILED
    assert finished.failure.code == GenerationErrorCode.INSUFFICIENT_EVIDENCE and finished.failure.message == C06_REASON
    [step] = finished.steps
    assert step.status == StepStatus.FAILED and step.resource_ids == () and step.error.message == C06_REASON
    assert setup.review.all() == []  # no se redactó ni se guardó ningún recurso
    assert finished.evidence  # lo recuperado queda guardado para la evaluación (GET …/evidence)


def test_c01_still_generates_with_the_same_corpus(setup):
    evidence = CorpusEvidence(CASES["C-01"]["documents"])  # los 6 archivos, con el distractor de bases de datos
    finished = run(setup, evidence, "explicacion", instructions=CASES["C-01"]["instructions"], key="clave-qa05-c01")
    assert finished.status == RequestStatus.SUCCEEDED and finished.steps[0].resource_ids


def test_a_sequence_shares_one_retrieval_and_one_decision(setup):
    evidence = CorpusEvidence(CASES["C-06"]["documents"])
    finished = run(setup, evidence, "pregunta_detonante", "explicacion", instructions=CASES["C-06"]["instructions"],
                   key="clave-qa05-secuencia")
    assert finished.status == RequestStatus.FAILED and len(evidence.queries) == 1
    assert all(step.status == StepStatus.FAILED and step.error.message == C06_REASON for step in finished.steps)


@pytest.mark.parametrize("instructions", ["", "Usa ejemplos breves y un lenguaje sencillo para los estudiantes."])
def test_without_a_topic_the_request_is_never_rejected_by_this_check(setup, instructions):
    evidence = CorpusEvidence(CASES["C-06"]["documents"])
    finished = run(setup, evidence, "explicacion", instructions=instructions, key=f"clave-qa05-{len(instructions)}")
    assert finished.status == RequestStatus.SUCCEEDED


def test_the_check_can_be_turned_off(setup):
    evidence = CorpusEvidence(CASES["C-06"]["documents"])
    finished = run(setup, evidence, "explicacion", instructions=CASES["C-06"]["instructions"], key="clave-qa05-off",
                   topic_coverage_threshold=0)
    assert finished.status == RequestStatus.SUCCEEDED


def test_regeneration_from_review_applies_the_same_check(setup):
    evidence = CorpusEvidence(CASES["C-06"]["documents"])
    setup.evidence = evidence
    setup.use_case._start_generation._evidence = evidence
    params = {**SAVED_PARAMS, "resourceType": "explicacion", "stage": "explain",
              "instructions": CASES["C-06"]["instructions"], "topK": 8}
    request = setup.use_case.execute(StartRegenerationCommand("docente-a", "u1", "rec-api-1", 2, params)).request
    RunGenerationRequest(setup.repository, setup.membership, evidence, setup.review, ReviewVerificationAdapter(),
                         RuleBasedGenerator(), heartbeat_seconds=0).execute(request.id)
    finished = setup.repository.get("docente-a", request.id)
    assert finished.mode == GenerationMode.REGENERATION and finished.status == RequestStatus.FAILED
    assert finished.failure.code == GenerationErrorCode.INSUFFICIENT_EVIDENCE and finished.failure.message == C06_REASON
