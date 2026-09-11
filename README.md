# Fundos de investimento CAIXA

Streamlit para comparar cotas, carteiras e fronteira eficiente. O backend usa
PostgreSQL fornecido pelo **mesmo projeto Supabase**, incluindo o contador de
simulações. Não é necessário criar outro banco/projeto para o contador.

## Arquitetura

```text
CVM → ZIP/CSV → pandas em lotes → COPY/staging → UPSERT PostgreSQL
Streamlit → database.py → cotas dos CNPJs/período selecionados → pandas → cálculos
Streamlit → UUID da análise concluída → simulacoes (no mesmo PostgreSQL)
GitHub Actions → cnpj.py → PostgreSQL (sem commit/push de dados)
```

`analytics.py` preserva as fórmulas financeiras e a otimização existentes.
`database.py` concentra conexões, SQL, consultas, cadastro, cargas e contador.
Usa `psycopg` e o protocolo PostgreSQL, sem API REST ou `supabase-py`.
O `COPY` transmite registros em fluxo: não são feitos INSERTs individuais.

## Tabelas e precisão

O arquivo [supabase/schema.sql](supabase/schema.sql) cria a estrutura de forma
idempotente, sem remover dados:

| Objeto | Campos e tipos PostgreSQL | Chave |
|---|---|---|
| `fundos` | `cnpj TEXT`, `nome TEXT`, `atualizado_em TIMESTAMPTZ` | `cnpj` |
| `cotas_diarias` | `cnpj TEXT`, `id_subclasse TEXT DEFAULT ''`, `data DATE`, `valor_cota DOUBLE PRECISION`, `arquivo_origem TEXT`, `atualizado_em TIMESTAMPTZ` | `(cnpj, id_subclasse, data)` |
| `cargas` | `arquivo TEXT`, `url TEXT`, `periodo_inicial TEXT`, `periodo_final TEXT`, `processado_em TIMESTAMPTZ`, `linhas_inseridas BIGINT`, `status TEXT`, `erro TEXT`, `linhas_atualizadas BIGINT DEFAULT 0` | `arquivo` |
| `simulacoes` | `id UUID`, `criado_em TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP` | `id` |
| `fundos_controle` | View: `cnpj`, `nome`, `primeira_data_disponivel`, `ultima_data_disponivel`, `quantidade_registros`, `status` | — |

Todas as colunas das três primeiras tabelas são NOT NULL, exceto
`cargas.processado_em`, `cargas.linhas_inseridas` e `cargas.erro`.
Índices adicionais: `(cnpj, data) INCLUDE (valor_cota)`, `(data)` e
`simulacoes(criado_em)`. As PKs já impõem unicidade; não há UNIQUE redundante.
O histórico não tem FK para o cadastro; a chave primária impede duplicação de cotas.

`DOUBLE PRECISION` armazena cotas em ponto flutuante de 64 bits, compatível com
os cálculos NumPy. Patrimônio, captação, resgate e quantidade de cotistas não
fazem parte da base.
Retornos continuam sendo calculados em memória.

## Configuração inicial no Supabase

1. Abra **Connect** no projeto existente. Use conexão PostgreSQL direta ou
   **Session pooler** (útil quando o ambiente não tem IPv6). Prefira Session
   pooler para este fluxo com tabelas temporárias, COPY e transações longas.
2. Guarde a connection string em `DATABASE_URL` no ambiente do backend ou em
   `.env` local. O arquivo `.env.example` lista apenas os nomes das variáveis.
   `.env` é carregado sem sobrescrever variáveis já configuradas e é ignorado
   pelo Git. Codifique caracteres especiais da senha na URL.
3. Use TLS (`sslmode=require`, ou `verify-full` com certificado configurado).
   O código exige ao menos TLS para conexões remotas.
4. Aplique o schema como administrador/proprietário. A aplicação e o coletor
   não criam tabelas automaticamente. Confira espaço disponível e limites de
   conexões do **projeto existente** no painel antes da carga.

Não são necessários `SUPABASE_URL`, `SUPABASE_KEY` ou Service Role Key.
Não coloque credenciais no frontend, nas mensagens de erro ou no repositório.
RLS fica habilitada, sem acesso público para `anon`/`authenticated`, e a view
usa `security_invoker`. As credenciais administrativas devem ficar restritas
à instalação da estrutura.

Para separar permissões de operação, execute também
[supabase/backend_roles.sql](supabase/backend_roles.sql) como administrador.
Ele cria grupos **sem login e sem senha**:

- `fundos_app`: consulta cadastro/cotas e lê/insere eventos do contador;
- `fundos_coletor`: consulta, insere e atualiza cadastro/cotas/cargas, sem DELETE.

Crie usuários PostgreSQL de backend com senha fora do código, conceda o grupo
correspondente (`GRANT fundos_app TO seu_usuario_app`, por exemplo) e use
connection strings diferentes em cada ambiente, ambas chamadas `DATABASE_URL`.
Confirme que os usuários herdam os grupos. O arquivo de grupos inclui grants e
políticas RLS; não concede acesso à API pública.

