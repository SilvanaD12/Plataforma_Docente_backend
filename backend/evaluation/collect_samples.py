"""Pide una generación por caso de cases.json y guarda las muestras para Ragas.

Uso (desde backend/):
    export EVAL_EMAIL=... EVAL_PASSWORD=...
    python evaluation/collect_samples.py --api http://127.0.0.1:8000

Crea (o reutiliza) la cuenta de evaluación, un curso con una unidad, sube y procesa el corpus
y guarda una línea por caso en evaluation/results/samples.jsonl con la pregunta, el contexto
recuperado (retrievedChunks) y la respuesta generada.

Con el plan gratuito de Gemini, varias generaciones seguidas superan el límite por minuto y el backend
responde con el generador por reglas (fallback). Para que todas las muestras sean de la IA:
    python evaluation/collect_samples.py --api https://plataforma5e-api.onrender.com --delay 15

--topic agrega artículos de Wikipedia como material de la unidad (la misma búsqueda por tema de la
plataforma), para que la recuperación tenga varios fragmentos entre los que elegir.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
COURSE_CODE = 'EVAL-RAG'
TYPE_NAMES = {
    'pregunta_detonante': 'Pregunta detonante', 'sondeo_diagnostico': 'Sondeo diagnóstico',
    'guia_exploracion': 'Guía de exploración', 'caso_indagacion': 'Caso con preguntas de indagación',
    'explicacion': 'Explicación citada', 'glosario': 'Glosario', 'ejercicio_aplicacion': 'Ejercicio de aplicación',
    'item_opcion_multiple': 'Ítem de opción múltiple',
}


def fail(message: str) -> None:
    print(f'Error: {message}', file=sys.stderr)
    sys.exit(1)


def request(client: httpx.Client, method: str, path: str, retries: int = 3, **kwargs) -> httpx.Response:
    """Reintenta errores 502/503/504 y de conexión (Render tarda en despertar)."""
    for attempt in range(retries + 1):
        try:
            response = client.request(method, path, **kwargs)
            if response.status_code not in (502, 503, 504) or attempt == retries:
                return response
        except httpx.TransportError:
            if attempt == retries:
                raise
        time.sleep(5 * (attempt + 1))
    raise RuntimeError('unreachable')


def login(client: httpx.Client, email: str, password: str) -> dict:
    created = request(client, 'POST', '/api/v1/accounts', json={'name': 'Evaluación RAG', 'email': email, 'password': password})
    if created.status_code == 201:
        return {'Authorization': f"Bearer {created.json()['token']}"}
    session = request(client, 'POST', '/api/v1/sessions', json={'email': email, 'password': password})
    if session.status_code != 200:
        fail(f'no se pudo iniciar sesión ({session.status_code}): {session.text}')
    return {'Authorization': f"Bearer {session.json()['token']}"}


def ensure_unit(client: httpx.Client, headers: dict) -> dict:
    courses = request(client, 'GET', '/api/v1/courses', headers=headers).json()
    course = next((c for c in courses if c.get('code') == COURSE_CODE), None)
    if course is None:
        response = request(client, 'POST', '/api/v1/courses', headers=headers, json={
            'code': COURSE_CODE, 'name': 'Redes de computadoras (evaluación RAG)', 'term': '2026-II',
            'summary': 'Curso de redes de computadoras: protocolos de transporte y de red.',
            'learningGoal': 'Explica cómo se comunican los equipos en una red.',
            'units': [{'title': 'Protocolos de transporte', 'outcomes': [{'text': 'Distingue TCP, UDP e IP según su función'}]}],
        })
        if response.status_code != 201:
            fail(f'no se pudo crear el curso ({response.status_code}): {response.text}')
        course = response.json()
    return course['units'][0]


def ensure_material(client: httpx.Client, headers: dict, unit: dict, corpus: Path) -> None:
    documents = request(client, 'GET', '/api/v1/documents', headers=headers).json()
    document = next((d for d in documents if d.get('unitId') == unit['id'] and d.get('fileName') == corpus.name), None)
    if document is None:
        context = {'unitId': unit['id'], 'outcomeIds': [o['id'] for o in unit.get('outcomes', [])],
                   'documentType': 'Separata o apuntes de clase', 'suggestedStage': None, 'usePermission': True}
        uploaded = request(client, 'POST', '/api/v1/documents', headers=headers,
                           files={'file': (corpus.name, corpus.read_bytes(), 'text/plain')}, data={'context': json.dumps(context)})
        if uploaded.status_code != 201:
            fail(f'no se pudo subir el corpus ({uploaded.status_code}): {uploaded.text}')
        document = uploaded.json()
    if document.get('status') != 'procesado':
        processed = request(client, 'POST', f"/api/v1/documents/{document['id']}/process", headers=headers)
        if processed.status_code != 200:
            fail(f'no se pudo procesar el corpus ({processed.status_code}): {processed.text}')


def ensure_topics(client: httpx.Client, headers: dict, unit: dict, topics: list[str]) -> None:
    """Agrega cada tema de Wikipedia como material procesado de la unidad, si todavía no está."""
    documents = request(client, 'GET', '/api/v1/documents', headers=headers).json()
    present = {((d.get('origin') or {}).get('topic') or '').casefold() for d in documents if d.get('unitId') == unit['id']}
    for topic in topics:
        if topic.casefold() in present:
            continue
        response = request(client, 'POST', '/api/v1/documents/from-topic', headers=headers,
                           json={'unitId': unit['id'], 'topic': topic, 'maxResults': 1})
        if response.status_code != 201:
            fail(f'no se pudo agregar el tema «{topic}» ({response.status_code}): {response.text[:200]}')
        print(f"Material desde el tema «{topic}»: {', '.join(d['fileName'] for d in response.json())}")
        present.add(topic.casefold())


def resource_text(resource: dict) -> str:
    """Texto completo del recurso tal como lo leería el docente (respuesta que califica Ragas)."""
    parts = [resource.get('title', ''), resource.get('body', '')]
    for letter, option in zip('ABCDEFGH', resource.get('options') or []):
        mark = ' (correcta)' if option.get('isCorrect') else ''
        parts.append(f"{letter}) {option.get('text', '')}{mark}. {option.get('feedback', '')}".strip())
    return '\n'.join(p for p in parts if p)


def cites_material(resource: dict) -> bool:
    cited = [f for c in resource.get('citations') or [] for f in c.get('fragmentIds', [])]
    cited += [f for o in resource.get('options') or [] for f in o.get('sourceFragmentIds', [])]
    return bool(cited)


def main() -> None:
    parser = argparse.ArgumentParser(description='Recolecta muestras de generación para la evaluación con Ragas.')
    parser.add_argument('--api', default='http://127.0.0.1:8000', help='URL base del backend (sin / al final)')
    parser.add_argument('--cases', type=Path, default=HERE / 'cases.json')
    parser.add_argument('--corpus', type=Path, default=HERE / 'corpus' / 'protocols.txt')
    parser.add_argument('--out', type=Path, default=HERE / 'results' / 'samples.jsonl')
    parser.add_argument('--topic', action='append', default=[], dest='topics',
                        help='tema de Wikipedia que se agrega como material (se puede repetir)')
    parser.add_argument('--delay', type=float, default=0, help='segundos de espera entre casos (plan gratuito de Gemini: 15)')
    parser.add_argument('--retries', type=int, default=2,
                        help='reintentos de un caso que la IA no respondió y redactó el generador por reglas')
    args = parser.parse_args()

    email, password = os.getenv('EVAL_EMAIL'), os.getenv('EVAL_PASSWORD')
    if not email or not password:
        fail('define EVAL_EMAIL y EVAL_PASSWORD (la contraseña debe tener al menos 8 caracteres)')
    cases = json.loads(args.cases.read_text(encoding='utf-8'))['cases']
    args.out.parent.mkdir(parents=True, exist_ok=True)

    samples, citing, warned = [], 0, False
    with httpx.Client(base_url=args.api.rstrip('/'), timeout=180) as client:
        headers = login(client, email, password)
        unit = ensure_unit(client, headers)
        ensure_material(client, headers, unit, args.corpus)
        ensure_topics(client, headers, unit, args.topics)
        for number, case in enumerate(cases):
            if number and args.delay:
                time.sleep(args.delay)  # respeta el límite de solicitudes por minuto del proveedor de IA
            body = {
                'unitId': unit['id'], 'outcomeId': None, 'stage': case['stage'],
                'resourceType': case['resourceType'], 'quantity': case.get('quantity', 1),
                'difficulty': case.get('difficulty', 'intermedia'), 'optionCount': case.get('optionCount', 4),
                'topK': case.get('topK', 8), 'evidenceThreshold': 0.6, 'instructions': case['instructions'],
                'audience': '', 'competency': '', 'modalities': ['Textual'],
            }
            for attempt in range(args.retries + 1):
                started = time.perf_counter()
                response = request(client, 'POST', '/api/v1/generations', headers=headers, json=body)
                elapsed = round(time.perf_counter() - started, 2)
                data = response.json() if response.status_code == 200 else {}
                # fallback: la IA no respondió (límite de uso, respuesta ilegible) y redactó el generador por reglas.
                if not (data.get('generator') or {}).get('fallback') or attempt == args.retries:
                    break
                wait = max(args.delay, 30)
                print(f"{case['id']}: la IA no respondió; reintento {attempt + 1} de {args.retries} en {wait:.0f} s")
                time.sleep(wait)
            if response.status_code != 200:
                print(f"{case['id']}: sin muestra ({response.status_code}) {response.text[:200]}")
                continue
            if 'retrievedChunks' not in data and not warned:
                print('Aviso: la respuesta no trae retrievedChunks; se usa solo lo citado (fragments) como contexto.')
                warned = True
            contexts = [c['text'] for c in data.get('retrievedChunks') or data.get('fragments') or []]
            for resource in data['resources']:
                cites = cites_material(resource)
                citing += cites
                samples.append({
                    'case_id': case['id'], 'stage': case['stage'], 'resource_type': case['resourceType'],
                    'user_input': f"{TYPE_NAMES.get(case['resourceType'], case['resourceType'])}: {case['instructions']}",
                    'retrieved_contexts': contexts,
                    'response': resource_text(resource),
                    'cited_contexts': [f['text'] for f in data.get('fragments', [])],
                    'cites_material': cites,
                    'generator': (data.get('generator') or {}).get('description'),
                    'uses_ai': bool((data.get('generator') or {}).get('usesAi')),
                    'fallback': bool((data.get('generator') or {}).get('fallback')),
                    'seconds': elapsed,
                })
            print(f"{case['id']} · {case['stage']} · {case['resourceType']}: {len(data['resources'])} recurso(s), "
                  f"{len(contexts)} fragmento(s) recuperado(s), {elapsed} s · {(data.get('generator') or {}).get('description')}")

    with args.out.open('w', encoding='utf-8') as file:
        for sample in samples:
            file.write(json.dumps(sample, ensure_ascii=False) + '\n')
    print(f'{len(samples)} muestras en {args.out.relative_to(Path.cwd()) if args.out.is_relative_to(Path.cwd()) else args.out} · '
          f'trazabilidad (I22): {citing}/{len(samples)} recursos citan el material')
    fallbacks = sum(s['fallback'] for s in samples)
    if not any(s['uses_ai'] or s['fallback'] for s in samples):
        print('El backend usa el generador por reglas (sin IA): sirve como ensayo, no como evaluación de la IA.')
    elif fallbacks:
        print(f'{fallbacks} muestra(s) las redactó el generador por reglas porque la IA no respondió: '
              'repite con un --delay mayor para evaluar solo a la IA.')
    else:
        print(f'Las {len(samples)} muestras las redactó la IA.')


if __name__ == '__main__':
    main()
