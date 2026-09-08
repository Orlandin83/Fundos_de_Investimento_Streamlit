# Entrega e validação da migração

Data: 07/09/2026. Código implementado; **corte no Supabase ainda pendente**.
Não havia `DATABASE_URL` nem `.env` configurados durante a execução.
Nenhum projeto Supabase foi criado e nenhum dado remoto foi alterado.

## Evidência executada

Foi iniciado PostgreSQL 16.2 temporário local, sem porta TCP, para testar o SQL
e migrar a origem real em modo somente leitura. Resultado:

| Verificação | Resultado |
|---|---|
| Cadastro | 195 fundos, origem = destino |
| Histórico | 566.895 cotas, todas as chaves e valores conferidos |
| Fundos com histórico | 194 |
| Cobertura | 15/03/2002 a 28/08/2026; contagens e limites por CNPJ iguais |
| Controle de cargas | 89 registros conferidos |
| Subclasses | Chave completa preservada, incluindo 20 registros com subclasse preenchida |
| Reexecução da migração completa | 0 inserções, 0 atualizações, validação aprovada |
| Armazenamento local | Aproximadamente 106 MB de tabelas e índices; não é uma medição da cota Supabase |
| Suíte de testes | 16 testes passaram, sem skips na execução com PostgreSQL |
| Cálculos antes/depois | Cotas, pontos da fronteira, pesos de mínimo risco e 3.000 carteiras iguais |
| Streamlit AppTest | Inicialização, seleção, fronteira e contador aprovados; rerun não duplicou evento |
| Arquivo original | `git diff --exit-code -- dados/fundos.duckdb` confirmou ausência de alteração |
| Revisão de diff | `git diff --check` sem erros |

A amostra de retornos diários/base 100 incluiu os CNPJs
`52699555000177`, `04885832000193`, `02201163000168`, `65795384000121`
e `11060594000142`. A comparação com o código original de `analytics.py`
usou `04885832000193` e `02201163000168`, de 01/01/2024 a 28/08/2026,
com igualdade exata dos arrays numéricos.

Foi corrigida a conversão de DATE para `datetime64[us]`, preservando o tipo que
o DuckDB entregava ao pandas. Nenhuma fórmula financeira foi alterada.

Os testes também cobrem correções e idempotência de ZIP CVM sintético, retomada
do cadastro PostgreSQL sem Numbers, duplicatas entre lotes, rollback de arquivo
interrompido, rollback de migração divergente, RLS/papéis restritos e eventos
simultâneos no contador. O download real da CVM e o GitHub Actions remoto não
foram executados; o caminho de rede existente foi preservado.

## A. Arquivos criados

- `database.py`: acesso PostgreSQL centralizado, COPY/upsert e contador.
- `simulation_counter.py`: identidade por análise/sessão e repetição segura.
- `supabase/schema.sql`: três tabelas migradas, view e tabela de simulações.
- `supabase/backend_roles.sql`: papéis opcionais com permissões e políticas RLS.
- `scripts/migrate_duckdb_to_supabase.py`: migração atômica e comparação completa.
- `requirements-migration.txt`: DuckDB exclusivamente para migração/testes.
- `.env.example`: nomes de variáveis, sem credenciais.
- `.github/workflows/testes.yml`: testes com PostgreSQL efêmero no runner.
- `tests/test_database.py`, `tests/test_simulation_counter.py`: verificações.
- `README.md` e este relatório.

## B. Arquivos alterados

`cnpj.py`, `analytics.py`, `app.py`, `requirements.txt`, `.gitignore` e
`.github/workflows/atualizar-base.yml`. `benchmarks.py` e as fórmulas financeiras
existentes permaneceram sem alterações. Nenhum commit/push foi executado.

## C. Estrutura do Supabase

`fundos` (PK CNPJ), `cotas_diarias` (PK CNPJ/subclasse/data), `cargas` (PK arquivo),
`fundos_controle` (view) e `simulacoes` (PK UUID). São objetos do mesmo banco.
Tipos, índices e nulabilidade estão no schema e no README.

## D. Variáveis de ambiente

`DATABASE_URL` é a única variável necessária em produção. `TEST_DATABASE_URL`
é opcional, exclusiva para PostgreSQL local descartável. Não são necessárias
chaves Supabase REST. A senha deve ser configurada fora do código/chat.

## E. Secret GitHub

`DATABASE_URL` em Actions Secrets. Configure a conexão do coletor, idealmente
com o papel `fundos_coletor`. O workflow não tem permissão para gravar no Git.

## F. Migração inicial

Com o banco Supabase configurado e as atualizações pausadas:

```bash
python -m pip install -r requirements-migration.txt
python scripts/migrate_duckdb_to_supabase.py --aplicar-schema
python scripts/migrate_duckdb_to_supabase.py --validar-apenas
```

Exija conclusão com código zero antes de ativar a atualização diária.
O README explica lotes, rollback, reexecução e tratamento de divergências.

## G. Testar localmente

`python -m unittest discover -s tests -v`. Para executar todas as verificações,
exporte `TEST_DATABASE_URL` com host local e banco descartável `fundos_test*`.
Sem essa variável, dez testes de integração são ignorados explicitamente.
O CI de testes prepara seu próprio PostgreSQL; não usa o Supabase.

## H. Confirmar a leitura pelo Streamlit

Execute `python database.py` e `streamlit run app.py` com `DATABASE_URL`
configurada. Não existe fallback local. Confira datas/retornos conhecidos e
o contador após uma carteira válida. No Streamlit Cloud, configure o secret
no nível raiz e reinicie o app. O cache de dados expira em cinco minutos.

## I. Confirmar a atualização automática

Depois da paridade remota, execute `Atualizar base de fundos` manualmente em
Actions. Confira status OK, inseridas/atualizadas e `processado_em` em `cargas`,
novos dados no app e ausência de commit automático. Execute novamente para
verificar idempotência, considerando possíveis correções publicadas pela CVM.
Essa verificação remota permanece pendente.

## J. Retirada posterior do DuckDB

Mantenha `dados/fundos.duckdb` até validar Supabase, Streamlit e Actions reais.
Depois, `git rm --cached dados/fundos.duckdb` retira o arquivo do índice sem
apagar a cópia local. O arquivo ainda está rastreado; `.gitignore` não o remove
retroativamente. Não foi reescrito o histórico Git.

Referências restantes a DuckDB são intencionais: migração inicial, teste de
migração, dependência exclusiva, regras de ignore, README e este relatório.
Não existem imports DuckDB no app, coletor ou camada analítica de produção.

## K. Configurações manuais pendentes

No projeto Supabase existente, obtenha a conexão PostgreSQL (direta ou Session
pooler), configure a senha fora do código, TLS, acesso de rede e espaço disponível.
Aplique o schema; opcionalmente aplique os papéis e crie logins de backend com
privilégios separados. Configure `DATABASE_URL` no ambiente local, Streamlit e
GitHub Actions e conclua a migração/validação remota antes de publicar o corte.
Não é necessário criar outro projeto nem habilitar uma API pública para o contador.
