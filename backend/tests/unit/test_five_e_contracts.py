"""Contratos 5E (docs/api/contracts): un ítem de evaluación se acepta con evidencia y se rechaza sin ella."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from platform5e.infrastructure.http.schemas.evaluate import ResourceEvaluateItemModel

VALID_ITEM = {
    "id": "rec-001",
    "title": "Complejidad de desencolar",
    "prompt": "¿Cuál es la complejidad de desencolar en un arreglo lineal sin apuntador circular?",
    "options": [
        {"id": "a", "text": "O(n)", "is_correct": True, "feedback": "Correcto: se desplazan los elementos.",
         "source_fragment_ids": ["f-u2-03"]},
        {"id": "b", "text": "O(1)", "is_correct": False, "feedback": "Incorrecto: hay que reubicar los elementos.",
         "source_fragment_ids": ["f-u2-04"], "key_similarity": 0.74},
        {"id": "c", "text": "O(log n)", "is_correct": False, "feedback": "Incorrecto: no hay partición logarítmica.",
         "source_fragment_ids": ["f-u2-03"], "key_similarity": 0.42},
    ],
    "citations": [{"claim": "Desencolar desplaza los elementos restantes.", "fragment_ids": ["f-u2-03"]}],
}


def test_item_with_cited_evidence_is_accepted():
    item = ResourceEvaluateItemModel.model_validate(VALID_ITEM)
    assert item.stage_5e == "evaluate" and item.status == "pendiente" and len(item.options) == 3


@pytest.mark.parametrize(
    "broken",
    [
        lambda item: item.update(citations=[]),
        lambda item: item["options"][0].update(source_fragment_ids=[]),
        lambda item: item.update(options=item["options"][:2]),
    ],
    ids=["without-citations", "option-without-evidence", "fewer-than-three-options"],
)
def test_item_without_evidence_or_options_is_rejected(broken):
    item = deepcopy(VALID_ITEM)
    broken(item)
    with pytest.raises(ValidationError):
        ResourceEvaluateItemModel.model_validate(item)
