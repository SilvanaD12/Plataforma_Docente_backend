-- migrate:up
-- GEN-P1: planes de generación (specs/006-plan-de-generacion/data-model.md, «Persistencia»).
-- Las fechas son texto ISO 8601 en UTC con microsegundos, como las demás tablas del proyecto. Al borrar un curso, sus
-- planes se borran junto con sus pedidos de generación (SQLAlchemyAccountRepository.delete_course).

CREATE TABLE IF NOT EXISTS gen_generation_plans (
    id TEXT PRIMARY KEY,
    teacher_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    status TEXT NOT NULL CHECK (status IN ('draft', 'approved', 'used')),
    origin TEXT NOT NULL CHECK (origin IN ('teacher', 'implicit')),
    inputs JSONB NOT NULL,
    evidence JSONB NOT NULL,
    retrieval_mode TEXT CHECK (retrieval_mode IN ('hybrid', 'bm25_fallback')),
    referents JSONB NOT NULL DEFAULT '[]'::jsonb,
    session_context JSONB NOT NULL DEFAULT '{"previousTypologies": []}'::jsonb,
    items JSONB NOT NULL DEFAULT '[]'::jsonb,
    generator JSONB NOT NULL,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    used_by_request_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    approved_at TEXT,
    used_at TEXT,
    CONSTRAINT uq_gen_generation_plans_teacher_key UNIQUE (teacher_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_gen_generation_plans_teacher_unit_updated
    ON gen_generation_plans (teacher_id, unit_id, updated_at DESC);

-- migrate:down
DROP TABLE IF EXISTS gen_generation_plans;
