# Distribuição dos resultados projetados

A etapa aparece após a comparação histórica das carteiras. Reutiliza suas
alocações originais; mudar a janela da projeção não otimiza os pesos novamente.
A carteira do usuário exige 100% de alocação, e a de maior Sharpe só aparece
quando seu cálculo está disponível.

O histórico é carregado desde o início da base até a data final selecionada
na simulação. São utilizadas apenas datas comuns aos fundos, incluindo o CDB
sintético quando selecionado. As janelas de 12, 24 e 36 meses, 5 e 10 anos só
aparecem quando há cobertura completa. “Desde o início” corresponde ao primeiro
registro comum disponível, não necessariamente à constituição dos fundos.
Uma cota anterior ao corte é preservada como base do primeiro retorno.

O prazo projetado acompanha a janela selecionada, podendo ser ajustado. Em
“Desde o início”, o padrão é 12 meses, uma escolha de interface que evita
extrapolar automaticamente por décadas; não é uma recomendação de investimento.
A projeção começa na última cota disponível, inclusive em simulações com data
final no passado. A tela e o relatório mostram as datas efetivas.

## Modelo

Para cada intervalo observado, calcula-se o retorno simples da carteira com
pesos constantes, incluindo a correlação entre os fundos implicitamente:

    r_i = soma_j(peso_j * retorno_ij)
    l_i = log(1 + r_i)
    dt_i = duração do intervalo em dias / 365,25
    mu = soma(l_i) / soma(dt_i)
    sigma² = soma((l_i - mu * dt_i)² / dt_i) / (n - 1)

Para T = meses projetados / 12, o log-retorno acumulado tem distribuição normal
com média mu*T e desvio sigma*sqrt(T). Os limites centrais de cobertura p são
exp(mu*T ± quantil_normal((1+p)/2)*sigma*sqrt(T)) - 1. A curva exibida aplica
esta transformação também à densidade, portanto é lognormal na escala do
patrimônio e deslocada em −1 na escala de rentabilidade. Referência das fórmulas:
[NIST — Lognormal Distribution](https://itl.nist.gov/div898/handbook/eda/section3/eda3669.htm).

Usar a duração dos intervalos acomoda datas irregulares sem inventar retornos
zero em feriados ou lacunas. Exigem-se pelo menos 60 retornos, cotas positivas
finitas, datas únicas e pesos não negativos somando 100%. Volatilidade quase
nula ou parâmetros numericamente extremos impedem a exibição da curva.

O modelo supõe incrementos independentes e parâmetros constantes. Pressupõe
rebalanceamento nas datas observadas, diferentemente do gráfico retrospectivo
sem rebalanceamento. Não inclui custos de negociação, impostos, aportes nem
incerteza dos parâmetros estimados; taxas já refletidas nas cotas permanecem
incorporadas. As faixas são probabilidades condicionadas ao modelo, não garantia
de cobertura futura ou intervalos de confiança da média. A otimização com dados
históricos pode favorecer as estimativas das carteiras selecionadas.

O gráfico, as faixas, os prazos e a nota metodológica entram no relatório
exportado. A implementação não adiciona dependências nem altera o banco.

## Verificação

    .venv/bin/python -m unittest discover -s tests -v

`tests/test_projecao.py` verifica capitalização, quantis, correlação, janelas,
validações e interação no Streamlit com dados sintéticos e serviços simulados.
Os testes de integração PostgreSQL requerem `TEST_DATABASE_URL`.
