"""GEN-01 (T045): evaluation/collect_samples.py usa los pedidos de generación (POST /api/v1/generation-requests).

Ejecuta el script contra el servidor real con el generador por reglas y comprueba que escribe muestras con pregunta,
contexto y respuesta que run_ragas.py acepta, y que un caso que el servidor rechaza queda registrado con su motivo sin
detener los demás.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
EVALUATION = BACKEND_ROOT / "evaluation"


def _cases(tmp_path: Path) -> Path:
    all_cases = {case["id"]: case for case in json.loads((EVALUATION / "cases.json").read_text(encoding="utf-8"))["cases"]}
    explanation = next(case for case in all_cases.values() if case["resourceType"] == "explicacion")
    invalid = {**all_cases["c01"], "id": "c-invalido", "resourceType": "tipo_inexistente"}
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"cases": [all_cases["c01"], invalid, explanation]}), encoding="utf-8")
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
        env={**os.environ, "EVAL_EMAIL": "evaluacion.rag@correo.pe", "EVAL_PASSWORD": "clave-segura-9"},
        capture_output=True,
        text=True,
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
    assert {s["case_id"] for s in samples} <= {"c01", "c05", "c06"}
    assert _run_ragas_loader()(out) == samples  # run_ragas.py las acepta sin cambios

    # El caso inválido no detuvo la corrida: su motivo quedó en failures.jsonl.
    failures = [json.loads(line) for line in (out.parent / "failures.jsonl").read_text(encoding="utf-8").splitlines()]
    invalid = next(f for f in failures if f["case_id"] == "c-invalido")
    assert invalid["problems"][0]["code"] and invalid["problems"][0]["message"]
    assert "c-invalido · engage · tipo_inexistente: sin muestra" in result.stdout
