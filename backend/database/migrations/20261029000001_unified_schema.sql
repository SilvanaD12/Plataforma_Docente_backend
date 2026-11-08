-- migrate:up
-- Habilitar extensión vector de forma segura únicamente si está disponible en el motor
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'vector') THEN
        BEGIN
            CREATE EXTENSION IF NOT EXISTS vector;
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'No se pudo activar la extensión vector: %', SQLERRM;
        END;
    ELSE
        RAISE NOTICE 'La extensión pgvector no está disponible en este sistema PostgreSQL.';
    END IF;
END $$;

-- Cuentas de docentes (HU-001)
CREATE TABLE IF NOT EXISTS ep002_usuarios (
    email TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    sal TEXT NOT NULL,
    clave TEXT NOT NULL,
    creado TEXT NOT NULL
);

-- Sesiones activas
CREATE TABLE IF NOT EXISTS ep002_sesiones (
    huella TEXT PRIMARY KEY,
    docente TEXT NOT NULL,
    vence DOUBLE PRECISION NOT NULL
);

-- Cursos académicos
CREATE TABLE IF NOT EXISTS ep002_cursos (
    docente TEXT NOT NULL,
    id TEXT NOT NULL,
    codigo TEXT NOT NULL,
    datos JSONB NOT NULL,
    PRIMARY KEY (docente, id),
    CONSTRAINT uq_ep002_cursos_docente_codigo UNIQUE (docente, codigo)
);

-- Documentos y material de referencia
CREATE TABLE IF NOT EXISTS ep002_documentos (
    id TEXT PRIMARY KEY,
    docente TEXT NOT NULL,
    unidad TEXT NOT NULL,
    nombre TEXT NOT NULL,
    datos JSONB NOT NULL,
    contenido BYTEA NOT NULL,
    CONSTRAINT uq_ep002_documentos_docente_unidad_nombre UNIQUE (docente, unidad, nombre)
);
CREATE INDEX IF NOT EXISTS idx_ep002_documentos_docente_unidad ON ep002_documentos (docente, unidad);

-- Fragmentos de texto procesados con soporte léxico y vectorial (EN-011 / EN-013 / ADR-009 / EN-024)
CREATE TABLE IF NOT EXISTS ep002_fragmentos (
    id TEXT PRIMARY KEY,
    docente TEXT NOT NULL,
    documento TEXT NOT NULL,
    unidad TEXT NOT NULL,
    orden INTEGER NOT NULL,
    ubicacion TEXT NOT NULL,
    texto TEXT NOT NULL,
    modelo_embedding TEXT,
    texto_tsv tsvector GENERATED ALWAYS AS (to_tsvector('spanish', texto)) STORED
);

-- Fragmentos de texto procesados con soporte léxico y vectorial (EN-011 / EN-013 / ADR-009 / EN-024)
CREATE TABLE IF NOT EXISTS ep002_fragmentos (
    id TEXT PRIMARY KEY,
    docente TEXT NOT NULL,
    documento TEXT NOT NULL,
    unidad TEXT NOT NULL,
    orden INTEGER NOT NULL,
    ubicacion TEXT NOT NULL,
    texto TEXT NOT NULL,
    modelo_embedding TEXT,
    texto_tsv tsvector GENERATED ALWAYS AS (to_tsvector('spanish', texto)) STORED
);

-- Asegurar columnas si la tabla ya existía previamente en entornos desplegados (ej. Neon)
ALTER TABLE ep002_fragmentos ADD COLUMN IF NOT EXISTS modelo_embedding TEXT;
ALTER TABLE ep002_fragmentos ADD COLUMN IF NOT EXISTS texto_tsv tsvector GENERATED ALWAYS AS (to_tsvector('spanish', texto)) STORED;

-- Manejo condicional y tolerante para entornos con/sin pgvector (CI, Neon, Render)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'vector') THEN
        ALTER TABLE ep002_fragmentos ADD COLUMN IF NOT EXISTS embedding vector(768);

        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'ep002_fragmentos_embedding_con_modelo'
        ) THEN
            ALTER TABLE ep002_fragmentos 
            ADD CONSTRAINT ep002_fragmentos_embedding_con_modelo 
            CHECK ((embedding IS NULL) = (modelo_embedding IS NULL));
        END IF;

        EXECUTE 'CREATE INDEX IF NOT EXISTS ep002_fragmentos_embedding_hnsw ON ep002_fragmentos USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)';
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_ep002_fragmentos_docente ON ep002_fragmentos (docente);
CREATE INDEX IF NOT EXISTS idx_ep002_fragmentos_documento ON ep002_fragmentos (documento);
CREATE INDEX IF NOT EXISTS idx_ep002_fragmentos_unidad ON ep002_fragmentos (unidad);
CREATE INDEX IF NOT EXISTS ep002_fragmentos_texto_tsv_gin ON ep002_fragmentos USING gin (texto_tsv);

-- Recursos pedagógicos generados para una unidad
CREATE TABLE IF NOT EXISTS ep002_recursos (
    id TEXT PRIMARY KEY,
    docente TEXT NOT NULL,
    unidad TEXT NOT NULL,
    creado TEXT NOT NULL,
    datos JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ep002_recursos_docente_unidad ON ep002_recursos (docente, unidad);

-- Historial de descargas generadas en una unidad
CREATE TABLE IF NOT EXISTS ep002_descargas (
    id TEXT PRIMARY KEY,
    docente TEXT NOT NULL,
    unidad TEXT NOT NULL,
    creado TEXT NOT NULL,
    datos JSONB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ep002_descargas_docente_unidad ON ep002_descargas (docente, unidad);

-- Generaciones demo y asociación por docente
CREATE TABLE IF NOT EXISTS generaciones_demo (
    id TEXT PRIMARY KEY,
    resultado JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS ep002_generaciones_docente (
    id TEXT PRIMARY KEY,
    docente TEXT NOT NULL
);

-- Archivos generados de recursos (imágenes y audios, ADR-011)
CREATE TABLE IF NOT EXISTS media_assets (
    id TEXT PRIMARY KEY,
    teacher_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    details JSONB NOT NULL,
    content BYTEA NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_media_assets_teacher_id ON media_assets (teacher_id);
CREATE INDEX IF NOT EXISTS idx_media_assets_resource_id ON media_assets (resource_id);

-- migrate:down
DROP TABLE IF EXISTS media_assets;
DROP TABLE IF EXISTS ep002_generaciones_docente;
DROP TABLE IF EXISTS generaciones_demo;
DROP TABLE IF EXISTS ep002_descargas;
DROP TABLE IF EXISTS ep002_recursos;
DROP TABLE IF EXISTS ep002_fragmentos;
DROP TABLE IF EXISTS ep002_documentos;
DROP TABLE IF EXISTS ep002_cursos;
DROP TABLE IF EXISTS ep002_sesiones;
DROP TABLE IF EXISTS ep002_usuarios;
DO $$
BEGIN
    DROP EXTENSION IF EXISTS vector;
EXCEPTION WHEN OTHERS THEN
    NULL;
END $$;