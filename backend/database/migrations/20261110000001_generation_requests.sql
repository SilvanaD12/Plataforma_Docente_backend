-- migrate:up
-- GEN-01: pedidos de generación en segundo plano y sus pasos (specs/002-generacion-multiple/data-model.md).
-- Las fechas son texto ISO 8601 en UTC con microsegundos, como las demás tablas del proyecto.

CREATE TABLE IF NOT EXISTS gen_generation_requests (
    id TEXT PRIMARY KEY,
    teacher_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('individual', 'sequence', 'regeneration')),
    idempotency_key TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    parameters JSONB NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'running', 'succeeded', 'partially_succeeded', 'failed', 'interrupted')
    ),
    retrieval_mode TEXT CHECK (retrieval_mode IN ('hybrid', 'bm25_fallback')),
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
    regeneration JSONB,
    failure JSONB,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    heartbeat_at TEXT,
    worker_boot_id TEXT,
    CONSTRAINT uq_gen_generation_requests_teacher_key UNIQUE (teacher_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_gen_generation_requests_teacher_unit_created
    ON gen_generation_requests (teacher_id, unit_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_gen_generation_requests_status_heartbeat
    ON gen_generation_requests (status, heartbeat_at);

CREATE TABLE IF NOT EXISTS gen_generation_steps (
    request_id TEXT NOT NULL REFERENCES gen_generation_requests (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    stage TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    agent TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'running', 'succeeded', 'rejected', 'failed', 'interrupted')
    ),
    resource_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    rejections JSONB NOT NULL DEFAULT '[]'::jsonb,
    generator JSONB,
    grounding JSONB,
    distractor_reliability JSONB,
    error JSONB,
    started_at TEXT,
    finished_at TEXT,
    PRIMARY KEY (request_id, position)
);

-- migrate:down
DROP TABLE IF EXISTS gen_generation_steps;
DROP TABLE IF EXISTS gen_generation_requests;
