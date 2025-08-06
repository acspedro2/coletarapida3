import streamlit as st
import requests
import re
from io import BytesIO
import json
import os
import gspread
from datetime import datetime

# --- Configuração da Página e Título ---
st.set_page_config(
    page_title="Leitura de Fichas SUS",
    page_icon="🩺",
    layout="centered"
)

st.title("🩺 Leitura Automática de Fichas SUS")
st.markdown("---")

# --- CONEXÃO COM O GOOGLE SHEETS E SECRETS ---

# 1. Obter as credenciais e a ID da planilha das variáveis de ambiente do Render
# Usamos os.environ.get() para garantir a compatibilidade com o Render
try:
    credenciais_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_CREDENTIALS")
    planilha_id = os.environ.get("GOOGLE_SHEETS_ID")
    
    # Adicionando o API Key do OCR Space como variável de ambiente
    ocr_api_key = os.environ.get("OCR_SPACE_API_KEY")

    if not credenciais_json or not planilha_id or not ocr_api_key:
        st.error("Erro: Variáveis de ambiente faltando no Render. Verifique a configuração.")
        st.stop()

    credenciais = json.loads(credenciais_json)
    gc = gspread.service_account_from_dict(credenciais)
    
    # Acessa a primeira aba da planilha com o ID fornecido
    planilha = gc.open_by_key(planilha_id).sheet1 
    
except Exception as e:
    st.error(f"Erro ao conectar com o Google Sheets ou carregar credenciais. Verifique as variáveis de ambiente no Render. Erro: {e}")
    st.stop()

# --- FUNÇÕES ---

def extrair_texto_ocr(image_bytes):
    try:
        response = requests.post(
            'https://api.ocr.space/parse/image',
            headers={'apikey': ocr_api_key},
            files={'filename': image_bytes},
            data={'language': 'por', 'isOverlayRequired': False}
        )
        response.raise_for_status() # Lança um erro se a resposta HTTP for um erro
        result = response.json()
        
        if result['OCRExitCode'] == 1:
            return result['ParsedResults'][0]['ParsedText']
        else:
            st.warning("O OCR não conseguiu extrair texto da imagem. Tente uma imagem mais clara.")
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de conexão com o serviço OCR. Verifique sua chave de API e a internet. Erro: {e}")
        return None
    except (KeyError, IndexError) as e:
        st.error(f"Formato de resposta do OCR inesperado. Erro: {e}")
        return None

def extrair_dados(texto):
    # Regex adaptado para o formato do documento que você enviou
    dados = {
        'ID Família': re.search(r"FAM\s?(\d+)", texto),
        'Nome': re.search(r"(?<=Nome:\n)[A-ZÇ\s]+", texto),
        'Data de Nascimento': re.search(r"Nascimento\s*:\s*(\d{2}/\d{2}/\d{4})", texto),
        'Telefone': re.search(r"(?<=Telefone\(s\)\nCELULAR\n\()\d{2}\)\s?\d{4,5}[-]?\d{4}", texto),
        'CPF': re.search(r"CPF:\n(\d{3}\.\d{3}\.\d{3}-\d{2})", texto)
    }

    return {
        'ID Família': dados['ID Família'].group(0) if dados['ID Família'] else '',
        'Nome': dados['Nome'].group(0).strip() if dados['Nome'] else '',
        'Data de Nascimento': dados['Data de Nascimento'].group(1) if dados['Data de Nascimento'] else '',
        'Telefone': dados['Telefone'].group(0).strip() if dados['Telefone'] else '',
        'CPF': dados['CPF'].group(1) if dados['CPF'] else '',
        'Data de Envio': datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    }

# --- STREAMLIT APP ---

st.subheader("Envie a imagem da ficha SUS")

uploaded_file = st.file_uploader("Escolha uma imagem", type=['jpg', 'jpeg', 'png'])

if uploaded_file is not None:
    st.image(uploaded_file, caption="Imagem enviada", use_column_width=True)
    
    with st.spinner("Analisando imagem via OCR..."):
        image_bytes = BytesIO(uploaded_file.getvalue())
        texto = extrair_texto_ocr(image_bytes)

    if not texto:
        st.error("Erro ao processar imagem. Verifique a imagem e tente novamente.")
    else:
        st.success("Texto extraído com sucesso!")
        st.text_area("Texto completo extraído:", texto, height=200)

        dados = extrair_dados(texto)
        
        st.subheader("Dados Extraídos:")
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**ID Família:** {dados['ID Família']}")
            st.write(f"**Nome:** {dados['Nome']}")
            st.write(f"**Data de Nascimento:** {dados['Data de Nascimento']}")
        with col2:
            st.write(f"**CPF:** {dados['CPF']}")
            st.write(f"**Telefone:** {dados['Telefone']}")
            st.write(f"**Data de Envio:** {dados['Data de Envio']}")

        if st.button("✅ Enviar para Google Sheets"):
            try:
                # Cria a lista com os dados na ordem correta das colunas da planilha
                nova_linha = [
                    dados['ID Família'],
                    dados['Nome'],
                    dados['Data de Nascimento'],
                    dados['Telefone'],
                    dados['CPF'],
                    dados['Data de Envio']
                ]
                
                planilha.append_row(nova_linha)
                st.success("Dados enviados para a planilha com sucesso!")
            except Exception as e:
                st.error(f"Erro ao enviar dados para a planilha. Verifique se as colunas estão corretas. Erro: {e}")

