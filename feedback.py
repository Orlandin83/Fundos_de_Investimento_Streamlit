"""Coleta anônima e exportação privada das avaliações do aplicativo."""
from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from uuid import UUID

from database import BASE_DIR, ErroBanco, consultar_dataframe, operacao_banco

QUESTOES = {
    'facilidade': 'Facilidade de uso',
    'clareza': 'Clareza dos gráficos e resultados',
    'utilidade': 'Utilidade para comparar fundos e carteiras',
}
LIMITE_COMENTARIO = 2000
PASTA_EXPORTACAO = BASE_DIR / 'dados' / 'feedback'


def registrar_feedback(id_envio: UUID, notas: dict, comentario: str = '', autoriza_trecho: bool = False) -> None:
    """UUID identifica somente o envio, permitindo repetição segura após falha de rede."""
    if set(notas) != set(QUESTOES):
        raise ValueError('Questões de avaliação inválidas.')
    for nota in notas.values():
        if nota is not None and (type(nota) is not int or not 1 <= nota <= 5):
            raise ValueError('As notas devem estar entre 1 e 5.')
    comentario = comentario.strip()
    if len(comentario) > LIMITE_COMENTARIO or '\x00' in comentario:
        raise ValueError(f'O comentário deve ter até {LIMITE_COMENTARIO} caracteres válidos.')
    if not any(n is not None for n in notas.values()) and not comentario:
        raise ValueError('Selecione ao menos uma nota ou escreva um comentário.')
    if type(autoriza_trecho) is not bool:
        raise ValueError('Autorização inválida.')
    with operacao_banco() as conexao:
        conexao.execute('''
            INSERT INTO public.avaliacoes
                (id, facilidade, clareza, utilidade, comentario, autoriza_trecho)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        ''', (UUID(str(id_envio)), *(notas[c] for c in QUESTOES), comentario,
              autoriza_trecho and bool(comentario)))


def aplicar_schema_feedback() -> None:
    with operacao_banco() as conexao:
        conexao.execute((BASE_DIR / 'supabase' / 'feedback.sql').read_text())


def _texto_csv(valor):
    # Comentários não podem virar fórmulas ao serem abertos no Excel.
    if isinstance(valor, str) and valor.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + valor
    return valor


def _gravar_csv(caminho: Path, colunas, linhas) -> None:
    temporario = caminho.with_suffix('.csv.tmp')
    try:
        with temporario.open('w', newline='', encoding='utf-8-sig') as arquivo:
            os.chmod(temporario, 0o600)
            escritor = csv.writer(arquivo, delimiter=';')
            escritor.writerow(colunas)
            for linha in linhas:
                escritor.writerow([_texto_csv(v) for v in linha])
        temporario.replace(caminho)
    finally:
        temporario.unlink(missing_ok=True)


def exportar_avaliacoes(pasta: Path = PASTA_EXPORTACAO) -> int:
    """Exporta snapshot completo e resumo; não apaga nem altera respostas no banco."""
    with operacao_banco() as conexao:
        dados = consultar_dataframe(conexao, '''
            SELECT id, criado_em, facilidade, clareza, utilidade, comentario, autoriza_trecho
            FROM public.avaliacoes ORDER BY criado_em, id
        ''')
    pasta.mkdir(parents=True, exist_ok=True)
    _gravar_csv(pasta / 'avaliacoes.csv', dados.columns,
                dados.astype(object).where(dados.notna(), '').itertuples(index=False, name=None))
    resumo = []
    for chave, rotulo in QUESTOES.items():
        notas = dados[chave].dropna().astype(float)
        resumo.append([rotulo, len(notas), f'{notas.mean():.2f}'.replace('.', ',') if len(notas) else '',
                       *(int((notas == n).sum()) for n in range(1, 6))])
    notas = dados[list(QUESTOES)].stack().dropna().astype(float)
    resumo.append(['Geral (notas respondidas)', len(notas),
                   f'{notas.mean():.2f}'.replace('.', ',') if len(notas) else '',
                   *(int((notas == n).sum()) for n in range(1, 6))])
    _gravar_csv(pasta / 'resumo.csv', ['Questão', 'Notas respondidas', 'Média', '1 estrela', '2 estrelas',
                                     '3 estrelas', '4 estrelas', '5 estrelas'], resumo)
    return len(dados)


def main() -> int:
    parser = argparse.ArgumentParser(description='Exportar avaliações anônimas para arquivos locais privados.')
    parser.add_argument('--aplicar-schema', action='store_true', help='Cria somente a tabela de avaliações e suas permissões.')
    args = parser.parse_args()
    try:
        if args.aplicar_schema:
            aplicar_schema_feedback()
            print('Tabela de avaliações preparada.')
        else:
            quantidade = exportar_avaliacoes()
            print(f'{quantidade} avaliações exportadas para {PASTA_EXPORTACAO / "avaliacoes.csv"}')
            print(f'Médias e distribuição das notas: {PASTA_EXPORTACAO / "resumo.csv"}')
    except (ErroBanco, OSError) as erro:
        parser.exit(1, f'{erro}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
