"""
Puerto reducido de la generación síncrona retirada (GEN-01, T046 parcial).

Ya no se crean generaciones por esta vía: queda solo lo que todavía se usa.
- `get_demo_catalog`: el catálogo con el que Cuentas siembra el curso de demostración (`DEMO_CATALOG`).
- `get_by_id`: la lectura del historial de `GET /api/v1/generations/{id}` sobre `generaciones_demo`.

Pendiente en un PR aparte con CC-01: mover a Cuentas la siembra del curso de demostración y las clases ORM del
historial y de la pertenencia, y retirar este puerto y el repositorio reducido.
"""

from __future__ import annotations

from typing import Any, Protocol


class GenerationRepositoryPort(Protocol):
    """Lectura del catálogo de demostración y de las generaciones guardadas antes de GEN-01."""

    def get_demo_catalog(self) -> dict[str, Any]:
        """Obtiene el catálogo de demostración con el que Cuentas siembra el curso de ejemplo."""
        ...

    def get_by_id(self, generation_id: str) -> dict[str, Any] | None:
        """Obtiene una generación guardada por su identificador, o None si no existe."""
        ...
