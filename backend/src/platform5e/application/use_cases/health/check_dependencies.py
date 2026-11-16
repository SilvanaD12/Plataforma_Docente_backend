"""Use case: check the health of every external dependency in parallel."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from platform5e.application.ports.outbound.dependency_probe_port import DependencyProbePort, ProbeResult
from platform5e.application.services.provider_errors import public_reason, redact_secrets

PROBE_TIMEOUT_SECONDS: float = 3.0
DEFAULT_CACHE_TTL_SECONDS: float = 30.0


@dataclass(frozen=True)
class DependencyCheckResult:
    """Aggregated result of all dependency probes."""

    status: str  # "ok" | "degraded"
    checked_at: str  # ISO 8601
    checks: list[ProbeResult]
    database_down: bool = False


class CheckDependencies:
    """Runs all dependency probes in parallel and caches the result for *cache_ttl_seconds*."""

    def __init__(
        self,
        probes: Sequence[DependencyProbePort],
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        self._probes = list(probes)
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache: DependencyCheckResult | None = None
        self._cache_expires_at: float = 0.0
        self._lock = threading.Lock()

    def execute(self) -> DependencyCheckResult:
        now = time.monotonic()
        with self._lock:
            if self._cache is not None and now < self._cache_expires_at:
                return self._cache

        result = self._run_probes()

        with self._lock:
            self._cache = result
            self._cache_expires_at = time.monotonic() + self._cache_ttl_seconds

        return result

    def _run_probes(self) -> DependencyCheckResult:
        checks: list[ProbeResult] = []

        if not self._probes:
            return DependencyCheckResult(
                status="ok",
                checked_at=datetime.now(timezone.utc).isoformat(),
                checks=[],
            )

        with ThreadPoolExecutor(max_workers=len(self._probes)) as pool:
            futures = {pool.submit(probe.probe, PROBE_TIMEOUT_SECONDS): probe for probe in self._probes}
            for future in as_completed(futures):
                probe = futures[future]
                try:
                    res = future.result()
                    checks.append(
                        ProbeResult(
                            name=res.name,
                            status=res.status,
                            latency_ms=res.latency_ms,
                            detail=redact_secrets(res.detail),
                        )
                    )
                except Exception as exc:
                    checks.append(
                        ProbeResult(
                            name=probe.dependency_name,
                            status="down",
                            latency_ms=round(PROBE_TIMEOUT_SECONDS * 1000, 1),
                            detail=public_reason(exc),
                        )
                    )

        checks.sort(key=lambda c: c.name)

        database_down = any(c.name == "database" and c.status == "down" for c in checks)
        has_degraded = any(c.status in ("down", "slow") for c in checks)

        status = "degraded" if has_degraded else "ok"

        return DependencyCheckResult(
            status=status,
            checked_at=datetime.now(timezone.utc).isoformat(),
            checks=checks,
            database_down=database_down,
        )
