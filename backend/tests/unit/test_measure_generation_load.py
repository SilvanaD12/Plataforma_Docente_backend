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


@pytest.fixture(autouse=True)
def approved_plans(load, monkeypatch):
    """T021: cada secuencia genera desde un plan aprobado. Aquí el plan es falso; `planned_body` se prueba aparte."""
    monkeypatch.setattr(load, "planned_body",
                        lambda client, headers, unit_id, key: {"planId": f"plan-{unit_id}", "planVersion": 1})


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


def test_a_measured_send_that_fails_by_network_is_recorded_and_the_run_goes_on(load, monkeypatch, tmp_path):
    """Revisión del PR #27: la 2.ª secuencia medida falla por red. No se cae el script: se reintenta un par de veces
    con la misma clave, se registra el envío fallido, siguen los demás y la corrida queda incompleta."""
    import httpx

    attempts: list[str] = []

    def post_request(client, headers, key, body):
        if "-concurrency-" in key:
            index = int(key.rsplit("-", 1)[-1])
            if index == 2:
                return httpx.Response(429, headers={"Retry-After": "30"},
                                      json={"error": {"code": "TOO_MANY_ACTIVE_REQUESTS", "message": "x"}})
            return httpx.Response(202, json={"id": f"c{index}"})
        if key.endswith("-sequence-1"):
            attempts.append(key)
            raise httpx.ConnectError("conexión rechazada")
        return httpx.Response(202, json={"id": f"m{key.rsplit('-', 1)[-1]}"})

    monkeypatch.setattr(load, "post_request", post_request)
    statuses = {"c0": final_status("c0", 5), "c1": final_status("c1", 5),
                **{f"m{i}": final_status(f"m{i}", 10 * (i + 1)) for i in (0, 2, 3, 4)}}

    report = run(load, FakeClient(statuses))  # no lanza

    assert [r["id"] for r in report["requests"]] == ["m0", "m2", "m3", "m4"]  # la aceptada antes sigue y se consulta
    assert all(r["finished"] for r in report["requests"])
    [failed] = report["failedSends"]
    assert failed["index"] == 1 and failed["key"].endswith("-sequence-1")
    assert failed["error"] == {"type": "ConnectError", "message": "conexión rechazada"}
    assert len(attempts) == 1 + load.MAX_SEND_RETRIES and set(attempts) == {failed["key"]}  # misma clave, acotado
    assert report["complete"] is False
    summary = report["summary"]
    assert summary["finishedRequests"] == 4 and summary["failedSends"] == [failed["key"]]
    text = load.format_summary(summary, "rules")
    assert "Corrida incompleta: 4 de 5 pedidos terminaron" in text and failed["key"] in text

    monkeypatch.setattr(load, "RESULTS", tmp_path)
    written = load.write_report(report, "rules")
    assert json.loads(written.read_text(encoding="utf-8"))["failedSends"][0]["index"] == 1


def test_a_status_answer_that_is_not_json_is_recorded_and_polling_goes_on(load, monkeypatch):
    """Un 200 que no es JSON (por ejemplo, la página de un proxy) no detiene la espera: queda como error."""
    import httpx

    fake_posts(monkeypatch, load)
    statuses = {"c0": final_status("c0", 5), "c1": final_status("c1", 5),
                **{f"m{i}": final_status(f"m{i}", 10 + i) for i in range(5)}}

    class HtmlFor(FakeClient):
        def get(self, path, headers=None, params=None):
            if path.endswith("/m2"):
                return httpx.Response(200, text="<html>proxy</html>")
            return super().get(path, headers, params)

    report = run(load, HtmlFor(statuses))
    [broken] = [r for r in report["requests"] if r["id"] == "m2"]
    assert broken["status"] == "unknown" and broken["error"]["type"] == "JSONDecodeError"
    assert report["complete"] is False and report["summary"]["finishedRequests"] == 4


def test_a_network_failure_before_any_request_stops_with_a_clear_message_and_no_report(
    load, monkeypatch, tmp_path, capsys
):
    import sys

    import httpx

    class Collect:
        @staticmethod
        def login(client, email, password):
            raise httpx.ConnectError("conexión rechazada")

        @staticmethod
        def fail(message):
            print(f"Error: {message}", file=sys.stderr)
            raise SystemExit(1)

    monkeypatch.setattr(load, "load_collect_samples", lambda: Collect)
    monkeypatch.setattr(load, "RESULTS", tmp_path / "results")
    monkeypatch.setenv("EVAL_EMAIL", "carga@correo.pe")
    monkeypatch.setenv("EVAL_PASSWORD", "clave-que-no-debe-aparecer")
    monkeypatch.setattr(sys, "argv", ["measure_generation_load.py", "--api", "http://servidor.test"])

    with pytest.raises(SystemExit) as stopped:
        load.main()

    assert stopped.value.code == 1
    err = capsys.readouterr().err
    assert "no se pudo preparar la medición" in err and "ConnectError" in err and "ningún pedido" in err
    assert "clave-que-no-debe-aparecer" not in err
    assert not (tmp_path / "results").exists()  # no hay informe


