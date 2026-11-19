"""
Controles de seguridad HTTP (QA-08 y QA-16):
- Límite de intentos fallidos de inicio de sesión por (correo, IP) en 15 minutos con reserva atómica por intento.
- Límite de peticiones por IP en rutas costosas (QA-16) respetando TRUSTED_PROXIES.
- Límite de tamaño máximo de cuerpo (413 Payload Too Large) antes de leer el payload (QA-16).
- Cabeceras de seguridad globales en todas las respuestas HTTP.
"""

from __future__ import annotations

import ipaddress
import math
import os
import re
import threading
import time
from collections import deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

TrustedProxies = tuple[list[ipaddress.IPv4Network | ipaddress.IPv6Network], set[str]]

DEFAULT_EXPENSIVE_RATE_LIMIT_MAX_REQUESTS = 60
DEFAULT_EXPENSIVE_RATE_LIMIT_WINDOW_SECONDS = 60
DEFAULT_MAX_UPLOAD_BODY_BYTES = 25 * 1024 * 1024  # 25 MB
DEFAULT_MAX_JSON_BODY_BYTES = 1 * 1024 * 1024  # 1 MB

_EXPENSIVE_POST_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/api/v1/generation-requests/?$"),
    re.compile(r"^/api/v1/generation-requests/interpret/?$"),
    re.compile(r"^/api/v1/documents/?$"),
    re.compile(r"^/api/v1/documents/from-topic/?$"),
    re.compile(r"^/api/v1/documents/[^/]+/process/?$"),
    re.compile(r"^/api/v1/units/[^/]+/exports/?$"),
    re.compile(r"^/api/v1/units/[^/]+/resources/[^/]+/regenerations/?$"),
)

_UPLOAD_PATH_PATTERN = re.compile(r"^/api/v1/documents/?$")


def _read_positive_int_env(name: str, default: int, *, allow_zero: bool = False) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if allow_zero and value == 0:
        return 0
    return value if value > 0 else default


def is_expensive_endpoint(method: str, path: str) -> bool:
    """Indica si la petición corresponde a una de las rutas costosas sujetas a límite por IP."""
    if method.upper() != "POST":
        return False
    return any(pattern.match(path) for pattern in _EXPENSIVE_POST_PATTERNS)


def is_document_upload_endpoint(method: str, path: str) -> bool:
    """Indica si la petición corresponde a la subida multipart de documentos (límite 25 MB)."""
    return method.upper() == "POST" and bool(_UPLOAD_PATH_PATTERN.match(path))


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


class IpRateLimiter:
    """Limita la tasa de peticiones por IP cliente en una ventana deslizante (QA-16)."""

    def __init__(
        self,
        max_requests: int = DEFAULT_EXPENSIVE_RATE_LIMIT_MAX_REQUESTS,
        window_seconds: int = DEFAULT_EXPENSIVE_RATE_LIMIT_WINDOW_SECONDS,
    ) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check_and_record(self, client_ip: str, now: float | None = None) -> int:
        """Registra una petición para client_ip y retorna 0 si está dentro del límite,
        o Retry-After (> 0 en segundos) si superó el cupo.
        """
        if self._max_requests <= 0:
            return 0
        current = time.monotonic() if now is None else now
        key = client_ip.strip() or "unknown"
        cutoff = current - self._window_seconds
        with self._lock:
            entries = self._hits.get(key)
            if entries is None:
                entries = deque()
                self._hits[key] = entries
            while entries and entries[0] <= cutoff:
                entries.popleft()
            if len(entries) >= self._max_requests:
                remaining = (entries[0] + self._window_seconds) - current
                return max(1, math.ceil(remaining))
            entries.append(current)
            return 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


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


class IpRateLimitMiddleware(BaseHTTPMiddleware):
    """Aplica límite de peticiones por IP en las rutas costosas configuradas (QA-16)."""

    def __init__(
        self,
        app: ASGIApp,
        limiter: IpRateLimiter | None = None,
        trusted_proxies: TrustedProxies | None = None,
    ) -> None:
        super().__init__(app)
        max_requests = _read_positive_int_env(
            "EXPENSIVE_RATE_LIMIT_MAX_REQUESTS",
            DEFAULT_EXPENSIVE_RATE_LIMIT_MAX_REQUESTS,
            allow_zero=True,
        )
        window_seconds = _read_positive_int_env(
            "EXPENSIVE_RATE_LIMIT_WINDOW_SECONDS",
            DEFAULT_EXPENSIVE_RATE_LIMIT_WINDOW_SECONDS,
        )
        self._limiter = limiter or IpRateLimiter(
            max_requests=max_requests,
            window_seconds=window_seconds,
        )
        self._trusted_proxies = trusted_proxies

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not is_expensive_endpoint(request.method, request.url.path):
            return await call_next(request)

        client_ip = extract_client_ip(request, trusted_proxies=self._trusted_proxies)
        retry_after = self._limiter.check_and_record(client_ip)
        if retry_after > 0:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "Demasiadas solicitudes en poco tiempo. Espera unos segundos e intenta de nuevo.",
                    }
                },
            )
        return await call_next(request)


class _BodyTooLargeError(Exception):
    """Excepción interna cuando el flujo entrante supera el tamaño máximo permitido."""


class PayloadSizeLimitMiddleware:
    """Middleware ASGI puro que rechaza con 413 si Content-Length o el stream superan el límite (QA-16).

    Se implementa a nivel ASGI para validar Content-Length antes de leer el cuerpo.
    """

    def __init__(
        self,
        app: ASGIApp,
        max_upload_bytes: int | None = None,
        max_json_bytes: int | None = None,
    ) -> None:
        self.app = app
        self.max_upload_bytes = (
            _read_positive_int_env("MAX_UPLOAD_BODY_BYTES", DEFAULT_MAX_UPLOAD_BODY_BYTES)
            if max_upload_bytes is None
            else max_upload_bytes
        )
        self.max_json_bytes = (
            _read_positive_int_env("MAX_JSON_BODY_BYTES", DEFAULT_MAX_JSON_BODY_BYTES)
            if max_json_bytes is None
            else max_json_bytes
        )

    def _limit_for_request(self, method: str, path: str) -> int:
        if is_document_upload_endpoint(method, path):
            return self.max_upload_bytes
        return self.max_json_bytes

    @staticmethod
    def _build_413_response(limit_bytes: int) -> JSONResponse:
        limit_mb = limit_bytes / (1024 * 1024)
        formatted = f"{limit_mb:.0f} MB" if limit_mb >= 1 and limit_mb.is_integer() else f"{limit_bytes} bytes"
        return JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "PAYLOAD_TOO_LARGE",
                    "message": f"El tamaño de la solicitud supera el máximo permitido ({formatted}).",
                }
            },
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        if method in {"GET", "HEAD", "OPTIONS"}:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        limit = self._limit_for_request(method, path)

        headers = dict(scope.get("headers") or [])
        raw_content_length = headers.get(b"content-length")
        if raw_content_length is not None:
            try:
                content_length = int(raw_content_length.decode("latin-1").strip())
            except ValueError:
                content_length = -1
            if content_length > limit:
                response = self._build_413_response(limit)
                await response(scope, receive, send)
                return

        received_bytes = 0
        response_started = False

        async def guarded_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                received_bytes += len(chunk)
                if received_bytes > limit:
                    raise _BodyTooLargeError()
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, guarded_receive, tracked_send)
        except _BodyTooLargeError:
            if not response_started:
                response = self._build_413_response(limit)
                await response(scope, receive, send)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Agrega cabeceras HTTP de endurecimiento de seguridad a todas las respuestas."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response