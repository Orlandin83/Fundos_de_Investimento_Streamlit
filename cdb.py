"""CDB retrospectivo bruto, usando a convenção de datas do benchmark CDI."""
import numpy as np
import pandas as pd

from benchmarks import BENCHMARK_CDI, ErroBenchmark, acumular_taxas_percentuais
from database import consultar_benchmark

CDB_ID = 'simulado:cdb_cdi'
AVISO_CDB = (
    'CDB simulado: rentabilidade bruta, sem IR, IOF ou custos. O percentual escolhido '
    'é aplicado a todo o histórico disponível do CDI; não representa uma oferta '
    'histórica nem considera vencimento, liquidez ou risco de crédito do emissor.'
)


def simular_cdb(taxas: pd.Series, percentual: float) -> pd.Series:
    """Aplica o percentual a cada taxa diária antes de capitalizar (base 100).

    Como no benchmark do app, a primeira data é a cota-base e cada data
    seguinte incorpora a taxa dessa data. Não replica arredondamentos contratuais.
    """
    if not np.isfinite(percentual) or percentual <= 0:
        raise ValueError('O percentual do CDI deve ser positivo e finito.')
    if taxas.empty or not np.isfinite(taxas.to_numpy(dtype=float)).all():
        raise ErroBenchmark('CDI ausente ou inválido para simular o CDB.')
    return acumular_taxas_percentuais(taxas * (percentual / 100), CDB_ID)


def incluir_cdb(cotas, selecionados, inicio, fim, percentual, datas_comuns=True):
    """Acumula todo o CDI antes de alinhar às datas dos fundos, sem preencher lacunas."""
    taxas = consultar_benchmark(BENCHMARK_CDI, inicio, fim)
    serie = simular_cdb(taxas, percentual)
    outros = [c for c in selecionados if c != CDB_ID]
    if outros:
        # Preserva fundos sem dados para impedir uma carteira parcial silenciosa.
        resultado = cotas.reindex(columns=outros).join(serie, how='outer')
    else:
        resultado = serie.to_frame()
    resultado = resultado.reindex(columns=list(selecionados)).sort_index()
    return resultado.dropna(how='any' if datas_comuns else 'all')
