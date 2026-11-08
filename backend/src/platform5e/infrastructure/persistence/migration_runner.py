"""Runner nativo para aplicar migraciones SQL en database/migrations."""
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.engine import Engine


def apply_database_migrations(engine: Engine) -> None:
    """Aplica archivos .sql pendientes de la carpeta migrations de forma determinista."""
    # 1. Intentar resolver la carpeta desde el archivo o desde el directorio actual de ejecución (CWD)
    migrations_dir: Path | None = None

    # Opción A: Directorio de trabajo actual (típico en Render: backend/database/migrations)
    cwd_candidate = Path.cwd() / "database" / "migrations"
    if cwd_candidate.is_dir():
        migrations_dir = cwd_candidate
    else:
        # Opción B: Explorar parents del archivo (desarrollo local / editable)
        current_path = Path(__file__).resolve()
        for parent in current_path.parents:
            candidate = parent / "database" / "migrations"
            if candidate.is_dir():
                migrations_dir = candidate
                break

    # Si es PostgreSQL y no se localizan las migraciones, fallar de inmediato
    if not migrations_dir or not migrations_dir.is_dir():
        if engine.dialect.name == "postgresql":
            raise RuntimeError(
                f"No se encontró el directorio de migraciones 'database/migrations'. "
                f"CWD={Path.cwd()}"
            )
        return

    migration_files = sorted(migrations_dir.glob("*.sql"))
    if not migration_files:
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(255) PRIMARY KEY
                );
                """
            )
        )
        applied = {
            row[0]
            for row in conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
        }

        for file_path in migration_files:
            version = file_path.name.split("_")[0]
            if version in applied:
                continue

            content = file_path.read_text(encoding="utf-8")
            if "-- migrate:up" in content:
                content = content.split("-- migrate:up")[1]
                if "-- migrate:down" in content:
                    content = content.split("-- migrate:down")[0]

            conn.execute(text(content))
            conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:v)"),
                {"v": version},
            )