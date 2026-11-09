-- migrate:up
-- REV-01 (REV-C12): reserva atómica del pedido de regeneración. Guarda la versión del recurso desde la que se pidió;
-- una segunda solicitud desde la misma versión no puede reservarlo y no genera otro recurso. NULL: sin pedido en curso.
ALTER TABLE ep002_recursos ADD COLUMN IF NOT EXISTS regeneration_claim INTEGER NULL;

-- migrate:down
ALTER TABLE ep002_recursos DROP COLUMN IF EXISTS regeneration_claim;
