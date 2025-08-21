import streamlit as st
import requests
import json
import cohere
from cohere.responses.chat import ChatResponse
from google.oauth2.service_account import Credentials
import gspread
import pandas as pd
from PIL import Image
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

# --- CONFIGURAÇÕES ---
COHEREKEY = "sua_chave_cohere_aqui"
OCRSPACEKEY = "sua_chave_ocrspace_aqui"
SHEETSID = "id_da_planilha_google_aqui"

gcp_service_account = """
{
  "type": "service_account",
  "project_id": "seu_projeto_id",
  "private_key_id": "xxxxxxxxxxxxxxxxxxxx",
  "private_key": "-----BEGIN PRIVATE KEY-----\\nxxxxxxxxxxxxxxxxxxxxxxxxxxxx\\n-----END PRIVATE KEY-----\\n",
  "client_email": "seu_email@seuprojeto.iam.gserviceaccount.com",
  "client_id": "xxxxxxxxxxxxxxxxxxxx",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/seu_email%40seuprojeto.iam.gserviceaccount.com"
}
"""

# --- INICIALIZA CLIENTES ---
co = cohere.Client(COHEREKEY)

# --- FUNÇÕES ---
def extrair_texto_ocr(image_file):
    url_api = "https://api.ocr.space/parse/image"
    result = requests.post(
        url_api,
        files={"filename": image_file},
        data={"apikey": OCRSPACEKEY, "language": "por"}
    )
    result = result.json()
    if result["IsErroredOnProcessing"]:
        return None
    return result["ParsedResults"][0]["ParsedText"]


def extrair_dados_com_cohere(texto_extraido: str) -> str:
    try:
        response: ChatResponse = co.chat(
            model="command-r-plus",
            message=f"Extraia os principais dados estruturados desta ficha SUS:\n{texto_extraido}"
        )
        return response.text
    except Exception as e:
        return f"Erro ao chamar Cohere: {e}"


def salvar_no_sheets(dados):
    try:
        creds_dict = json.loads(gcp_service_account)
        creds = Credentials.from_service_account_info(creds_dict)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEETSID).sheet1

        # se dados for string, transforma em lista para salvar
        if isinstance(dados, dict):
            valores = list(dados.values())
        else:
            valores = [dados]

        sheet.append_row(valores)
        return "✅ Dados salvos com sucesso no Google Sheets!"
    except Exception as e:
        return f"Erro ao salvar no Sheets: {e}"


def exportar_pdf(nome_arquivo, texto):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.drawString(100, 800, "Ficha SUS - Dados Extraídos")
    c.drawString(100, 780, texto[:4000])  # limita para não estourar
    c.save()
    buffer.seek(0)
    return buffer


# --- INTERFACE STREAMLIT ---
st.title("📄 Coleta Inteligente - Fichas SUS")

uploaded_file = st.file_uploader("Envie a imagem da ficha SUS", type=["jpg", "jpeg", "png", "pdf"])

if uploaded_file:
    st.image(uploaded_file, caption="Imagem Carregada.", use_column_width=True)

    if st.button("🔎 Extrair Dados da Imagem"):
        with st.spinner("Processando imagem..."):
            texto_extraido = extrair_texto_ocr(uploaded_file)

            if texto_extraido:
                st.subheader("📜 Texto OCR Extraído")
                st.text(texto_extraido)

                st.subheader("🤖 Dados Estruturados (Cohere)")
                dados = extrair_dados_com_cohere(texto_extraido)
                st.success(dados)

                # salvar no Google Sheets
                resultado = salvar_no_sheets(dados)
                st.info(resultado)

                # exportar para PDF
                pdf_buffer = exportar_pdf("ficha.pdf", dados)
                st.download_button(
                    label="📥 Baixar PDF com Dados",
                    data=pdf_buffer,
                    file_name="ficha_extraida.pdf",
                    mime="application/pdf"
                )
            else:
                st.error("❌ Não foi possível extrair texto da imagem.")
