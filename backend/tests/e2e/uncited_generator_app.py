"""Aplicación para pruebas de punta a punta con un generador que deja de citar el material cuando se le pide.

Mientras exista el archivo de E2E_UNCITED_FLAG, el generador redacta un recurso con una afirmación que no está en el
material, y la verificación lo rechaza: el pedido termina `failed` después de crearse. Sin el archivo, redacta el
generador por reglas de siempre. Se arranca con E2E_APP_FACTORY=tests.e2e.uncited_generator_app:create_application.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from platform5e.application.services.generation.rule_based_generator import RuleBasedGenerator

UNCITED_CLAIM = "El protocolo SCTP reemplazó a TCP en todos los navegadores web desde el año 2015."


class SwitchableGenerator:
    """El generador por reglas, salvo cuando existe el archivo de la bandera."""

    def __init__(self, flag: Path) -> None:
        self._rules = RuleBasedGenerator()
        self._flag = flag

    def __getattr__(self, name: str) -> Any:
        return getattr(self._rules, name)

    def generate(self, context: dict[str, Any]) -> dict[str, Any]:
        if self._flag.exists():
            return {
                "recursos": [
                    {
                        "titulo": "Protocolos que reemplazaron a TCP",
                        "contenido": UNCITED_CLAIM,
                        "citas": [{"afirmacion": UNCITED_CLAIM, "fragmentos": ["F1"]}],
                        "alternativas": [],
                    }
                ]
            }
        return self._rules.generate(context)


def create_application() -> FastAPI:
    import platform5e.main as main

    generator = SwitchableGenerator(Path(os.environ["E2E_UNCITED_FLAG"]))
    original = main.create_generators
    main.create_generators = lambda *args, **kwargs: (generator, generator)
    try:
        return main.create_application()
    finally:
        main.create_generators = original
