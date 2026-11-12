"""GEN-01 · T044: cálculos del script de medición de carga (percentiles, duraciones, llamadas por paso y resumen).

Sin servidor ni red: el script se carga desde backend/scripts.
"""

from __future__ import annotations

import importlib.util
import json
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


# --------------------------------------------------------------------------- revisión del PR #27: fallos de red


def final_status(request_id, seconds):
    return {
        "id": request_id, "status": "succeeded", "createdAt": "2026-11-12T10:00:00+00:00",
        "startedAt": "2026-11-12T10:00:00+00:00", "finishedAt": f"2026-11-12T10:00:{seconds:02d}+00:00",
        "steps": [{"generator": {"usesAi": False, "fallback": False}, "rejections": [], "resourceIds": ["r"]}],
    }


class FakeClient:
    """Lo que `run_measurement` usa del cliente HTTP: consultas de estado. Un id en `unreadable` siempre falla."""

    def __init__(self, statuses, unreadable=()):
        self.statuses, self.unreadable = statuses, set(unreadable)

    def get(self, path, headers=None, params=None):
        import httpx

        request_id = path.rsplit("/", 1)[-1]
        if request_id in self.unreadable:
            raise httpx.ConnectError("conexión rechazada")
        return httpx.Response(200, json=self.statuses[request_id])


def fake_posts(monkeypatch, load, failing_concurrent_index=None):
    """POST simulados: los envíos de concurrencia aceptan dos y rechazan uno con 429 (o fallan por red), y las
    secuencias medidas se aceptan con ids m0..m4."""
    import httpx

    def post_request(client, headers, key, body):
        if "-concurrency-" in key:
            index = int(key.rsplit("-", 1)[-1])
            if index == failing_concurrent_index:
                raise httpx.ConnectTimeout("tiempo agotado al conectar")
            if index == 2:
                return httpx.Response(429, headers={"Retry-After": "30"},
                                      json={"error": {"code": "TOO_MANY_ACTIVE_REQUESTS", "message": "x"}})
            return httpx.Response(202, json={"id": f"c{index}"})
        return httpx.Response(202, json={"id": f"m{key.rsplit('-', 1)[-1]}"})

    monkeypatch.setattr(load, "post_request", post_request)


def run(load, client, poll=0.01, budget=0.3):
    import time

    return load.run_measurement(client, "http://servidor.test", {"Authorization": "x"}, "u1", "prueba", poll,
                                time.monotonic() + budget)


def test_a_network_failure_in_the_concurrency_check_is_inconclusive_and_the_report_is_written(
    load, monkeypatch, tmp_path
):
    fake_posts(monkeypatch, load, failing_concurrent_index=1)
    statuses = {"c0": final_status("c0", 5), **{f"m{i}": final_status(f"m{i}", 10 + i) for i in range(5)}}

    report = run(load, FakeClient(statuses))  # no lanza

    concurrency = report["concurrency"]
    assert concurrency["result"].startswith("INCONCLUSO") and "1 envío" in concurrency["result"]
    [failed] = [a for a in concurrency["answers"] if a.get("error")]
    assert failed["status"] is None and failed["error"]["type"] == "ConnectTimeout"
    assert "tiempo agotado" in failed["error"]["message"]
    assert [r["id"] for r in concurrency["requests"]] == ["c0"]  # la aceptada se espera y se guarda
    assert report["summary"]["concurrencyCheck"] == concurrency["result"]

    monkeypatch.setattr(load, "RESULTS", tmp_path)
    written = load.write_report(report, "rules")
    saved = json.loads(written.read_text(encoding="utf-8"))
    assert saved["concurrency"]["result"].startswith("INCONCLUSO")
    assert "Authorization" not in written.read_text(encoding="utf-8")


def test_an_accepted_request_whose_status_cannot_be_read_marks_the_run_incomplete(load, monkeypatch):
    fake_posts(monkeypatch, load)
    statuses = {"c0": final_status("c0", 5), "c1": final_status("c1", 5),
                **{f"m{i}": final_status(f"m{i}", 10 * (i + 1)) for i in range(5)}}

    report = run(load, FakeClient(statuses, unreadable={"m3"}))

    [lost] = [r for r in report["requests"] if r["id"] == "m3"]
    assert lost["idempotencyKey"].endswith("-sequence-3") and lost["status"] == "unknown"
    assert lost["finished"] is False and lost["error"]["type"] == "ConnectError"
    assert report["complete"] is False
    summary = report["summary"]
    assert summary["finishedRequests"] == 4 and summary["unfinishedRequests"] == ["m3"]
    assert summary["percentileSample"] == 4
    # Percentiles solo con los 4 terminados: 10, 20, 30 y 50 s.
    assert summary["durationSeconds"]["p50"] == 25.0
    text = load.format_summary(summary, "rules")
    assert "Corrida incompleta: 4 de 5 pedidos terminaron" in text
