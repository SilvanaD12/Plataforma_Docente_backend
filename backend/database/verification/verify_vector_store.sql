-- Verificación de EN-011 adaptada al esquema unificado ep002_* (EN-024)
-- Se ejecuta dentro de una transacción que termina en ROLLBACK: no deja datos en la base.

\set ON_ERROR_STOP on
\pset footer off

BEGIN;

-- ---------------------------------------------------------------------------
-- C01 · Extensión instalada y operativa
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    version_vector text;
BEGIN
    SELECT extversion INTO version_vector FROM pg_extension WHERE extname = 'vector';
    IF version_vector IS NULL THEN
        RAISE EXCEPTION 'C01: la extensión vector no está instalada';
    END IF;
    RAISE NOTICE 'C01 · pgvector instalado, versión %', version_vector;

    IF ('[1,0]'::vector <=> '[0,1]'::vector) <> 1 THEN
        RAISE EXCEPTION 'C01: la distancia coseno entre vectores ortogonales debería ser 1';
    END IF;
    IF ('[1,2]'::vector <=> '[2,4]'::vector) > 1e-6 THEN
        RAISE EXCEPTION 'C01: la distancia coseno entre vectores paralelos debería ser 0';
    END IF;
    RAISE NOTICE 'C01 · operador de distancia coseno (<=>) correcto';

    BEGIN
        PERFORM '[1,2,3]'::vector(768);
        RAISE EXCEPTION 'C01: vector(768) aceptó un vector de 3 dimensiones';
    EXCEPTION WHEN data_exception THEN
        RAISE NOTICE 'C01 · vector(768) rechaza dimensiones distintas: %', SQLERRM;
    END;
END
$$;

-- ---------------------------------------------------------------------------
-- Datos de prueba en ep002_*: 1 docente, 1 curso, 4 unidades, 1 documento por unidad, 4.000 fragmentos
-- ---------------------------------------------------------------------------
INSERT INTO ep002_usuarios (email, nombre, sal, clave, creado)
VALUES ('docente.prueba@5e.edu.pe', 'Docente de Prueba', 'sal123', 'hash123', now()::text);

INSERT INTO ep002_cursos (docente, id, codigo, datos)
VALUES ('docente.prueba@5e.edu.pe', 'curso-en011', 'PRUEBA-EN011', '{"nombre": "Curso de prueba EN-011"}'::jsonb);

INSERT INTO ep002_documentos (id, docente, unidad, nombre, datos, contenido)
SELECT 'doc-en011-' || n, 'docente.prueba@5e.edu.pe', 'u' || n, 'prueba-unidad-' || n || '.pdf', '{"paginas": 50}'::jsonb, '\x010203'::bytea
FROM generate_series(1, 4) AS n;

-- Componentes uniformes en [-0,5; 0,5]
INSERT INTO ep002_fragmentos (id, docente, documento, unidad, orden, ubicacion, texto, embedding, modelo_embedding)
SELECT 'frag-ruido-' || g, 'docente.prueba@5e.edu.pe', 'doc-en011-' || (1 + g % 4), 'u' || (1 + g % 4), g, 'Página ' || (1 + g % 50), 'Fragmento de ruido ' || g,
       (SELECT array_agg(random() - 0.5) FROM generate_series(1, 768) WHERE g > 0)::vector(768),
       'prueba-aleatorio'
FROM generate_series(1, 4000) AS g;

-- Vectores conocidos: consulta q y fragmentos cercanos (q + ruido · escala).
CREATE TEMP TABLE consulta_prueba ON COMMIT DROP AS
SELECT (SELECT array_agg(random() - 0.5) FROM generate_series(1, 768))::vector(768) AS q;

INSERT INTO ep002_fragmentos (id, docente, documento, unidad, orden, ubicacion, texto, embedding, modelo_embedding)
SELECT 'frag-plantado-' || p.orden, 'docente.prueba@5e.edu.pe', 'doc-en011-' || p.numero_unidad, 'u' || p.numero_unidad, 10000 + p.orden, 'Página 1', p.texto,
       (SELECT array_agg(qv.c + p.escala * (random() - 0.5))
          FROM unnest((SELECT q::real[] FROM consulta_prueba)) AS qv(c))::vector(768),
       'prueba-plantado'
FROM (VALUES (1, 1, 0.10, 'PLANTADO-A1'),
             (1, 2, 0.30, 'PLANTADO-A2'),
             (1, 3, 0.60, 'PLANTADO-A3'),
             (2, 4, 0.05, 'PLANTADO-B1')) AS p(numero_unidad, orden, escala, texto);

