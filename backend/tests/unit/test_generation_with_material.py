"""
Generación con el material del docente (RAG) usando puertos falsos: sin red y sin base de datos.
"""

from __future__ import annotations

from typing import Any

import pytest

from platform5e.application.ports.outbound.chunk_repository_port import ChunkRepositoryPort
from platform5e.application.ports.outbound.evidence_retriever_port import EvidenceRetrieverPort
from platform5e.application.ports.outbound.generation_repository_port import GenerationRepositoryPort
from platform5e.application.ports.outbound.language_model_port import ResourceGeneratorPort
from platform5e.application.ports.outbound.resource_repository_port import ResourceReviewRepositoryPort
from platform5e.application.ports.outbound.teacher_repository_port import TeacherRepositoryPort
from platform5e.application.services.generation.generation_service import GenerationService
from platform5e.application.services.generation.prompt_drafting import (
    build_generation_context,
    build_prompt_instructions,
    normalize_generated_resources,
    parse_json_response,
)
from platform5e.domain.generation.errors import GenerationError
from platform5e.domain.materials.text_analysis import retrieve_relevant_chunks
from platform5e.infrastructure.retrieval.bm25_evidence_retriever import Bm25EvidenceRetriever

MOCK_UNIT = {
    "id": "u1",
    "number": 1,
    "title": "Protocolos de transporte",
    "outcomes": [{"id": "ra-1", "code": "RA1.1", "text": "Distingue TCP y UDP"}],
}
MOCK_COURSE = {
    "id": "c1",
    "name": "Redes",
    "summary": "Curso de redes.",
    "learningGoal": "Explica cómo se comunican los equipos.",
    "units": [MOCK_UNIT],
}
MOCK_FRAGMENTS = [
    {
        "id": "f1",
        "documento_id": "doc1",
        "documentId": "doc1",
        "unidad_id": "u1",
        "unitId": "u1",
        "orden": 0,
        "ubicacion": "p. 1",
        "location": "p. 1",
        "texto": "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable.",
        "text": "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable.",
    },
    {
        "id": "f2",
        "documento_id": "doc1",
        "documentId": "doc1",
        "unidad_id": "u1",
        "unitId": "u1",
        "orden": 1,
        "ubicacion": "p. 2",
        "location": "p. 2",
        "texto": "El protocolo UDP no establece conexión y es más rápido.",
        "text": "El protocolo UDP no establece conexión y es más rápido.",
    },
]
MOCK_DOCUMENT = {"id": "doc1", "unitId": "u1", "fileName": "apuntes.pdf"}


def make_request_dict(**overrides) -> dict[str, Any]:
    base = {
        "unitId": "u1",
        "outcomeId": None,
        "stage": "evaluate",
        "resourceType": "item_opcion_multiple",
        "quantity": 1,
        "difficulty": "intermedia",
        "optionCount": 3,
        "topK": 5,
        "evidenceThreshold": 0.6,
        "instructions": "contexto peruano",
        "audience": "Tercer ciclo",
        "competency": "Pensamiento crítico",
        "modalities": ["Textual"],
    }
    return {**base, **overrides}


MOCK_ITEM = {
    "titulo": "TCP o UDP",
    "contenido": "¿Qué protocolo garantiza una entrega confiable?",
    "citas": [{"afirmacion": "TCP garantiza la entrega", "fragmentos": ["F1"]}],
    "alternativas": [
        {"texto": "TCP", "correcta": True, "retroalimentacion": "Correcto.", "fragmentos": ["F1"]},
        {
            "texto": "UDP",
            "correcta": False,
            "retroalimentacion": "No confirma la entrega.",
            "error_conceptual": "Cree que ser más rápido implica ser confiable.",
            "fragmentos": ["F2"],
        },
        {
            "texto": "IP",
            "correcta": False,
            "retroalimentacion": "IP no es un protocolo de transporte.",
            "error_conceptual": "Confunde la capa de red con la de transporte.",
            "fragmentos": [],
        },
    ],
}


class MockGenerationRepository(GenerationRepositoryPort):
    def __init__(self) -> None:
        self.saved_results: list[tuple[dict[str, Any], str | None]] = []

    def get_demo_catalog(self) -> dict[str, Any]:
        return {"units": [], "examples": [], "fragments": [], "documents": [], "notice": ""}

    def save(self, result: dict[str, Any], teacher_id: str | None = None) -> None:
        self.saved_results.append((result, teacher_id))

    def get_by_id(self, generation_id: str) -> dict[str, Any] | None:
        return None


