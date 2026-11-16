"""Schemas for the health-check routes."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from platform5e.infrastructure.http.schemas.common import ApiResponse


class HealthResponse(ApiResponse):
    status: Literal["ok"]


class DependencyCheckItem(ApiResponse):
    name: Literal["database", "gemini", "wikipedia"] = Field(
        description="Dependency identifier."
    )
    status: Literal["up", "down", "slow", "not_configured"] = Field(
        description="Current status of the dependency."
    )
    latency_ms: float = Field(description="Probe round-trip time in milliseconds.", alias="latencyMs")
    detail: str = Field(description="Human-readable explanation (generic, no secrets).")


class DependencyHealthResponse(ApiResponse):
    status: Literal["ok", "degraded"] = Field(
        description="'ok' when all dependencies are up; 'degraded' when an external one is down or slow."
    )
    checked_at: str = Field(description="ISO 8601 UTC timestamp of the check.", alias="checkedAt")
    checks: list[DependencyCheckItem] = Field(description="Per-dependency results.")
