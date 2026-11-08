"""Esquemas de cuentas y sesiones."""

from __future__ import annotations

from pydantic import ConfigDict, Field

from platform5e.infrastructure.http.schemas.common import ApiRequest, ApiResponse


class RegistrationRequest(ApiRequest):
    model_config = ConfigDict(str_strip_whitespace=False)  # la contraseña se guarda tal cual
    name: str = Field(min_length=2, max_length=100, description="Teacher full name.", examples=["Ana Pérez"])
    email: str = Field(min_length=3, max_length=254, description="Unique e-mail.", examples=["ana.perez@upao.edu.pe"])
    password: str = Field(min_length=8, max_length=200, description="At least 8 characters.", examples=["clave-segura-1"])


class LoginRequest(ApiRequest):
    model_config = ConfigDict(str_strip_whitespace=False)
    email: str = Field(min_length=3, max_length=254, examples=["ana.perez@upao.edu.pe"])
    password: str = Field(min_length=1, max_length=200, examples=["clave-segura-1"])


class ProfileResponse(ApiResponse):
    email: str = Field(examples=["ana.perez@upao.edu.pe"])
    name: str = Field(examples=["Ana Pérez"])


class SessionResponse(ProfileResponse):
    token: str = Field(description="Bearer token. Send it as `Authorization: Bearer <token>`.")
    expires_in: int = Field(description="Seconds until the session expires (8 hours).", examples=[28800])
