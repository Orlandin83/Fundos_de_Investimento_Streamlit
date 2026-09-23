-- Executar como proprietário no projeto PostgreSQL atual. Nenhum dado pessoal estruturado.
BEGIN;
CREATE TABLE IF NOT EXISTS public.avaliacoes (
    id UUID PRIMARY KEY,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    facilidade SMALLINT CHECK (facilidade BETWEEN 1 AND 5),
    clareza SMALLINT CHECK (clareza BETWEEN 1 AND 5),
    utilidade SMALLINT CHECK (utilidade BETWEEN 1 AND 5),
    comentario TEXT NOT NULL DEFAULT '' CHECK (char_length(comentario) <= 2000),
    autoriza_trecho BOOLEAN NOT NULL DEFAULT FALSE,
    CHECK (facilidade IS NOT NULL OR clareza IS NOT NULL OR utilidade IS NOT NULL OR btrim(comentario) <> ''),
    CHECK (NOT autoriza_trecho OR btrim(comentario) <> '')
);
ALTER TABLE public.avaliacoes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.avaliacoes FROM PUBLIC;
DO $$
DECLARE papel TEXT;
BEGIN
    FOREACH papel IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = papel) THEN
            EXECUTE format('REVOKE ALL ON public.avaliacoes FROM %I', papel);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fundos_app') THEN
        GRANT INSERT ON public.avaliacoes TO fundos_app;
        DROP POLICY IF EXISTS avaliacoes_backend_insercao ON public.avaliacoes;
        CREATE POLICY avaliacoes_backend_insercao ON public.avaliacoes
            FOR INSERT TO fundos_app WITH CHECK (true);
    END IF;
END $$;
COMMIT;
