"""QA-17 (y ráfaga de QA-16): carga de docentes simultáneos con Locust.

Solo contra la pila local (PostgreSQL en Docker o SQLite, `LLM_PROVIDER=rules`). Nunca contra Render, Neon ni Vercel
ni con una clave de IA real. Comandos en specs/005-atributos-calidad/plan.md (QA-17).

Cada usuario virtual, al empezar (on_start), crea su cuenta con un correo único (POST /api/v1/accounts), inicia sesión
(POST /api/v1/sessions) y prepara un curso con una unidad y el material procesado (evaluation/corpus/protocols.txt):
sin material procesado, la generación responde 400. Esas peticiones aparecen en las estadísticas como «[preparación] …».
Después repite, con pesos:
- GET /api/v1/courses
- GET /api/v1/documents/search?query=…&unitId=…&topK=8
- POST /api/v1/generation-requests (con Idempotency-Key) y GET /api/v1/generation-requests/[id] hasta un estado final.
  Cada usuario espera su pedido antes de crear otro, así que nunca tiene más de 1 activo (el límite es 2). Un 429
  TOO_MANY_ACTIVE_REQUESTS es del negocio, no un error: se cuenta aparte, como «POST … [429 pedidos activos]», y se
  reintenta con la misma clave después de `Retry-After`. Cualquier otro 429 (por ejemplo, el límite por IP de QA-16)
  cuenta como fallo. «[pedido completo] creado→final» mide el pedido de punta a punta.
Las peticiones se nombran por la plantilla de la ruta, no por su id.

El límite de inicio de sesión (QA-08) va por correo e IP: con un correo por usuario no se alcanza; no se toca.
Nunca se imprimen ni se escriben el token ni la contraseña.

Variables de entorno (todas opcionales):
- LOCUST_PROFILE              steady (por defecto) | burst: sin espera entre tareas y con un usuario liviano de /health.
- LOCUST_WAIT_MIN, LOCUST_WAIT_MAX   segundos de espera entre tareas (por defecto 1 y 3; en burst, 0 y 0).
- LOCUST_WEIGHT_COURSES, LOCUST_WEIGHT_SEARCH, LOCUST_WEIGHT_GENERATION   pesos de las tareas (3, 3 y 1); 0 la quita.
- LOCUST_HEALTH_WEIGHT        peso del usuario de GET /health frente a 10 docentes (por defecto 0; en burst, 1).
- LOCUST_RESOURCE_TYPES       tipos del pedido, separados por comas (por defecto explicacion; con varios, secuencia).
- LOCUST_SEARCH_QUERY         texto de la búsqueda de evidencia (por defecto «protocolo TCP»).
- LOCUST_POLL_SECONDS         segundos entre consultas del pedido (1).
- LOCUST_REQUEST_TIMEOUT      segundos máximos de espera de un pedido hasta su estado final (120).
- LOCUST_MAX_RETRIES_429      reintentos de un POST que recibe 429 de pedidos activos (5).
- LOCUST_EMAIL_DOMAIN, LOCUST_PASSWORD   dominio de los correos de prueba y contraseña de las cuentas locales.
- LOCUST_CORPUS               archivo de material (por defecto backend/evaluation/corpus/protocols.txt).
"""

from __future__ import annotations

import time
from uuid import uuid4

import gevent
from locust import HttpUser, between, constant, task
from locust.exception import StopUser

from payloads import (  # mismo directorio: Locust lo agrega a sys.path
    FINAL_STATUSES,
    TOO_MANY_ACTIVE_REQUESTS,
    account_body,
    course_body,
    document_context,
    error_code,
    generation_body,
    load_settings,
    retry_after_seconds,
    search_params,
    session_body,
    unique_email,
)

SETTINGS = load_settings()
CORPUS_BYTES = SETTINGS.corpus.read_bytes()
REQUESTS_PATH = "/api/v1/generation-requests"


def _wait_time():
    if SETTINGS.wait_max <= 0:
        return constant(0)
    return between(SETTINGS.wait_min, SETTINGS.wait_max)


