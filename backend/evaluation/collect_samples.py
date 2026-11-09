"""Pide una generación por caso de cases.json y guarda las muestras para Ragas.

Uso (desde backend/):
    export EVAL_EMAIL=... EVAL_PASSWORD=...
    python evaluation/collect_samples.py --api http://127.0.0.1:8000

Crea (o reutiliza) la cuenta de evaluación, un curso con una unidad, sube y procesa el corpus y, por cada caso, crea un
pedido de generación individual (POST /api/v1/generation-requests, con la cabecera Idempotency-Key). Después consulta
GET /api/v1/generation-requests/{id} cada --poll segundos hasta que el pedido termine o pase --timeout.

Guarda una línea por recurso en evaluation/results/samples.jsonl con la pregunta (user_input), el contexto
(retrieved_contexts) y la respuesta (response), los campos que lee run_ragas.py. La API de pedidos no devuelve los
fragmentos recuperados: el contexto es la copia histórica de la evidencia que se guardó con cada recurso (campo
`evidence` de GET /api/v1/units/{unitId}/resources), es decir, los fragmentos que el recurso cita.

Si un pedido falla, vence el tiempo o un paso se rechaza sin recursos, el motivo se registra en
evaluation/results/failures.jsonl (no en samples.jsonl, porque run_ragas.py exige contexto en cada muestra) y se sigue
con el caso siguiente. Si el servidor rechaza el pedido o su consulta de forma definitiva (4xx salvo 429), se deja de
consultar y se registran su código HTTP (`status`), su `code` y su `message`; los 429, los 5xx y los fallos de red se
reintentan hasta --timeout, al crear el pedido y al consultarlo. Ninguna espera interna (Retry-After, reintentos ni
--poll) pasa del tiempo que queda: al agotarse se registra TIMEOUT. Los rechazos de un pedido que sí entregó recursos van en el campo `problems` de cada muestra.

La clave de cada pedido sale de una marca de la corrida (--run-id), del id del caso y del intento, así que repetir la
corrida con la misma marca no duplica pedidos. El caso y el intento siempre quedan completos: si la clave pasa de 128
caracteres, solo se recorta el run-id y se le agrega un hash corto del run-id completo.

Con el plan gratuito de Gemini, varias generaciones seguidas superan el límite por minuto y el backend
responde con el generador por reglas (fallback). Para que todas las muestras sean de la IA:
    python evaluation/collect_samples.py --api https://plataforma5e-api.onrender.com --delay 15

--topic agrega artículos de Wikipedia como material de la unidad (la misma búsqueda por tema de la
plataforma), para que la recuperación tenga varios fragmentos entre los que elegir.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
COURSE_CODE = 'EVAL-RAG'
REQUESTS_PATH = '/api/v1/generation-requests'
FINAL_STATUSES = {'succeeded', 'partially_succeeded', 'failed', 'interrupted'}
TYPE_NAMES = {
    'pregunta_detonante': 'Pregunta detonante', 'sondeo_diagnostico': 'Sondeo diagnóstico',
    'guia_exploracion': 'Guía de exploración', 'caso_indagacion': 'Caso con preguntas de indagación',
    'explicacion': 'Explicación citada', 'glosario': 'Glosario', 'ejercicio_aplicacion': 'Ejercicio de aplicación',
    'item_opcion_multiple': 'Ítem de opción múltiple',
}


def fail(message: str) -> None:
    print(f'Error: {message}', file=sys.stderr)
    sys.exit(1)


def remaining(deadline: float | None) -> float:
    """Segundos que quedan hasta `deadline` (infinito si no hay límite)."""
    return float('inf') if deadline is None else max(0.0, deadline - time.monotonic())


def pause(seconds: float, deadline: float | None = None) -> None:
    """Espera `seconds`, pero nunca más de lo que queda hasta `deadline`."""
    wait = min(seconds, remaining(deadline))
    if wait > 0:
        time.sleep(wait)


def request(
    client: httpx.Client, method: str, path: str, retries: int = 3, deadline: float | None = None, **kwargs
) -> httpx.Response:
    """Reintenta errores 502/503/504 y de conexión (Render tarda en despertar). Con `deadline`, ninguna espera pasa de
    lo que queda y, al agotarse, devuelve la última respuesta (o relanza el error de red) sin esperar más."""
    for attempt in range(retries + 1):
        try:
            response = client.request(method, path, **kwargs)
            if response.status_code not in (502, 503, 504) or attempt == retries or remaining(deadline) <= 0:
                return response
        except httpx.TransportError:
            if attempt == retries or remaining(deadline) <= 0:
                raise
        pause(5 * (attempt + 1), deadline)
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


MAX_KEY_LENGTH = 128
RUN_HASH_LENGTH = 12


def _key_part(value: str) -> str:
    return re.sub(r'[^A-Za-z0-9_-]', '-', value)


def idempotency_key(run_id: str, case_id: str, attempt: int) -> str:
    """Clave del pedido: `eval-{run-id}-{caso}-{intento}`, de 8 a 128 caracteres (letras, números, «-» y «_»).

    El caso y el intento siempre quedan completos. Si no cabe todo, solo se recorta el run-id y se le agrega un hash
    corto del run-id completo, para que dos run-id largos con el mismo comienzo no den la misma clave. La misma corrida
    da siempre las mismas claves.
    """
    tail = f'-{_key_part(case_id)}-{attempt}'
    run = _key_part(run_id)
    room = MAX_KEY_LENGTH - len('eval-') - len(tail)
    if len(run) > room:
        digest = hashlib.sha256(run_id.encode('utf-8')).hexdigest()[:RUN_HASH_LENGTH]
        if room < RUN_HASH_LENGTH:
            raise ValueError(f'el id del caso «{case_id}» es demasiado largo para la clave del pedido')
        keep = room - RUN_HASH_LENGTH - 1
        run = f'{run[:keep]}-{digest}' if keep > 0 else digest
    return f'eval-{run}{tail}'


def is_transient(response: httpx.Response | None) -> bool:
    """Sin respuesta (fallo de red), 429 o 5xx: puede cambiar si se vuelve a intentar."""
    return response is None or response.status_code == 429 or response.status_code >= 500


def start_request(
    client: httpx.Client, headers: dict, key: str, body: dict, deadline: float
) -> httpx.Response | None:
    """Crea el pedido. Reintenta los 429 (con Retry-After), los 5xx y los fallos de red con la misma clave hasta
    `deadline`; ninguna espera pasa de lo que queda. Devuelve None si se acaba el tiempo."""
    while True:
        try:
            response = request(client, 'POST', REQUESTS_PATH, deadline=deadline,
                               headers={**headers, 'Idempotency-Key': key}, json=body)
        except httpx.TransportError:
            response = None
        if not is_transient(response):
            return response
        if remaining(deadline) <= 0:
            return None
        wait = 5.0
        if response is not None and response.status_code == 429:
            wait = float(response.headers.get('Retry-After') or 5)
            print(f'  hay pedidos en curso; nuevo intento en {min(wait, remaining(deadline)):.0f} s')
        pause(wait, deadline)
        if remaining(deadline) <= 0:
            return None


def server_problem(response: httpx.Response) -> dict:
    """El rechazo del servidor como lo registra failures.jsonl: código HTTP, `code` y `message`."""
    try:
        error = response.json().get('error') or {}
    except (ValueError, AttributeError):
        error = {}
    return {'status': response.status_code, 'code': error.get('code') or f'HTTP_{response.status_code}',
            'message': error.get('message') or response.text[:200]}


def is_definitive_rejection(response: httpx.Response) -> bool:
    """4xx salvo 429: repetir la consulta no cambia la respuesta."""
    return 400 <= response.status_code < 500 and response.status_code != 429


def wait_until_final(
    client: httpx.Client, headers: dict, request_id: str, poll: float, deadline: float
) -> tuple[dict | None, dict | None]:
    """Consulta el pedido cada `poll` segundos hasta un estado final. Devuelve (estado, None) si terminó, o (None,
    rechazo) si el servidor lo rechaza de forma definitiva (4xx salvo 429) o se acaba el tiempo. Los 429, los 5xx y
    los fallos de red se reintentan hasta el tiempo máximo."""
    while True:
        try:
            response = request(client, 'GET', f'{REQUESTS_PATH}/{request_id}', deadline=deadline, headers=headers)
        except httpx.TransportError:
            response = None
        if response is not None:
            if response.status_code == 200 and response.json().get('status') in FINAL_STATUSES:
                return response.json(), None
            if is_definitive_rejection(response):
                return None, {**server_problem(response), 'requestId': request_id}
        if remaining(deadline) <= 0:
            return None, None
        pause(poll, deadline)
        if remaining(deadline) <= 0:
            return None, None


def step_problems(status: dict) -> list[dict]:
    """Motivos de los pasos rechazados o fallidos, y del pedido si falló."""
    problems = []
    for step in status.get('steps') or []:
        if step.get('error'):
            problems.append({'step': step.get('position'), 'kind': 'error', **step['error']})
        for rejection in step.get('rejections') or []:
            problems.append({'step': step.get('position'), 'kind': rejection.get('kind'),
                             'title': rejection.get('title'), 'message': rejection.get('reason')})
    if status.get('failure'):
        problems.append({'kind': 'request', **status['failure']})
    return problems


def run_case(client: httpx.Client, headers: dict, unit: dict, case: dict, args: argparse.Namespace,
             attempt: int) -> tuple[dict | None, dict | None, float]:
    """Crea y espera el pedido de un caso. Devuelve (estado final, falla, segundos)."""
    body = {
        'mode': 'individual', 'unitId': unit['id'], 'resourceTypes': [case['resourceType']],
        'quantity': case.get('quantity', 1), 'outcomeId': None, 'difficulty': case.get('difficulty', 'intermedia'),
        'optionCount': case.get('optionCount', 4), 'topK': case.get('topK', 8), 'evidenceThreshold': 0.6,
        'instructions': case['instructions'], 'audience': '', 'competency': '', 'modalities': ['Textual'],
    }
    key = idempotency_key(args.run_id, case['id'], attempt)
    started = time.perf_counter()
    deadline = time.monotonic() + args.timeout
    response = start_request(client, headers, key, body, deadline)
    if response is None:
        timeout = {'code': 'TIMEOUT', 'message': f'no se pudo crear el pedido en {args.timeout:g} s'}
        return None, timeout, round(time.perf_counter() - started, 2)
    if response.status_code not in (200, 202):
        return None, server_problem(response), round(time.perf_counter() - started, 2)
    status, rejected = wait_until_final(client, headers, response.json()['id'], args.poll, deadline)
    elapsed = round(time.perf_counter() - started, 2)
    if rejected is not None:
        return None, rejected, elapsed
    if status is None:
        return None, {'code': 'TIMEOUT', 'message': f'el pedido no terminó en {args.timeout:g} s',
                      'requestId': response.json()['id']}, elapsed
    return status, None, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description='Recolecta muestras de generación para la evaluación con Ragas.')
    parser.add_argument('--api', default='http://127.0.0.1:8000', help='URL base del backend (sin / al final)')
    parser.add_argument('--cases', type=Path, default=HERE / 'cases.json')
    parser.add_argument('--corpus', type=Path, default=HERE / 'corpus' / 'protocols.txt')
    parser.add_argument('--out', type=Path, default=HERE / 'results' / 'samples.jsonl')
    parser.add_argument('--failures', type=Path, default=None,
                        help='casos sin muestra y su motivo (por defecto failures.jsonl junto a --out)')
    parser.add_argument('--topic', action='append', default=[], dest='topics',
                        help='tema de Wikipedia que se agrega como material (se puede repetir)')
    parser.add_argument('--delay', type=float, default=0, help='segundos de espera entre casos (plan gratuito de Gemini: 15)')
    parser.add_argument('--retries', type=int, default=2,
                        help='reintentos de un caso que la IA no respondió y redactó el generador por reglas')
    parser.add_argument('--timeout', type=float, default=600, help='segundos máximos de espera por pedido')
    parser.add_argument('--poll', type=float, default=2, help='segundos entre consultas del estado del pedido')
    parser.add_argument('--run-id', default=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S'),
                        help='marca de la corrida para las claves de idempotencia (repetirla no duplica pedidos)')
    args = parser.parse_args()

    email, password = os.getenv('EVAL_EMAIL'), os.getenv('EVAL_PASSWORD')
    if not email or not password:
        fail('define EVAL_EMAIL y EVAL_PASSWORD (la contraseña debe tener al menos 8 caracteres)')
    cases = json.loads(args.cases.read_text(encoding='utf-8'))['cases']
    args.out.parent.mkdir(parents=True, exist_ok=True)
    failures_path = args.failures or args.out.with_name('failures.jsonl')

    samples, failures = [], []
    with httpx.Client(base_url=args.api.rstrip('/'), timeout=180) as client:
        headers = login(client, email, password)
        unit = ensure_unit(client, headers)
        ensure_material(client, headers, unit, args.corpus)
        ensure_topics(client, headers, unit, args.topics)
        for number, case in enumerate(cases):
            if number and args.delay:
                time.sleep(args.delay)  # respeta el límite de solicitudes por minuto del proveedor de IA
            for attempt in range(args.retries + 1):
                status, failure, elapsed = run_case(client, headers, unit, case, args, attempt)
                steps = (status or {}).get('steps') or []
                # fallback: la IA no respondió (límite de uso, respuesta ilegible) y redactó el generador por reglas.
                fallback = any((step.get('generator') or {}).get('fallback') for step in steps)
                if not fallback or attempt == args.retries:
                    break
                wait = max(args.delay, 30)
                print(f"{case['id']}: la IA no respondió; reintento {attempt + 1} de {args.retries} en {wait:.0f} s")
                time.sleep(wait)

            label = f"{case['id']} · {case['stage']} · {case['resourceType']}"
            if failure is not None:
                print(f"{label}: sin muestra ({failure['code']}) {failure['message']}")
                failures.append({'case_id': case['id'], 'stage': case['stage'], 'resource_type': case['resourceType'],
                                 'status': None, 'problems': [failure], 'seconds': elapsed})
                continue

            problems = step_problems(status)
            resource_ids = [rid for step in steps for rid in step.get('resourceIds') or []]
            stored = {r['id']: r for r in request(client, 'GET', f"/api/v1/units/{unit['id']}/resources",
                                                  headers=headers).json()} if resource_ids else {}
            case_samples = []
            for step in steps:
                generator = step.get('generator') or {}
                for resource_id in step.get('resourceIds') or []:
                    resource = stored.get(resource_id)
                    if resource is None:
                        problems.append({'kind': 'missing', 'message': f'el recurso {resource_id} ya no está en revisión'})
                        continue
                    # Contexto: la copia histórica de la evidencia guardada con el recurso.
                    contexts = [item['text'] for item in resource.get('evidence') or [] if item.get('text')]
                    cites = cites_material(resource)
                    case_samples.append({
                        'case_id': case['id'], 'stage': case['stage'], 'resource_type': case['resourceType'],
                        'user_input': f"{TYPE_NAMES.get(case['resourceType'], case['resourceType'])}: {case['instructions']}",
                        'retrieved_contexts': contexts,
                        'response': resource_text(resource),
                        'cited_contexts': contexts,
                        'cites_material': cites,
                        'generator': generator.get('description'),
                        'uses_ai': bool(generator.get('usesAi')),
                        'fallback': bool(generator.get('fallback')),
                        'seconds': elapsed,
                        'request_id': status['id'],
                        'request_status': status['status'],
                        'retrieval_mode': status.get('retrievalMode'),
                        'problems': problems,
                    })
            without_context = [s for s in case_samples if not s['retrieved_contexts']]
            if without_context:
                problems.append({'kind': 'context', 'message': f'{len(without_context)} recurso(s) sin evidencia guardada'})
            samples.extend(s for s in case_samples if s['retrieved_contexts'])
            if not any(s['retrieved_contexts'] for s in case_samples):
                failures.append({'case_id': case['id'], 'stage': case['stage'], 'resource_type': case['resourceType'],
                                 'status': status['status'], 'request_id': status['id'], 'problems': problems,
                                 'seconds': elapsed})
                reason = '; '.join(p.get('message') or p.get('code', '') for p in problems) or 'sin recursos'
                print(f"{label}: sin muestra ({status['status']}) {reason[:200]}")
                continue
            contexts_count = len(case_samples[0]['retrieved_contexts'])
            print(f"{label}: {len(case_samples)} recurso(s), {contexts_count} fragmento(s) de evidencia, {elapsed} s · "
                  f"{case_samples[0]['generator']} · búsqueda {status.get('retrievalMode') or 'desconocida'}")

    with args.out.open('w', encoding='utf-8') as file:
        for sample in samples:
            file.write(json.dumps(sample, ensure_ascii=False) + '\n')
    with failures_path.open('w', encoding='utf-8') as file:
        for failure in failures:
            file.write(json.dumps(failure, ensure_ascii=False) + '\n')
    citing = sum(s['cites_material'] for s in samples)
    if failures:
        print(f'{len(failures)} caso(s) sin muestra; el motivo está en {failures_path}')
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