-- Fragmento para búsqueda por palabras en español
INSERT INTO ep002_fragmentos (id, docente, documento, unidad, orden, ubicacion, texto)
VALUES ('frag-pila-1', 'docente.prueba@5e.edu.pe', 'doc-en011-1', 'u1', 20000, 'Página 3',
        'Las pilas siguen la política LIFO: el último en entrar es el primero en salir.');

ANALYZE ep002_fragmentos;

SELECT count(*) AS fragmentos_de_prueba,
       count(embedding) AS con_embedding,
       count(DISTINCT unidad) AS unidades
FROM ep002_fragmentos;

-- ---------------------------------------------------------------------------
-- C02 · Consulta top-k por similitud filtrada por unidad
-- ---------------------------------------------------------------------------
SET LOCAL hnsw.iterative_scan = relaxed_order;

CREATE FUNCTION pg_temp.plan_de(consulta text) RETURNS text LANGUAGE plpgsql AS $f$
DECLARE
    plan text := '';
    fila record;
BEGIN
    FOR fila IN EXECUTE 'EXPLAIN (COSTS OFF) ' || consulta LOOP
        plan := plan || E'\n    ' || fila."QUERY PLAN";
    END LOOP;
    RETURN regexp_replace(plan, '''\[[^]]*\]''', '''[q: 768 valores]''', 'g');
END
$f$;

CREATE FUNCTION pg_temp.textos_de(consulta text) RETURNS text[] LANGUAGE plpgsql AS $f$
DECLARE
    resultado text[];
BEGIN
    EXECUTE 'SELECT array_agg(texto) FROM (' || consulta || ') r' INTO resultado;
    RETURN resultado;
END
$f$;

\echo
\echo 'C02 · Top-5 de la unidad u1 por distancia coseno:'
SELECT f.texto, f.unidad, round((f.embedding <=> cp.q)::numeric, 4) AS distancia
FROM ep002_fragmentos f
CROSS JOIN consulta_prueba cp
WHERE f.unidad = 'u1' AND f.docente = 'docente.prueba@5e.edu.pe'
ORDER BY f.embedding <=> cp.q
LIMIT 5;

DO $$
DECLARE
    q               vector(768);
    consulta_unidad text;
    consulta_global text;
    plan            text;
    top_natural     text[];
    top_global      text[];
    top_hnsw        text[];
    top_exacto      text[];
    comunes         integer;
    esperado_unidad text[] := ARRAY['PLANTADO-A1', 'PLANTADO-A2', 'PLANTADO-A3'];
