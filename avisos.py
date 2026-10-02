"""Aviso aprovado, compartilhado pelo site e pelo relatório."""
from html import escape


AVISO_INVESTIMENTO = (
    "Este material tem caráter exclusivamente informativo e educacional e não constitui "
    "recomendação de investimento, oferta ou solicitação de aplicação em fundos de "
    "investimento. As análises e simulações não consideram os objetivos, a situação "
    "financeira ou o perfil de risco de cada investidor.",
    "Antes de investir, leia atentamente o regulamento e os demais documentos oficiais "
    "dos fundos, incluindo a lâmina de informações essenciais, quando aplicável, "
    "disponíveis nos canais oficiais do administrador e do gestor. Consulte especialmente "
    "a política de investimentos, os fatores de risco, as taxas e as condições de aplicação "
    "e resgate, e avalie a adequação do investimento ao seu perfil.",
    "Rentabilidade passada não representa garantia de rentabilidade futura. As simulações "
    "apresentadas não asseguram resultados futuros. Fundos de investimento não contam "
    "com garantia do administrador, do gestor, de qualquer mecanismo de seguro ou do "
    "Fundo Garantidor de Créditos — FGC.",
)


def aviso_investimento_html():
    return ''.join(f'<p>{escape(paragrafo)}</p>' for paragrafo in AVISO_INVESTIMENTO)
