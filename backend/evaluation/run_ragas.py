"""Califica las muestras de collect_samples.py con Ragas, usando Gemini como juez.

Uso (desde backend/, con el entorno de evaluation/ activo):
    export GEMINI_API_KEY=...
    python evaluation/run_ragas.py --delay 4
    python evaluation/run_ragas.py --contexts cited   # para comparar con lo que citan los recursos

Contexto (--contexts, TA-010, research R12):
- retrieved (por defecto): todo lo que el pedido recuperó del material y entregó al modelo, en el orden de la
  recuperación (retrieved_contexts). Es el criterio del backlog.
- cited: solo los fragmentos que cita cada recurso (cited_contexts), como hasta el PR #16. Las muestras sin fragmentos
  citados se omiten y se informan.

Métricas:
- faithfulness: qué parte de lo que afirma el recurso está respaldada por el contexto.
- answer_relevancy: qué tan bien responde el recurso al pedido (no usa el contexto). Se calcula con strictness=1: el
  juez genera una sola pregunta por llamada. Ragas usa strictness=3 por defecto y lo envía como n=3 (tres candidatos en
  una llamada), y el endpoint compatible con OpenAI de Gemini lo rechaza («400 Multiple candidates is not enabled for
  this model»), así que answer_relevancy quedaba en None en todas las muestras (T068).
- context_precision: qué tan útiles fueron los fragmentos del contexto para el recurso, y si los útiles van primero.
- context_recall: qué parte de la respuesta de referencia está en el contexto. Solo se calcula si todas las muestras
  traen `reference` (el campo reference de cases.json); si no, se omite y se explica por qué.

Escribe evaluation/results/scores.csv, summary.json y summary.md, con el contexto, las métricas usadas y, junto al
juez, el strictness de answer_relevancy.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
GEMINI_OPENAI_URL = 'https://generativelanguage.googleapis.com/v1beta/openai/'
METRICS = ('faithfulness', 'answer_relevancy', 'context_precision')
RECALL = 'context_recall'
CONTEXT_FIELDS = {'retrieved': 'retrieved_contexts', 'cited': 'cited_contexts'}
# Una pregunta por llamada: el juez rechaza n>1 («Multiple candidates is not enabled»), que es lo que envía el 3 por defecto.
RELEVANCY_STRICTNESS = 1


def metric_names(with_recall: bool) -> tuple[str, ...]:
    return (*METRICS, RECALL) if with_recall else METRICS


def select_contexts(samples: list[dict], mode: str) -> tuple[list[dict], list[str]]:
    """Las muestras con el contexto elegido en `contexts`, y los case_id que se omiten por no tener ese contexto."""
    field = CONTEXT_FIELDS[mode]
    kept, skipped = [], []
    for sample in samples:
        contexts = sample.get(field) or []
        if contexts:
            kept.append({**sample, 'contexts': contexts})
        else:
            skipped.append(sample['case_id'])
    return kept, skipped


def recall_enabled(samples: list[dict]) -> tuple[bool, str | None]:
    """context_recall necesita la respuesta de referencia de todas las muestras: si falta en alguna, se omite."""
    missing = [s for s in samples if not str(s.get('reference') or '').strip()]
    if samples and not missing:
        return True, None
    return False, (f'{RECALL} se omite: {len(missing)} de {len(samples)} muestras no tienen respuesta de '
                   'referencia (reference).')


def load_samples(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(f'Error: no existe {path}. Corre antes evaluation/collect_samples.py.')
    samples = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    empty = [s['case_id'] for s in samples if not s.get('retrieved_contexts')]
    if empty:
        sys.exit(f'Error: estas muestras no tienen contexto recuperado: {", ".join(empty)}')
    return samples


def build_judge(model: str, embedding_model: str):
    key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
    if not key:
        sys.exit('Error: define GEMINI_API_KEY con la clave de Google AI Studio.')
    warnings.filterwarnings('ignore', category=DeprecationWarning)
    from langchain_community.chat_models import ChatOpenAI
    from langchain_community.embeddings import OpenAIEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper

    llm = ChatOpenAI(model=model, openai_api_key=key, openai_api_base=GEMINI_OPENAI_URL, temperature=0)
    embeddings = OpenAIEmbeddings(model=embedding_model, openai_api_key=key, openai_api_base=GEMINI_OPENAI_URL,
                                  check_embedding_ctx_length=False)
    return LangchainLLMWrapper(llm), LangchainEmbeddingsWrapper(embeddings)


def build_ragas_metrics(with_recall: bool) -> list:
    """Las métricas de Ragas, en el orden de metric_names(with_recall)."""
    from ragas.metrics import Faithfulness, LLMContextPrecisionWithoutReference, LLMContextRecall, ResponseRelevancy

    metrics = [Faithfulness(), ResponseRelevancy(strictness=RELEVANCY_STRICTNESS), LLMContextPrecisionWithoutReference()]
    if with_recall:
        metrics.append(LLMContextRecall())
    return metrics


def ragas_evaluator(llm, embeddings, with_recall: bool):
    """Evaluador real: califica una muestra con las métricas de Ragas y el juez dado. Devuelve {métrica: valor}."""
    from ragas import EvaluationDataset, evaluate
    from ragas.run_config import RunConfig

    metrics = build_ragas_metrics(with_recall)
    names = dict(zip((m.name for m in metrics), metric_names(with_recall)))
    config = RunConfig(max_workers=1, timeout=180, max_retries=5)

    def evaluate_one(row: dict) -> dict:
        dataset = EvaluationDataset.from_list([row])
        result = evaluate(dataset=dataset, metrics=metrics, llm=llm, embeddings=embeddings, run_config=config,
                          show_progress=False)
        values = result.to_pandas().iloc[0].to_dict()
        return {name: values.get(original) for original, name in names.items()}

    return evaluate_one


def score_samples(samples: list[dict], evaluate_one, metrics: tuple[str, ...], delay: float = 0) -> list[dict]:
    """Califica cada muestra con `evaluate_one`, usando su contexto elegido (`contexts`). La referencia solo se
    envía si se calcula context_recall."""
    rows = []
    for index, sample in enumerate(samples, 1):
        row_input = {'user_input': sample['user_input'], 'response': sample['response'],
                     'retrieved_contexts': sample['contexts']}
        if RECALL in metrics:
            row_input['reference'] = sample['reference']
        values = evaluate_one(row_input)
        row = {'case_id': sample['case_id'], 'stage': sample['stage'], 'resource_type': sample['resource_type'],
               'cites_material': sample.get('cites_material', False)}
        for name in metrics:
            value = values.get(name)
            row[name] = None if value is None or value != value else round(float(value), 4)  # NaN -> None
        rows.append(row)
        print(f"{index}/{len(samples)} {sample['case_id']}: " + ', '.join(f'{m}={row[m]}' for m in metrics))
        if delay and index < len(samples):
            time.sleep(delay)  # respeta el límite de solicitudes por minuto del plan gratuito
    return rows


def summarize(rows: list[dict], metrics: tuple[str, ...] = METRICS, contexts: str = 'retrieved',
              skipped: list[str] | None = None, notes: list[str] | None = None) -> dict:
    def mean(values):
        values = [v for v in values if v is not None]
        return round(statistics.mean(values), 4) if values else None

    by_stage = {}
    for stage in dict.fromkeys(r['stage'] for r in rows):
        group = [r for r in rows if r['stage'] == stage]
        by_stage[stage] = {m: mean(r[m] for r in group) for m in metrics} | {'samples': len(group)}
    return {
        'samples': len(rows),
        'contexts': contexts,
        'metrics': list(metrics),
        'skipped': list(skipped or []),
        'notes': list(notes or []),
        'traceability_I22': f"{sum(r['cites_material'] for r in rows)}/{len(rows)}",
        'means': {m: mean(r[m] for r in rows) for m in metrics},
        'by_stage': by_stage,
    }


def write_outputs(rows: list[dict], summary: dict, out_dir: Path, model: str,
                  metrics: tuple[str, ...] = METRICS) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / 'scores.csv').open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=['case_id', 'stage', 'resource_type', 'cites_material', *metrics])
        writer.writeheader()
        writer.writerows(rows)
    judge = {'judge': model, 'answer_relevancy_strictness': RELEVANCY_STRICTNESS}
    (out_dir / 'summary.json').write_text(json.dumps(summary | judge, ensure_ascii=False, indent=2), encoding='utf-8')
    fmt = lambda v: '—' if v is None else f'{v:.2f}'
    lines = [
        '# Evaluación RAG con Ragas', '',
        f"Juez: {model} (answer_relevancy con strictness={RELEVANCY_STRICTNESS}) · Muestras: {summary['samples']} · Trazabilidad (I22): {summary['traceability_I22']} recursos citan el material",
        f"Contexto: {summary.get('contexts', 'retrieved')}", *summary.get('notes', []), '',
        '| Métrica | Promedio |', '|---|---|',
        *[f'| {m} | {fmt(v)} |' for m, v in summary['means'].items()], '',
        '| Etapa | Muestras | ' + ' | '.join(metrics) + ' |', '|---|---|' + '---|' * len(metrics),
        *[f"| {s} | {v['samples']} | " + ' | '.join(fmt(v[m]) for m in metrics) + ' |' for s, v in summary['by_stage'].items()],
    ]
    (out_dir / 'summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Califica las muestras RAG con Ragas y Gemini como juez.')
    parser.add_argument('--samples', type=Path, default=HERE / 'results' / 'samples.jsonl')
    parser.add_argument('--out', type=Path, default=HERE / 'results')
    parser.add_argument('--model', default=os.getenv('RAGAS_JUDGE_MODEL', 'gemini-3.8-flash'))
    parser.add_argument('--embedding-model', default=os.getenv('RAGAS_EMBEDDING_MODEL', 'gemini-embedding-001'))
    parser.add_argument('--delay', type=float, default=0, help='segundos de espera entre muestras (plan gratuito: 4)')
    parser.add_argument('--contexts', choices=tuple(CONTEXT_FIELDS), default='retrieved',
                        help='retrieved: todo lo recuperado (por defecto); cited: solo lo que cita cada recurso')
    parser.add_argument('--check', action='store_true', help='solo valida samples.jsonl, sin llamar al juez')
    return parser


def main() -> None:
    args = build_parser().parse_args()

    samples = load_samples(args.samples)
    print(f'{len(samples)} muestras válidas en {args.samples}')
    if args.check:
        return
    selected, skipped = select_contexts(samples, args.contexts)
    if skipped:
        print(f"{len(skipped)} muestra(s) sin fragmentos citados se omiten con --contexts {args.contexts}: "
              + ', '.join(skipped))
    if not selected:
        sys.exit(f'Error: ninguna muestra tiene contexto con --contexts {args.contexts}.')
    with_recall, recall_note = recall_enabled(selected)
    if recall_note:
        print(recall_note)
    metrics = metric_names(with_recall)
    llm, embeddings = build_judge(args.model, args.embedding_model)
    rows = score_samples(selected, ragas_evaluator(llm, embeddings, with_recall), metrics, args.delay)
    summary = summarize(rows, metrics, args.contexts, skipped, [recall_note] if recall_note else [])
    write_outputs(rows, summary, args.out, args.model, metrics)
    print(json.dumps(summary['means'], ensure_ascii=False))
    print(f'Resultados en {args.out}/scores.csv, summary.json y summary.md')


if __name__ == '__main__':
    main()
