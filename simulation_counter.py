"""Identidade de uma análise por sessão; reruns e tentativas usam o mesmo UUID."""
from hashlib import sha256
from uuid import UUID, uuid4

import pandas as pd

from database import registrar_simulacao


def contar_analise(cotas: pd.DataFrame, pesos: pd.Series, estado, pesos_fixos: dict[str, float] | None = None) -> bool:
    ordenadas = cotas.sort_index(axis=1)
    assinatura = sha256()
    assinatura.update(str(tuple(ordenadas.columns)).encode())
    assinatura.update(pd.util.hash_pandas_object(ordenadas, index=True).values.tobytes())
    assinatura.update(pd.util.hash_pandas_object(pesos.reindex(ordenadas.columns), index=True).values.tobytes())
    if pesos_fixos:
        assinatura.update(repr(sorted(pesos_fixos.items())).encode())
    chave = assinatura.hexdigest()
    eventos = estado.setdefault('simulacoes_da_sessao', {})
    if chave not in eventos:
        eventos[chave] = {'id': str(uuid4()), 'registrada': False}
    evento = eventos[chave]
    if evento['registrada']:
        return False
    # Se houver perda de conexão após COMMIT, repetir o UUID não duplica o evento.
    registrar_simulacao(UUID(evento['id']))
    evento['registrada'] = True
    return True
