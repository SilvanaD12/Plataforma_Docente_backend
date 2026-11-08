"""Califica las muestras de collect_samples.py con Ragas, usando Gemini como juez.

Uso (desde backend/, con el entorno de evaluation/ activo):
    export GEMINI_API_KEY=...
    python evaluation/run_ragas.py --delay 4

Métricas sin respuesta de referencia (el docente no escribe una respuesta «correcta»):
- faithfulness: qué parte de lo que afirma el recurso está respaldada por el contexto recuperado.
- answer_relevancy: qué tan bien responde el recurso al pedido.
- context_precision: qué tan útiles fueron los fragmentos recuperados para el recurso.

Escribe evaluation/results/scores.csv, summary.json y summary.md.
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


def score_samples(samples: list[dict], llm, embeddings, delay: float) -> list[dict]:
    from ragas import EvaluationDataset, evaluate
    from ragas.metrics import Faithfulness, LLMContextPrecisionWithoutReference, ResponseRelevancy
    from ragas.run_config import RunConfig

    metrics = [Faithfulness(), ResponseRelevancy(), LLMContextPrecisionWithoutReference()]
    names = dict(zip((m.name for m in metrics), METRICS))
    config = RunConfig(max_workers=1, timeout=180, max_retries=5)
    rows = []
    for index, sample in enumerate(samples, 1):
        dataset = EvaluationDataset.from_list([{
            'user_input': sample['user_input'], 'retrieved_contexts': sample['retrieved_contexts'], 'response': sample['response'],
        }])
        result = evaluate(dataset=dataset, metrics=metrics, llm=llm, embeddings=embeddings, run_config=config, show_progress=False)
        values = result.to_pandas().iloc[0].to_dict()
        row = {'case_id': sample['case_id'], 'stage': sample['stage'], 'resource_type': sample['resource_type'],
               'cites_material': sample.get('cites_material', False)}
        for original, name in names.items():
            value = values.get(original)
            row[name] = None if value is None or value != value else round(float(value), 4)  # NaN -> None
        rows.append(row)
        print(f"{index}/{len(samples)} {sample['case_id']}: " + ', '.join(f'{m}={row[m]}' for m in METRICS))
        if delay and index < len(samples):
            time.sleep(delay)  # respeta el límite de solicitudes por minuto del plan gratuito
    return rows


def summarize(rows: list[dict]) -> dict:
    def mean(values):
        values = [v for v in values if v is not None]
        return round(statistics.mean(values), 4) if values else None

    by_stage = {}
    for stage in dict.fromkeys(r['stage'] for r in rows):
        group = [r for r in rows if r['stage'] == stage]
        by_stage[stage] = {m: mean(r[m] for r in group) for m in METRICS} | {'samples': len(group)}
    return {
        'samples': len(rows),
        'traceability_I22': f"{sum(r['cites_material'] for r in rows)}/{len(rows)}",
        'means': {m: mean(r[m] for r in rows) for m in METRICS},
        'by_stage': by_stage,
    }


def write_outputs(rows: list[dict], summary: dict, out_dir: Path, model: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / 'scores.csv').open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=['case_id', 'stage', 'resource_type', 'cites_material', *METRICS])
        writer.writeheader()
        writer.writerows(rows)
    (out_dir / 'summary.json').write_text(json.dumps(summary | {'judge': model}, ensure_ascii=False, indent=2), encoding='utf-8')
    fmt = lambda v: '—' if v is None else f'{v:.2f}'
    lines = [
        '# Evaluación RAG con Ragas', '',
        f"Juez: {model} · Muestras: {summary['samples']} · Trazabilidad (I22): {summary['traceability_I22']} recursos citan el material", '',
        '| Métrica | Promedio |', '|---|---|',
        *[f'| {m} | {fmt(v)} |' for m, v in summary['means'].items()], '',
        '| Etapa | Muestras | ' + ' | '.join(METRICS) + ' |', '|---|---|' + '---|' * len(METRICS),
        *[f"| {s} | {v['samples']} | " + ' | '.join(fmt(v[m]) for m in METRICS) + ' |' for s, v in summary['by_stage'].items()],
    ]
    (out_dir / 'summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description='Califica las muestras RAG con Ragas y Gemini como juez.')
    parser.add_argument('--samples', type=Path, default=HERE / 'results' / 'samples.jsonl')
    parser.add_argument('--out', type=Path, default=HERE / 'results')
    parser.add_argument('--model', default=os.getenv('RAGAS_JUDGE_MODEL', 'gemini-3.8-flash'))
    parser.add_argument('--embedding-model', default=os.getenv('RAGAS_EMBEDDING_MODEL', 'gemini-embedding-001'))
    parser.add_argument('--delay', type=float, default=0, help='segundos de espera entre muestras (plan gratuito: 4)')
    parser.add_argument('--check', action='store_true', help='solo valida samples.jsonl, sin llamar al juez')
    args = parser.parse_args()

    samples = load_samples(args.samples)
    print(f'{len(samples)} muestras válidas en {args.samples}')
    if args.check:
        return
    llm, embeddings = build_judge(args.model, args.embedding_model)
    rows = score_samples(samples, llm, embeddings, args.delay)
    summary = summarize(rows)
    write_outputs(rows, summary, args.out, args.model)
    print(json.dumps(summary['means'], ensure_ascii=False))
    print(f'Resultados en {args.out}/scores.csv, summary.json y summary.md')


if __name__ == '__main__':
    main()
