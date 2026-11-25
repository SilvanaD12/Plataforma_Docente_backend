-- migrate:up
ALTER TABLE ep002_documentos ADD COLUMN IF NOT EXISTS content_hash TEXT;
CREATE INDEX IF NOT EXISTS idx_ep002_documentos_docente_hash ON ep002_documentos (docente, content_hash);

-- migrate:down
DROP INDEX IF EXISTS idx_ep002_documentos_docente_hash;
ALTER TABLE ep002_documentos DROP COLUMN IF EXISTS content_hash;