"""
GEN-01 (research R3): ejecuta los pedidos de generación en segundo plano con un grupo de hilos del proceso.

No usa una cola externa: el `lifespan` de FastAPI crea el ejecutor y lo cierra al apagar. El ejecutor renueva el
latido de todos los pedidos que tiene en cola o en ejecución, así el barrido periódico (`StaleRequestSweeper`) solo
interrumpe los que no tienen dueño: los que dejó un proceso que se reinició o se detuvo.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from platform5e.application.ports.outbound.generation_job_runner_port import GenerationJobRunnerPort
from platform5e.application.ports.outbound.generation_request_repository_port import (
    GenerationRequestRepositoryPort,
)
from platform5e.domain.generation.errors import GenerationErrorCode
from platform5e.domain.generation.generation_request import Problem, RequestStatus
from platform5e.infrastructure.settings import (
    DEFAULT_GENERATION_HEARTBEAT_SECONDS,
    DEFAULT_GENERATION_MAX_WORKERS,
)

logger = logging.getLogger("platform5e.generation.runner")

UNEXPECTED_FAILURE_MESSAGE: str = (
    "La generación se detuvo por un error inesperado del servidor. Los recursos ya generados siguen en revisión; "
    "crea un pedido nuevo para intentarlo otra vez."
)


class ThreadPoolGenerationRunner(GenerationJobRunnerPort):
    """Encola `run_request(request_id)` en un `ThreadPoolExecutor`.

    Una excepción no controlada se registra en el log y deja el pedido en `failed` (si todavía no terminó), para que
    el docente no espere un pedido que ya no avanza.

    Mientras un pedido está en la cola del grupo de hilos o en ejecución, un hilo aparte renueva su latido cada
    `heartbeat_seconds` (research R3).
    """

    def __init__(
        self,
        run_request: Callable[[str], None],
        repository: GenerationRequestRepositoryPort,
        max_workers: int = DEFAULT_GENERATION_MAX_WORKERS,
        heartbeat_seconds: float = DEFAULT_GENERATION_HEARTBEAT_SECONDS,
    ) -> None:
        self._run_request = run_request
        self._repository = repository
        self._max_workers = max_workers
        self._heartbeat_seconds = heartbeat_seconds
        self._executor: ThreadPoolExecutor | None = None
        self._tracked: set[str] = set()
        self._tracked_lock = threading.Lock()
        self._stop_heartbeat = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None

    def start(self) -> None:
        """Crea el grupo de hilos y el hilo de latidos. Lo llama el `lifespan` de la aplicación al arrancar."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="generation")
            self._stop_heartbeat.clear()
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop, name="generation-runner-heartbeat", daemon=True
            )
            self._heartbeat_thread.start()

    def tracked_request_ids(self) -> frozenset[str]:
        """Pedidos que este ejecutor tiene en cola o en ejecución."""
        with self._tracked_lock:
            return frozenset(self._tracked)

    def submit(self, request_id: str) -> Future[None]:
        """Encola la ejecución sin bloquear. Devuelve el `Future` para las pruebas; los casos de uso no lo usan.

        Antes de `start()` o después de `shutdown()` lanza RuntimeError: el pedido queda en cola y el barrido del
        próximo arranque lo marca como interrumpido.
        """
        if self._executor is None:
            raise RuntimeError("El ejecutor de pedidos de generación no está activo.")
        with self._tracked_lock:
            self._tracked.add(request_id)
        self._beat(request_id)  # desde ahora el pedido tiene dueño, aunque espere en la cola
        try:
            return self._executor.submit(self._run_safely, request_id)
        except RuntimeError:
            self._untrack(request_id)
            raise

    def shutdown(self, wait: bool) -> None:
        """Deja de aceptar pedidos. Sin `wait`, cancela los que esperan en la cola; los que están en curso terminan.

        Los pedidos cancelados dejan de latir y el barrido de otro proceso, o el del próximo arranque, los interrumpe.
        """
        if self._executor is not None:
            self._executor.shutdown(wait=wait, cancel_futures=not wait)
        self._stop_heartbeat.set()
        if self._heartbeat_thread is not None:
            self._heartbeat_thread.join(timeout=self._heartbeat_seconds + 1)
        if not wait:
            with self._tracked_lock:
                self._tracked.clear()

    def _run_safely(self, request_id: str) -> None:
        try:
            self._run_request(request_id)
        except Exception:
            logger.exception("El pedido de generación %s falló con un error no controlado.", request_id)
            self._mark_failed(request_id)
        finally:
            self._untrack(request_id)

    def _untrack(self, request_id: str) -> None:
        with self._tracked_lock:
            self._tracked.discard(request_id)

    def _heartbeat_loop(self) -> None:
        while not self._stop_heartbeat.wait(self._heartbeat_seconds):
            for request_id in self.tracked_request_ids():
                self._beat(request_id)

    def _beat(self, request_id: str) -> None:
        try:
            self._repository.heartbeat(request_id)
        except Exception:  # un latido perdido no detiene el ejecutor; el siguiente lo renueva
            logger.warning("No se pudo renovar el latido del pedido de generación %s.", request_id, exc_info=True)

    def _mark_failed(self, request_id: str) -> None:
        try:
            self._repository.finish(
                request_id,
                RequestStatus.FAILED,
                Problem(GenerationErrorCode.GENERATION_FAILED, UNEXPECTED_FAILURE_MESSAGE),
            )
        except Exception:
            # Si tampoco se puede guardar, el barrido de arranque lo marcará como interrumpido.
            logger.exception("No se pudo marcar como fallido el pedido de generación %s.", request_id)
