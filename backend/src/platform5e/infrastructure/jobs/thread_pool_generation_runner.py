"""
GEN-01 (research R3): ejecuta los pedidos de generación en segundo plano con un grupo de hilos del proceso.

No usa una cola externa: el `lifespan` de FastAPI crea el ejecutor y lo cierra al apagar. Si el proceso se reinicia,
el barrido de arranque del repositorio marca como interrumpidos los pedidos que quedaron a medias.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from platform5e.application.ports.outbound.generation_job_runner_port import GenerationJobRunnerPort
from platform5e.application.ports.outbound.generation_request_repository_port import (
    GenerationRequestRepositoryPort,
)
from platform5e.domain.generation.errors import GenerationErrorCode
from platform5e.domain.generation.generation_request import Problem, RequestStatus
from platform5e.infrastructure.settings import DEFAULT_GENERATION_MAX_WORKERS

logger = logging.getLogger("platform5e.generation.runner")

UNEXPECTED_FAILURE_MESSAGE: str = (
    "La generación se detuvo por un error inesperado del servidor. Los recursos ya generados siguen en revisión; "
    "crea un pedido nuevo para intentarlo otra vez."
)


class ThreadPoolGenerationRunner(GenerationJobRunnerPort):
    """Encola `run_request(request_id)` en un `ThreadPoolExecutor`.

    Una excepción no controlada se registra en el log y deja el pedido en `failed` (si todavía no terminó), para que
    el docente no espere un pedido que ya no avanza.
    """

    def __init__(
        self,
        run_request: Callable[[str], None],
        repository: GenerationRequestRepositoryPort,
        max_workers: int = DEFAULT_GENERATION_MAX_WORKERS,
    ) -> None:
        self._run_request = run_request
        self._repository = repository
        self._max_workers = max_workers
        self._executor: ThreadPoolExecutor | None = None

    def start(self) -> None:
        """Crea el grupo de hilos. Lo llama el `lifespan` de la aplicación al arrancar."""
        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="generation")

    def submit(self, request_id: str) -> Future[None]:
        """Encola la ejecución sin bloquear. Devuelve el `Future` para las pruebas; los casos de uso no lo usan.

        Antes de `start()` o después de `shutdown()` lanza RuntimeError: el pedido queda en cola y el barrido del
        próximo arranque lo marca como interrumpido.
        """
        if self._executor is None:
            raise RuntimeError("El ejecutor de pedidos de generación no está activo.")
        return self._executor.submit(self._run_safely, request_id)

    def shutdown(self, wait: bool) -> None:
        """Deja de aceptar pedidos. Sin `wait`, cancela los que esperan en la cola; los que están en curso terminan."""
        if self._executor is not None:
            self._executor.shutdown(wait=wait, cancel_futures=not wait)

    def _run_safely(self, request_id: str) -> None:
        try:
            self._run_request(request_id)
        except Exception:
            logger.exception("El pedido de generación %s falló con un error no controlado.", request_id)
            self._mark_failed(request_id)

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
