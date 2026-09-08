-- PostgreSQL 15+. Aplicar uma vez antes de iniciar o coletor/Streamlit.
-- Idempotente; não remove nem substitui dados existentes.
BEGIN;
CREATE TABLE IF NOT EXISTS public.fundos (
    cnpj TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    atualizado_em TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS public.cotas_diarias (
    cnpj TEXT NOT NULL,
    id_subclasse TEXT NOT NULL DEFAULT '',
    data DATE NOT NULL,
    valor_cota DOUBLE PRECISION NOT NULL,
    arquivo_origem TEXT NOT NULL,
    atualizado_em TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (cnpj, id_subclasse, data)
);
CREATE INDEX IF NOT EXISTS cotas_cnpj_data_idx
    ON public.cotas_diarias (cnpj, data) INCLUDE (valor_cota);
CREATE INDEX IF NOT EXISTS cotas_data_idx ON public.cotas_diarias (data);
CREATE TABLE IF NOT EXISTS public.cargas (
    arquivo TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    periodo_inicial TEXT NOT NULL,
    periodo_final TEXT NOT NULL,
    processado_em TIMESTAMPTZ,
    linhas_inseridas BIGINT,
    status TEXT NOT NULL,
    erro TEXT,
    linhas_atualizadas BIGINT NOT NULL DEFAULT 0
);
ALTER TABLE public.cargas ADD COLUMN IF NOT EXISTS linhas_atualizadas BIGINT NOT NULL DEFAULT 0;
CREATE OR REPLACE VIEW public.fundos_controle WITH (security_invoker = true) AS
SELECT f.cnpj, f.nome,
       MIN(c.data) AS primeira_data_disponivel,
       MAX(c.data) AS ultima_data_disponivel,
       COUNT(c.data) AS quantidade_registros,
       CASE WHEN COUNT(c.data) = 0 THEN 'SEM DADOS' ELSE 'OK' END AS status
FROM public.fundos f LEFT JOIN public.cotas_diarias c USING (cnpj)
GROUP BY f.cnpj, f.nome;

-- Uma linha por análise concluída. UUID permite repetir a escrita sem contar duas vezes.
-- Sem IP, carteira, CNPJ de usuário ou qualquer dado pessoal.
CREATE TABLE IF NOT EXISTS public.simulacoes (
    id UUID PRIMARY KEY,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS simulacoes_criado_em_idx ON public.simulacoes (criado_em);

-- Sem políticas públicas: acesso somente pelo backend PostgreSQL autorizado.
ALTER TABLE public.fundos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cotas_diarias ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cargas ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.simulacoes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.fundos, public.cotas_diarias, public.cargas,
    public.fundos_controle, public.simulacoes FROM PUBLIC;
DO $$
DECLARE papel TEXT;
BEGIN
    FOREACH papel IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = papel) THEN
            EXECUTE format('REVOKE ALL ON public.fundos, public.cotas_diarias, public.cargas, public.fundos_controle, public.simulacoes FROM %I', papel);
        END IF;
    END LOOP;
END $$;
COMMIT;
