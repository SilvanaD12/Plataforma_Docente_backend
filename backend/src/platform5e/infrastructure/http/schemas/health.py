"""Esquema de la comprobación de salud."""

from __future__ import annotations

from typing import Literal

from platform5e.infrastructure.http.schemas.common import ApiResponse


class HealthResponse(ApiResponse):
    status: Literal["ok"]
