"""Protección para las pruebas que vacían una base de datos: solo se permite una base en esta máquina."""

from __future__ import annotations

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

LOCAL_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})


class NonLocalDatabaseError(RuntimeError):
    """La URL de la base de pruebas no apunta a esta máquina."""


def ensure_local_database_url(url: str) -> str:
    """Devuelve la URL si su host es localhost, 127.0.0.1 o ::1. Si no, lanza NonLocalDatabaseError sin conectarse.

    Una URL sin host (socket local) también se rechaza, para que la regla sea explícita.
    """
    try:
        host = make_url(url).host
    except ArgumentError:
        # No se repite la URL: podría contener la contraseña.
        raise NonLocalDatabaseError("La URL de la base de pruebas no es válida. No se tocó la base.") from None
    normalized = (host or "").strip("[]").lower()
    if normalized not in LOCAL_HOSTS:
        raise NonLocalDatabaseError(
            f"La prueba vacía el esquema public y solo se ejecuta contra una base local "
            f"(localhost, 127.0.0.1 o ::1); el host recibido es {host!r}. No se tocó la base."
        )
    return url
