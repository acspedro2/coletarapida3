# streamlit_app.py - VERSÃO COM GERAÇÃO DE PDF OTIMIZADA

import streamlit as st
import json
import cohere
import gspread
import time
import re
import pandas as pd
from datetime import datetime
from io import BytesIO
from dateutil.relativedelta import relativedelta
# A biblioteca 'pdf2image' e outras pesadas podem ser importadas dentro das funções se necessário

# --- CONFIGURAÇÕES E CLIENTES (INICIALIZAÇÃO) ---
try:
    cohere_client = cohere.Client(st.secrets["COHERE_API_KEY"])
except Exception as e:
    st.error(f"Erro ao inicializar o cliente Cohere: {e}")
    cohere_client = None

# --- FUNÇÕES DE VALIDAÇÃO E OUTRAS ---
# (Cole aqui as suas funções como validar_cpf, analisar_carteira_vacinacao, etc.)
def validar_cpf(cpf: str) -> bool:
    cpf = ''.join(re.findall(r'\d', str(cpf)))
    if not cpf or len(cpf) != 11 or cpf == cpf[0] * 11: return False
    try:
        soma = sum(int(cpf[i]) * (10 - i) for i in range(9)); d1 = (soma * 10 % 11) % 10
        if d1 != int(cpf[9]): return False
        soma = sum(int(cpf[i]) * (11 - i) for i in range(10)); d2 = (soma * 10 % 11) % 10
        if d2 != int(cpf[10]): return False
    except: return False
    return True

# --- FUNÇÃO OTIMIZADA PARA GERAR PDF ---
def gerar_capa_prontuario_pdf(dados_paciente):
    """
    Gera um PDF da capa do prontuário.
    A importação da biblioteca reportlab é feita AQUI DENTRO para economizar memória.
    """
    try:
        # PASSO 1: Importar a biblioteca somente quando a função é chamada
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm

        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        largura, altura = A4

        # Título
        c.setFont("Helvetica-Bold", 18)
        c.drawCentredString(largura / 2, altura - 2 * cm, "Capa de Prontuário")

        # Linha divisória
        c.line(2 * cm, altura - 2.5 * cm, largura - 2 * cm, altura - 2.5 * cm)

        # Dados do Paciente
        c.setFont("Helvetica", 12)
        y = altura - 4 * cm
        c.drawString(3 * cm, y, f"Nome Completo: {dados_paciente.get('nome', '')}")
        y -= 1 * cm
        c.drawString(3 * cm, y, f"Data de Nascimento: {dados_paciente.get('data_nasc', '')}")
        y -= 1 * cm
        c.drawString(3 * cm, y, f"CPF: {dados_paciente.get('cpf', '')}")
        y -= 1 * cm
        c.drawString(3 * cm, y, f"Nome da Mãe: {dados_paciente.get('mae', '')}")
        y -= 1 * cm
        c.drawString(3 * cm, y, f"CNS: {dados_paciente.get('cns', '')}")

        c.showPage()
        c.save()

        buffer.seek(0)
        return buffer
    except Exception as e:
        st.error(f"Erro ao gerar o PDF: {e}")
        return None

# --- INTERFACE PRINCIPAL ---
def main():
    st.set_page_config(page_title="Coleta Inteligente", page_icon="🤖", layout="wide")
    st.title("Coleta Inteligente")

    st.header("Coleta de Dados do Paciente")

    # Campos para coleta de dados
    nome = st.text_input("Nome Completo")
    data_nasc = st.text_input("Data de Nascimento (DD/MM/AAAA)")
    cpf = st.text_input("CPF")
    nome_mae = st.text_input("Nome da Mãe")
    cns = st.text_input("Cartão Nacional de Saúde (CNS)")

    st.divider()

    st.header("Geração de Documentos")

    if st.button("Gerar Capa de Prontuário em PDF"):
        if nome and data_nasc: # Validação simples
            with st.spinner("A gerar PDF... A primeira vez pode demorar um pouco."):
                dados_paciente = {
                    "nome": nome,
                    "data_nasc": data_nasc,
                    "cpf": cpf,
                    "mae": nome_mae,
                    "cns": cns
                }
                
                pdf_buffer = gerar_capa_prontuario_pdf(dados_paciente)

                if pdf_buffer:
                    st.success("PDF gerado com sucesso!")
                    st.download_button(
                        label="Baixar Capa do Prontuário",
                        data=pdf_buffer,
                        file_name=f"capa_prontuario_{nome.replace(' ', '_').lower()}.pdf",
                        mime="application/pdf"
                    )
        else:
            st.warning("Por favor, preencha pelo menos o Nome e a Data de Nascimento.")


if __name__ == "__main__":
    main()
