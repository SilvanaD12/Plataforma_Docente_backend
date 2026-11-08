"""
Bases de los esquemas HTTP: campos en snake_case en Python y en camelCase en el JSON, y el formato común de errores.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiRequest(BaseModel):
    """Cuerpo de una petición: rechaza campos desconocidos y recorta espacios."""

    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, alias_generator=to_camel, populate_by_name=True
    )


class ApiResponse(BaseModel):
    """Respuesta documentada. Los campos no declarados se conservan (extra="allow")."""

    model_config = ConfigDict(extra="allow", alias_generator=to_camel, populate_by_name=True)


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable code.", examples=["UNIT_NOT_FOUND"])
    message: str = Field(
        description="Message for the teacher, in Spanish.", examples=["La unidad no pertenece a tus cursos."]
    )
    details: list[dict[str, Any]] | None = Field(
        default=None, description="Validation problems (422 only): location and reason of each one."
    )


class ErrorResponse(BaseModel):
    """Every error has the same shape: `{"error": {"code", "message"}}`."""

    error: ErrorBody


ERROR_DESCRIPTIONS: dict[int, str] = {
    400: "The request breaks a business rule (the code says which one).",
    401: "Missing, invalid or expired session token.",
    404: "The entity does not exist or does not belong to the teacher.",
    409: "Conflict with the current state (duplicate or blocked approval).",
    413: "The file is larger than the limit.",
    422: "Invalid parameters (type, range or unknown field).",
    503: "The database or an external source is not available.",
}


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """`responses=` for FastAPI: each status documented with the common ErrorResponse model."""
    return {code: {"model": ErrorResponse, "description": ERROR_DESCRIPTIONS[code]} for code in status_codes}