# --------------------------------------------------------------------------- QA-06: 5 docentes a la vez


def test_each_teacher_gets_its_own_account_from_the_base_email(load):
    assert [load.teacher_email("carga@correo.pe", i) for i in range(3)] == [
        "carga.carga1@correo.pe", "carga.carga2@correo.pe", "carga.carga3@correo.pe",
    ]


def test_post_times_report_p50_p95_and_max(load):
    answers = [{"status": 202, "ms": ms} for ms in (100.0, 200.0, 300.0, 400.0, 500.0)]
    answers.append({"status": None, "ms": None, "error": {"type": "ConnectError", "message": "x"}})
    summary = load.post_time_summary(answers)
    assert summary["sent"] == 6 and summary["measured"] == 5
    assert summary["p50"] == 300.0 and summary["p95"] == pytest.approx(480.0) and summary["max"] == 500.0
    assert summary["byStatus"] == {"202": 5, "sin respuesta": 1}
    assert load.post_time_summary([])["p95"] is None


def teachers(count=5):
    return [{"index": i, "headers": {"Authorization": f"Bearer t{i}"}, "unitId": f"u{i}"} for i in range(count)]


def test_the_posts_of_all_teachers_leave_together_and_each_is_timed(load, monkeypatch):
    """Revisión del PR #58: en vez de medir cuánto se separan los envíos, el POST falso de los 4 docentes que reciben
    respuesta espera en una barrera de 4 (el 5.º falla por red). Solo pasa si esos envíos están en curso a la vez; si
    el script los mandara uno por uno, la barrera se rompería y quedarían como errores. Sin `sleep`."""
    import threading

    import httpx

    together = threading.Barrier(4)  # los 4 envíos que responden; el 5.º falla por red sin esperar

    def post_request(client, headers, key, body):
        index = int(key.rsplit("-", 1)[-1])
        assert headers == {"Authorization": f"Bearer t{index}"} and body == {"planId": f"plan-u{index}",
                                                                            "planVersion": 1}
        if index == 4:
            raise httpx.ConnectError("conexión rechazada")
        together.wait(timeout=10)  # amplio: solo se agota si los envíos no salen a la vez
        return httpx.Response(202, json={"id": f"gen-{index}"})

    monkeypatch.setattr(load, "post_request", post_request)
    answers = load.simultaneous_posts("http://servidor.test", teachers(), "prueba")

    assert [a["key"] for a in answers] == [f"load-prueba-teacher-{i}" for i in range(5)]
    assert [a["status"] for a in answers] == [202, 202, 202, 202, None]
    assert all(isinstance(a["ms"], float) and a["ms"] >= 0 for a in answers[:4]) and answers[4]["ms"] is None
    assert [a["requestId"] for a in answers] == ["gen-0", "gen-1", "gen-2", "gen-3", None]
    assert answers[4]["error"]["type"] == "ConnectError"
    assert all("headers" not in a for a in answers)  # la sesión no va al informe


class TeacherClient:
    """Consultas de estado con la sesión de cada docente: cada pedido solo lo ve su dueño."""

    def __init__(self, statuses):
        self.statuses = statuses

    def get(self, path, headers=None, params=None):
        import httpx

        request_id = path.rsplit("/", 1)[-1]
        assert headers["Authorization"] == f"Bearer t{request_id.rsplit('-', 1)[-1]}"
        return httpx.Response(200, json=self.statuses[request_id])


def test_the_teachers_mode_reports_post_times_and_end_to_end_durations(load, monkeypatch):
    import time

    import httpx

    monkeypatch.setattr(load, "post_request",
                        lambda client, headers, key, body: httpx.Response(202, json={"id": f"gen-{key[-1]}"}))
    statuses = {f"gen-{i}": final_status(f"gen-{i}", 10 + i) for i in range(5)}
    report = load.run_teachers_measurement(TeacherClient(statuses), "http://servidor.test", teachers(), "prueba",
                                           0.01, time.monotonic() + 1)

    assert report["mode"] == "teachers" and report["teachers"] == 5 and report["complete"] is True
    assert [r["id"] for r in report["requests"]] == [f"gen-{i}" for i in range(5)]
    summary = report["summary"]
    assert summary["postMs"]["measured"] == 5 and summary["postMs"]["byStatus"] == {"202": 5}
    assert summary["durationSeconds"]["p50"] == 12.0 and summary["finishedRequests"] == 5
    text = load.format_summary(summary, "rules")
    assert "POST simultáneos (docentes)" in text and "POST p50 / p95 / máx" in text
    assert "Authorization" not in json.dumps(report)


