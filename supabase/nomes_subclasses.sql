-- Migração pontual, sem alterar cotas ou permissões existentes.
ALTER TABLE public.fundos
ADD COLUMN IF NOT EXISTS nomes_subclasses JSONB NOT NULL DEFAULT '{}';
