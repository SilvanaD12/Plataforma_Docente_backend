"""
HU-003: un pedido con varios tipos de recurso se reparte entre los agentes de etapa sin repetir contenido.
Usa los puertos falsos de las pruebas de generación: sin red y sin base de datos.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from platform5e.application.services.generation.generation_service import (
    NO_REPEAT_INSTRUCTION,
    GenerationService,
)
from platform5e.application.services.generation.prompt_drafting import (
    build_generation_context,
    build_prompt_instructions,
)
from platform5e.domain.generation.errors import GenerationError
from platform5e.domain.generation.resource_formats import RESOURCE_CATALOG
from platform5e.domain.generation.sequence import (
    SequenceError,
    content_similarity,
    order_resource_types,
    stage_agent,
)
from platform5e.infrastructure.http.schemas.generations import GenerationRequest
from platform5e.infrastructure.retrieval.bm25_evidence_retriever import Bm25EvidenceRetriever
from tests.unit.test_generation_with_material import (
    MOCK_COURSE,
    MOCK_FRAGMENTS,
    MOCK_ITEM,
    MOCK_UNIT,
    MockGenerationRepository,
    MockMaterialChunkRepository,
    MockTeacherConfigRepository,
    make_request_dict,
)

DISTINCT_RESOURCES: dict[str, dict[str, Any]] = {
    "pregunta_detonante": {
        "titulo": "Video en vivo sin esperas",
        "contenido": "¿Por qué una transmisión en vivo tolera perder algunos datos a cambio de rapidez?",
        "citas": [{"afirmacion": "UDP no establece conexión y es más rápido", "fragmentos": ["F2"]}],
        "alternativas": [],
    },
    "explicacion": {
        "titulo": "Entrega confiable con TCP",
        "contenido": "TCP garantiza la entrega: antes de enviar datos establece una conexión.",
        "citas": [{"afirmacion": "TCP garantiza una entrega confiable", "fragmentos": ["F1"]}],
        "alternativas": [],
    },
    "item_opcion_multiple": MOCK_ITEM,
}
REPEATED_RESOURCE = {
    "titulo": "Protocolos TCP y UDP",
    "contenido": "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable; UDP es más rápido.",
    "citas": [{"afirmacion": "TCP garantiza una entrega confiable", "fragmentos": ["F1"]}],
    "alternativas": [],
}


class StageAwareGenerator:
    """Generador falso: responde según el tipo pedido y guarda cada contexto recibido."""

    description = "IA falsa"
    uses_ai = True

    def __init__(self, responses: dict[str, Any] | None = None, retry_responses: dict[str, Any] | None = None):
        self.responses = responses or DISTINCT_RESOURCES
        self.retry_responses = retry_responses or {}
        self.contexts: list[dict[str, Any]] = []

    def generate(self, context: dict[str, Any]) -> dict[str, Any]:
        self.contexts.append(context)
        resource_type = context["solicitud"]["tipo"]
        retrying = NO_REPEAT_INSTRUCTION in context["solicitud"]["indicaciones"]
        if retrying and resource_type in self.retry_responses:
            return {"recursos": [self.retry_responses[resource_type]]}
        return {"recursos": [self.responses[resource_type]]}


def build_service(generator: StageAwareGenerator, demo: bool = False) -> tuple[GenerationService, MockGenerationRepository]:
    repo = MockGenerationRepository()
    service = GenerationService(
        repository=repo,
        teacher_repository=MockTeacherConfigRepository(),
        chunk_repository=MockMaterialChunkRepository(),
        primary_generator=generator,
        evidence_retriever=Bm25EvidenceRetriever(),
        demo_examples_enabled=demo,
    )
    return service, repo


def sequence_request(*resource_types: str, **overrides: Any) -> dict[str, Any]:
    return make_request_dict(resourceTypes=list(resource_types), stage=None, resourceType=None, **overrides)


def test_types_are_ordered_by_class_stage_without_duplicates():
    assert order_resource_types(["item_opcion_multiple", "pregunta_detonante", "explicacion", "pregunta_detonante"]) == [
        "pregunta_detonante",
        "explicacion",
        "item_opcion_multiple",
    ]
    assert stage_agent("mapa_conceptual") == "Agente de Explicar"
    for invalid in ([], ["tipo_inventado"], list(RESOURCE_CATALOG)[:9]):
        with pytest.raises(SequenceError):
            order_resource_types(invalid)


def test_similarity_is_high_for_the_same_text_and_low_for_different_texts():
    text = "El protocolo TCP garantiza una entrega confiable de los datos"
    assert content_similarity(text, text) == 1.0
    assert content_similarity(text, "La encapsulación agrega encabezados en cada capa") < 0.2
    assert content_similarity("", text) == 0.0


def test_each_stage_agent_drafts_its_resource_in_class_order():
    generator = StageAwareGenerator()
    service, repo = build_service(generator)
    result = service.generate_sequence(
        sequence_request("item_opcion_multiple", "pregunta_detonante", "explicacion"), "docente"
    )

    assert [r["stage"] for r in result["resources"]] == ["engage", "explain", "evaluate"]
    assert [r["agent"] for r in result["resources"]] == ["Agente de Enganchar", "Agente de Explicar", "Agente de Evaluar"]
    assert [s["agent"] for s in result["sequence"]] == ["Agente de Enganchar", "Agente de Explicar", "Agente de Evaluar"]
    assert all(step["generated"] == 1 and step["rejected"] == [] for step in result["sequence"])
    assert len({r["requestId"] for r in result["resources"]}) == 1
    assert result["request"]["resourceTypes"] == ["pregunta_detonante", "explicacion", "item_opcion_multiple"]
    assert result["request"]["stage"] == "engage" and repo.saved_results[0][1] == "docente"
    assert result["resources"][2]["params"]["resourceType"] == "item_opcion_multiple"  # «Regenerar» por recurso

    # Contexto compartido: misma evidencia para todos y cada agente ve lo que redactaron los anteriores.
    assert len({tuple(f["id"] for f in c["fragmentos"]) for c in generator.contexts}) == 1
    assert generator.contexts[0]["secuenciaPrevia"] == []
    assert [p["titulo"] for p in generator.contexts[2]["secuenciaPrevia"]] == [
        "Video en vivo sin esperas",
        "Entrega confiable con TCP",
    ]


def test_a_repeated_resource_is_asked_again_and_rejected_if_it_still_repeats():
    generator = StageAwareGenerator({"pregunta_detonante": REPEATED_RESOURCE, "explicacion": REPEATED_RESOURCE})
    service, _ = build_service(generator)
    result = service.generate_sequence(sequence_request("pregunta_detonante", "explicacion"), "docente")

    assert [r["type"] for r in result["resources"]] == ["pregunta_detonante"]
    explain_step = result["sequence"][1]
    assert explain_step["generated"] == 0 and "repetía" in explain_step["rejected"][0]
    assert sum(NO_REPEAT_INSTRUCTION in c["solicitud"]["indicaciones"] for c in generator.contexts) == 1
    assert "Se descartaron 1 recurso(s)" in result["notice"]


def test_the_retry_keeps_the_new_resource_when_it_no_longer_repeats():
    generator = StageAwareGenerator(
        {"pregunta_detonante": REPEATED_RESOURCE, "explicacion": REPEATED_RESOURCE},
        retry_responses={"explicacion": DISTINCT_RESOURCES["explicacion"]},
    )
    service, _ = build_service(generator)
    result = service.generate_sequence(sequence_request("pregunta_detonante", "explicacion"), "docente")

    assert [r["title"] for r in result["resources"]] == ["Protocolos TCP y UDP", "Entrega confiable con TCP"]
    assert result["sequence"][1] == {
        "stage": "explain",
        "resourceType": "explicacion",
        "agent": "Agente de Explicar",
        "generated": 1,
        "rejected": [],
    }


def test_invalid_sequences_and_units_without_material_are_rejected():
    service, _ = build_service(StageAwareGenerator())
    with pytest.raises(GenerationError) as err:
        service.generate_sequence(sequence_request("tipo_inventado"), "docente")
    assert err.value.code == "INVALID_SEQUENCE"

    empty, _ = build_service(StageAwareGenerator())
    empty._chunk_repository = MockMaterialChunkRepository([])
    with pytest.raises(GenerationError) as err:
        empty.generate_sequence(sequence_request("explicacion"), "docente")
    assert err.value.code == "NO_PROCESSED_MATERIAL"

    with pytest.raises(GenerationError) as err:
        service.generate_sequence(sequence_request("explicacion", outcomeId="ra-otra"), "docente")
    assert err.value.code == "INVALID_OUTCOME"


def test_the_prompt_lists_what_previous_agents_wrote():
    request = {**make_request_dict(), "stage": "explain", "resourceType": "explicacion"}
    context = build_generation_context(MOCK_COURSE, MOCK_UNIT, request, MOCK_FRAGMENTS, {"doc1": "apuntes.pdf"})
    context["secuenciaPrevia"] = [{"etapa": "engage", "titulo": "Video en vivo", "resumen": "¿Por qué tolera perder datos?"}]
    _, user_prompt = build_prompt_instructions(context)
    assert "OTROS AGENTES YA REDACTARON" in user_prompt and "- Video en vivo: ¿Por qué tolera perder datos?" in user_prompt
    assert "OTROS AGENTES" not in build_prompt_instructions({**context, "secuenciaPrevia": []})[1]


def test_the_request_contract_accepts_one_type_or_a_sequence():
    single = GenerationRequest.model_validate({"unitId": "u1", "stage": "explain", "resourceType": "explicacion"})
    assert single.to_domain()["resourceTypes"] is None
    sequence = GenerationRequest.model_validate({"unitId": "u1", "resourceTypes": ["explicacion", "glosario"]})
    assert sequence.to_domain()["resourceTypes"] == ["explicacion", "glosario"]
    for invalid in ({"unitId": "u1"}, {"unitId": "u1", "stage": "explain"}, {"unitId": "u1", "resourceTypes": []}):
        with pytest.raises(ValidationError):
            GenerationRequest.model_validate(invalid)
