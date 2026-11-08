"""
Autenticación de las rutas: el esquema HTTP Bearer de OpenAPI y la dependencia que entrega el docente en sesión.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform5e.application.services.accounts.account_service import AccountService

teacher_security_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="TeacherSession",
    description="Get the token with POST /api/v1/sessions (or POST /api/v1/accounts). In Authorize paste only the token.",
)


def extract_authorization_header(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(teacher_security_scheme),
) -> str | None:
    """Devuelve la cabecera Authorization tal como llegó; el servicio de cuentas la valida.

    auto_error=False: las cabeceras mal formadas también llegan al servicio, que responde 401 con su propio código.
    """
    return request.headers.get("Authorization")


def current_teacher_dependency(account_service: AccountService) -> Callable[..., str]:
    """Dependencia de FastAPI que exige sesión y entrega el identificador del docente (su correo)."""

    def current_teacher(authorization: str | None = Depends(extract_authorization_header)) -> str:
        return account_service.authenticate_token(authorization)

    return current_teacher
