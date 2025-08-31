# streamlit_app.py - VERSÃO LEVE E FUNCIONAL

import streamlit as st
import requests
import json
import cohere
import gspread
from PIL import Image
import time
import re
import pandas as pd
from datetime import datetime
from io import BytesIO
from dateutil.relativedelta import relativedelta
from pdf2image import convert_from_bytes

# --- CONFIGURAÇÕES E CLIENTES (INICIALIZAÇÃO) ---
# Tenta inicializar os clientes uma única vez
try:
    cohere_client = cohere.Client(st.secrets["COHERE_API_KEY"])
except Exception as e:
    st.error(f"Erro ao inicializar o cliente Cohere: {e}")
    cohere_client = None

# --- MOTOR DE REGRAS: CALENDÁRIO NACIONAL DE IMUNIZAÇÕES (PNI) ---
CALENDARIO_PNI = [
    {"vacina": "BCG", "dose": "Dose Única", "idade_meses": 0, "detalhe": "Protege contra formas graves de tuberculose."},
    {"vacina": "Hepatite B", "dose": "1ª Dose", "idade_meses": 0, "detalhe": "Primeira dose, preferencialmente nas primeiras 12-24 horas de vida."},
    {"vacina": "Pentavalente", "dose": "1ª Dose", "idade_meses": 2, "detalhe": "Protege contra Difteria, Tétano, Coqueluche, Hepatite B e Haemophilus influenzae B."},
    {"vacina": "VIP (Poliomielite inativada)", "dose": "1ª Dose", "idade_meses": 2, "detalhe": "Protege contra a poliomielite."},
    {"vacina": "Pneumocócica 10V", "dose": "1ª Dose", "idade_meses": 2, "detalhe": "Protege contra doenças pneumocócicas."},
    {"vacina": "Rotavírus", "dose": "1ª Dose", "idade_meses": 2, "detalhe": "Idade máxima para iniciar o esquema: 3 meses e 15 dias."},
    {"vacina": "Meningocócica C", "dose": "1ª Dose", "idade_meses": 3, "detalhe": "Protege contra a meningite C."},
    {"vacina": "Pentavalente", "dose": "2ª Dose", "idade_meses": 4, "detalhe": "Reforço da proteção."},
    {"vacina": "VIP (Poliomielite inativada)", "dose": "2ª Dose", "idade_meses": 4, "detalhe": "Reforço da proteção."},
    {"vacina": "Pneumocócica 10V", "dose": "2ª Dose", "idade_meses": 4, "detalhe": "Reforço da proteção."},
    {"vacina": "Rotavírus", "dose": "2ª Dose", "idade_meses": 4, "detalhe": "Idade máxima para a última dose: 7 meses e 29 dias."},
    {"vacina": "Meningocócica C", "dose": "2ª Dose", "idade_meses": 5, "detalhe": "Reforço da proteção."},
    {"vacina": "Pentavalente", "dose": "3ª Dose", "idade_meses": 6, "detalhe": "Finalização do esquema primário."},
    {"vacina": "VIP (Poliomielite inativada)", "dose": "3ª Dose", "idade_meses": 6, "detalhe": "Finalização do esquema primário."},
    {"vacina": "Febre Amarela", "dose": "Dose Inicial", "idade_meses": 9, "detalhe": "Proteção contra a febre amarela. Reforço aos 4 anos."},
    {"vacina": "Tríplice Viral", "dose": "1ª Dose", "idade_meses": 12, "detalhe": "Protege contra Sarampo, Caxumba e Rubéola."},
    {"vacina": "Pneumocócica 10V", "dose": "Reforço", "idade_meses": 12, "detalhe": "Dose de reforço."},
    {"vacina": "Meningocócica C", "dose": "Reforço", "idade_meses": 12, "detalhe": "Dose de reforço."},
]

# --- FUNÇÕES ---
# (Aqui entram todas as suas funções originais que NÃO dependem de reportlab, matplotlib, etc.)
def analisar_carteira_vacinacao(data_nascimento_str, vacinas_administradas):
    try:
        data_nascimento = datetime.strptime(data_nascimento_str, "%d/%m/%Y")
    except ValueError:
        return {"erro": "Formato da data de nascimento inválido. Utilize DD/MM/AAAA."}
    hoje = datetime.now()
    idade = relativedelta(hoje, data_nascimento)
    idade_total_meses = idade.years * 12 + idade.months
    vacinas_tomadas_set = {(v['vacina'], v['dose']) for v in vacinas_administradas}
    relatorio = {"em_dia": [], "em_atraso": [], "proximas_doses": []}
    for regra in CALENDARIO_PNI:
        vacina_requerida = (regra['vacina'], regra['dose'])
        idade_recomendada_meses = regra['idade_meses']
        if idade_total_meses >= idade_recomendada_meses:
            if vacina_requerida in vacinas_tomadas_set:
                relatorio["em_dia"].append(regra)
            else:
                relatorio["em_atraso"].append(regra)
        else:
            relatorio["proximas_doses"].append(regra)
    return relatorio

# ... Adicione aqui as suas outras funções como validar_cpf, ocr_space_api, extrair_dados_com_cohere, etc.

# --- INTERFACE PRINCIPAL ---
def main():
    st.set_page_config(page_title="Coleta Inteligente", page_icon="🤖", layout="wide")
    st.title("Coleta Inteligente - Versão Funcional")

    st.info("Bem-vindo! Esta é a versão funcional da aplicação, com o módulo de relatórios desativado para economizar memória.")

    # Exemplo de como a sua interface pode começar
    st.header("Análise de Carteira de Vacinação")
    
    if cohere_client is None:
        st.error("Cliente Cohere não inicializado. Verifique os segredos.")
        return

    data_nasc = st.text_input("Data de Nascimento da Criança (DD/MM/AAAA)", "01/01/2024")
    if st.button("Analisar Carteira (Exemplo)"):
        # Exemplo sem vacinas administradas
        relatorio = analisar_carteira_vacinacao(data_nasc, [])
        if "erro" in relatorio:
            st.error(relatorio["erro"])
        else:
            st.subheader("Status Vacinal")
            
            st.write("**Vacinas em Atraso:**")
            if relatorio["em_atraso"]:
                for vacina in relatorio["em_atraso"]:
                    st.warning(f"- **{vacina['vacina']} ({vacina['dose']})**: {vacina['detalhe']}")
            else:
                st.write("Nenhuma vacina em atraso.")

            st.write("**Próximas Doses Recomendadas:**")
            if relatorio["proximas_doses"]:
                for vacina in relatorio["proximas_doses"]:
                    st.info(f"- **{vacina['vacina']} ({vacina['dose']})**: Recomendada aos {vacina['idade_meses']} meses.")
            else:
                st.write("Esquema vacinal completo para a idade.")

if __name__ == "__main__":
    main()
