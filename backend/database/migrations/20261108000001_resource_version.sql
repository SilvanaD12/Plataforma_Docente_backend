-- migrate:up
-- REV-01 (REV-R12): versión de cada recurso para rechazar con conflicto los guardados que parten de una versión
-- anterior. Los recursos existentes quedan en la versión 1.
ALTER TABLE ep002_recursos ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

-- migrate:down
ALTER TABLE ep002_recursos DROP COLUMN IF EXISTS version;