Referências: [conexões Supabase](https://supabase.com/docs/guides/database/connecting-to-postgres),
[COPY no Psycopg](https://www.psycopg.org/psycopg3/docs/basic/copy.html),
[secrets Streamlit](https://docs.streamlit.io/develop/concepts/connections/secrets-management).

## Preparar um banco vazio

O projeto em uso já possui os dados no Supabase. Para configurar outra instalação:

```bash
python -m pip install -r requirements.txt
python database.py --aplicar-schema
```

Cadastre os fundos com `python adicionar_fundo.py`, conforme abaixo, ou
diretamente na tabela `fundos` (CNPJ, nome e `atualizado_em`).
Execute `python cnpj.py --meses-reprocessar 2` para carregar o histórico da CVM.
A primeira coleta percorre os arquivos disponíveis e pode demorar.
Não há armazenamento persistente de cotas em arquivos locais.

## Incluir fundos e importar todo o histórico

Com as dependências instaladas e `DATABASE_URL` configurada no `.env`, execute:

```bash
python adicionar_fundo.py
```

No menu, escolha `1` para incluir, `2` para alterar o nome, `3` para excluir
um cadastro ou `0` para sair. Alteração e exclusão localizam o fundo pelo CNPJ
e mostram seu nome atual. A exclusão pede confirmação e preserva as cotas
históricas, removendo o fundo do aplicativo e das próximas coletas. O cache do
aplicativo pode levar até cinco minutos para refletir a alteração.
A exclusão exige permissão `DELETE` em `public.fundos` e política RLS compatível
(ou conexão proprietária); o grupo `fundos_coletor` não possui essa permissão.

Na opção `1`, informe CNPJ (com ou sem pontuação) e nome. O programa pergunta se deseja
incluir outro CNPJ; responda `s` para continuar ou `n` para iniciar a importação.
São aceitos CNPJs numéricos com dígitos verificadores válidos, exceto os fundos
explicitamente excluídos do projeto.

O script cadastra os fundos no Supabase e percorre todos os ZIPs disponíveis
nos diretórios de Informes Diários da CVM, filtrando os CNPJs informados.
Cada ZIP é baixado uma vez para todos eles, e suas cotas são gravadas em uma
transação. O histórico disponível pode começar depois da criação do fundo;
um CNPJ sem cotas recebe um aviso ao final.

Não é necessário alterar o schema. A importação não usa nem altera o controle
global `cargas`, pois abrange apenas os fundos informados. Se houver falha,
execute novamente com os mesmos CNPJs: todos os arquivos serão relidos, sem
duplicar cotas já gravadas. Não há retomada por arquivo nesta versão simples.
Os ZIPs temporários são removidos e o resumo mostra quantidade e datas por fundo.
O nome informado atualiza o cadastro caso o CNPJ já exista.

As próximas execuções de `cnpj.py` consultam o cadastro do banco, incluindo os
novos fundos mesmo que exista uma planilha Numbers local.

## Executar e validar o Streamlit

```bash
python -m pip install -r requirements.txt
python database.py
streamlit run app.py
```

`python database.py` verifica a conexão PostgreSQL e apresenta contagens/datas,
sem mostrar credenciais. Não há fallback para banco local na aplicação.
No Streamlit Cloud, configure `DATABASE_URL` como secret de **nível raiz**:
o Streamlit o disponibiliza como variável de ambiente no backend. Reinicie o
app depois de trocar credenciais/destino, para descartar caches anteriores.

Selecione fundos e período conhecidos, confira as datas e retornos e execute
uma carteira com pelo menos dois fundos e 60 retornos comuns. O contador no
rodapé deve aumentar uma vez após o cálculo bem-sucedido. Alterar apenas um
benchmark ou reexecutar a tela com os mesmos dados/pesos não deve aumentar o
contador na mesma sessão.

As consultas históricas filtram CNPJ e intervalo e retornam somente `data`,
`cnpj`, `valor_cota`. O cadastro é agregado no servidor. Caches de cadastro,
limites e cotas expiram em cinco minutos; o de cotas tem limite de 128 entradas.
O contador tem cache de 60 segundos, invalidado após um novo evento. Dados
novos aparecem na próxima interação após o TTL; uma tela inativa não se atualiza
sozinha. O cache de benchmarks existente continua com seis horas.

Se surgirem subclasses simultâneas para um CNPJ/data, o app informa a
ambiguidade. Não soma, calcula média ou escolhe uma subclasse silenciosamente.

## Alocações travadas na otimização

Em **Monte sua carteira**, informe um percentual e marque **Travar na otimização**
no fundo desejado. É possível travar vários fundos; a opção começa desmarcada.
A fronteira, as duas carteiras otimizadas e as diversificações simuladas respeitam
os mesmos percentuais fixos. **Distribuir igualmente** divide somente o saldo
entre os fundos livres. Desmarque a opção para liberar um fundo novamente.

Por exemplo, travar um fundo em 15% deixa 85% para a otimização dos demais.
Com uma trava ativa, a otimização pode ser consultada antes de completar os
pesos livres da carteira manual. A comparação com a carteira manual só aparece
quando ela totaliza 100%.

Permanece o piso de 1% por fundo, inclusive nos percentuais travados. Restrições
que não deixam saldo suficiente geram uma mensagem e impedem a otimização.
Se as restrições determinarem uma única carteira, o sistema apresenta essa
alocação e informa que menor risco e maior retorno coincidem.

O gráfico histórico das carteiras otimizadas usa esses pesos como alocação
inicial, sem rebalanceamento: os percentuais podem variar durante o histórico.
Travar uma alocação não implica mantê-la constante nessa simulação retrospectiva.
Alterar as travas constitui uma nova análise para o contador da sessão.

## Contador no mesmo banco

Cada linha de `simulacoes` representa uma análise de carteira/fronteira
concluída; as 3.000 diversificações internas do cálculo **não** são 3.000 eventos.
Não se conta uma tentativa que falhou ou que não possui dados suficientes.
O contador começa em zero; não há histórico anterior de uso para importar.

O identificador UUID é estável por dados e pesos dentro da sessão Streamlit.
A escrita usa `ON CONFLICT DO NOTHING`, inclusive em caso de perda da resposta
após COMMIT. Uma sessão nova conta novamente; não é um contador de pessoas
únicas nem um mecanismo antifraude. Dados corrigidos/pesos diferentes geram
nova análise. A tabela guarda somente UUID e timestamp, sem dados pessoais.
Ela compartilha armazenamento com as cotas e cresce com o uso; acompanhe o
consumo no painel. Uma indisponibilidade do contador não impede os resultados.
Se a sessão terminar antes de uma tentativa de gravação bem-sucedida, esse
evento poderá não ser contabilizado.

## Atualização CVM e GitHub Actions

```bash
python cnpj.py --meses-reprocessar 2
```

O universo vem de `fundos` no PostgreSQL, inclusive nas execuções locais.
A leitura de Numbers permanece disponível via `carregar_fundos(caminho)` para
uso explícito em Python. O cadastro precisa estar preenchido
antes de iniciar a automação. Os três FIIs excluídos continuam fora das análises
e das novas coletas, mas seus registros existentes não são apagados.

O coletor reprocessa os dois arquivos mensais mais recentes, processa pendentes
e usa `cargas` para retomar. Correções antigas exigem reprocessamento explícito:
`python cnpj.py --inicio 2025-01 --fim 2025-02 --forcar`.
Se usar `--manter-cache`, remova o ZIP correspondente ou use a janela recente
para garantir um novo download de uma correção antiga.

Cada arquivo é transmitido para staging, deduplicado pela chave completa e
mesclado atomicamente. Registros ausentes em uma republicação permanecem no
histórico. Cotas sem mudança não têm o timestamp alterado; o registro de carga
é atualizado para auditar cada execução, com quantidades efetivas de inserções
e correções.
Falhas desfazem o arquivo inteiro, preservando arquivos já concluídos.
Uma conexão perdida encerra com erro; uma nova execução retoma pelos controles.

No GitHub, configure **Settings → Secrets and variables → Actions → Secrets →
DATABASE_URL** com a conexão do coletor. Não use Repository Variables para senha.
O workflow `Atualizar base de fundos` usa apenas `contents: read`, executa testes
e grava diretamente no PostgreSQL. Não há `git add`, commit ou push de banco.

Com a conexão configurada, execute **Run workflow** e confira:

1. conclusão sem erro e logs com inseridas/atualizadas por arquivo;
2. `cargas.status = 'OK'` e `processado_em` recente;
3. novas datas/correções no Streamlit depois do TTL;
4. ausência de commit automático no repositório.

Execute novamente para verificar ausência de novas inserções para a mesma
publicação CVM. O arquivo pode ter correções legítimas entre duas execuções.

```sql
SELECT arquivo, status, processado_em, linhas_inseridas, linhas_atualizadas
FROM public.cargas ORDER BY processado_em DESC LIMIT 10;
SELECT COUNT(*), MIN(data), MAX(data) FROM public.cotas_diarias;
SELECT COUNT(*) FROM public.simulacoes;
```

## Testes locais e CI

```bash
python -m unittest discover -s tests -v
```

Sem `TEST_DATABASE_URL`, testes de integração ficam explicitamente ignorados;
os testes de cálculos e identidade do contador continuam executando. Para a
suíte completa, configure `TEST_DATABASE_URL` para PostgreSQL **local,
descartável**, com nome `fundos_test*`, e instale `requirements.txt`.
Exporte a variável no shell para os testes; eles não leem essa variável de `.env`.
Os testes truncam somente esse banco de teste e rejeitam hosts remotos ou nomes
fora do padrão. Nunca aponte esse parâmetro para dados de produção.

O workflow `Testes PostgreSQL` cria um serviço PostgreSQL efêmero no runner e
executa a suíte completa, incluindo idempotência, precisão, rollback,
correções, consultas filtradas, RLS e concorrência do contador. Esse serviço
também não cria outro projeto Supabase e não precisa de Secrets de produção.

A pasta `dados/` é usada apenas para o cache temporário `dados/cache_cvm/`.
O coletor a recria quando necessário; os ZIPs são apagados após a carga, exceto
quando `--manter-cache` é informado.
