"""Aplicación para pruebas de punta a punta en la que la consulta de un pedido de generación falla una vez.

Mientras exista el archivo de E2E_FLAKY_LOOKUP_FLAG, la siguiente consulta de un pedido (`GetGenerationRequest.get`)
borra el archivo y lanza un RuntimeError, como una base de datos que no responde un momento. Las demás consultas
funcionan. Se arranca con E2E_APP_FACTORY=tests.e2e.flaky_request_lookup_app:create_application.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from platform5e.application.use_cases.generation.get_generation_request import GetGenerationRequest


def create_application() -> FastAPI:
    import platform5e.main as main

    flag = Path(os.environ["E2E_FLAKY_LOOKUP_FLAG"])
    original_get = GetGenerationRequest.get

    def get(self, teacher_id: str, request_id: str):
        try:
            flag.unlink()
        except FileNotFoundError:
            return original_get(self, teacher_id, request_id)
        raise RuntimeError("la base no respondió (falla temporal de prueba)")

    GetGenerationRequest.get = get  # type: ignore[method-assign]
    return main.create_application()
