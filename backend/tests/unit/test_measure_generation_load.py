"""GEN-01 · T044: cálculos del script de medición de carga (percentiles, duraciones, llamadas por paso y resumen).

Sin servidor ni red: el script se carga desde backend/scripts.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "measure_generation_load.py"


@pytest.fixture(scope="module")
def load():
    spec = importlib.util.spec_from_file_location("measure_generation_load", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_percentile_interpolates_between_ranks(load):
    assert load.percentile([], 50) is None
    assert load.percentile([7.0], 95) == 7.0
    assert load.percentile([10.0, 20.0, 30.0, 40.0, 50.0], 50) == 30.0
    assert load.percentile([50.0, 10.0, 40.0, 20.0, 30.0], 95) == pytest.approx(48.0)  # 40 + 0.8 * 10
    assert load.percentile([1.0, 2.0], 50) == 1.5


def test_request_durations_use_created_started_and_finished(load):
    status = {
        "createdAt": "2026-11-12T10:00:00+00:00",
        "startedAt": "2026-11-12T10:00:05+00:00",
        "finishedAt": "2026-11-12T10:01:05+00:00",
    }
    assert load.request_durations(status) == (65.0, 60.0)
    assert load.request_durations({**status, "finishedAt": None}) == (None, None)


def step(generator=None, rejections=()):
    return {"generator": generator, "rejections": [{"kind": kind, "reason": "x"} for kind in rejections]}


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        # Generador por reglas: una redacción, ninguna llamada a IA.
        (step({"usesAi": False, "fallback": False}), (1, 0, 0, False)),
        # IA sin repetición visible: al menos 1 llamada; hasta 2 redacciones con su reintento de JSON.
        (step({"usesAi": True, "fallback": False}), (1, 1, 4, False)),
        # Un rechazo por repetición prueba que hubo reintento.
        (step({"usesAi": True, "fallback": False}, ["repetition"]), (2, 2, 4, True)),
        # Respaldo: la IA se llamó y falló; redactó el de reglas.
        (step({"usesAi": False, "fallback": True}, ["grounding"]), (1, 1, 4, False)),
        # Paso sin redactar (por ejemplo, DEADLINE_EXCEEDED): ninguna llamada.
        (step(None), (0, 0, 0, False)),
    ],
)
def test_step_model_calls_estimate(load, given, expected):
    calls = load.step_model_calls(given)
    assert (calls["generatorCalls"], calls["aiCallsMin"], calls["aiCallsMax"], calls["repetitionRetry"]) == expected


def test_summary_aggregates_requests_steps_and_the_concurrency_check(load):
    def status(seconds, steps):
        return {
            "id": f"gen-{seconds}",
            "status": "succeeded",
            "createdAt": "2026-11-12T10:00:00+00:00",
            "startedAt": "2026-11-12T10:00:00+00:00",
            "finishedAt": f"2026-11-12T10:00:{seconds:02d}+00:00",
            "steps": steps,
        }

    ai = {"usesAi": True, "fallback": False}
    deadline_step = {"generator": None, "rejections": [], "resourceIds": [],
                     "error": {"code": "DEADLINE_EXCEEDED", "message": "x"}}
    records = [
        load.request_record(status(10, [{"generator": ai, "rejections": [], "resourceIds": ["a", "b"]}]), "k1"),
        load.request_record(status(30, [
            {"generator": ai, "rejections": [{"kind": "repetition", "reason": "x"}], "resourceIds": ["c"]},
            deadline_step,
        ]), "k2"),
    ]
    summary = load.summarize(records, {"result": "OK"})

    assert summary["requests"] == 2 and summary["durationSeconds"]["p50"] == 20.0
    assert summary["resources"] == 3 and summary["rejections"] == 1
    assert summary["rejectionsByKind"] == {"repetition": 1}
    assert summary["generatorCallsPerStep"] == {"min": 0, "avg": 1.0, "max": 2}
    assert summary["deadlineExceededSteps"] == 1 and summary["deadlineExceededRequests"] == 1
    assert summary["concurrencyCheck"] == "OK"
    text = load.format_summary(summary, "rules")
    assert "p50 / p95" in text and "DEADLINE_EXCEEDED" in text and "OK" in text