BEGIN
    SELECT cp.q INTO q FROM consulta_prueba cp;

    consulta_unidad := format(
        'SELECT texto FROM ep002_fragmentos WHERE unidad = ''u1'' AND docente = ''docente.prueba@5e.edu.pe'' ORDER BY embedding <=> %L::vector(768) LIMIT 10',
        q::text);
    consulta_global := format(
        'SELECT texto FROM ep002_fragmentos WHERE docente = ''docente.prueba@5e.edu.pe'' ORDER BY embedding <=> %L::vector(768) LIMIT 10', q::text);

    -- 1) Consulta filtrada por unidad
    plan := pg_temp.plan_de(consulta_unidad);
    RAISE NOTICE 'C02.1 · Consulta filtrada por unidad, plan:%', plan;
    top_natural := pg_temp.textos_de(consulta_unidad);
    IF top_natural[1:3] <> esperado_unidad OR 'PLANTADO-B1' = ANY (top_natural) THEN
        RAISE EXCEPTION 'C02.1: resultado inesperado: %', top_natural;
    END IF;
    RAISE NOTICE 'C02.1 · Top-3 correcto (%), sin fragmentos de otras unidades', array_to_string(top_natural[1:3], ', ');

    -- 2) Consulta sin filtro
    plan := pg_temp.plan_de(consulta_global);
    RAISE NOTICE 'C02.2 · Consulta sin filtro, plan:%', plan;
    IF position('ep002_fragmentos_embedding_hnsw' IN plan) = 0 THEN
        RAISE EXCEPTION 'C02.2: la consulta sin filtro no usa el índice ep002_fragmentos_embedding_hnsw';
    END IF;
    top_global := pg_temp.textos_de(consulta_global);
    IF top_global[1:4] <> ARRAY['PLANTADO-B1', 'PLANTADO-A1', 'PLANTADO-A2', 'PLANTADO-A3'] THEN
        RAISE EXCEPTION 'C02.2: top-4 inesperado: %', top_global[1:4];
    END IF;
    RAISE NOTICE 'C02.2 · Usa ep002_fragmentos_embedding_hnsw y devuelve el top-4 esperado (%)', array_to_string(top_global[1:4], ', ');

    -- 3) Consulta filtrada con índice forzado
    PERFORM set_config('enable_sort', 'off', true);
    plan := pg_temp.plan_de(consulta_unidad);
    top_hnsw := pg_temp.textos_de(consulta_unidad);
    PERFORM set_config('enable_sort', 'on', true);
    RAISE NOTICE 'C02.3 · Consulta filtrada con el índice HNSW forzado (enable_sort = off), plan:%', plan;
    IF position('ep002_fragmentos_embedding_hnsw' IN plan) = 0 THEN
        RAISE EXCEPTION 'C02.3: no se pudo usar el índice HNSW con el filtro por unidad';
    END IF;
    IF top_hnsw[1:3] <> esperado_unidad OR 'PLANTADO-B1' = ANY (top_hnsw) THEN
        RAISE EXCEPTION 'C02.3: resultado inesperado con el índice HNSW: %', top_hnsw;
    END IF;
    IF coalesce(array_length(top_hnsw, 1), 0) <> 10 THEN
        RAISE EXCEPTION 'C02.3: el índice devolvió % filas en lugar de 10', coalesce(array_length(top_hnsw, 1), 0);
    END IF;

    -- 4) Comparación con búsqueda exacta
    PERFORM set_config('enable_indexscan', 'off', true);
    top_exacto := pg_temp.textos_de(consulta_unidad);
    PERFORM set_config('enable_indexscan', 'on', true);
    SELECT count(*) INTO comunes FROM unnest(top_hnsw) t WHERE t = ANY (top_exacto);
    IF top_exacto[1:3] <> top_hnsw[1:3] THEN
        RAISE EXCEPTION 'C02.3: el top-3 del índice (%) difiere de la búsqueda exacta (%)', top_hnsw[1:3], top_exacto[1:3];
    END IF;
    RAISE NOTICE 'C02.3 · Con el índice HNSW y el filtro: 10 filas, top-3 correcto e igual a la búsqueda exacta; recall@10: %/10', comunes;
END
$$;

-- ---------------------------------------------------------------------------
-- Preparación de HU-012 · Búsqueda por palabras en español
-- ---------------------------------------------------------------------------
\echo
\echo 'HU-012 · Fragmentos que contienen «pila» (con stemming en español):'
SELECT texto, texto_tsv FROM ep002_fragmentos WHERE texto_tsv @@ plainto_tsquery('spanish', 'pila');

DO $$
DECLARE
    plan text := '';
    n    integer;
BEGIN
    SELECT count(*) INTO n FROM ep002_fragmentos WHERE texto_tsv @@ plainto_tsquery('spanish', 'pila');
    IF n <> 1 THEN
        RAISE EXCEPTION 'HU-012: se esperaba 1 fragmento con «pila» y se obtuvieron %', n;
    END IF;
    RAISE NOTICE 'HU-012 · «pila» encuentra «pilas» (stemming español)';

    plan := pg_temp.plan_de($q$SELECT id FROM ep002_fragmentos WHERE texto_tsv @@ plainto_tsquery('spanish', 'pila')$q$);
    RAISE NOTICE 'HU-012 · Plan elegido por PostgreSQL:%', plan;

    PERFORM set_config('enable_seqscan', 'off', true);
    plan := pg_temp.plan_de($q$SELECT id FROM ep002_fragmentos WHERE texto_tsv @@ plainto_tsquery('spanish', 'pila')$q$);
    SELECT count(*) INTO n FROM ep002_fragmentos WHERE texto_tsv @@ plainto_tsquery('spanish', 'pila');
    PERFORM set_config('enable_seqscan', 'on', true);
    RAISE NOTICE 'HU-012 · Plan sin lectura secuencial (enable_seqscan = off):%', plan;
    IF position('ep002_fragmentos_texto_tsv_gin' IN plan) = 0 OR n <> 1 THEN
        RAISE EXCEPTION 'HU-012: el índice ep002_fragmentos_texto_tsv_gin no responde la búsqueda por palabras';
    END IF;
    RAISE NOTICE 'HU-012 · El índice ep002_fragmentos_texto_tsv_gin responde la búsqueda (1 fragmento)';
END
$$;

\echo
\echo 'VERIFICACIÓN EN-011 / EN-024 SUPERADA'
ROLLBACK;