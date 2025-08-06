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

# --- Configuração da Página e Título ---
st.set_page_config(
    page_title="Aplicativo de Coleta Rápida",
    page_icon=":camera:",
    layout="centered"
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
        st.error("Erro de configuração: Variáveis de ambiente faltando. Verifique a configuração no Render.")
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
    Se algum dado não for encontrado, retorne um campo vazio.
    Retorne os dados como um objeto JSON. Exemplo:
    {"ID Família": "...", "Nome Completo": "...", "Data de Nascimento": "...", "Telefone": "...", "CPF": "..."}
    """
    
    try:
        response = model.generate_content([prompt, image])
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        dados = json.loads(json_string)
        return dados
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
    idade = calcular_idade(linha['Data de Nascimento'])
    if idade is not None and idade >= 60:
        return ['background-color: orange'] * len(linha)
    else:
        return [''] * len(linha)

# --- STREAMLIT APP ---
planilha_conectada = conectar_planilha()
st.subheader("Envie a imagem da ficha SUS")
uploaded_file = st.file_uploader("Escolha uma imagem", type=['jpg', 'jpeg', 'png'])

if uploaded_file is not None:
    st.image(uploaded_file, caption="Pré-visualização", use_container_width=True)
    
    with st.spinner("Analisando imagem..."):
        image_bytes_original = BytesIO(uploaded_file.read())
        
        asterisco_presente = detectar_asterisco(image_bytes_original)
        
        image_bytes_original.seek(0)
        dados = extrair_dados_com_gemini(image_bytes_original)

    if not dados:
        st.error("Erro ao processar imagem ou extrair dados. Verifique a imagem e tente novamente.")
    else:
        st.success("Dados extraídos com sucesso!")
        
        # Formata o nome se o asterisco for detectado
        nome_paciente = dados.get('Nome Completo', '')
        if asterisco_presente:
            nome_paciente = f"**{nome_paciente.upper()}**"
        
        st.subheader("Dados Extraídos:")
        
        dados_formatados = {
            'ID Família': dados.get('ID Família', ''),
            'Nome': nome_paciente,
            'Data de Nascimento': dados.get('Data de Nascimento', ''),
            'Telefone': dados.get('Telefone', ''),
            'CPF': dados.get('CPF', ''),
            'Data de Envio': datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        }
        df_dados = pd.DataFrame([dados_formatados])
        
        st.dataframe(df_dados.style.apply(destacar_idosos, axis=1), hide_index=True, use_container_width=True)

        if st.button("✅ Enviar para Google Sheets"):
            if not dados.get('ID Família') or not dados.get('Nome Completo'):
                st.warning("Dados principais (ID e Nome) não foram encontrados. Envio cancelado.")
            else:
                try:
                    nova_linha = [
                        dados.get('ID Família', ''),
                        dados.get('Nome Completo', ''),
                        dados.get('Data de Nascimento', ''),
                        dados.get('Telefone', ''),
                        dados.get('CPF', ''),
                        datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                    ]
                    
                    planilha_conectada.append_row(nova_linha)
                    st.success("Dados enviados para a planilha com sucesso!")
                except Exception as e:
                    st.error(f"Erro ao enviar dados para a planilha. Verifique se as colunas estão corretas. Erro: {e}")
