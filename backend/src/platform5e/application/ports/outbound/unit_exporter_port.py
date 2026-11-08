"""
Puerto de salida para exportar los recursos aprobados de una unidad a un archivo descargable (SCORM, Moodle XML…).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ExportedFile:
    """Archivo listo para descargar: nombre, tipo MIME y contenido."""

    file_name: str
    media_type: str
    content: bytes


class UnitExporterPort(Protocol):
    """Un adaptador por formato. `format` es el valor que pide el cliente (por ejemplo, «scorm_zip»)."""

    format: str

    def supports(self, resource: Mapping) -> bool:
        """Si el recurso entra en este formato (Moodle solo importa ítems de opción múltiple)."""
        ...

    def export(self, resources: Sequence[Mapping], course: Mapping, unit: Mapping) -> ExportedFile:
        """Arma el archivo con los recursos ya aprobados, en el orden de la clase."""
        ...
