# Evidencia QA-15 — Prevención de Inyección SQL (ISO/IEC 25023)

- **Fecha:** $(Get-Date -Format "yyyy-MM-dd")
- **Entorno:** FastAPI (`LLM_PROVIDER=rules`), SQLite y PostgreSQL 16 + pgvector.

## 1. Análisis estático de código (Bandit & Semgrep)
- **Bandit (`bandit -r backend/src -ll`):**
  - **0 hallazgos de severidad alta (`High: 0`)** (`docs/evidence/QA-15/bandit.txt`).
  - **3 avisos informativos `B608` (`Severity: Medium`, `Confidence: Low`)** en `sqlalchemy_chunk_repository.py` (líneas 136, 172 y 205), generados por el uso de f-strings para concatenar cláusulas SQL internas constantes (`document_filter` y `where_clause`). Todos los valores de usuario se pasan mediante parámetros enlazados (`:model`, `:document`, `:vector`, `:limit`, `:unit`, `:teacher`), por lo que son falsos positivos auditados.
- **Semgrep (`p/python`, `p/sql-injection`):**
  - Se auditaron 7 avisos `avoid-sqlalchemy-text`: las 3 consultas vectoriales `pgvector` en `sqlalchemy_chunk_repository.py` (líneas 135, 171, 204) y 4 sentencias `ALTER TABLE` de migración local SQLite en `sqlalchemy_resource_repository.py` (líneas 32, 34, 36, 38) que usan únicamente la constante interna `TeacherResourceORM.__tablename__`.
  - Documentados con `# nosemgrep` tras validación -> **0 bloqueantes** (`docs/evidence/QA-15/semgrep.txt`).

## 2. Pruebas E2E automatizadas (`pytest`)
- Ejecución de `backend/tests/e2e/test_sql_injection.py` (`docs/evidence/QA-15/pytest-sqli.txt`): **2 passed**.
- Verificado que entradas con comillas simples, comentarios SQL (`--`) y operadores lógicos en `POST /api/v1/sessions`, `POST /api/v1/courses`, `PUT /api/v1/courses/{id}`, `GET /api/v1/documents/search` y `POST /api/v1/generation-requests/interpret` nunca producen errores `500`, no filtran trazas internas y mantienen el aislamiento estricto entre docentes.

## 3. Integración continua (CI)
- Incorporado el job `security-static-analysis` en `.github/workflows/backend-ci.yml` para ejecutar Bandit y Semgrep automáticamente en cada Pull Request.
