import streamlit as st
import gspread
import requests
import json
import os
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
        st.error("Erro de configuração: Variáveis de ambiente faltando no Render. Verifique a configuração.")
        st.stop()

    credenciais = json.loads(credenciais_json)
    
except Exception as e:
    st.error(f"Erro ao carregar as variáveis de ambiente. Verifique se os nomes e valores estão corretos. Erro: {e}")
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

def pre_processar_imagem_ocr(image_bytes):
    """Aplica filtros para melhorar a qualidade da imagem para o OCR tradicional."""
    # ... (código existente para pré-processamento, sem alterações)
    try:
        np_array = np.frombuffer(image_bytes.read(), np.uint8)
        imagem = cv2.imdecode(np_array, cv2.IMREAD_COLOR)
        imagem_cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
        imagem_binaria = cv2.adaptiveThreshold(imagem_cinza, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)
        is_success, buffer = cv2.imencode(".png", imagem_binaria)
        if is_success:
            return BytesIO(buffer)
        else:
            image_bytes.seek(0)
            return image_bytes
    except Exception as e:
        st.warning(f"Erro ao pré-processar a imagem. Usando a imagem original. Erro: {e}")
        image_bytes.seek(0)
        return image_bytes

def extrair_texto_ocr(image_bytes):
    """Tenta extrair texto de uma imagem usando o serviço de OCR."""
    try:
        response = requests.post(
            'https://api.ocr.space/parse/image',
            headers={'apikey': ocr_api_key},
            files={'filename': image_bytes},
            data={'language': 'por', 'isOverlayRequired': False},
            timeout=15
        )
        response.raise_for_status()
        result = response.json()
        if result['OCRExitCode'] == 1 and result['ParsedResults']:
            return result['ParsedResults'][0]['ParsedText']
        else:
            return None
    except requests.exceptions.RequestException:
        return None
    except Exception:
        return None

def detectar_asterisco(image_bytes):
    """Detecta a presença de um asterisco no canto superior esquerdo da imagem."""
    try:
        np_array = np.frombuffer(image_bytes.read(), np.uint8)
        imagem_cv = cv2.imdecode(np_array, cv2.IMREAD_COLOR)

        # Converte para tons de cinza
        imagem_cinza = cv2.cvtColor(imagem_cv, cv2.COLOR_BGR2GRAY)
        
        # Define a Região de Interesse (ROI) no canto superior esquerdo
        roi = imagem_cinza[0:200, 0:200]
        
        # Cria um modelo de asterisco simples
        template = np.array([
            [0, 0, 0, 255, 0, 0, 0],
            [0, 0, 255, 255, 255, 0, 0],
            [0, 255, 0, 255, 0, 255, 0],
            [255, 255, 255, 255, 255, 255, 255],
            [0, 255, 0, 255, 0, 255, 0],
            [0, 0, 255, 255, 255, 0, 0],
            [0, 0, 0, 255, 0, 0, 0]
        ], dtype=np.uint8)
        
        # Redimensiona o template para um tamanho apropriado
        template = cv2.resize(template, (30, 30))

        # Procura o asterisco na ROI usando template matching
        res = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

        # Se o valor de correspondência for alto, considera que o asterisco foi encontrado
        if max_val > 0.6:  # O valor 0.6 é um threshold, pode ser ajustado
            return True
        return False
    except Exception as e:
        st.warning(f"Erro ao detectar asterisco. Erro: {e}")
        return False

def extrair_dados_com_gemini(image_bytes):
    """
    Extrai dados da imagem usando a API do Google Gemini.
    """
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel('gemini-pro-vision')

    image = Image.open(image_bytes)

    # O prompt instrui o modelo a extrair informações específicas do formulário
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

# --- STREAMLIT APP ---
planilha_conectada = conectar_planilha()
st.subheader("Envie a imagem da ficha SUS")
uploaded_file = st.file_uploader("Escolha uma imagem", type=['jpg', 'jpeg', 'png'])

if uploaded_file is not None:
    st.image(uploaded_file, caption="Pré-visualização", use_container_width=True)
    
    with st.spinner("Analisando imagem..."):
        image_bytes_original = BytesIO(uploaded_file.read())
        image_bytes_original.seek(0)
        
        # Detecção de asterisco
        asterisco_presente = detectar_asterisco(image_bytes_original)
        image_bytes_original.seek(0)
        
        # Extração de dados com Gemini
        dados = extrair_dados_com_gemini(image_bytes_original)

    if not dados:
        st.error("Erro ao processar imagem ou extrair dados. Verifique a imagem e tente novamente.")
    else:
        st.success("Dados extraídos com sucesso!")
        
        st.subheader("Dados Extraídos:")
        
        # Formata o nome se o asterisco for detectado
        nome_paciente = dados.get('Nome Completo', '')
        if asterisco_presente:
            nome_paciente = f"**{nome_paciente.upper()}**"
        
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**ID Família:** {dados.get('ID Família', '')}")
            st.write(f"**Nome:** {nome_paciente}")
            st.write(f"**Data de Nascimento:** {dados.get('Data de Nascimento', '')}")
        with col2:
            st.write(f"**CPF:** {dados.get('CPF', '')}")
            st.write(f"**Telefone:** {dados.get('Telefone', '')}")
            st.write(f"**Data de Envio:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

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
