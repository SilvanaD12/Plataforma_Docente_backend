"""
REV-01 · Puerto de salida hacia Generación para regenerar un recurso desde Revisión (REV-R10 · REV-C12, C13).

Decisión provisional D10, sin confirmación de Generación: Revisión define este puerto y un adaptador de infraestructura
lo implementa delegando en Generación, así que Revisión no depende del servicio de Generación. El pedido puede ser
síncrono (la primera respuesta ya trae `succeeded` o `failed`) o en segundo plano (`pending` o `running`, y se consulta
con `get_regeneration`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

RegenerationState = Literal["pending", "running", "succeeded", "failed"]


@dataclass(frozen=True)
class RegenerationStatus:
    request_id: str
    status: RegenerationState
    new_resource_ids: tuple[str, ...] = ()
    reason: str | None = None


class ResourceRegenerationPort(Protocol):
    def request_regeneration(
        self, teacher_id: str, resource_id: str, resource_version: int, params: dict[str, Any]
    ) -> RegenerationStatus:
        """Pide un recurso nuevo con los parámetros guardados del anterior (`params`, con `unitId`) y la evidencia
        vigente del material. `resource_version` es la versión del anterior al pedirlo."""
        ...

    def get_regeneration(self, teacher_id: str, request_id: str) -> RegenerationStatus | None:
        """Estado de un pedido anterior, o None si no existe o es de otro docente."""
        ...
