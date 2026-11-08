"""Servidor real para las pruebas de punta a punta (TA-007).

Levanta uvicorn en un subproceso independiente y ejecuta llamadas HTTP reales.
"""

from __future__ import annotations

from collections.abc import Iterator
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _reset_postgres(url: str) -> None:
    """Deja la base de PostgreSQL sin tablas para que cada servidor arranque limpio."""
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()


@pytest.fixture
def server(tmp_path: Path) -> Iterator[str]:
    """Levanta la API en un puerto libre y devuelve su URL base. Se apaga al terminar."""
    database_url = os.getenv("E2E_DATABASE_URL")
    if database_url:
        _reset_postgres(database_url)
    else:
        database_url = f"sqlite:///{tmp_path / 'e2e.db'}"

    port = _free_port()
    src_dir = str(BACKEND_ROOT / "src")
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    pythonpath = f"{src_dir}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else src_dir

    environment = {
        **os.environ,
        "PYTHONPATH": pythonpath,
        "DATABASE_URL": database_url,
        "DEMO_CATALOG": "true",
        "LLM_PROVIDER": "rules",
        "TOPIC_SEARCH_ENABLED": "false",
    }
    record = (tmp_path / "uvicorn.log").open("w", encoding="utf-8")

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "platform5e.main:create_application",
            "--factory",
            "--app-dir",
            src_dir,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        stdout=record,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        limit = time.monotonic() + 30
        while True:
            if process.poll() is not None:
                record.flush()
                record.close()
                error_log = (tmp_path / "uvicorn.log").read_text(encoding="utf-8", errors="replace")
                pytest.fail("El servidor terminó al arrancar:\n" + error_log)
            try:
                if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > limit:
                record.flush()
                record.close()
                error_log = (tmp_path / "uvicorn.log").read_text(encoding="utf-8", errors="replace")
                pytest.fail("El servidor no respondió en 30 s:\n" + error_log)
            time.sleep(0.2)
        yield base
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        if not record.closed:
            record.close()