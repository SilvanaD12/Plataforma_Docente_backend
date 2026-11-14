"""TA-010 (T066): opciones de evaluation/run_ragas.py sin llamar a ningún modelo.

El juez y las métricas de Ragas se reemplazan por un evaluador falso: se prueba qué contexto recibe cada métrica,
cuándo se agrega context_recall y qué se escribe en los resultados. Research R12.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "evaluation" / "run_ragas.py"


@pytest.fixture
def ragas():
    spec = importlib.util.spec_from_file_location("run_ragas", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def sample(case_id: str, **fields) -> dict:
    return {
        "case_id": case_id, "stage": "explain", "resource_type": "explicacion", "cites_material": True,
        "user_input": "Explicación citada: TCP y UDP.", "response": "TCP es confiable.",
        "retrieved_contexts": ["TCP es confiable.", "UDP es rápido.", "IP enruta."],
        "cited_contexts": ["TCP es confiable."],
        **fields,
    }


class FakeEvaluator:
    """Devuelve un valor fijo por métrica y guarda lo que recibió cada muestra."""

    def __init__(self, values: dict[str, float]) -> None:
        self.values = values
        self.inputs: list[dict] = []

    def __call__(self, row: dict) -> dict[str, float]:
        self.inputs.append(row)
        return dict(self.values)


# --contexts


def test_the_contexts_option_defaults_to_retrieved(ragas):
    parser = ragas.build_parser()
    assert parser.parse_args([]).contexts == "retrieved"
    assert parser.parse_args(["--contexts", "cited"]).contexts == "cited"
    with pytest.raises(SystemExit):
        parser.parse_args(["--contexts", "todo"])


def test_retrieved_uses_everything_retrieved_and_cited_only_what_the_resource_cites(ragas):
    samples = [sample("c01")]
    [retrieved], skipped = ragas.select_contexts(samples, "retrieved")
    assert retrieved["contexts"] == samples[0]["retrieved_contexts"] and skipped == []
    [cited], skipped = ragas.select_contexts(samples, "cited")
    assert cited["contexts"] == ["TCP es confiable."] and skipped == []


def test_samples_without_cited_fragments_are_skipped_only_in_cited_mode(ragas):
    samples = [sample("c01"), sample("c02", cited_contexts=[]), sample("c03")]
    del samples[2]["cited_contexts"]  # muestra anterior a TA-010
    kept, skipped = ragas.select_contexts(samples, "cited")
    assert [s["case_id"] for s in kept] == ["c01"] and skipped == ["c02", "c03"]
    kept, skipped = ragas.select_contexts(samples, "retrieved")
    assert len(kept) == 3 and skipped == []


# context_recall


def test_context_recall_is_added_only_when_every_sample_has_a_reference(ragas):
    with_reference = [sample("c01", reference="TCP es confiable."), sample("c02", reference="UDP es rápido.")]
    enabled, message = ragas.recall_enabled(with_reference)
    assert enabled and message is None
    assert ragas.metric_names(enabled) == ("faithfulness", "answer_relevancy", "context_precision", "context_recall")

    mixed = [sample("c01", reference="TCP es confiable."), sample("c02"), sample("c03", reference="  ")]
    enabled, message = ragas.recall_enabled(mixed)
    assert not enabled
    assert message == "context_recall se omite: 2 de 3 muestras no tienen respuesta de referencia (reference)."
    assert ragas.metric_names(enabled) == ("faithfulness", "answer_relevancy", "context_precision")


def test_each_metric_receives_the_chosen_contexts_and_the_reference_only_with_recall(ragas):
    samples, _ = ragas.select_contexts([sample("c01", reference="TCP es confiable.")], "cited")
    evaluator = FakeEvaluator({"faithfulness": 1.0, "answer_relevancy": 0.8, "context_precision": float("nan"),
                               "context_recall": 0.5})
    [row] = ragas.score_samples(samples, evaluator, ragas.metric_names(True))
    assert evaluator.inputs == [{"user_input": "Explicación citada: TCP y UDP.", "response": "TCP es confiable.",
                                 "retrieved_contexts": ["TCP es confiable."], "reference": "TCP es confiable."}]
    assert row["context_precision"] is None and row["context_recall"] == 0.5  # NaN -> None

    evaluator = FakeEvaluator({"faithfulness": 1.0, "answer_relevancy": 0.8, "context_precision": 0.4})
    [row] = ragas.score_samples(samples, evaluator, ragas.metric_names(False))
    assert "reference" not in evaluator.inputs[0] and "context_recall" not in row


def test_the_summary_records_the_contexts_and_the_metrics_used(ragas, tmp_path):
    rows = [{"case_id": "c01", "stage": "explain", "resource_type": "explicacion", "cites_material": True,
             "faithfulness": 1.0, "answer_relevancy": 0.5, "context_precision": 0.25}]
    metrics = ragas.metric_names(False)
    summary = ragas.summarize(rows, metrics, contexts="retrieved", skipped=["c09"], notes=["nota"])
    assert summary["contexts"] == "retrieved" and summary["skipped"] == ["c09"] and summary["notes"] == ["nota"]
    assert summary["means"] == {"faithfulness": 1.0, "answer_relevancy": 0.5, "context_precision": 0.25}
    ragas.write_outputs(rows, summary, tmp_path, "juez-falso", metrics)
    header = (tmp_path / "scores.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header == "case_id,stage,resource_type,cites_material,faithfulness,answer_relevancy,context_precision"
    assert "Contexto: retrieved" in (tmp_path / "summary.md").read_text(encoding="utf-8")


def test_main_uses_the_fake_judge_and_explains_a_skipped_recall(ragas, tmp_path, monkeypatch, capsys):
    samples_path = tmp_path / "samples.jsonl"
    samples_path.write_text("\n".join(json.dumps(s) for s in [sample("c01"), sample("c02", cited_contexts=[])]),
                            encoding="utf-8")
    evaluator = FakeEvaluator({"faithfulness": 1.0, "answer_relevancy": 0.5, "context_precision": 0.5})
    monkeypatch.setattr(ragas, "build_judge", lambda model, embedding_model: ("llm", "embeddings"))
    monkeypatch.setattr(ragas, "ragas_evaluator", lambda llm, embeddings, with_recall: evaluator)
    monkeypatch.setattr(sys, "argv", ["run_ragas.py", "--samples", str(samples_path), "--out", str(tmp_path),
                                      "--contexts", "cited"])
    ragas.main()

    out = capsys.readouterr().out
    # Se cuenta sobre las muestras que se califican (c02 ya se omitió por no tener fragmentos citados).
    assert "context_recall se omite: 1 de 1 muestras no tienen respuesta de referencia (reference)." in out
    assert "1 muestra(s) sin fragmentos citados se omiten con --contexts cited: c02" in out
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["contexts"] == "cited" and summary["samples"] == 1 and summary["skipped"] == ["c02"]
    assert [row["retrieved_contexts"] for row in evaluator.inputs] == [["TCP es confiable."]]
