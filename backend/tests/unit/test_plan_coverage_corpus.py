"""GEN-P2 (T013): falsos rechazos de la regla estricta de los recursos de un solo párrafo, con recursos cortos del
corpus de T067 marcados a mano (tests/fixtures/plan_coverage_short_resources.json, research R5).

La prueba falla si la regla rechaza más del 5 % de los recursos marcados como correctos o deja pasar alguno marcado
como incorrecto. Si falla por falsos rechazos, se afloja la regla y se registra en research R5. Sin llamadas a Gemini.
"""

from __future__ import annotations

import json
from pathlib import Path

from platform5e.domain.generation.plan_coverage import check_plan_coverage

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "plan_coverage_short_resources.json"
MAX_FALSE_REJECTIONS: float = 0.05


def test_the_strict_rule_on_short_resources_keeps_false_rejections_under_five_percent():
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    results = {case["id"]: check_plan_coverage(case["resource"], case["own"], case["foreign"]) for case in cases}
    correct = [case["id"] for case in cases if case["label"] == "correct"]
    incorrect = [case["id"] for case in cases if case["label"] == "incorrect"]
    false_rejections = [case_id for case_id in correct if not results[case_id].accepted]
    let_through = [case_id for case_id in incorrect if results[case_id].accepted]

    assert len(correct) >= 10 and len(incorrect) >= 6
    assert {case["type"] for case in cases} == {"pregunta_detonante", "item_opcion_multiple", "audio_detonante"}
    assert len(false_rejections) / len(correct) <= MAX_FALSE_REJECTIONS, false_rejections
    assert let_through == [], let_through
