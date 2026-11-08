"""
Errores del núcleo de dominio independientes de HTTP y de la infraestructura de persistencia.
"""


class DomainError(Exception):
    """Excepción base para todos los errores que ocurren dentro de las reglas de negocio."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class EntityNotFoundError(ValueError, DomainError):
    """Se lanza cuando la entidad pedida no existe o no pertenece al docente."""

    def __init__(self, message: str = "Entity not found") -> None:
        super().__init__(message)


class PersistenceUnavailableError(DomainError):
    """Se lanza cuando la capa de persistencia no responde o no está disponible."""

    def __init__(
        self,
        message: str = "Could not save or query. Please check database connection.",
    ) -> None:
        super().__init__(message)


class DuplicateRecordError(DomainError):
    """Se lanza cuando se intenta crear una entidad con identificadores o claves ya existentes."""

    def __init__(
        self,
        message: str = "The record already exists. Refresh the list and review the data.",
    ) -> None:
        super().__init__(message)
