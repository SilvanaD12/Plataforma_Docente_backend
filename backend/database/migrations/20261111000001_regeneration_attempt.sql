-- migrate:up
-- REV-01 (REV-C12): intento de regeneración vigente del recurso. Desde la misma versión puede haber un intento fallido
-- y otro nuevo; cada escritura del resultado compara este valor en el mismo UPDATE, para que la respuesta tardía de un
-- intento viejo no cambie el registro, la reserva ni el recurso del intento nuevo. NULL: sin regeneración pedida.
ALTER TABLE ep002_recursos ADD COLUMN IF NOT EXISTS regeneration_attempt VARCHAR NULL;

-- migrate:down
ALTER TABLE ep002_recursos DROP COLUMN IF EXISTS regeneration_attempt;
