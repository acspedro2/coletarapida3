import streamlit as st
import requests
import json
import cohere
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

# --- Configurações de API e credenciais ---
COHEREKEY = "sua_chave_cohere_aqui"
OCRSPACEKEY = "sua_chave_ocrspace_aqui"
SHEETSID = "id_da_planilha_google_aqui"

# Credenciais do Google Service Account (JSON copiado do GCP)
gcp_service_account = """
{
  "type": "service_account",
  "project_id": "seu_projeto_id",
  "private_key_id": "xxxxxxxxxxxxxxxxxxxx",
  "private_key": "-----BEGIN PRIVATE KEY-----\nxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n-----END PRIVATE KEY-----\n",
  "client_email": "seu_email@seuprojeto.iam.gserviceaccount.com",
  "client_id": "xxxxxxxxxxxxxxxxxxxx",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/seu_email%40seuprojeto.iam.gserviceaccount.com"
}
"""

# --- Inicializar cliente Cohere ---
co = cohere.Client(api_key=COHEREKEY)

# --- Função: OCR com OCR.Space ---
def ocr_space_api(file):
    url = "https://api.ocr.space/parse/image"
    payload = {"language": "por", "isOverlayRequired": False}
    files = {"file": file}
    headers = {"apikey": OCRSPACEKEY}

    response = requests.post(url, data=payload, files=files, headers=headers)
    result = response.json()
    try:
        return result["ParsedResults"][0]["ParsedText"]
    except:
        return "Erro no OCR"

# --- Função: Extração com Cohere ---
def extrair_dados_com_cohere(texto_extraido: str) -> str:
    try:
        response = co.chat(
            model="command-r-plus",
            message=f"Extraia os principais dados estruturados desta ficha SUS:\n{texto_extraido}"
        )
        return response.text
    except Exception as e:
        return f"Erro ao chamar Cohere: {e}"

# --- Função: Salvar no Google Sheets ---
def salvar_no_sheets(dados):
    try:
        creds_dict = json.loads(gcp_service_account)
        creds = Credentials.from_service_account_info(creds_dict)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEETSID).sheet1

        # Adiciona como linha única (pode ajustar conforme estrutura)
        valores = [dados]
        sheet.append_row(valores)
        return "✅ Dados salvos com sucesso no Google Sheets!"
    except Exception as e:
        return f"Erro ao salvar no Sheets: {e}"

# --- Interface Streamlit ---
st.title("📑 Coleta Rápida SUS")

uploaded_file = st.file_uploader("Envie a ficha SUS (imagem)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    st.image(Image.open(uploaded_file), caption="Imagem enviada", use_column_width=True)

    if st.button("Processar"):
        with st.spinner("Fazendo OCR..."):
            texto_extraido = ocr_space_api(uploaded_file)
            st.text_area("📄 Texto OCR:", texto_extraido, height=200)

        with st.spinner("Extraindo dados com Cohere..."):
            dados_extraidos = extrair_dados_com_cohere(texto_extraido)
            st.text_area("📊 Dados Estruturados:", dados_extraidos, height=200)

        if st.button("Salvar no Google Sheets"):
            resultado = salvar_no_sheets(dados_extraidos)
            st.success(resultado)
