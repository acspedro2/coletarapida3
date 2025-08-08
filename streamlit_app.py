import streamlit as st
import gspread
import requests
import json
import os
import re
from io import BytesIO
from datetime import datetime
from gspread.exceptions import APIError
import pandas as pd
import cv2
import numpy as np
import google.generativeai as genai
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

# --- Configuração da Página e Título ---
st.set_page_config(
    page_title="Aplicativo de Coleta Rápida",
    page_icon=":camera:",
    layout="wide"
)

st.title("Aplicativo de Coleta Rápida")
st.markdown("---")

# --- CONEXÃO E VARIÁVEIS DE AMBIENTE ---
try:
    credenciais_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_CREDENTIALS")
    planilha_id = os.environ.get("GOOGLE_SHEETS_ID")
    ocr_api_key = os.environ.get("OCR_SPACE_API_KEY")
    gemini_api_key = os.environ.get("GOOGLE_GEMINI_API_KEY")

    if not credenciais_json or not planilha_id or not ocr_api_key or not gemini_api_key:
        st.error("Erro de configuração: Variáveis de ambiente faltando no Render. Verifique a configuração.")
        st.stop()

    credenciais = json.loads(credenciais_json)
    
except Exception as e:
    st.error(f"Erro ao carregar as variáveis de ambiente. Verifique os nomes e valores. Erro: {e}")
    st.stop()

# --- FUNÇÕES ---

@st.cache_resource
def conectar_planilha():
    """Tenta conectar com o Google Sheets e retorna o objeto da planilha."""
    try:
        gc = gspread.service_account_from_dict(credenciais)
        planilha = gc.open_by_key(planilha_id).sheet1 
        return planilha
    except APIError as e:
        st.error("Erro de permissão! Verifique se a planilha foi compartilhada com a conta de serviço.")
        st.stop()
    except Exception as e:
        st.error(f"Não foi possível conectar à planilha. Verifique a ID e as permissões. Erro: {e}")
        st.stop()

@st.cache_data(ttl=60)
def ler_dados_da_planilha():
    """Lê todos os dados da planilha para o dashboard."""
    try:
        planilha_obj = conectar_planilha()
        dados = planilha_obj.get_all_records()
        df = pd.DataFrame(dados)
        return df
    except Exception as e:
        st.error(f"Erro ao ler dados da planilha para o dashboard. Erro: {e}")
        return pd.DataFrame()

def detectar_asterisco(image_bytes):
    """Detecta a presença de um asterisco no canto superior esquerdo da imagem."""
    try:
        image_bytes.seek(0)
        np_array = np.frombuffer(image_bytes.read(), np.uint8)
        imagem_cv = cv2.imdecode(np_array, cv2.IMREAD_COLOR)

        imagem_cinza = cv2.cvtColor(imagem_cv, cv2.COLOR_BGR2GRAY)
        
        roi = imagem_cinza[0:200, 0:200]
        
        template = np.array([
            [0, 0, 0, 255, 0, 0, 0],
            [0, 0, 255, 255, 255, 0, 0],
            [0, 255, 0, 255, 0, 255, 0],
            [255, 255, 255, 255, 255, 255, 255],
            [0, 255, 0, 255, 0, 255, 0],
            [0, 0, 255, 255, 255, 0, 0],
            [0, 0, 0, 255, 0, 0, 0]
        ], dtype=np.uint8)
        
        template = cv2.resize(template, (30, 30))

        res = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)

        if max_val > 0.6:
            return True
        return False
    except Exception as e:
        return False

def extrair_dados_com_gemini(image_bytes):
    """Extrai dados da imagem usando a API do Google Gemini."""
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel('gemini-2.5-pro')

    image_bytes.seek(0)
    image = Image.open(image_bytes)

    prompt = """
    Analise esta imagem de um formulário e extraia as seguintes informações de forma estruturada:
    - ID Família (ex: FAM001)
    - Nome Completo
    - Data de Nascimento (formato DD/MM/AAAA)
    - Telefone (com DDD)
    - CPF (formato 000.000.000-00)
    - Nome da Mãe
    - Nome do Pai
    - Sexo (ex: FEMININO, MASCULINO)
    - CNS (formato 000 0000 0000 0000)
    - Município de Nascimento
    Se algum dado não for encontrado, retorne um campo vazio.
    Retorne os dados como um objeto JSON. Exemplo:
    {"ID Família": "...", "Nome Completo": "...", "Data de Nascimento": "...", "Telefone": "...", "CPF": "...", "Nome da Mãe": "...", "Nome do Pai": "...", "Sexo": "...", "CNS": "...", "Município de Nascimento": "..."}
    """
    
    try:
        response = model.generate_content([prompt, image])
        
        if response.text:
            json_string = response.text.replace('```json', '').replace('```', '').strip()
            dados = json.loads(json_string)
            return dados
        else:
            st.warning(f"A IA bloqueou a resposta para o arquivo. A imagem pode conter dados sensíveis ou foi sinalizada pelo filtro de segurança.")
            return None
            
    except Exception as e:
        st.error(f"Erro ao extrair dados com Gemini. Verifique a chave da API e a imagem. Erro: {e}")
        return None

def calcular_idade(data_nascimento):
    """Calcula a idade a partir da data de nascimento."""
    if not data_nascimento:
        return None
    try:
        data_nasc = datetime.strptime(data_nascimento, '%d/%m/%Y')
        hoje = datetime.now()
        return hoje.year - data_nasc.year - ((hoje.month, hoje.day) < (data_nasc.month, data_nasc.day))
    except (ValueError, TypeError):
        return None

def destacar_idosos(linha):
    """Aplica estilo à linha se a idade for 60 ou mais."""
    idade = calcular_idade(linha.get('Data de Nascimento', ''))
    if idade is not None and idade >= 60:
