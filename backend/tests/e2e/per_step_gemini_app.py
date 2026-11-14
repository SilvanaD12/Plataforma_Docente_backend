"""Aplicación para pruebas de punta a punta con Gemini falso que devuelve cada paso de la actividad como un recurso.

Es el adaptador real de Gemini con un transporte HTTP falso (sin red ni clave real): responde siempre con tres
recursos «Paso N: …» sin «pasos_guiados», como se vio con gemini-3.5-flash-lite. La generación los rechaza con su
motivo y redacta el generador por reglas, que queda como respaldo con su motivo en `generator.fallbackReason`.
Se arranca con E2E_APP_FACTORY=tests.e2e.per_step_gemini_app:create_application.
"""

from __future__ import annotations

import json

import httpx
from fastapi import FastAPI

from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator
from platform5e.infrastructure.llm.gemini_language_model import GeminiLanguageModel

GEMINI_MODEL = "gemini-3.5-flash-lite"
# Oraciones del material de las pruebas de punta a punta: cada «paso» pasa la verificación de anclaje y se rechaza
# por su forma, que es lo que se prueba.
STEP_INSTRUCTIONS = [
    "El protocolo TCP es orientado a la conexión y garantiza una entrega confiable de los datos.",
    "El protocolo UDP no establece conexión ni confirma la entrega; por eso es más rápido.",
    "El enrutador es el dispositivo que decide el camino de cada paquete hasta su destino.",
]


def per_step_answer(request: httpx.Request) -> httpx.Response:
    items = [
        {
            "titulo": f"Paso {number}: Simulación {number}",
            "contenido": instruction,
            "citas": [{"afirmacion": instruction, "fragmentos": ["F1"]}],
            "alternativas": [],
        }
        for number, instruction in enumerate(STEP_INSTRUCTIONS, 1)
    ]
    answer = json.dumps({"recursos": items}, ensure_ascii=False)
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": answer}]}}]})


def create_application() -> FastAPI:
    import platform5e.main as main

    gemini = GeminiLanguageModel("gemini", "clave-de-prueba", model=GEMINI_MODEL,
                                 client=httpx.Client(transport=httpx.MockTransport(per_step_answer)))
    original = main.create_generators
    main.create_generators = lambda *args, **kwargs: (gemini, RuleBasedGenerator())
    try:
        return main.create_application()
    finally:
        main.create_generators = original