class TeacherUser(HttpUser):
    """Un docente: prepara su curso y su material y luego lista cursos, busca evidencia y genera recursos."""

    weight = 10
    wait_time = _wait_time()

    def on_start(self) -> None:
        email = unique_email(SETTINGS.email_domain)
        self._expect("[preparación] POST /api/v1/accounts", 201, "post", "/api/v1/accounts",
                     json=account_body(email, SETTINGS.password))
        session = self._expect("[preparación] POST /api/v1/sessions", 200, "post", "/api/v1/sessions",
                               json=session_body(email, SETTINGS.password))
        self.auth = {"Authorization": f"Bearer {session['token']}"}  # solo en memoria
        course = self._expect("[preparación] POST /api/v1/courses", 201, "post", "/api/v1/courses",
                              json=course_body(), headers=self.auth)
        self.unit = course["units"][0]
        document = self._expect(
            "[preparación] POST /api/v1/documents", 201, "post", "/api/v1/documents", headers=self.auth,
            files={"file": (SETTINGS.corpus.name, CORPUS_BYTES, "text/plain")},
            data={"context": document_context(self.unit)},
        )
        processed = self._expect("[preparación] POST /api/v1/documents/[id]/process", 200, "post",
                                 f"/api/v1/documents/{document['id']}/process", headers=self.auth)
        if processed.get("status") != "procesado":
            raise StopUser()

    def _expect(self, name: str, status: int, method: str, path: str, **kwargs) -> dict:
        """Petición de preparación: si no responde `status`, se marca como fallo (con el código HTTP y el código de
        error, nunca el cuerpo) y el usuario se detiene."""
        with self.client.request(method.upper(), path, name=name, catch_response=True, **kwargs) as response:
            if response.status_code != status:
                body = _json(response)
                response.failure(f"HTTP {response.status_code} {error_code(body) or ''}".strip())
                raise StopUser()
            return _json(response)

    def list_courses(self) -> None:
        self.client.get("/api/v1/courses", headers=self.auth, name="GET /api/v1/courses")

    def search_evidence(self) -> None:
        self.client.get("/api/v1/documents/search", headers=self.auth, name="GET /api/v1/documents/search",
                        params=search_params(SETTINGS.search_query, self.unit["id"]))

    def generate(self) -> None:
        started = time.perf_counter()
        request_id = self._create_request()
        if request_id is None:
            return
        deadline = time.monotonic() + SETTINGS.request_timeout
        while time.monotonic() < deadline:
            gevent.sleep(SETTINGS.poll_seconds)
            with self.client.get(f"{REQUESTS_PATH}/{request_id}", headers=self.auth,
                                 name=f"GET {REQUESTS_PATH}/[id]", catch_response=True) as response:
                if response.status_code != 200:
                    response.failure(f"HTTP {response.status_code}")
                    continue
                if _json(response).get("status") in FINAL_STATUSES:
                    self._report_request(started, None)
                    return
        self._report_request(started, f"el pedido no terminó en {SETTINGS.request_timeout:g} s")

    def _create_request(self) -> str | None:
        """Crea el pedido. Ante un 429 de pedidos activos espera `Retry-After` y reintenta con la misma clave."""
        key = f"locust-{uuid4().hex}"
        body = generation_body(self.unit["id"], SETTINGS.resource_types)
        for _ in range(SETTINGS.max_retries_429 + 1):
            with self.client.post(REQUESTS_PATH, json=body, headers={**self.auth, "Idempotency-Key": key},
                                  name=f"POST {REQUESTS_PATH}", catch_response=True) as response:
                payload = _json(response)
                if response.status_code in (200, 202):
                    return payload.get("id")
                if response.status_code == 429 and error_code(payload) == TOO_MANY_ACTIVE_REQUESTS:
                    response.success()  # límite de negocio: se cuenta aparte, abajo
                    self.environment.events.request.fire(
                        request_type="POST", name=f"POST {REQUESTS_PATH} [429 pedidos activos]",
                        response_time=response.elapsed.total_seconds() * 1000, response_length=0,
                        exception=None, context={},
                    )
                    gevent.sleep(retry_after_seconds(response.headers))
                    continue
                response.failure(f"HTTP {response.status_code} {error_code(payload) or ''}".strip())
                return None
        return None

    def _report_request(self, started: float, problem: str | None) -> None:
        """«[pedido completo] creado→final»: del POST al estado final, como una petición más en las estadísticas."""
        self.environment.events.request.fire(
            request_type="PEDIDO", name="[pedido completo] creado→final",
            response_time=(time.perf_counter() - started) * 1000, response_length=0,
            exception=RuntimeError(problem) if problem else None, context={},
        )


# Pesos de las tareas desde el entorno; una tarea con peso 0 no se ejecuta.
TeacherUser.tasks = [
    function
    for function, weight in (
        (TeacherUser.list_courses, SETTINGS.weight_courses),
        (TeacherUser.search_evidence, SETTINGS.weight_search),
        (TeacherUser.generate, SETTINGS.weight_generation),
    )
    for _ in range(max(0, weight))
] or [TeacherUser.list_courses]


class HealthUser(HttpUser):
    """Perfil burst (QA-16): consulta GET /health sin esperas, para medir la disponibilidad durante la ráfaga."""

    abstract = SETTINGS.health_weight <= 0
    weight = max(SETTINGS.health_weight, 1)
    wait_time = constant(0) if SETTINGS.profile == "burst" else between(1, 3)

    @task
    def health(self) -> None:
        self.client.get("/health", name="GET /health")


def _json(response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
