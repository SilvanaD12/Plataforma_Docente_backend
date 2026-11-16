"""
QA-06: tiempo límite de cada llamada a Gemini, medido de punta a punta (reloj de pared).

El timeout de httpx se aplica a cada operación (conectar, cada lectura), no a la llamada completa: un proveedor que
envía la respuesta de a poco nunca lo dispara y la llamada puede quedar colgada minutos. Aquí la llamada corre en un
hilo propio que lee la respuesta por partes; quien llama espera solo hasta el límite y, si se cumple, recibe
`CallDeadlineExceeded` y sigue con su respaldo. El hilo de fondo se detiene en la siguiente parte que llega (o al vencer
el timeout de lectura de httpx, que nunca supera el límite).
"""

from __future__ import annotations

import threading
import time
from typing import Any

import httpx

MAX_CALL_DEADLINE_SECONDS: float = 60.0
DEFAULT_CALL_DEADLINE_SECONDS: float = MAX_CALL_DEADLINE_SECONDS


class CallDeadlineExceeded(TimeoutError):
    """La llamada al proveedor no terminó antes de su tiempo límite."""


def seconds_label(seconds: float) -> str:
    """60 → «60», 0.3 → «0,3»: para los motivos que ve el docente."""
    return f"{seconds:g}".replace(".", ",")


def _capped_timeout(timeout: httpx.Timeout, remaining: float) -> httpx.Timeout:
    limit = lambda value: remaining if value is None else min(value, remaining)  # noqa: E731
    return httpx.Timeout(connect=limit(timeout.connect), read=limit(timeout.read), write=limit(timeout.write),
                         pool=limit(timeout.pool))


def post_with_deadline(
    client: httpx.Client, url: str, deadline: float, headers: dict[str, str], payload: dict[str, Any]
) -> httpx.Response:
    """POST con un tiempo límite total (`deadline`, en `time.monotonic()`). Devuelve la respuesta ya leída; los errores
    de red de httpx se relanzan tal cual. Lanza `CallDeadlineExceeded` si no termina a tiempo."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise CallDeadlineExceeded()
    cancelled = threading.Event()
    outcome: dict[str, Any] = {}

    def call() -> None:
        try:
            with client.stream("POST", url, headers=headers, json=payload,
                               timeout=_capped_timeout(client.timeout, remaining)) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    if cancelled.is_set() or time.monotonic() > deadline:
                        return  # quien llamó ya siguió con su respaldo: se deja de leer
                    body.extend(chunk)
                outcome["response"] = httpx.Response(
                    response.status_code,
                    headers={"content-type": response.headers.get("content-type", "application/json")},
                    content=bytes(body),
                    request=response.request,
                )
        except Exception as error:  # se relanza en el hilo de quien llamó
            outcome["error"] = error

    worker = threading.Thread(target=call, name="llamada-proveedor-ia", daemon=True)
    worker.start()
    worker.join(max(0.0, deadline - time.monotonic()))
    if worker.is_alive() or not outcome:
        cancelled.set()
        raise CallDeadlineExceeded()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["response"]
