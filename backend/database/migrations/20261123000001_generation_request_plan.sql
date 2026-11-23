-- migrate:up
-- GEN-P2: el pedido de generación parte de un plan aprobado (specs/006-plan-de-generacion/data-model.md, «Cambios en
-- el pedido de generación»). `plan_id` y `plan_version` son NULL en los pedidos anteriores al plan; cada paso guarda
-- el ítem del plan que redacta. No hay clave foránea al plan: al borrar el curso se borran sus planes y sus pedidos.
ALTER TABLE gen_generation_requests ADD COLUMN IF NOT EXISTS plan_id TEXT NULL;
ALTER TABLE gen_generation_requests ADD COLUMN IF NOT EXISTS plan_version INTEGER NULL CHECK (plan_version >= 1);
ALTER TABLE gen_generation_steps ADD COLUMN IF NOT EXISTS plan_item_position INTEGER NULL CHECK (plan_item_position >= 1);
CREATE INDEX IF NOT EXISTS idx_gen_generation_requests_plan ON gen_generation_requests (teacher_id, plan_id);

-- migrate:down
DROP INDEX IF EXISTS idx_gen_generation_requests_plan;
ALTER TABLE gen_generation_steps DROP COLUMN IF EXISTS plan_item_position;
ALTER TABLE gen_generation_requests DROP COLUMN IF EXISTS plan_version;
ALTER TABLE gen_generation_requests DROP COLUMN IF EXISTS plan_id;