def test_main_with_teachers_prepares_one_account_each_and_writes_the_report(load, monkeypatch, tmp_path, capsys):
    import sys

    import httpx

    logins: list[str] = []

    class Collect:
        @staticmethod
        def login(client, email, password):
            logins.append(email)
            return {"Authorization": f"Bearer t{len(logins) - 1}"}

        @staticmethod
        def ensure_unit(client, headers):
            return {"id": f"u{headers['Authorization'][-1]}", "outcomes": []}

        @staticmethod
        def ensure_material(client, headers, unit, corpus):
            return None

        @staticmethod
        def fail(message):
            raise SystemExit(message)

    def server(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/generator":
            return httpx.Response(200, json={"provider": "rules", "description": "Generador por reglas (sin IA)"})
        if request.url.params.get("active") == "true":
            return httpx.Response(200, json=[])
        request_id = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=final_status(request_id, 9))

    real_client = httpx.Client
    monkeypatch.setattr(load.httpx, "Client",
                        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(server)))
    monkeypatch.setattr(load, "post_request",
                        lambda client, headers, key, body: httpx.Response(202, json={"id": f"gen-{key[-1]}"}))
    monkeypatch.setattr(load, "load_collect_samples", lambda: Collect)
    monkeypatch.setattr(load, "RESULTS", tmp_path)
    monkeypatch.setenv("EVAL_EMAIL", "carga@correo.pe")
    monkeypatch.setenv("EVAL_PASSWORD", "clave-que-no-debe-aparecer")
    monkeypatch.setattr(sys, "argv", ["measure_generation_load.py", "--api", "http://servidor.test", "--teachers",
                                      "5", "--poll", "0.01", "--run-id", "prueba"])
    load.main()

    assert logins == [f"carga.carga{i}@correo.pe" for i in range(1, 6)]
    [written] = list(tmp_path.glob("load-rules-*.json"))
    report = json.loads(written.read_text(encoding="utf-8"))
    assert report["mode"] == "teachers" and report["summary"]["postMs"]["measured"] == 5
    assert "clave-que-no-debe-aparecer" not in written.read_text(encoding="utf-8") + capsys.readouterr().out


# --------------------------------------------------------------------------- T021: plan antes de cada secuencia


class PlanServer:
    """Crea y aprueba planes; con `reject`, el plan responde 422 al aprobarlo (PLAN_INVALID)."""

    def __init__(self, reject: bool = False) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.reject = reject

    def __call__(self, request):
        import httpx

        body = json.loads(request.content) if request.content else {}
        self.calls.append((request.method, request.url.path, {**body, "key": request.headers.get("Idempotency-Key")}))
        if request.url.path == "/api/v1/generation-plans":
            return httpx.Response(201, json={"id": "gen-plan-1", "version": 1, "status": "draft"})
        if request.url.path.endswith("/approve"):
            if self.reject:
                return httpx.Response(422, json={"error": {"code": "PLAN_INVALID", "message": "x"}})
            return httpx.Response(200, json={"id": "gen-plan-1", "version": 1, "status": "approved"})
        return httpx.Response(404)


def test_each_sequence_creates_and_approves_its_plan_of_eight_types_by_five(load, monkeypatch):
    import httpx

    monkeypatch.undo()  # el `planned_body` real
    server = PlanServer()
    with httpx.Client(base_url="http://servidor.test", transport=httpx.MockTransport(server)) as client:
        body = load.planned_body(client, {"Authorization": "x"}, "u1", "load-prueba-sequence-0")
    assert body == {"planId": "gen-plan-1", "planVersion": 1}
    (_, created_path, created), (_, approve_path, approve) = server.calls
    assert created_path == "/api/v1/generation-plans" and created["key"] == "load-prueba-sequence-0-plan"
    assert created["unitId"] == "u1" and len(created["resourceTypes"]) == 8
    assert {t["quantity"] for t in created["resourceTypes"]} == {load.QUANTITY}
    assert approve_path == "/api/v1/generation-plans/gen-plan-1/approve" and approve["expectedVersion"] == 1


def test_a_rejected_plan_counts_as_a_refused_send_and_the_run_goes_on(load, monkeypatch):
    import httpx

    def planned(client, headers, unit_id, key):
        if key.endswith("-sequence-1"):
            raise load.PlanRejected(httpx.Response(422, json={"error": {"code": "PLAN_INVALID", "message": "x"}}))
        return {"planId": f"plan-{key}", "planVersion": 1}

    monkeypatch.setattr(load, "planned_body", planned)
    monkeypatch.setattr(load, "post_request",
                        lambda client, headers, key, body: httpx.Response(202, json={"id": f"m{key[-1]}"}))
    submitted, refused, failed = load.submit_measured(None, {}, "u1", "prueba", 0.01, __import__("time").monotonic() + 1)
    assert sorted(submitted.values()) == [f"load-prueba-sequence-{i}" for i in (0, 2, 3, 4)]
    [rejected] = refused
    assert rejected["key"].endswith("-sequence-1") and rejected["status"] == 422
    assert rejected["errorCode"] == "PLAN_INVALID" and failed == []
