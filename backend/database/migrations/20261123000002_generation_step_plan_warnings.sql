-- migrate:up
-- GEN-P2 (corrección tras la medición de P4, specs/006-plan-de-generacion/research.md R5): avisos de solapamiento de
-- los recursos de la IA que se entregaron aunque no respetaron del todo su plan: [{title, reason, resourceId}].
ALTER TABLE gen_generation_steps ADD COLUMN IF NOT EXISTS plan_warnings JSONB NULL;

-- migrate:down
ALTER TABLE gen_generation_steps DROP COLUMN IF EXISTS plan_warnings;
