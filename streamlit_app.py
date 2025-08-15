import streamlit as st
import gspread
import json
import os
import pandas as pd
import google.generativeai as genai
from io import BytesIO
from datetime import datetime
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch

# --- Configuração da Página e Título ---
st.set_page_config(
    page_title="Coleta Inteligente",
    page_icon="🤖",
    layout="wide"
)

st.title("🤖 Coleta Inteligente")

# --- CONEXÃO E VARIÁVEIS DE AMBIENTE ---
try:
    gemini_api_key = st.secrets["GEMINIKEY"]
    google_sheets_id = st.secrets["SHEETSID"]
    google_credentials_dict = st.secrets["gcp_service_account"]
except KeyError as e:
    st.error(f"Erro de configuração: A chave secreta '{e.args[0]}' não foi encontrada. Verifique o nome no painel de Secrets do Streamlit Cloud.")
    st.stop()
except Exception as e:
    st.error(f"Erro inesperado ao carregar as chaves secretas. Verifique a formatação no painel de Secrets. Erro: {e}")