class MockTeacherConfigRepository(TeacherRepositoryPort):
    def get_courses(self, teacher_id: str) -> list[dict[str, Any]]:
        return [MOCK_COURSE]

    def get_documents(self, teacher_id: str) -> list[dict[str, Any]]:
        return [MOCK_DOCUMENT]

    def init_catalog(self, teacher_id: str) -> None: ...
    def get_user_by_email(self, email: str) -> dict[str, Any] | None: return None
    def create_user(self, user_data: dict[str, Any]) -> None: ...
    def save_session(self, fingerprint: str, teacher_id: str, expires_at: float) -> None: ...
    def get_session(self, fingerprint: str) -> tuple[str, float] | None: return None
    def delete_session(self, fingerprint: str) -> None: ...
    def save_course(self, teacher_id: str, course_data: dict[str, Any]) -> None: ...
    def delete_course(self, teacher_id: str, course_id: str, unit_ids: list[str]) -> None: ...
    def save_document(self, teacher_id: str, metadata: dict[str, Any], content: bytes) -> None: ...
    def get_document(self, teacher_id: str, document_id: str) -> tuple[dict[str, Any], bytes] | None: return None
    def delete_document(self, teacher_id: str, document_id: str) -> None: ...
    def get_history(self, teacher_id: str) -> list[dict[str, Any]]: return []
    def get_generation_owner(self, generation_id: str) -> str | None: return None


