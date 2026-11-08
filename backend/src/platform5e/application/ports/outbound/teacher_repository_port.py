"""
Puerto de persistencia para cuentas de docentes, sesiones, cursos y documentos base.
"""

from __future__ import annotations

from typing import Any, Protocol


class TeacherRepositoryPort(Protocol):
    """Contrato de persistencia para la gestión de docentes, cursos, unidades y sesiones."""

    def init_catalog(self, teacher_id: str) -> None:
        """Inicializa las estructuras base y el catálogo para un nuevo docente."""
        ...

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        """Busca y retorna los datos del usuario a partir de su correo electrónico."""
        ...

    def create_user(self, user_data: dict[str, Any]) -> None:
        """Registra un nuevo usuario docente en el sistema."""
        ...

    def save_session(self, fingerprint: str, teacher_id: str, expires_at: float) -> None:
        """Guarda o renueva el token/sesión de autenticación."""
        ...

    def get_session(self, fingerprint: str) -> tuple[str, float] | None:
        """Recupera la sesión activa asociada a una huella/token."""
        ...

    def delete_session(self, fingerprint: str) -> None:
        """Revoca e invalida la sesión indicada."""
        ...

    def get_courses(self, teacher_id: str) -> list[dict[str, Any]]:
        """Lista todos los cursos creados por el docente."""
        ...

    def save_course(self, teacher_id: str, course_data: dict[str, Any]) -> None:
        """Guarda o actualiza la definición de un curso pedagógico."""
        ...

    def delete_course(self, teacher_id: str, course_id: str, unit_ids: list[str]) -> None:
        """Elimina un curso y sus unidades asociadas."""
        ...

    def get_documents(self, teacher_id: str) -> list[dict[str, Any]]:
        """Lista los documentos subidos por el docente."""
        ...

    def save_document(self, teacher_id: str, metadata: dict[str, Any], content: bytes) -> None:
        """Almacena el binario y los metadatos de un nuevo documento."""
        ...

    def get_document(self, teacher_id: str, document_id: str) -> tuple[dict[str, Any], bytes] | None:
        """Recupera los metadatos y el contenido binario de un documento."""
        ...

    def delete_document(self, teacher_id: str, document_id: str) -> None:
        """Elimina un documento y su contenido asociado."""
        ...

    def get_history(self, teacher_id: str) -> list[dict[str, Any]]:
        """Retorna el historial de actividad y generaciones del docente."""
        ...

    def get_generation_owner(self, generation_id: str) -> str | None:
        """Determina el identificador del docente propietario de una generación."""
        ...