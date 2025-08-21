import streamlit as st
import requests
import pandas as pd
import cohere
from PIL import Image
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import io
import json

# --- Configurações de API e credenciais ---
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

# --- Inicializa Cohere ---
co = cohere.Client(COHEREKEY)

# --- Função para OCR com OCR.Space ---
def ocr_space_file(filename, api_key):
    payload = {'isOverlayRequired': False, 'apikey': api_key, 'language': 'por'}
    with open(filename, 'rb') as f:
        r = requests.post('https://api.ocr.space/parse/image',
                          files={filename: f},
                          data=payload)
    return r.json()

# --- Função para extrair dados com Cohere ---
def extrair_dados_com_cohere(texto_extraido: str) -> str:
    try:
        response = co.chat(
            model="command-r-plus",
            message=f"Extraia os dados estruturados deste texto em formato JSON com campos claros (nome, cpf, data_nascimento, endereco, telefone, etc): {texto_extraido}"
        )
        return response.text
    except Exception as e:
        return f"Erro ao chamar Cohere: {e}"

# --- Função para salvar no Google Sheets ---
def salvar_no_sheets(dados):
    try:
        creds_dict = json.loads(gcp_service_account)
        scope = ["https://spreadsheets.google.com/feeds",
                 "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SHEETSID).sheet1

        valores = list(dados.values())
        sheet.append_row(valores)
        return "✅ Dados salvos com sucesso no Google Sheets!"
    except Exception as e:
        return f"Erro ao salvar no Sheets: {e}"

# --- Função para gerar PDF ---
def gerar_pdf(dados: dict) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    largura, altura = A4

    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, altura - 50, "Ficha SUS - Dados Estruturados")

    c.setFont("Helvetica", 12)
    y = altura - 100
    for chave, valor in dados.items():
        c.drawString(50, y, f"{chave}: {valor}")
        y -= 20
        if y < 50:
            c.showPage()
            y = altura - 50

    c.save()
    buffer.seek(0)
    return buffer

# --- Interface Streamlit ---
st.title("📄 Coleta Inteligente de Fichas")

uploaded_file = st.file_uploader("Faça upload de uma imagem da ficha", type=["jpg", "png", "jpeg"])

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    st.image(image, caption='Imagem Carregada.', use_column_width=True)

    if st.button("🔎 Extrair Dados da Imagem"):
        with st.spinner("📖 Executando OCR..."):
            with open("temp_img.png", "wb") as f:
                f.write(uploaded_file.getbuffer())

            ocr_result = ocr_space_file("temp_img.png", OCRSPACEKEY)

            if ocr_result and "ParsedResults" in ocr_result:
                texto_extraido = ocr_result["ParsedResults"][0]["ParsedText"]

                st.subheader("📌 Texto Bruto do OCR")
                st.text(texto_extraido)

                with st.spinner("🤖 Organizando dados com Cohere..."):
                    dados_extraidos = extrair_dados_com_cohere(texto_extraido)

                st.subheader("📊 Dados Estruturados pela IA")
                st.write(dados_extraidos)

                try:
                    dados_dict = json.loads(dados_extraidos)

                    # Botão salvar no Sheets
                    if st.button("💾 Salvar no Google Sheets"):
                        msg = salvar_no_sheets(dados_dict)
                        st.success(msg)

                    # Geração de PDF
                    pdf_bytes = gerar_pdf(dados_dict)
                    st.download_button(
                        label="📥 Baixar Ficha em PDF",
                        data=pdf_bytes,
                        file_name=f"ficha_{dados_dict.get('nome','paciente')}.pdf",
                        mime="application/pdf"
                    )

                except Exception as e:
                    st.error(f"Erro ao converter dados em JSON: {e}")
            else:
                st.error("❌ Não foi possível extrair texto via OCR.")