class MockMaterialChunkRepository(ChunkRepositoryPort):
    def __init__(self, fragments: list[dict[str, Any]] = MOCK_FRAGMENTS) -> None:
        self.fragments_list = fragments

    def get_chunks_by_unit(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        return [f for f in self.fragments_list if f.get("unitId") == unit_id or f.get("unidad_id") == unit_id]

    def replace_chunks(self, teacher_id: str, document_id: str, unit_id: str, chunks: list[dict[str, Any]]) -> None: ...
    def get_chunks_by_document(self, teacher_id: str, document_id: str) -> list[dict[str, Any]]: return []
    def update_document(self, teacher_id: str, document_data: dict[str, Any]) -> None: ...


class MockGenerator(ResourceGeneratorPort):
    def __init__(
        self,
        response_data: dict[str, Any] | None = None,
        error: Exception | None = None,
        description: str = "IA falsa",
        uses_ai: bool = True,
    ) -> None:
        self.response_data = response_data
        self.error = error
        self.description = description
        self.uses_ai = uses_ai
        self.captured_contexts: list[dict[str, Any]] = []

    def generate(self, context: dict[str, Any]) -> dict[str, Any]:
        self.captured_contexts.append(context)
        if self.error:
            raise self.error
        return self.response_data or {}


def build_service_setup(
    generator: MockGenerator | None = None,
    fallback: MockGenerator | None = None,
    chunk_repo: ChunkRepositoryPort | None = None,
    retriever: EvidenceRetrieverPort | None = None,
) -> tuple[GenerationService, MockGenerationRepository]:
    repo = MockGenerationRepository()
    service = GenerationService(
        repository=repo,
        teacher_repository=MockTeacherConfigRepository(),
        chunk_repository=chunk_repo or MockMaterialChunkRepository(),
        primary_generator=generator or MockGenerator({"recursos": [MOCK_ITEM]}),
        fallback_generator=fallback,
        evidence_retriever=retriever or Bm25EvidenceRetriever(),
    )
    return service, repo


def test_generates_from_material_cites_chunks_and_saves_history():
    ai_gen = MockGenerator({"recursos": [MOCK_ITEM]})
    service, repo = build_service_setup(ai_gen)
    result = service.generate(make_request_dict(), "docente")
    assert result["mode"] == "rag" and result["generator"] == {
        "description": "IA falsa",
        "usesAi": True,
        "fallback": False,
    }
    resource = result["resources"][0]
    assert resource["source"] == "rag" and resource["status"] == "pendiente" and resource["outcomeId"] == "ra-1"

    real_mapping = {f["etiqueta"]: f["id"] for f in ai_gen.captured_contexts[0]["fragmentos"]}
    # El modelo citó F1, que aquí es el fragmento de UDP: la verificación de anclaje (HU-016) lo corrige al de TCP.
    assert real_mapping["F1"] == "f2"
    assert resource["citations"] == [{"claim": "TCP garantiza la entrega", "fragmentIds": ["f1"]}]
    assert resource["grounding"]["correctedClaims"] == 1 and resource["grounding"]["removedClaims"] == []
    assert sorted(o["text"] for o in resource["options"]) == ["IP", "TCP", "UDP"]
    assert sum(o["isCorrect"] for o in resource["options"]) == 1

    without_source = next(o for o in resource["options"] if o["text"] == "IP")
    assert without_source["sourceFragmentIds"] == ["f1"] and without_source["feedback"]  # la cita ya corregida
    assert {f["id"] for f in result["fragments"]} == {"f1", "f2"}
    assert result["documents"] == [MOCK_DOCUMENT]
    assert repo.saved_results[0][1] == "docente"

    context = ai_gen.captured_contexts[0]
    assert context["curso"]["sumilla"] == "Curso de redes." and context["fragmentos"][0]["etiqueta"] == "F1"
    assert resource["generatorKind"] == "ia" and resource["params"]["optionCount"] == 3
    assert {e["id"] for e in resource["evidence"]} == {real_mapping["F1"], real_mapping["F2"]}
    assert resource["evidence"][0]["documentName"] == "apuntes.pdf"


def test_generated_resources_are_saved_for_review():
    class MockReviewRepo(ResourceReviewRepositoryPort):
        def __init__(self) -> None:
            self.saved_records: list[tuple[str, str, list[str]]] = []

        def save_resources(self, teacher_id: str, unit_id: str, resources: list[dict[str, Any]]) -> None:
            self.saved_records.append((teacher_id, unit_id, [r["id"] for r in resources]))

        def get_resources_by_unit(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]: return []
        def get_resource_by_id(self, teacher_id: str, resource_id: str) -> dict[str, Any] | None: return None
        def delete_resource(self, teacher_id: str, resource_id: str) -> None: ...
        def get_downloads(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]: return []
        def save_download(self, teacher_id: str, unit_id: str, download_record: dict[str, Any]) -> None: ...
        def delete_downloads(self, teacher_id: str, unit_id: str) -> None: ...

    review_repo = MockReviewRepo()
    service = GenerationService(
        repository=MockGenerationRepository(),
        teacher_repository=MockTeacherConfigRepository(),
        chunk_repository=MockMaterialChunkRepository(),
        primary_generator=MockGenerator({"recursos": [MOCK_ITEM]}),
        review_repository=review_repo,
        evidence_retriever=Bm25EvidenceRetriever(),
    )
    result = service.generate(make_request_dict(), "docente")
    assert review_repo.saved_records == [("docente", "u1", [result["resources"][0]["id"]])]


def test_if_the_ai_fails_the_fallback_is_used_and_reported(caplog):
    rules_gen = MockGenerator({"recursos": [MOCK_ITEM]}, description="Reglas", uses_ai=False)
    service, _ = build_service_setup(MockGenerator(error=RuntimeError("429 límite")), rules_gen)
    result = service.generate(make_request_dict(), "docente")
    assert result["generator"]["description"] == "Reglas" and result["generator"]["fallback"] is True
    assert result["resources"][0]["generatorKind"] == "respaldo"
    assert "429 límite" in caplog.text
    assert "no respondió" in result["notice"] and "generador por reglas" in result["notice"]


def test_if_the_ai_does_not_cite_properly_the_fallback_is_used():
    bad_output = {
        "recursos": [
            {
                "titulo": "x",
                "contenido": "y",
                "citas": [{"afirmacion": "z", "fragmentos": ["F9"]}],
                "alternativas": [],
            }
        ]
    }
    rules_gen = MockGenerator({"recursos": [MOCK_ITEM]}, description="Reglas", uses_ai=False)
    service, _ = build_service_setup(MockGenerator(bad_output), rules_gen)
    result = service.generate(make_request_dict(), "docente")
    assert "citas válidas" in result["notice"]


def test_without_valid_resources_rejects_without_inventing():
    service, repo = build_service_setup(MockGenerator({"recursos": []}), fallback=None)
    with pytest.raises(GenerationError) as err:
        service.generate(make_request_dict(), "docente")
    assert err.value.code == "INSUFFICIENT_EVIDENCE" and repo.saved_results == []


def test_outcome_from_another_unit_is_rejected():
    service, _ = build_service_setup(MockGenerator({"recursos": [MOCK_ITEM]}))
    with pytest.raises(GenerationError) as err:
        service.generate(make_request_dict(outcomeId="ra-otro"), "docente")
    assert err.value.code == "INVALID_OUTCOME"


def test_unit_without_material_or_demo_asks_for_upload():
    service, _ = build_service_setup(MockGenerator({"recursos": [MOCK_ITEM]}), chunk_repo=MockMaterialChunkRepository([]))
    with pytest.raises(GenerationError) as err:
        service.generate(make_request_dict(), "docente")
    assert err.value.code == "NO_PROCESSED_MATERIAL" and "pestaña Material" in err.value.message


def test_without_teacher_uses_the_demo():
    service, _ = build_service_setup(MockGenerator({"recursos": [MOCK_ITEM]}))
    with pytest.raises(GenerationError) as err:
        service.generate(make_request_dict(unitId="u2"))
    assert err.value.code == "NO_PROCESSED_MATERIAL"


def test_instructions_include_course_request_and_chunks():
    context = build_generation_context(
        MOCK_COURSE,
        MOCK_UNIT,
        make_request_dict(outcomeId="ra-1"),
        [{**f, "relevance": 1} for f in MOCK_FRAGMENTS],
        {"doc1": "apuntes.pdf"},
    )
    system_inst, user_prompt = build_prompt_instructions(context)
    assert "Evaluar" in system_inst and "JSON" in system_inst
    assert "Genera solo texto" in system_inst  # Sprint 1: sin multimedia
    for text_sample in (
        "SUMILLA: Curso de redes.",
        "RA1.1: Distingue TCP y UDP",
        "exactamente 3 alternativas",
        "Tercer ciclo",
        "Pensamiento crítico",
        "contexto peruano",
        "[F1] (apuntes.pdf, p. 1)",
    ):
        assert text_sample in user_prompt

    empty_context = build_generation_context(
        {},
        {"title": "U", "number": 2},
        make_request_dict(stage="explain", resourceType="glosario", audience="", competency="", modalities=[], instructions=""),
        [],
        {},
    )
    _, empty_user_prompt = build_prompt_instructions(empty_context)
    assert "no registrada" in empty_user_prompt and "alternativas" in empty_user_prompt


@pytest.mark.parametrize(
    "raw_input,expected_output",
    [
        ('{"recursos": []}', {"recursos": []}),
        ('```json\n{"recursos": [1]}\n```', {"recursos": [1]}),
        ('Aquí tienes: {"recursos": [2]} ¡listo!', {"recursos": [2]}),
    ],
)
def test_extract_json_tolerates_common_formats(raw_input: str, expected_output: dict[str, Any]):
    assert parse_json_response(raw_input) == expected_output


@pytest.mark.parametrize("invalid_raw", ["", None, "sin json", "{roto"])
def test_extract_json_rejects_unreadable_output(invalid_raw: str | None):
    with pytest.raises(ValueError):
        parse_json_response(invalid_raw)


# Afirmación respaldada por el material de prueba (HU-016 rechaza las que no lo están).
SUPPORTED_CLAIM = "El protocolo TCP garantiza una entrega confiable"


def build_test_context(quantity: int = 1, options: int = 3) -> dict[str, Any]:
    return build_generation_context(
        MOCK_COURSE, MOCK_UNIT, make_request_dict(quantity=quantity, optionCount=options), MOCK_FRAGMENTS, {}
    )


def test_normalize_accepts_joined_tags_and_key_as_text():
    options = [
        {"texto": "TCP", "correcta": "true", "fragmentos": "F1, F2"},
        {"texto": "UDP", "correcta": "false", "retroalimentacion": "No confirma.", "errorConceptual": "Rapidez = confianza."},
        {"texto": "IP", "esCorrecta": False, "retroalimentacion": "Es de red.", "error": "Confunde las capas."},
    ]
    item_payload = {**MOCK_ITEM, "citas": [{"afirmacion": SUPPORTED_CLAIM, "fragmentos": "Fragmentos F2 y F1"}], "alternativas": options}
    normalized = normalize_generated_resources({"recursos": [item_payload]}, build_test_context())[0]
    assert normalized["citas"][0]["fragmentIds"] == ["f2", "f1"]
    correct_opt = next(a for a in normalized["alternativas"] if a["correcta"])
    assert correct_opt["texto"] == "TCP" and correct_opt["fragmentos"] == ["f1", "f2"]


def test_normalize_accepts_tags_in_several_formats_and_trims_quantity():
    item_payload = {**MOCK_ITEM, "citas": [{"afirmacion": SUPPORTED_CLAIM, "fragmentos": ["f2", "[F1]", 1, "F7"]}]}
    resources = normalize_generated_resources({"recursos": [item_payload, item_payload]}, build_test_context(quantity=1))
    assert len(resources) == 1 and resources[0]["citas"][0]["fragmentIds"] == ["f2", "f1"]
    assert normalize_generated_resources([item_payload], build_test_context())[0]["titulo"] == "TCP o UDP"
    assert normalize_generated_resources("no es lista", build_test_context()) == []


@pytest.mark.parametrize(
    "options_case",
    [
        [{"texto": "A", "correcta": True}, {"texto": "B", "correcta": True}, {"texto": "C"}],
        [{"texto": "A"}, {"texto": "B"}, {"texto": "C"}],
        [{"texto": "A", "correcta": True}, {"texto": "a"}, {"texto": "B"}],
        "no es lista",
    ],
)
def test_normalize_discards_invalid_items(options_case):
    assert normalize_generated_resources({"recursos": [{**MOCK_ITEM, "alternativas": options_case}]}, build_test_context()) == []


def test_normalize_discards_uncited_or_empty_resources_and_fills_title():
    ctx = build_generation_context(
        MOCK_COURSE, MOCK_UNIT, make_request_dict(stage="explain", resourceType="explicacion", quantity=3), MOCK_FRAGMENTS, {}
    )
    resources = normalize_generated_resources(
        {
            "recursos": [
                {"contenido": "Texto", "citas": [{"afirmacion": SUPPORTED_CLAIM, "fragmentos": "F1"}]},
                {"titulo": "Sin cita", "contenido": "Texto", "citas": []},
                {"titulo": "Vacío", "contenido": "", "citas": [{"afirmacion": "x", "fragmentos": ["F1"]}]},
                "basura",
            ]
        },
        ctx,
    )
    assert len(resources) == 1 and resources[0]["titulo"] == "Explicación citada 1" and resources[0]["alternativas"] is None


def test_without_demo_examples_a_unit_without_material_asks_for_upload():
    service = GenerationService(
        repository=MockGenerationRepository(),
        teacher_repository=MockTeacherConfigRepository(),
        chunk_repository=MockMaterialChunkRepository([]),
        primary_generator=MockGenerator({"recursos": [MOCK_ITEM]}),
        fallback_generator=None,
        demo_examples_enabled=False,
    )
    with pytest.raises(GenerationError) as err:
        service.generate(make_request_dict(), "docente")
    assert err.value.code == "NO_PROCESSED_MATERIAL" and "pestaña Material" in err.value.message
    with pytest.raises(GenerationError):
        service.generate(make_request_dict(), None)


class MockEvidenceRetriever(EvidenceRetrieverPort):
    """Buscador falso: devuelve siempre el primer fragmento y guarda lo que le pidieron."""

    description = "buscador falso"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def retrieve(
        self, query: str, chunks: list[dict[str, Any]], top_k: int, unit_id: str | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append((query, top_k))
        return [{**chunks[0], "relevance": 0.9}]


def test_generation_uses_the_injected_evidence_retriever():
    retriever = MockEvidenceRetriever()
    item = {**MOCK_ITEM, "alternativas": [{**alt, "fragmentos": ["F1"]} for alt in MOCK_ITEM["alternativas"]]}
    ai_gen = MockGenerator({"recursos": [item]})
    service, _ = build_service_setup(ai_gen, retriever=retriever)
    result = service.generate(make_request_dict(topK=20), "docente")

    query, top_k = retriever.calls[0]
    assert "Protocolos de transporte" in query and "contexto peruano" in query
    assert top_k == 12  # el servicio acota topK antes de llamar al puerto
    assert [f["id"] for f in ai_gen.captured_contexts[0]["fragmentos"]] == ["f1"]
    assert result["retrievedChunks"] == [
        {"id": "f1", "location": "p. 1", "text": MOCK_FRAGMENTS[0]["text"], "relevance": 0.9}
    ]


def test_without_evidence_retriever_material_is_not_used():
    service = GenerationService(
        repository=MockGenerationRepository(),
        teacher_repository=MockTeacherConfigRepository(),
        chunk_repository=MockMaterialChunkRepository(),
        primary_generator=MockGenerator({"recursos": [MOCK_ITEM]}),
        demo_examples_enabled=False,
    )
    with pytest.raises(GenerationError) as err:
        service.generate(make_request_dict(), "docente")
    assert err.value.code == "NO_PROCESSED_MATERIAL"


def test_bm25_adapter_delegates_to_the_domain_search():
    retriever = Bm25EvidenceRetriever()
    assert retriever.description == "búsqueda por palabras (BM25)"
    query = "protocolo confiable con conexión"
    assert retriever.retrieve(query, MOCK_FRAGMENTS, 2) == retrieve_relevant_chunks(query, MOCK_FRAGMENTS, 2)
