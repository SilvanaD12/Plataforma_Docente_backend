"""
Controles de seguridad HTTP (QA-08):
- Límite de intentos fallidos de inicio de sesión por (correo, IP) en 15 minutos.
- Cabeceras de seguridad globales en todas las respuestas HTTP.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


class LoginRateLimiter:
    """Limita intentos fallidos de inicio de sesión por (correo normalizado, IP)."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 15 * 60) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._failures: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: tuple[str, str], now: float) -> deque[float]:
        timestamps = self._failures.get(key)
        if timestamps is None:
            timestamps = deque()
            self._failures[key] = timestamps
        cutoff = now - self._window_seconds
        while timestamps and timestamps[0] <= cutoff:
            timestamps.popleft()
        return timestamps

    def retry_after_seconds(self, email: str, client_ip: str, now: float | None = None) -> int:
        """Retorna > 0 con los segundos restantes si la pareja (email, ip) ya alcanzó el límite."""
        current = time.monotonic() if now is None else now
        key = (email.strip().lower(), client_ip.strip() or "unknown")
        with self._lock:
            timestamps = self._prune(key, current)
            if len(timestamps) < self._max_attempts:
                if not timestamps:
                    self._failures.pop(key, None)
                return 0
            remaining = (timestamps[0] + self._window_seconds) - current
            return max(1, math.ceil(remaining))

    def record_failure(self, email: str, client_ip: str, now: float | None = None) -> int:
        """Registra un intento fallido. Retorna Retry-After (> 0) si se superó el máximo permitido."""
        current = time.monotonic() if now is None else now
        key = (email.strip().lower(), client_ip.strip() or "unknown")
        with self._lock:
            timestamps = self._prune(key, current)
            if len(timestamps) >= self._max_attempts:
                remaining = (timestamps[0] + self._window_seconds) - current
                return max(1, math.ceil(remaining))
            timestamps.append(current)
            return 0

    def reset(self, email: str, client_ip: str) -> None:
        """Limpia el historial de fallos tras un inicio de sesión exitoso."""
        key = (email.strip().lower(), client_ip.strip() or "unknown")
        with self._lock:
            self._failures.pop(key, None)


def extract_client_ip(request: Request) -> str:
    """Obtiene la IP del cliente considerando proxy inverso (X-Forwarded-For)."""
    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if forwarded:
        first_ip = forwarded.split(",")[0].strip()
        if first_ip:
            return first_ip
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Agrega cabeceras HTTP de endurecimiento de seguridad a todas las respuestas."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response