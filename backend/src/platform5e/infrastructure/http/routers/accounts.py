"""
Adaptador HTTP de cuentas y sesiones (HU-001): registro, inicio y cierre de sesión.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from platform5e.application.services.accounts.account_service import AccountService
from platform5e.domain.accounts.teacher_account import AccountConfigurationError
from platform5e.infrastructure.http.dependencies import current_teacher_dependency, extract_authorization_header
from platform5e.infrastructure.http.schemas.accounts import (
    LoginRequest,
    ProfileResponse,
    RegistrationRequest,
    SessionResponse,
)
from platform5e.infrastructure.http.schemas.common import error_responses
from platform5e.infrastructure.http.security import LoginRateLimiter, extract_client_ip


def create_accounts_router(
    account_service: AccountService,
    login_rate_limiter: LoginRateLimiter | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    current_teacher = current_teacher_dependency(account_service)
    rate_limiter = login_rate_limiter or LoginRateLimiter()

    @router.post(
        "/accounts",
        tags=["accounts"],
        status_code=status.HTTP_201_CREATED,
        response_model=SessionResponse,
        summary="Register a teacher account",
        responses=error_responses(400, 409, 422),
    )
    def register_account(body: RegistrationRequest) -> dict[str, Any]:
        """Creates the account (PBKDF2 password hash) and opens a session right away. 409 if the e-mail is taken.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X POST "$BASE_URL/api/v1/accounts" -H 'Content-Type: application/json' --data '{"name":"Ana Pérez","email":"ana@example.com","password":"clave-segura-1"}'
        ```

        Expected 201. Use a new e-mail; save the returned token for private calls."""
        return account_service.register_account(body.name, body.email, body.password)

    @router.post(
        "/sessions",
        tags=["sessions"],
        response_model=SessionResponse,
        summary="Sign in",
        responses=error_responses(401, 422, 429),
    )
    def login(body: LoginRequest, request: Request) -> dict[str, Any] | JSONResponse:
        """Checks e-mail and password and returns a bearer token valid for 8 hours.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X POST "$BASE_URL/api/v1/sessions" -H 'Content-Type: application/json' --data '{"email":"ana@example.com","password":"clave-segura-1"}'
        ```

        Expected 200 with a token when the registered e-mail and password match."""
        client_ip = extract_client_ip(request)
        retry_after = rate_limiter.reserve_attempt(body.email, client_ip)
        if retry_after > 0:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(retry_after)},
                content={
                    "error": {
                        "code": "TOO_MANY_LOGIN_ATTEMPTS",
                        "message": "Demasiados intentos de inicio de sesión. Intenta nuevamente más tarde.",
                    }
                },
            )

        session = account_service.login(body.email, body.password)
        rate_limiter.reset(body.email, client_ip)
        return session

    @router.get(
        "/sessions/current",
        tags=["sessions"],
        response_model=ProfileResponse,
        summary="Get the signed-in teacher",
        responses=error_responses(401),
    )
    def get_current_session(teacher_id: str = Depends(current_teacher)) -> dict[str, Any]:
        """Returns the e-mail and name of the teacher who owns the token.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X GET "$BASE_URL/api/v1/sessions/current" -H "Authorization: Bearer $TOKEN"
        ```

        Expected 200. See the response schema below for the returned fields."""
        return account_service.get_profile(teacher_id)

    @router.delete(
        "/sessions/current",
        tags=["sessions"],
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Sign out",
        responses=error_responses(401),
    )
    def logout(authorization: str | None = Depends(extract_authorization_header)) -> Response:
        """Revokes the token: later requests with it get 401.

        Example (Bash/cURL). Set BASE_URL to the API URL and TOKEN to a valid bearer token.
        Use your own ids for path variables and replace sample ids such as unidad-1 in JSON bodies.

        ```bash
        curl --fail-with-body -i -X DELETE "$BASE_URL/api/v1/sessions/current" -H "Authorization: Bearer $TOKEN"
        ```

        Expected 204 with an empty body; the token is revoked."""
        account_service.logout(authorization)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router