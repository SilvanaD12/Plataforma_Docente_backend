"""GEN-P2, corrección tras P4: los rechazos «plan» de la medición con Gemini (backend/p4.db), rearmados con oraciones
del corpus de T067 (tests/fixtures/plan_coverage_p4_cases.json).

- Paráfrasis: el recurso desarrolla su concepto con otras palabras; antes se rechazaba por buscar la frase exacta.
- Conceptos de fondo: «capa de transporte» está en los fragmentos de la mayoría de los ítems; antes se rechazaba
  aunque el recurso solo lo usara como contexto.
- Una sola mención: «Transmission Control Protocol» nombrado una vez; antes contaba como desarrollado.
- Y el control: un recurso que sí desarrolla el concepto de otro ítem se sigue rechazando.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from platform5e.domain.generation.generation_plan import PlanItem
from platform5e.domain.generation.plan_coverage import backbone_concepts, check_plan_coverage
from platform5e.domain.generation.plan_validation import does_not_cover, short_concept_problem
from platform5e.domain.generation.topic_coverage import concept_key

DATA = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / "plan_coverage_p4_cases.json")
                  .read_text(encoding="utf-8"))
ITEMS = tuple(PlanItem(i["position"], "explain", i["resourceType"], 1, "Propósito", tuple(i["covers"]),
                       tuple(i["fragmentIds"])) for i in DATA["items"])
BACKBONE = backbone_concepts(ITEMS, DATA["fragments"])


def foreign_for(position: int, backbone: set[str]) -> list[str]:
    return [c for c in does_not_cover(ITEMS, position) if concept_key(c) not in backbone]


def test_the_planned_concepts_are_short_and_the_unit_backbone_is_detected():
    assert all(short_concept_problem(c) is None for item in ITEMS for c in item.covers)
    # Los dos términos de fondo de los rechazos de P4: están en los fragmentos de la mitad o más de los ítems.
    assert BACKBONE == {"capa transporte", "transmission control protocol"}


@pytest.mark.parametrize("case", DATA["cases"], ids=[case["id"] for case in DATA["cases"]])
def test_each_p4_case_follows_the_new_rules(case):
    item = next(i for i in ITEMS if i.position == case["item"])
    result = check_plan_coverage(case["resource"], item.covers, foreign_for(item.position, BACKBONE))
    assert result.accepted is case["expected"], result.problem


def test_without_the_backbone_exclusion_the_backbone_case_would_still_be_rejected():
    case = next(c for c in DATA["cases"] if c["kind"] == "backbone")
    item = next(i for i in ITEMS if i.position == case["item"])
    result = check_plan_coverage(case["resource"], item.covers, foreign_for(item.position, set()))
    assert result.developed == ["capa de transporte"]
