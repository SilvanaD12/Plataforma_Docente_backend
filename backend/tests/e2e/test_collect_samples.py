"""GEN-01 (T045) y TA-010 (T065): evaluation/collect_samples.py usa los pedidos de generación.

Ejecuta el script contra el servidor real con el generador por reglas y comprueba que escribe muestras con pregunta,
contexto y respuesta que run_ragas.py acepta, y que un caso que el servidor rechaza queda registrado con su motivo sin
detener los demás. Desde TA-010 el contexto es todo lo que recuperó el pedido (GET …/evidence), no solo lo citado.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[2]
EVALUATION = BACKEND_ROOT / "evaluation"


def _cases(tmp_path: Path) -> Path:
    all_cases = {case["id"]: case for case in json.loads((EVALUATION / "cases.json").read_text(encoding="utf-8"))["cases"]}
    explanation = next(case for case in all_cases.values() if case["resourceType"] == "explicacion")
    invalid = {**all_cases["c01"], "id": "c-invalido", "resourceType": "tipo_inexistente"}
    # TA-010: un caso con su propia unidad, competencia y respuesta de referencia, y una secuencia.
    own_unit = {
        **explanation, "id": "c-unidad", "unitTitle": "Capa de red", "outcomeText": "Explica el enrutamiento IP",
        "competency": "Resolución de problemas", "reference": "El enrutador decide el camino de cada paquete.",
        "expectedFragments": ["El enrutador es el dispositivo que decide el camino"],
    }
    sequence = {"id": "c-secuencia", "mode": "sequence", "resourceTypes": ["pregunta_detonante", "explicacion"],
                "topK": 8, "instructions": "Secuencia sobre TCP y UDP."}
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"cases": [all_cases["c01"], invalid, explanation, own_unit, sequence]}),
                    encoding="utf-8")
    return path


def _run_ragas_loader():
    """`load_samples` de run_ragas.py, sin instalar Ragas (solo usa la biblioteca estándar)."""
    spec = importlib.util.spec_from_file_location("run_ragas", EVALUATION / "run_ragas.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module.load_samples


def test_collect_samples_writes_samples_from_generation_requests(server: str, tmp_path: Path):
    out = tmp_path / "results" / "samples.jsonl"
    result = subprocess.run(
        [
            sys.executable, str(EVALUATION / "collect_samples.py"),
            "--api", server, "--cases", str(_cases(tmp_path)), "--out", str(out),
            "--poll", "0.2", "--timeout", "60", "--retries", "0", "--run-id", "e2e-t045",
        ],
        cwd=BACKEND_ROOT,
        # El script escribe en UTF-8 («·», tildes) aunque la configuración regional del sistema sea otra (Windows).
        env={
            **os.environ,
            "EVAL_EMAIL": "evaluacion.rag@correo.pe",
            "EVAL_PASSWORD": "clave-segura-9",
            "PYTHONIOENCODING": "utf-8",
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    samples = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert samples, result.stdout
    for sample in samples:
        assert sample["user_input"].strip()
        assert sample["retrieved_contexts"] and all(text.strip() for text in sample["retrieved_contexts"])
        assert sample["response"].strip()
        assert sample["request_id"].startswith("gen-req-") and sample["request_status"] in {
            "succeeded", "partially_succeeded",
        }
        assert sample["uses_ai"] is False and sample["fallback"] is False  # generador por reglas, sin respaldo
    assert {s["case_id"] for s in samples} <= {"c01", "c05", "c06", "c-unidad", "c-secuencia"}
    assert {"c-unidad", "c-secuencia"} <= {s["case_id"] for s in samples}
    assert _run_ragas_loader()(out) == samples  # run_ragas.py las acepta sin cambios

    # TA-010: el contexto es todo lo recuperado, en orden; lo citado queda aparte y es parte de lo recuperado.
    for sample in samples:
        assert sample["retrieved_count"] == len(sample["retrieved_contexts"]) and sample["limit"] == 8
        assert set(sample["cited_contexts"]) <= set(sample["retrieved_contexts"])
        assert sample["retrieval_mode"] in {"hybrid", "bm25_fallback"}
        query = sample["retrieval_query"]
        assert query["instructions"] and query["text"].startswith(query["unitTitle"])
    own = next(s for s in samples if s["case_id"] == "c-unidad")
    assert own["retrieval_query"]["unitTitle"] == "Capa de red"
    assert own["retrieval_query"]["outcomes"] == ["Explica el enrutamiento IP"]
    assert own["retrieval_query"]["competency"] == "Resolución de problemas"
    assert own["reference"] == "El enrutador decide el camino de cada paquete."
    assert own["expected_fragments"] == ["El enrutador es el dispositivo que decide el camino"]
    assert all("reference" not in s for s in samples if s["case_id"] != "c-unidad")
    sequence = [s for s in samples if s["case_id"] == "c-secuencia"]
    assert {s["resource_type"] for s in sequence} <= {"pregunta_detonante", "explicacion"}
    assert len({s["request_id"] for s in sequence}) == 1

    # Sin `modalities`: el pedido se guarda sin modalidad (HU-024 no filtra los tipos).
    with httpx.Client(base_url=server) as api:
        token = api.post("/api/v1/sessions", json={"email": "evaluacion.rag@correo.pe",
                                                  "password": "clave-segura-9"}).json()["token"]
        status = api.get(f"/api/v1/generation-requests/{samples[0]['request_id']}",
                         headers={"Authorization": f"Bearer {token}"}).json()
    assert status["parameters"]["modalities"] == []

    # El caso inválido no detuvo la corrida: su motivo quedó en failures.jsonl.
    failures = [json.loads(line) for line in (out.parent / "failures.jsonl").read_text(encoding="utf-8").splitlines()]
    invalid = next(f for f in failures if f["case_id"] == "c-invalido")
    assert invalid["problems"][0]["code"] and invalid["problems"][0]["message"]
    assert "c-invalido · engage · tipo_inexistente: sin muestra" in result.stdout


def test_t067_cases_with_the_topic_check_reject_c06_and_keep_c01_to_c05(server: str, tmp_path: Path):
    """QA-05: con el corpus de T068, C-06 (bases de datos en una unidad de redes) ya no entrega recursos y queda como
    `pass` en expectations.jsonl; C-01 a C-05 siguen dando muestras. Generador por reglas, sin IA."""
    out = tmp_path / "results" / "samples.jsonl"
    result = subprocess.run(
        [
            sys.executable, str(EVALUATION / "collect_samples.py"),
            "--api", server, "--cases", str(EVALUATION / "cases_t067.json"), "--corpus", str(EVALUATION / "corpus_t067"),
            "--out", str(out), "--poll", "0.2", "--timeout", "60", "--retries", "0", "--run-id", "e2e-qa05",
        ],
        cwd=BACKEND_ROOT,
        env={**os.environ, "EVAL_EMAIL": "evaluacion.qa05@correo.pe", "EVAL_PASSWORD": "clave-segura-9",
             "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, encoding="utf-8", timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    samples = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert sorted({s["case_id"] for s in samples}) == ["C-01", "C-02", "C-03", "C-04", "C-05"]
    [c06] = [json.loads(line) for line in (out.parent / "expectations.jsonl").read_text(encoding="utf-8").splitlines()]
    assert c06["case_id"] == "C-06" and c06["outcome"] == "pass" and c06["resources"] == []
    assert "llaves primarias, modelo relacional" in c06["reason"]
    assert "C-06 · no_evidence: cumple" in result.stdout
