"""Aplicación para pruebas de punta a punta con Gemini falso que responde 403 con la clave y el proyecto en el texto.

Es el adaptador real de Gemini con un transporte HTTP falso (sin red ni clave real). Revisión del PR #43: el pedido
debe devolver un `fallbackReason` genérico y el registro del servidor, el detalle con la clave oculta.
Se arranca con E2E_APP_FACTORY=tests.e2e.forbidden_gemini_app:create_application.
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI

from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.infrastructure.llm.gemini_language_model import GeminiLanguageModel

GEMINI_MODEL = "gemini-3.5-flash-lite"
FAKE_KEY = "AIzaSy" + "C" * 33
PROJECT = "987654321098"
GOOGLE_403 = {
    "error": {
        "code": 403,
        "message": f"Permission denied: Consumer 'api_key:{FAKE_KEY}' has been suspended. Project {PROJECT}.",
        "status": "PERMISSION_DENIED",
    }
}


def create_application() -> FastAPI:
    import platform5e.main as main

    transport = httpx.MockTransport(lambda request: httpx.Response(403, json=GOOGLE_403))
    gemini = GeminiLanguageModel("gemini", "clave-de-prueba", model=GEMINI_MODEL, client=httpx.Client(transport=transport))
    original = main.create_generators
    main.create_generators = lambda *args, **kwargs: (gemini, RuleBasedGenerator())
    try:
        return main.create_application()
    finally:
        main.create_generators = original
