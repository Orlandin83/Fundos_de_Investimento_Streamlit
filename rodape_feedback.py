"""Formulário público sem identificação e novidades publicadas manualmente."""
import json
from datetime import date
from uuid import uuid4

import streamlit as st

from database import BASE_DIR, ErroBanco
from feedback import LIMITE_COMENTARIO, QUESTOES, registrar_feedback


def fechar_feedback():
    st.session_state.feedback_aberto = False


@st.dialog('Avaliar e sugerir melhorias', on_dismiss=fechar_feedback)
def formulario_feedback():
    if st.session_state.get('feedback_enviado'):
        st.success('Obrigado! Sua avaliação foi recebida.')
        return
    if 'feedback_id' not in st.session_state:
        st.session_state.feedback_id = str(uuid4())
    st.write('Sua opinião ajuda a melhorar o aplicativo. Não é necessário se identificar.')
    st.caption('As notas e o comentário são opcionais. Responda ao menos uma questão ou deixe uma sugestão.')
    with st.form('formulario_feedback'):
        notas = {}
        for chave, rotulo in QUESTOES.items():
            st.markdown(f'**{rotulo}**')
            nota = st.feedback('stars', key=f'feedback_{chave}')
            notas[chave] = None if nota is None else nota + 1
        st.caption('1 estrela: muito insatisfeito · 5 estrelas: muito satisfeito')
        st.info('Não inclua dados pessoais ou informações que identifiquem você ou outras pessoas.')
        comentario = st.text_area('O que podemos melhorar? (opcional)', max_chars=LIMITE_COMENTARIO,
                                  key='feedback_comentario')
        autorizacao = st.checkbox('Autorizo a publicação de um trecho do meu comentário, sem identificação.',
                                  value=False, key='feedback_autoriza')
        enviar = st.form_submit_button('Enviar avaliação', type='primary')
    if enviar:
        try:
            registrar_feedback(st.session_state.feedback_id, notas, comentario, autorizacao)
        except ValueError as erro:
            st.warning(str(erro))
        except ErroBanco:
            st.error('Não foi possível enviar agora. Sua resposta continua no formulário; tente novamente.')
        else:
            st.session_state.feedback_enviado = True
            st.session_state.feedback_aberto = False
            st.rerun()


def exibir_rodape_feedback():
    with st.container(border=True):
        st.subheader('Ajude a melhorar o aplicativo')
        st.write('Avalie sua experiência e envie sugestões, sem precisar se identificar.')
        if st.button('Avaliar e sugerir melhorias', key='abrir_feedback', type='primary'):
            st.session_state.feedback_aberto = True
        if st.session_state.get('feedback_aberto'):
            formulario_feedback()
        if st.session_state.get('feedback_enviado'):
            st.success('Obrigado! Sua avaliação foi recebida.')
    with st.container(border=True):
        st.subheader('Novidades e melhorias')
        novidades = json.loads((BASE_DIR / 'novidades.json').read_text(encoding='utf-8'))
        for item in sorted(novidades, key=lambda n: n['data'], reverse=True)[:5]:
            st.markdown(f"**{item['titulo']}**")
            st.caption(date.fromisoformat(item['data']).strftime('%d/%m/%Y'))
            if item.get('trecho_feedback'):
                st.caption('Sugestão recebida, publicada com autorização:')
                st.text(item['trecho_feedback'])
            st.write(item['descricao'])
