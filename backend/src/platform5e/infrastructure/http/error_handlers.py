"""
Manejadores de errores (C02 de EN-006): traducen las excepciones del dominio y de validación a un JSON uniforme,
`{"error": {"code": "...", "message": "..."}}`, con el estado HTTP que corresponde.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from platform5e.domain.accounts.teacher_account import AccountConfigurationError
from platform5e.domain.generation.errors import GenerationError
from platform5e.domain.materials.chunking import MaterialError
from platform5e.domain.shared.errors import DuplicateRecordError, EntityNotFoundError, PersistenceUnavailableError


def error_json(status_code: int, code: str, message: str, details: list[dict[str, Any]] | None = None) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(status_code=status_code, content={"error": error})


async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Esquema o tipos inválidos (FastAPI y Pydantic)."""
    details = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return error_json(
        422,
        "INVALID_PARAMETERS",
        "La API rechazó los parámetros. Revisa la unidad, etapa, tipo, cantidad y contexto.",
        details,
    )


async def domain_error_handler(
    request: Request, exc: AccountConfigurationError | MaterialError | GenerationError
) -> JSONResponse:
    """Errores del dominio con código propio; el estado sale del error (400 si no trae uno)."""
    return error_json(getattr(exc, "status_code", 400), exc.code, exc.message)


async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return error_json(400, "VALIDATION_ERROR", str(exc))


async def not_found_handler(request: Request, exc: EntityNotFoundError) -> JSONResponse:
    return error_json(404, "RESOURCE_NOT_FOUND", str(exc))


async def conflict_error_handler(request: Request, exc: DuplicateRecordError) -> JSONResponse:
    return error_json(409, "DUPLICATE_RECORD", "El registro ya existe. Actualiza la lista y revisa los datos.")


async def persistence_unavailable_handler(request: Request, exc: PersistenceUnavailableError) -> JSONResponse:
    return error_json(
        503, "PERSISTENCE_UNAVAILABLE", "No se pudo guardar ni consultar. Comprueba la conexión de la base de datos."
    )
