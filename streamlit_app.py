# streamlit_app.py

import streamlit as st
import gspread
import cohere
# Adicione TODOS os outros imports do seu ficheiro original aqui
# (requests, json, pandas, etc.)

st.set_page_config(page_title="Teste de Conexão", layout="wide")
st.title("Depuração - Passo 1: Teste de Conexões e Segredos")

# --- Função de Conexão (do seu código original) ---
@st.cache_resource
def conectar_planilha():
    try:
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
        return client
    except Exception as e:
        # Esta função irá falhar se st.secrets["gcp_service_account"] estiver errado
        st.error("Erro DENTRO da função conectar_planilha()")
        st.exception(e)
        return None

# --- Início do Teste ---
try:
    st.info("A tentar ler os segredos e conectar...")

    # Teste 1: Conectar ao Google Sheets
    client = conectar_planilha()
    if client:
        st.success("✅ SUCESSO! Conexão com o Google Sheets funcionou.")
    else:
        st.error("❌ FALHA na conexão com o Google Sheets. Verifique o erro acima.")

    # Teste 2: Ler a chave da API do Cohere
    cohere_key = st.secrets["COHERE_API_KEY"]
    st.success("✅ SUCESSO! Chave da API do Cohere lida com sucesso.")

    # Teste 3: Ler a chave da API do OCR
    ocr_key = st.secrets["OCR_API_KEY"]
    st.success("✅ SUCESSO! Chave da API do OCR.space lida com sucesso.")

except Exception as e:
    st.error("❌ ERRO! A aplicação falhou ao tentar ler uma das chaves de API diretamente.")
    st.write("Verifique se os nomes das chaves no painel de Segredos do Streamlit estão corretos: `gcp_service_account`, `COHERE_API_KEY`, `OCR_API_KEY`.")
    st.exception(e)

