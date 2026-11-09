"""
Puerto de persistencia de los recursos generados: revisión docente e historial de descargas.
"""

from __future__ import annotations

from typing import Any, Protocol


class ResourceReviewRepositoryPort(Protocol):
    """Contrato para la persistencia del ciclo de vida de revisión y descargas."""

    def get_resources_by_unit(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        """Lista los recursos asignados a una unidad académica."""
        ...

    def get_resource_by_id(self, teacher_id: str, resource_id: str) -> dict[str, Any] | None:
        """Obtiene el detalle completo de un recurso por su ID."""
        ...

    def save_resources(
        self, teacher_id: str, unit_id: str, resources: list[dict[str, Any]]
    ) -> None:
        """Guarda o actualiza un lote de recursos para una unidad."""
        ...

    def save_resource_if_version(
        self,
        teacher_id: str,
        unit_id: str,
        resource: dict[str, Any],
        expected_version: int,
        increment: bool = True,
    ) -> bool:
        """REV-R12: guarda el recurso solo si su versión vigente es `expected_version`.

        Devuelve False, sin modificar nada, si la versión ya no es la vigente. Con `increment` la versión avanza en 1;
        sin él se conserva (actualizaciones que no cambian el contenido, como la de recursos antiguos de REV-R11).
        """
        ...

    def claim_regeneration(
        self, teacher_id: str, unit_id: str, resource: dict[str, Any], expected_version: int
    ) -> bool:
        """REV-C12: reserva de forma atómica el pedido de regeneración desde `expected_version` y guarda `resource`
        (con su registro `regeneration`) sin cambiar la versión. El `attemptId` de `resource["regeneration"]` pasa a ser
        el intento vigente.

        Devuelve False, sin modificar nada, si la versión ya no es la vigente o si otro pedido ya reservó esa versión.
        """
        ...

    def save_resource_if_attempt(
        self,
        teacher_id: str,
        unit_id: str,
        resource: dict[str, Any],
        expected_version: int,
        attempt_id: str,
        increment: bool = False,
    ) -> bool:
        """REV-C12: como `save_resource_if_version`, pero además solo si `attempt_id` sigue siendo el intento de
        regeneración vigente, comparado en la misma escritura. Así la respuesta tardía de un intento viejo no cambia
        nada del intento nuevo, aunque los dos partan de la misma versión.
        """
        ...

    def release_regeneration(self, teacher_id: str, unit_id: str, resource_id: str, attempt_id: str) -> None:
        """Libera la reserva (por ejemplo, si la regeneración falló) para poder pedirla otra vez, solo si `attempt_id`
        sigue siendo el intento vigente: un intento viejo no libera la reserva de uno nuevo."""
        ...

    def delete_resource(self, teacher_id: str, resource_id: str) -> None:
        """Elimina un recurso del repositorio."""
        ...

    def get_downloads(self, teacher_id: str, unit_id: str) -> list[dict[str, Any]]:
        """Obtiene el historial de descargas realizadas por el docente en la unidad."""
        ...

    def get_downloads_by_teacher(self, teacher_id: str) -> list[dict[str, Any]]:
        """REV-R9: todas las descargas del docente, de la más reciente a la más antigua, aunque el curso ya no exista."""
        ...

    def save_download(
        self, teacher_id: str, unit_id: str, download_record: dict[str, Any]
    ) -> None:
        """Registra un evento de descarga en el historial."""
        ...

    def delete_downloads(self, teacher_id: str, unit_id: str) -> None:
        """Limpia el historial de descargas de una unidad."""
        ...

