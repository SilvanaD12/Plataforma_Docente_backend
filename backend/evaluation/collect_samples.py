"""Pide una generación por caso de cases.json y guarda las muestras para Ragas.

Uso (desde backend/):
    export EVAL_EMAIL=... EVAL_PASSWORD=...
    python evaluation/collect_samples.py --api http://127.0.0.1:8000

Crea (o reutiliza) la cuenta de evaluación, un curso con una unidad, sube y procesa el corpus y, por cada caso, crea un
pedido de generación individual (POST /api/v1/generation-requests, con la cabecera Idempotency-Key). Después consulta
GET /api/v1/generation-requests/{id} cada --poll segundos hasta que el pedido termine o pase --timeout.

Guarda una línea por recurso en evaluation/results/samples.jsonl con la pregunta (user_input), el contexto
(retrieved_contexts) y la respuesta (response), los campos que lee run_ragas.py. El contexto es todo lo que el pedido
recuperó del material y entregó al modelo, en el orden de la recuperación (GET /api/v1/generation-requests/{id}/evidence,
TA-010, research R12); los fragmentos que cita cada recurso quedan aparte en cited_contexts. Cada muestra registra
además retrieved_count, limit, retrieval_mode y la consulta con que se recuperó (retrieval_query: título de la unidad,
resultados de aprendizaje, indicaciones y competencia). Hasta el PR #16 (commit 6ed774a) el contexto era solo lo citado.

Campos de cada caso de cases.json: id, instructions y resourceType (o mode "sequence" con resourceTypes), y de forma
opcional stage, quantity, difficulty, optionCount, topK, competency, unitTitle y outcomeText (una unidad propia para el
caso, con ese título y ese resultado de aprendizaje), reference (respuesta esperada, para context_recall) y
expectedFragments (pasajes del material que deberían recuperarse). Los casos sin campos nuevos se piden igual que antes.
El pedido no envía `modalities`, así que la modalidad (HU-024) no filtra los tipos.

Si un pedido falla, vence el tiempo o un paso se rechaza sin recursos, el motivo se registra en
evaluation/results/failures.jsonl (no en samples.jsonl, porque run_ragas.py exige contexto en cada muestra) y se sigue
con el caso siguiente. Si el servidor rechaza el pedido o su consulta de forma definitiva (4xx salvo 429), se deja de
consultar y se registran su código HTTP (`status`), su `code` y su `message`; los 429, los 5xx y los fallos de red se
reintentan hasta --timeout, al crear el pedido y al consultarlo. Ninguna espera interna (Retry-After, reintentos ni
--poll) ni el timeout de cada llamada HTTP pasan del tiempo que queda, y no se inicia ninguna llamada con el tiempo
agotado: se registra TIMEOUT. Los rechazos de un pedido que sí entregó recursos van en el campo `problems` de cada muestra.

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
CASE_MODES = ('individual', 'sequence')
DEFAULT_UNIT_TITLE = 'Protocolos de transporte'
DEFAULT_OUTCOME = 'Distingue TCP, UDP e IP según su función'
COURSE_HASH_LENGTH = 12
EVIDENCE_TIMEOUT = 60.0
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


class BudgetExhausted(Exception):
    """Se agotó el tiempo del caso antes de hacer la llamada: no se hace."""


def call_timeout(client: httpx.Client, deadline: float | None) -> httpx.Timeout:
    """El timeout normal del cliente, recortado a lo que queda hasta `deadline`."""
    normal = client.timeout
    if deadline is None:
        return normal
    left = remaining(deadline)
    limit = lambda value: left if value is None else min(value, left)  # noqa: E731
    return httpx.Timeout(connect=limit(normal.connect), read=limit(normal.read), write=limit(normal.write),
                         pool=limit(normal.pool))


def request(
    client: httpx.Client, method: str, path: str, retries: int = 3, deadline: float | None = None, **kwargs
) -> httpx.Response:
    """Reintenta errores 502/503/504 y de conexión (Render tarda en despertar).

    Con `deadline`: antes de cada llamada comprueba el tiempo restante y, si se agotó, lanza BudgetExhausted sin
    llamar; el timeout de cada llamada se recorta a lo que queda (si lo supera, httpx lanza un TimeoutException, que es
    un error de red), y ninguna espera entre reintentos pasa de lo que queda. Al agotarse, devuelve la última respuesta
    (o relanza el error de red) sin esperar más."""
    for attempt in range(retries + 1):
        if deadline is not None and remaining(deadline) <= 0:
            raise BudgetExhausted()
        try:
            response = client.request(method, path, timeout=call_timeout(client, deadline), **kwargs)
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


def ensure_unit(client: httpx.Client, headers: dict, code: str = COURSE_CODE, title: str = DEFAULT_UNIT_TITLE,
                outcome: str = DEFAULT_OUTCOME) -> dict:
    """La unidad del curso de evaluación `code`; si el curso no existe, lo crea con una unidad y un resultado."""
    courses = request(client, 'GET', '/api/v1/courses', headers=headers).json()
    course = next((c for c in courses if c.get('code') == code), None)
    if course is None:
        name = 'Redes de computadoras (evaluación RAG)' if code == COURSE_CODE else f'Evaluación RAG: {title}'[:150]
        response = request(client, 'POST', '/api/v1/courses', headers=headers, json={
            'code': code, 'name': name, 'term': '2026-II',
            'summary': 'Curso de redes de computadoras: protocolos de transporte y de red.',
            'learningGoal': 'Explica cómo se comunican los equipos en una red.',
            'units': [{'title': title, 'outcomes': [{'text': outcome}]}],
        })
        if response.status_code != 201:
            fail(f'no se pudo crear el curso ({response.status_code}): {response.text}')
        course = response.json()
    return course['units'][0]


def unit_spec(case: dict) -> tuple[str, str] | None:
    """(título, resultado) de la unidad propia del caso, o None si usa la unidad de evaluación de siempre. Si el caso
    trae solo uno de los dos, el otro es el de la unidad de evaluación."""
    if 'unitTitle' not in case and 'outcomeText' not in case:
        return None
    return case.get('unitTitle') or DEFAULT_UNIT_TITLE, case.get('outcomeText') or DEFAULT_OUTCOME


def course_code(title: str, outcome: str) -> str:
    """Código del curso de una unidad propia: `EVAL-RAG-` y un hash corto del título y el resultado (máximo 30)."""
    digest = hashlib.sha256(f'{title}\n{outcome}'.encode('utf-8')).hexdigest()[:COURSE_HASH_LENGTH]
    return f'{COURSE_CODE}-{digest}'


def ensure_case_unit(client: httpx.Client, headers: dict, case: dict, cache: dict) -> dict:
    """La unidad del caso: la de evaluación de siempre o, con unitTitle u outcomeText, una propia en su propio curso
    (se crea una vez y se reutiliza). `cache` evita volver a consultar los cursos en la misma corrida."""
    spec = unit_spec(case)
    if spec not in cache:
        cache[spec] = ensure_unit(client, headers) if spec is None else ensure_unit(
            client, headers, course_code(*spec), *spec
        )
    return cache[spec]


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
        except BudgetExhausted:
            return None
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
        except BudgetExhausted:
            return None, None
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


def case_mode(case: dict) -> str:
    mode = case.get('mode', 'individual')
    if mode not in CASE_MODES:
        raise ValueError(f"el caso «{case.get('id')}» tiene un mode no válido ({mode}): usa individual o sequence")
    return mode


def case_types(case: dict) -> list[str]:
    """Tipos del pedido: resourceType en un caso individual, resourceTypes en una secuencia."""
    if case_mode(case) == 'sequence':
        types = case.get('resourceTypes')
        if not isinstance(types, list) or not types:
            raise ValueError(f"el caso «{case.get('id')}» es una secuencia sin resourceTypes")
        return list(types)
    if not case.get('resourceType'):
        raise ValueError(f"el caso «{case.get('id')}» no tiene resourceType")
    return [case['resourceType']]


def case_label(case: dict) -> str:
    if case.get('mode') == 'sequence':
        return f"{case.get('id')} · secuencia · {', '.join(case.get('resourceTypes') or [])}"
    return f"{case.get('id')} · {case.get('stage', '')} · {case.get('resourceType', '')}"


def request_body(case: dict, unit: dict) -> dict:
    """Cuerpo del pedido del caso. Sin `modalities`: la modalidad (HU-024) no filtra los tipos."""
    return {
        'mode': case_mode(case), 'unitId': unit['id'], 'resourceTypes': case_types(case),
        'quantity': case.get('quantity', 1), 'outcomeId': None, 'difficulty': case.get('difficulty', 'intermedia'),
        'optionCount': case.get('optionCount', 4), 'topK': case.get('topK', 8), 'evidenceThreshold': 0.6,
        'instructions': case['instructions'], 'audience': '', 'competency': case.get('competency', ''),
    }


def retrieval_query(unit: dict, case: dict) -> dict:
    """La consulta con que el pedido recupera el material (`evidence_query_text` del backend): título de la unidad,
    sus resultados de aprendizaje (el pedido no elige uno), las indicaciones y la competencia."""
    outcomes = [o['text'] for o in unit.get('outcomes') or [] if o.get('text')]
    parts = {'unitTitle': unit.get('title', ''), 'outcomes': outcomes, 'instructions': case['instructions'],
             'competency': case.get('competency', '')}
    parts['text'] = ' '.join(filter(None, [parts['unitTitle'], *outcomes, parts['instructions'], parts['competency']]))
    return parts


def fetch_evidence(client: httpx.Client, headers: dict, request_id: str,
                   deadline: float | None) -> tuple[dict | None, dict | None]:
    """Todo lo que recuperó el pedido (GET …/evidence). Devuelve (evidencia, None) o (None, problema)."""
    problem = {'kind': 'evidence', 'requestId': request_id}
    try:
        response = request(client, 'GET', f'{REQUESTS_PATH}/{request_id}/evidence', deadline=deadline,
                           headers=headers)
    except BudgetExhausted:
        return None, {**problem, 'code': 'TIMEOUT', 'message': 'no hubo tiempo para leer la evidencia del pedido'}
    except httpx.TransportError as error:
        return None, {**problem, 'code': 'NETWORK_ERROR',
                      'message': f'no se pudo leer la evidencia del pedido: {error}'}
    if response.status_code != 200:
        return None, {'kind': 'evidence', **server_problem(response), 'requestId': request_id}
    return response.json(), None


def build_samples(case: dict, status: dict, stored: dict, evidence: dict, unit: dict, elapsed: float,
                  problems: list[dict]) -> list[dict]:
    """Una muestra por recurso entregado. El contexto es todo lo recuperado, en orden; lo citado queda aparte."""
    contexts = [fragment['text'] for fragment in evidence.get('fragments') or [] if fragment.get('text')]
    query = retrieval_query(unit, case)
    sequence = case_mode(case) == 'sequence'
    samples = []
    for step in status.get('steps') or []:
        generator = step.get('generator') or {}
        # En un caso individual la etapa y el tipo son los del caso, como antes; en una secuencia, los de cada paso.
        stage = step.get('stage') if sequence else case.get('stage')
        resource_type = step.get('resourceType') if sequence else case['resourceType']
        for resource_id in step.get('resourceIds') or []:
            resource = stored.get(resource_id)
            if resource is None:
                problems.append({'kind': 'missing', 'message': f'el recurso {resource_id} ya no está en revisión'})
                continue
            sample = {
                'case_id': case['id'], 'stage': stage, 'resource_type': resource_type,
                'user_input': f"{TYPE_NAMES.get(resource_type, resource_type)}: {case['instructions']}",
                'retrieved_contexts': contexts,
                'response': resource_text(resource),
                'cited_contexts': [item['text'] for item in resource.get('evidence') or [] if item.get('text')],
                'retrieved_count': len(contexts),
                'limit': evidence.get('limit'),
                'retrieval_mode': evidence.get('retrievalMode') or status.get('retrievalMode'),
                'retrieval_query': query,
                'cites_material': cites_material(resource),
                'generator': generator.get('description'),
                'uses_ai': bool(generator.get('usesAi')),
                'fallback': bool(generator.get('fallback')),
                'fallback_reason': generator.get('fallbackReason'),
                'seconds': elapsed,
                'request_id': status['id'],
                'request_status': status['status'],
                'problems': problems,
            }
            if 'reference' in case:
                sample['reference'] = case['reference']
            if 'expectedFragments' in case:
                sample['expected_fragments'] = case['expectedFragments']
            samples.append(sample)
    return samples


def generator_label(sample: dict) -> str:
    """El generador de la muestra y, si redactó el respaldo por reglas, por qué no se usó la IA."""
    reason = sample.get('fallback_reason')
    return f"{sample['generator']} (motivo: {reason})" if reason else str(sample['generator'])


def run_case(client: httpx.Client, headers: dict, unit: dict, case: dict, args: argparse.Namespace,
             attempt: int) -> tuple[dict | None, dict | None, float]:
    """Crea y espera el pedido de un caso. Devuelve (estado final, falla, segundos)."""
    body = request_body(case, unit)
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
        units: dict = {}
        prepared: set[str] = set()
        for number, case in enumerate(cases):
            if number and args.delay:
                time.sleep(args.delay)  # respeta el límite de solicitudes por minuto del proveedor de IA
            label = case_label(case)
            unit = ensure_case_unit(client, headers, case, units)
            if unit['id'] not in prepared:  # el corpus y los temas, una vez por unidad
                ensure_material(client, headers, unit, args.corpus)
                ensure_topics(client, headers, unit, args.topics)
                prepared.add(unit['id'])
            stage, types = case.get('stage'), ', '.join(case.get('resourceTypes') or [case.get('resourceType', '')])
            try:
                request_body(case, unit)
            except ValueError as invalid:
                print(f"{label}: sin muestra (INVALID_CASE) {invalid}")
                failures.append({'case_id': case.get('id'), 'stage': stage, 'resource_type': types, 'status': None,
                                 'problems': [{'code': 'INVALID_CASE', 'message': str(invalid)}], 'seconds': 0})
                continue
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

            if failure is not None:
                print(f"{label}: sin muestra ({failure['code']}) {failure['message']}")
                failures.append({'case_id': case['id'], 'stage': stage, 'resource_type': types,
                                 'status': None, 'problems': [failure], 'seconds': elapsed})
                continue

            problems = step_problems(status)
            resource_ids = [rid for step in steps for rid in step.get('resourceIds') or []]
            stored, evidence = {}, {}
            if resource_ids:
                stored = {r['id']: r for r in request(client, 'GET', f"/api/v1/units/{unit['id']}/resources",
                                                      headers=headers).json()}
                # TA-010: el contexto es todo lo que recuperó el pedido, no solo lo que citan los recursos.
                evidence, evidence_problem = fetch_evidence(client, headers, status['id'],
                                                            time.monotonic() + min(args.timeout, EVIDENCE_TIMEOUT))
                if evidence_problem is not None:
                    problems.append(evidence_problem)
                    evidence = {}
            case_samples = build_samples(case, status, stored, evidence, unit, elapsed, problems)
            without_context = [s for s in case_samples if not s['retrieved_contexts']]
            if without_context:
                problems.append({'kind': 'context', 'message': f'{len(without_context)} recurso(s) sin evidencia recuperada'})
            samples.extend(s for s in case_samples if s['retrieved_contexts'])
            if not any(s['retrieved_contexts'] for s in case_samples):
                failures.append({'case_id': case['id'], 'stage': stage, 'resource_type': types,
                                 'status': status['status'], 'request_id': status['id'], 'problems': problems,
                                 'seconds': elapsed})
                reason = '; '.join(p.get('message') or p.get('code', '') for p in problems) or 'sin recursos'
                print(f"{label}: sin muestra ({status['status']}) {reason[:200]}")
                continue
            first = case_samples[0]
            print(f"{label}: {len(case_samples)} recurso(s), {first['retrieved_count']} fragmento(s) recuperado(s) "
                  f"(límite {first['limit']}), {elapsed} s · {generator_label(first)} · "
                  f"búsqueda {first['retrieval_mode'] or 'desconocida'}")

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
