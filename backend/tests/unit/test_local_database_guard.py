"""La prueba de integración que vacía PostgreSQL solo acepta una base en esta máquina."""

from __future__ import annotations

import pytest

from tests.support.local_database import NonLocalDatabaseError, ensure_local_database_url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://test:test@localhost:55432/gen01",
        "postgresql+psycopg://test:test@LOCALHOST/gen01",
        "postgresql+psycopg://test:test@127.0.0.1:5432/gen01",
        "postgresql+psycopg://test:test@[::1]:5432/gen01",
    ],
)
def test_local_hosts_are_accepted(url):
    assert ensure_local_database_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://user:secret@ep-cool-name.us-east-2.aws.neon.tech/neondb",
        "postgresql+psycopg://user:secret@db:5432/app",
        "postgresql+psycopg://user:secret@127.0.0.2/app",
        "postgresql+psycopg://user:secret@localhost.example.com/app",
        "postgresql+psycopg://user:secret@/app",  # sin host: socket local, también se rechaza
        "no es una url",
    ],
)
def test_other_hosts_are_rejected_with_a_clear_message(url):
    with pytest.raises(NonLocalDatabaseError) as error:
        ensure_local_database_url(url)
    assert "No se tocó la base" in str(error.value)
    assert "secret" not in str(error.value)  # el mensaje no muestra la contraseña
