"""Database health probe: runs ``SELECT 1`` to verify connectivity."""

from __future__ import annotations

import time

from sqlalchemy import text
from sqlalchemy.engine import Engine

from platform5e.application.ports.outbound.dependency_probe_port import DependencyProbePort, ProbeResult
from platform5e.application.services.provider_errors import redact_secrets


class DatabaseProbeAdapter:
    """Probes the database with a trivial query."""

    dependency_name: str = "database"

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def probe(self, timeout_seconds: float) -> ProbeResult:
        start = time.monotonic()
        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            elapsed_ms = (time.monotonic() - start) * 1000
            status = "slow" if elapsed_ms > timeout_seconds * 1000 else "up"
            return ProbeResult(
                name=self.dependency_name,
                status=status,
                latency_ms=round(elapsed_ms, 1),
                detail="conexión activa" if status == "up" else "consulta tomó más de 3 s",
            )
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ProbeResult(
                name=self.dependency_name,
                status="down",
                latency_ms=round(elapsed_ms, 1),
                detail=redact_secrets(f"error de conexión: {type(exc).__name__}"),
            )
