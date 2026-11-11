-- migrate:up
-- REV-01 (REV-C12): estado del intento de regeneración vigente (running, succeeded o failed). La escritura del resultado
-- exige en el mismo UPDATE que siga en running: un intento que ya terminó no se reescribe, aunque llegue tarde otra
-- consulta del mismo intento. NULL: sin regeneración pedida.
ALTER TABLE ep002_recursos ADD COLUMN IF NOT EXISTS regeneration_status VARCHAR NULL;

-- migrate:down
ALTER TABLE ep002_recursos DROP COLUMN IF EXISTS regeneration_status;
