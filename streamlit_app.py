import streamlit as st
import gspread
import json
import os
import pandas as pd
import google.generativeai as genai
from io import BytesIO
from datetime import datetime
from PIL import Image

# --- Configuração da Página e Título ---
st.set_page_config(
    page_title="Coleta Inteligente",
    page_icon="🤖",
    layout="wide"
)

st.title("🤖 Coleta Inteligente")
st.markdown("---")

# --- CONEXÃO E VARIÁVEIS DE AMBIENTE ---
try:
    # Carrega os segredos do Streamlit Cloud
    gemini_api_key = st.secrets["GEMINIKEY"]
    google_sheets_id = st.secrets["SHEETSID"]
    
    # Carrega as credenciais da seção [gcp_service_account] que definimos nos segredos
    google_credentials_dict = st.secrets["gcp_service_account"]

except KeyError as e:
    st.error(f"Erro de configuração: A chave secreta '{e.args[0]}' não foi encontrada. Verifique o nome no painel de Secrets do Streamlit Cloud.")
    st.stop()
except Exception as e:
    st.error(f"Erro inesperado ao carregar as chaves secretas. Verifique a formatação no painel de Secrets. Erro: {e}")
    st.stop()


# --- FUNÇÕES ---

@st.cache_resource
def conectar_planilha():
    """Conecta com o Google Sheets usando as credenciais."""
    try:
        gc = gspread.service_account_from_dict(google_credentials_dict)
        planilha = gc.open_by_key(google_sheets_id).sheet1
        return planilha
    except Exception as e:
        st.error(f"Não foi possível conectar à planilha. Verifique a ID, as permissões de partilha e o formato das credenciais. Erro: {e}")
        st.stop()

def extrair_dados_com_gemini(image_bytes):
    """Extrai dados da imagem usando a API do Google Gemini."""
    try:
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel('gemini-pro-vision')

        image_bytes.seek(0)
        image = Image.open(image_bytes)

        prompt = """
        Analise esta imagem de
