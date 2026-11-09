"""GEN-01 (T013 y T014): redacción de un paso extraída de generation_service y contexto desde los puertos."""

from __future__ import annotations

from typing import Any

from platform5e.application.ports.outbound.evidence_provider_port import EvidenceFragment
from platform5e.application.ports.outbound.unit_membership_port import OutcomeRef, UnitContext
from platform5e.application.services.generation import generation_service, step_drafting
from platform5e.application.services.generation.prompt_drafting import (
    build_generation_context,
    build_step_context,
)
from platform5e.application.services.generation.step_drafting import (
    NO_REPEAT_INSTRUCTION,
    build_grounding_report,
    draft_resources,
    draft_step,
    filter_repeated,
    retrieval_limit,
)
from tests.support.generation_fakes import INVENTED_RESOURCE
from tests.unit.test_generation_with_material import (
    MOCK_COURSE,
    MOCK_DOCUMENT,
    MOCK_FRAGMENTS,
    MOCK_ITEM,
    MOCK_UNIT,
    make_request_dict,
)
from tests.unit.test_sequence_orchestrator import DISTINCT_RESOURCES, REPEATED_RESOURCE, StageAwareGenerator


def item_context(**overrides: Any) -> dict[str, Any]:
    request = make_request_dict(**overrides)
    return build_generation_context(MOCK_COURSE, MOCK_UNIT, request, MOCK_FRAGMENTS, {"doc1": "apuntes.pdf"})


class OneShotGenerator:
    description = "IA falsa"
    uses_ai = True

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def generate(self, context: dict[str, Any]) -> dict[str, Any]:
        return self.payload


# T013 · Extracción sin cambio de comportamiento


def test_the_service_reexports_the_extracted_names():
    """Los importadores actuales de generation_service siguen funcionando."""
    for name in ("NO_REPEAT_INSTRUCTION", "OPTION_LETTERS", "REQUEST_PARAMETERS", "build_grounding_report"):
        assert getattr(generation_service, name) is getattr(step_drafting, name)


def test_every_rejection_carries_its_kind():
    rejections: list[dict[str, Any]] = []
    invented = {**MOCK_ITEM, **{k: INVENTED_RESOURCE[k] for k in ("titulo", "contenido", "citas")}}
    resources, generator, warning = draft_resources(
        item_context(), OneShotGenerator({"recursos": [invented]}), None, rejections
    )
    assert resources == [] and generator is not None and warning
    assert rejections[0]["kind"] == "grounding" and rejections[0]["title"] == "Inventado"

    kept, repeated = filter_repeated([REPEATED_RESOURCE], [{**REPEATED_RESOURCE, "etapa": "engage"}])
    assert kept == [] and repeated[0]["kind"] == "repetition"
    assert repeated[0]["title"] == REPEATED_RESOURCE["titulo"] and "repetía" in repeated[0]["reason"]


def test_a_distractor_rejection_is_tagged():
    """HU-019: si el material muestra como correctos los distractores, el ítem se rechaza con kind distractor."""
    item = {
        **MOCK_ITEM,
        "alternativas": [
            {"texto": "TCP", "correcta": True, "retroalimentacion": "Correcto.", "fragmentos": ["F1"]},
            {
                "texto": "El protocolo TCP garantiza una entrega confiable",
                "correcta": False,
                "retroalimentacion": "No.",
                "error_conceptual": "Confunde.",
                "fragmentos": ["F1"],
            },
            {
                "texto": "Orientado a la conexión con entrega confiable",
                "correcta": False,
                "retroalimentacion": "No.",
                "error_conceptual": "Confunde.",
                "fragmentos": ["F1"],
            },
        ],
    }
    rejections: list[dict[str, Any]] = []
    resources, _, _ = draft_resources(item_context(), OneShotGenerator({"recursos": [item]}), None, rejections)
    assert resources == []
    assert [(r["kind"], r["title"]) for r in rejections] == [("distractor", "TCP o UDP")]
    assert "distractor(es) fiable(s)" in rejections[0]["reason"]


def test_draft_step_asks_again_once_and_keeps_a_new_resource():
    generator = StageAwareGenerator(
        {"explicacion": REPEATED_RESOURCE}, retry_responses={"explicacion": DISTINCT_RESOURCES["explicacion"]}
    )
    context = item_context(stage="explain", resourceType="explicacion")
    accepted = [{**REPEATED_RESOURCE, "etapa": "engage"}]
    drafted = draft_step(context, accepted, generator, None, [])

    assert [r["titulo"] for r in drafted.kept] == ["Entrega confiable con TCP"]
    assert drafted.repeated == [] and drafted.generator is generator and drafted.warning is None
    assert sum(NO_REPEAT_INSTRUCTION in c["solicitud"]["indicaciones"] for c in generator.contexts) == 1


def test_retrieval_limit_and_grounding_report_keep_their_rules():
    assert [retrieval_limit(v) for v in (None, 0, 1, 5, 12, 50)] == [8, 8, 3, 5, 12, 12]
    report = build_grounding_report([], [{"title": "T", "reason": "R", "kind": "grounding"}])
    assert report["rejectedResources"] == [{"title": "T", "reason": "R"}]  # sin `kind`: el informe no cambia


# T014 · Contexto desde los puertos


def test_the_context_from_ports_is_identical_to_the_current_context():
    request = make_request_dict(outcomeId="ra-1", stage="explain", resourceType="glosario", quantity=2)
    unit = UnitContext(
        course_id=MOCK_COURSE["id"],
        course_name=MOCK_COURSE["name"],
        course_summary=MOCK_COURSE["summary"],
        learning_goal=MOCK_COURSE["learningGoal"],
        unit_id=MOCK_UNIT["id"],
        unit_number=MOCK_UNIT["number"],
        unit_title=MOCK_UNIT["title"],
        outcomes=tuple(OutcomeRef(o["id"], o["code"], o["text"]) for o in MOCK_UNIT["outcomes"]),
    )
    fragments = [
        EvidenceFragment(
            chunk_id=chunk["id"],
            document_id=chunk["documentId"],
            document_name=MOCK_DOCUMENT["fileName"],
            location=chunk["location"],
            text=chunk["text"],
            relevance=0.5,
            source_url=None,
            license=None,
        )
        for chunk in MOCK_FRAGMENTS
    ]
    current = build_generation_context(
        MOCK_COURSE, MOCK_UNIT, request, MOCK_FRAGMENTS, {MOCK_DOCUMENT["id"]: MOCK_DOCUMENT["fileName"]}
    )
    from_ports = build_step_context(unit, request, fragments)

    assert from_ports == current
    assert [f["etiqueta"] for f in from_ports["fragmentos"]] == ["F1", "F2"]
    assert "secuenciaPrevia" not in from_ports  # lo agrega quien redacta la secuencia
