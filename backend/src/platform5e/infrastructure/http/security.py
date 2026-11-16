"""
Controles de seguridad HTTP (QA-08):
- Límite de intentos fallidos de inicio de sesión por (correo, IP) en 15 minutos con reserva atómica por intento.
- Resolución segura de IP cliente validando proxies de confianza.
- Cabeceras de seguridad globales en todas las respuestas HTTP.
"""

from __future__ import annotations

import ipaddress
import math
import os
import threading
import time
from collections import deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

TrustedProxies = tuple[list[ipaddress.IPv4Network | ipaddress.IPv6Network], set[str]]


class LoginRateLimiter:
    """Limita intentos fallidos de inicio de sesión por (correo normalizado, IP)."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 15 * 60) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._failures: dict[tuple[str, str], deque[tuple[float, object]]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: tuple[str, str], now: float) -> deque[tuple[float, object]]:
        entries = self._failures.get(key)
        if entries is None:
            entries = deque()
            self._failures[key] = entries
        cutoff = now - self._window_seconds
        while entries and entries[0][0] <= cutoff:
            entries.popleft()
        return entries

    def reserve_attempt(
        self, email: str, client_ip: str, now: float | None = None
    ) -> tuple[int, object | None]:
        """Reserva atómicamente un intento antes de verificar credenciales.

        Retorna (0, token) si el intento fue reservado dentro del cupo permitido,
        o (retry_after > 0, None) si ya se alcanzó el límite.
        """
        current = time.monotonic() if now is None else now
        key = (email.strip().lower(), client_ip.strip() or "unknown")
        with self._lock:
            entries = self._prune(key, current)
            if len(entries) >= self._max_attempts:
                remaining = (entries[0][0] + self._window_seconds) - current
                return max(1, math.ceil(remaining)), None
            token = object()
            entries.append((current, token))
            return 0, token

    def retry_after_seconds(self, email: str, client_ip: str, now: float | None = None) -> int:
        """Retorna > 0 con los segundos restantes si la pareja (email, ip) ya alcanzó el límite."""
        current = time.monotonic() if now is None else now
        key = (email.strip().lower(), client_ip.strip() or "unknown")
        with self._lock:
            entries = self._prune(key, current)
            if len(entries) < self._max_attempts:
                if not entries:
                    self._failures.pop(key, None)
                return 0
            remaining = (entries[0][0] + self._window_seconds) - current
            return max(1, math.ceil(remaining))

    def record_failure(self, email: str, client_ip: str, now: float | None = None) -> int:
        """Alias compatible para registrar un intento fallido."""
        retry_after, _ = self.reserve_attempt(email, client_ip, now=now)
        return retry_after

    def release_attempt(self, email: str, client_ip: str, token: object | None) -> None:
        """Libera únicamente la reserva asociada al token de un inicio de sesión exitoso."""
        if token is None:
            return
        key = (email.strip().lower(), client_ip.strip() or "unknown")
        with self._lock:
            entries = self._failures.get(key)
            if not entries:
                return
            remaining_entries = deque(item for item in entries if item[1] is not token)
            if remaining_entries:
                self._failures[key] = remaining_entries
            else:
                self._failures.pop(key, None)

    def reset(self, email: str, client_ip: str, token: object | None = None) -> None:
        """Libera la reserva del intento exitoso conservando las demás reservas activas."""
        if token is not None:
            self.release_attempt(email, client_ip, token)
            return
        key = (email.strip().lower(), client_ip.strip() or "unknown")
        with self._lock:
            self._failures.pop(key, None)


def parse_trusted_proxies(raw: str | None = None) -> TrustedProxies:
    """Parsea IPs/CIDRs y hosts literales de proxies de confianza separados por comas."""
    source = os.getenv("TRUSTED_PROXIES", "") if raw is None else raw
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    literal_hosts: set[str] = set()
    for item in source.split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            networks.append(ipaddress.ip_network(candidate, strict=False))
        except ValueError:
            literal_hosts.add(candidate.lower())
    return networks, literal_hosts


def _is_trusted_proxy(peer_text: str, trusted: TrustedProxies) -> bool:
    networks, literal_hosts = trusted
    if not networks and not literal_hosts:
        return False
    normalized = peer_text.strip().lower()
    if normalized in literal_hosts:
        return True
    try:
        addr = ipaddress.ip_address(peer_text.strip())
    except ValueError:
        return False
    return any(addr in net for net in networks)


def extract_client_ip(
    request: Request,
    trusted_proxies: TrustedProxies | None = None,
) -> str:
    """Obtiene la IP real del cliente confiando en X-Forwarded-For solo desde proxies autorizados."""
    peer_ip = request.client.host.strip() if (request.client and request.client.host) else ""
    if not peer_ip:
        return "unknown"

    trusted = parse_trusted_proxies() if trusted_proxies is None else trusted_proxies
    if not _is_trusted_proxy(peer_ip, trusted):
        return peer_ip

    forwarded = request.headers.get("x-forwarded-for", "").strip()
    if not forwarded:
        return peer_ip

    chain = [part.strip() for part in forwarded.split(",") if part.strip()]
    for hop_ip in reversed(chain):
        try:
            ipaddress.ip_address(hop_ip)
        except ValueError:
            return peer_ip
        if not _is_trusted_proxy(hop_ip, trusted):
            return hop_ip

    return chain[0] if chain else peer_ip


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Agrega cabeceras HTTP de endurecimiento de seguridad a todas las respuestas."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response