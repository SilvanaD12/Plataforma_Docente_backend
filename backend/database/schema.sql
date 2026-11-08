\restrict dbmate

-- Dumped from database version 17.8 (Debian 17.8-1.pgdg12+1)
-- Dumped by pg_dump version 18.6

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: curso; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.curso (
    id bigint NOT NULL,
    codigo text NOT NULL,
    nombre text NOT NULL
);


--
-- Name: curso_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.curso ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.curso_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: documento; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.documento (
    id bigint NOT NULL,
    unidad_id bigint NOT NULL,
    nombre_archivo text NOT NULL,
    tipo text NOT NULL,
    paginas integer,
    creado_en timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT documento_paginas_check CHECK ((paginas > 0)),
    CONSTRAINT documento_tipo_check CHECK ((tipo = ANY (ARRAY['pdf'::text, 'pptx'::text, 'txt'::text])))
);


--
-- Name: documento_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.documento ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.documento_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: fragmento; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fragmento (
    id bigint NOT NULL,
    documento_id bigint NOT NULL,
    unidad_id bigint NOT NULL,
    curso_id bigint NOT NULL,
    pagina integer,
    orden integer NOT NULL,
    texto text NOT NULL,
    embedding public.vector(768),
    modelo_embedding text,
    texto_tsv tsvector GENERATED ALWAYS AS (to_tsvector('spanish'::regconfig, texto)) STORED,
    creado_en timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT fragmento_embedding_con_modelo CHECK (((embedding IS NULL) = (modelo_embedding IS NULL))),
    CONSTRAINT fragmento_pagina_check CHECK ((pagina > 0))
);


--
-- Name: fragmento_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.fragmento ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.fragmento_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version character varying NOT NULL
);


--
-- Name: unidad; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.unidad (
    id bigint NOT NULL,
    curso_id bigint NOT NULL,
    numero integer NOT NULL,
    nombre text NOT NULL,
    CONSTRAINT unidad_numero_check CHECK ((numero > 0))
);


--
-- Name: unidad_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.unidad ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.unidad_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: curso curso_codigo_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.curso
    ADD CONSTRAINT curso_codigo_key UNIQUE (codigo);


--
-- Name: curso curso_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.curso
    ADD CONSTRAINT curso_pkey PRIMARY KEY (id);


--
-- Name: documento documento_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documento
    ADD CONSTRAINT documento_pkey PRIMARY KEY (id);


--
-- Name: fragmento fragmento_documento_id_orden_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fragmento
    ADD CONSTRAINT fragmento_documento_id_orden_key UNIQUE (documento_id, orden);


--
-- Name: fragmento fragmento_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fragmento
    ADD CONSTRAINT fragmento_pkey PRIMARY KEY (id);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: unidad unidad_curso_id_numero_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unidad
    ADD CONSTRAINT unidad_curso_id_numero_key UNIQUE (curso_id, numero);


--
-- Name: unidad unidad_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unidad
    ADD CONSTRAINT unidad_pkey PRIMARY KEY (id);


--
-- Name: documento_unidad_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX documento_unidad_idx ON public.documento USING btree (unidad_id);


--
-- Name: fragmento_documento_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fragmento_documento_idx ON public.fragmento USING btree (documento_id);


--
-- Name: fragmento_embedding_hnsw; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fragmento_embedding_hnsw ON public.fragmento USING hnsw (embedding public.vector_cosine_ops) WITH (m='16', ef_construction='64');


--
-- Name: fragmento_texto_tsv_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fragmento_texto_tsv_gin ON public.fragmento USING gin (texto_tsv);


--
-- Name: fragmento_unidad_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fragmento_unidad_idx ON public.fragmento USING btree (unidad_id);


--
-- Name: documento documento_unidad_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.documento
    ADD CONSTRAINT documento_unidad_id_fkey FOREIGN KEY (unidad_id) REFERENCES public.unidad(id) ON DELETE CASCADE;


--
-- Name: fragmento fragmento_curso_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fragmento
    ADD CONSTRAINT fragmento_curso_id_fkey FOREIGN KEY (curso_id) REFERENCES public.curso(id);


--
-- Name: fragmento fragmento_documento_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fragmento
    ADD CONSTRAINT fragmento_documento_id_fkey FOREIGN KEY (documento_id) REFERENCES public.documento(id) ON DELETE CASCADE;


--
-- Name: fragmento fragmento_unidad_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fragmento
    ADD CONSTRAINT fragmento_unidad_id_fkey FOREIGN KEY (unidad_id) REFERENCES public.unidad(id);


--
-- Name: unidad unidad_curso_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.unidad
    ADD CONSTRAINT unidad_curso_id_fkey FOREIGN KEY (curso_id) REFERENCES public.curso(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict dbmate


--
-- Dbmate schema migrations
--

INSERT INTO public.schema_migrations (version) VALUES
    ('20261005000001'),
    ('20261005000002');
