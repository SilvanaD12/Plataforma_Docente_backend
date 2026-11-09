"""
GEN-01 (research R3): barrido periódico de los pedidos de generación sin dueño.

El barrido de arranque solo ve lo que estaba vencido al arrancar: un pedido que otro proceso dejó en cola pocos segundos
antes quedaba en `queued` para siempre. Este barrido repite la misma regla cada `interval_seconds` mientras la API está
en marcha: interrumpe los pedidos `queued` o `running` cuyo latido, o su creación si nunca latieron, tiene más de
`stale_seconds`. Los pedidos de un ejecutor vivo no se tocan, porque ese ejecutor renueva su latido.

El `lifespan` de FastAPI lo inicia junto al ejecutor y lo detiene al apagar.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from platform5e.application.ports.outbound.generation_request_repository_port import (
    GenerationRequestRepositoryPort,
)
from platform5e.infrastructure.settings import (
    DEFAULT_GENERATION_SWEEP_INTERVAL_SECONDS,
    GENERATION_STALE_REQUEST_SECONDS,
)

logger = logging.getLogger("platform5e.generation.sweep")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StaleRequestSweeper:
    """Ejecuta `mark_interrupted(ahora - stale_seconds)` cada `interval_seconds` en un hilo aparte."""

    def __init__(
        self,
        repository: GenerationRequestRepositoryPort,
        interval_seconds: float = DEFAULT_GENERATION_SWEEP_INTERVAL_SECONDS,
        stale_seconds: float = GENERATION_STALE_REQUEST_SECONDS,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository
        self._interval_seconds = interval_seconds
        self._stale_seconds = stale_seconds
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def sweep(self) -> int:
        """Un barrido. Devuelve cuántos pedidos interrumpió."""
        changed = self._repository.mark_interrupted(self._clock() - timedelta(seconds=self._stale_seconds))
        if changed:
            logger.info("El barrido periódico interrumpió %s pedidos de generación sin dueño.", changed)
        return changed

    def start(self) -> None:
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, name="generation-sweep", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._interval_seconds + 5)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            try:
                self.sweep()
            except Exception:  # una base caída no detiene el barrido; lo intenta de nuevo en el siguiente
                logger.warning("Falló el barrido periódico de pedidos de generación.", exc_info=True)
