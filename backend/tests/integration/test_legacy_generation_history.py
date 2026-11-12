"""T046: el historial de la generación síncrona retirada es de Cuentas.

`SQLAlchemyAccountRepository` crea en SQLite las tablas `generaciones_demo` y `ep002_generaciones_docente` (antes las
creaba el repositorio de generación retirado) y lee el historial, el dueño y una generación guardada, con las claves
anteriores adaptadas. SQLite temporal; el esquema no cambia.
"""

from __future__ import annotations

from sqlalchemy import URL, create_engine, inspect
from sqlalchemy.orm import sessionmaker

from platform5e.infrastructure.persistence.repositories import sqlalchemy_account_repository as accounts

TEACHER = "docente@example.com"


def test_the_account_repository_owns_and_reads_the_legacy_generation_history(tmp_path, monkeypatch, request):
    engine = create_engine(URL.create("sqlite", database=str(tmp_path / "historial.db")))
    request.addfinalizer(engine.dispose)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(accounts, "engine", engine)
    monkeypatch.setattr(accounts, "SessionLocal", sessions)

    repository = accounts.SQLAlchemyAccountRepository()
    assert {"generaciones_demo", "ep002_generaciones_docente"} <= set(inspect(engine).get_table_names())

    older = {"request": {"id": "sol-1", "createdAt": "2026-10-01T10:00:00+00:00"}, "mode": "rag",
             "generator": {"descripcion": "Gemini", "usaIA": True, "fallback": False}}
    newer = {"request": {"id": "sol-2", "createdAt": "2026-10-02T10:00:00+00:00"}, "mode": "rag"}
    foreign = {"request": {"id": "sol-ajena", "createdAt": "2026-10-03T10:00:00+00:00"}, "mode": "rag"}
    with sessions() as session:
        for result, owner in ((older, TEACHER), (newer, TEACHER), (foreign, "otra@example.com")):
            session.add(accounts.GenerationORM(id=result["request"]["id"], result=result))
            session.add(accounts.TeacherGenerationORM(id=result["request"]["id"], teacher_id=owner))
        session.commit()

    assert [r["id"] for r in repository.get_history(TEACHER)] == ["sol-2", "sol-1"]
    assert repository.get_generation_owner("sol-ajena") == "otra@example.com"
    assert repository.get_generation_owner("sol-no-existe") is None
    stored = repository.get_generation("sol-1")
    assert stored["request"] == older["request"] and stored["mode"] == "rag"
    assert stored["generator"] == {"description": "Gemini", "usesAi": True, "fallback": False}  # claves adaptadas
    assert repository.get_generation("sol-no-existe") is None
