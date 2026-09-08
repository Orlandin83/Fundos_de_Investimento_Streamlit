-- Opcional, executar como administrador depois de schema.sql.
-- Papéis de grupo sem login/senha. Conceder a usuários backend separados.
BEGIN;
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fundos_app') THEN
        CREATE ROLE fundos_app NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fundos_coletor') THEN
        CREATE ROLE fundos_coletor NOLOGIN;
    END IF;
END $$;
GRANT USAGE ON SCHEMA public TO fundos_app, fundos_coletor;
GRANT SELECT ON public.fundos, public.cotas_diarias, public.fundos_controle TO fundos_app, fundos_coletor;
GRANT SELECT, INSERT ON public.simulacoes TO fundos_app;
GRANT INSERT, UPDATE ON public.fundos, public.cotas_diarias TO fundos_coletor;
GRANT SELECT, INSERT, UPDATE ON public.cargas TO fundos_coletor;
DO $$ BEGIN
    EXECUTE format('GRANT TEMPORARY ON DATABASE %I TO fundos_coletor', current_database());
END $$;
DROP POLICY IF EXISTS fundos_backend_leitura ON public.fundos;
CREATE POLICY fundos_backend_leitura ON public.fundos FOR SELECT TO fundos_app, fundos_coletor USING (true);
DROP POLICY IF EXISTS cotas_backend_leitura ON public.cotas_diarias;
CREATE POLICY cotas_backend_leitura ON public.cotas_diarias FOR SELECT TO fundos_app, fundos_coletor USING (true);
DROP POLICY IF EXISTS fundos_coletor_escrita ON public.fundos;
CREATE POLICY fundos_coletor_escrita ON public.fundos FOR ALL TO fundos_coletor USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS cotas_coletor_escrita ON public.cotas_diarias;
CREATE POLICY cotas_coletor_escrita ON public.cotas_diarias FOR ALL TO fundos_coletor USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS cargas_coletor ON public.cargas;
CREATE POLICY cargas_coletor ON public.cargas FOR ALL TO fundos_coletor USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS simulacoes_backend_leitura ON public.simulacoes;
CREATE POLICY simulacoes_backend_leitura ON public.simulacoes FOR SELECT TO fundos_app USING (true);
DROP POLICY IF EXISTS simulacoes_backend_insercao ON public.simulacoes;
CREATE POLICY simulacoes_backend_insercao ON public.simulacoes FOR INSERT TO fundos_app WITH CHECK (true);
COMMIT;
