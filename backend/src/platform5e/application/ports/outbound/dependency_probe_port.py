"""Port for probing external dependencies (database, LLM provider, open-source APIs)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProbeResult:
    """Result of a single dependency health probe."""

    name: str
    status: str  # "up" | "down" | "slow" | "not_configured"
    latency_ms: float
    detail: str


class DependencyProbePort(Protocol):
    """Probes a single external dependency and reports its status."""

    @property
    def dependency_name(self) -> str:
        """Stable identifier for this dependency (e.g. 'database', 'gemini', 'wikipedia')."""
        ...

    def probe(self, timeout_seconds: float) -> ProbeResult:
        """Run a lightweight health check.  Must NOT generate content or spend tokens."""
        ...
