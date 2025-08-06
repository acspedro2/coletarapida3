import streamlit as st
import gspread
import pandas as pd
import json
import os
import datetime
import re
import requests
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet

st.set_page_config(page_title="OCR Ficha SUS", page_icon=":camera:", layout="centered")

# --- Chave da API OCR.Space ---
OCR_API_KEY = os.getenv("OCR_SPACE_API_KEY")

# --- Conexão com o Google Sheets ---
try:
    credenciais_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_CREDENTIALS")
    planilha_id = os.environ.get("GOOGLE_SHEETS_ID")
    if not credenciais_json or not planilha_id or not OCR_API_KEY:
        st.error("Variáveis de ambiente faltando.")
        st.stop()
    credenciais = json.loads(credenciais_json)
    gc = gspread.service_account_from_dict(credenciais)
    planilha = gc.open_by_key(planilha_id).sheet1
except Exception as e:
    st.error(f"Erro ao conectar com Google Sheets: {e}")
    st.stop()

ids_existentes = [row[0] for row in planilha.get_all_values() if row]

def formatar_cpf(cpf_raw):
    cpf = re.sub(r'\D', '', cpf_raw)
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}" if len(cpf) == 11 else cpf_raw

def formatar_telefone(telefone_raw):
    tel = re.sub(r'\D', '', telefone_raw)
    if len(tel) == 11:
        return f"({tel[:2]}) {tel[2:7]}-{tel[7:]}"
    elif len(tel) == 10:
        return f"({tel[:2]}) {tel[2:6]}-{tel[6:]}"
    return telefone_raw

def formatar_data(data_raw):
    match = re.search(r'(\d{2})[^\d]?(\d{2})[^\d]?(\d{4})', data_raw)
    return f"{match.group(1)}/{match.group(2)}/{match.group(3)}" if match else data_raw

def extrair_dados(texto):
    def buscar(padrao, texto, grupo=1):
        match = re.search(padrao, texto, re.IGNORECASE)
        return match.group(grupo).strip() if match else ""
    return {
        "id_familia": buscar(r'FAM\d{3,}', texto),
        "nome_completo": buscar(r'(?:Nome completo|Nome)\s*[:\-]?\s*(.+)', texto),
        "data_nascimento": formatar_data(buscar(r'(\d{2}[\/\-\.]\d{2}[\/\-\.]\d{4})', texto)),
        "nome_mae": buscar(r'Nome da mãe\s*[:\-]?\s*(.+)', texto),
        "cpf": formatar_cpf(buscar(r'(\d{3}\.?\d{3}\.?\d{3}-?\d{2})', texto)),
        "telefone": formatar_telefone(buscar(r'(\(?\d{2}\)?\s?\d{4,5}-?\d{4})', texto)),
        "cns": buscar(r'\b(\d{15})\b', texto)
    }

def gerar_pdf(dados, caminho_imagem, caminho_pdf):
    doc = SimpleDocTemplate(caminho_pdf, pagesize=A4)
    estilos = getSampleStyleSheet()
    elementos = [
        Paragraph(f"<b>ID Família:</b> {dados['id_familia']}", estilos['Normal']),
        Paragraph(f"<b>Nome Completo:</b> {dados['nome_completo']}", estilos['Normal']),
        Paragraph(f"<b>Data de Nascimento:</b> {dados['data_nascimento']}", estilos['Normal']),
        Paragraph(f"<b>Nome da Mãe:</b> {dados['nome_mae']}", estilos['Normal']),
        Paragraph(f"<b>CPF:</b> {dados['cpf']}", estilos['Normal']),
        Paragraph(f"<b>Telefone:</b> {dados['telefone']}", estilos['Normal']),
        Paragraph(f"<b>CNS:</b> {dados['cns']}", estilos['Normal']),
        Spacer(1, 12)
    ]
    if os.path.exists(caminho_imagem):
        elementos.append(RLImage(caminho_imagem, width=300, height=200))
    doc.build(elementos)

def fazer_ocr_via_api(image_file):
    response = requests.post(
        "https://api.ocr.space/parse/image",
        files={"filename": image_file},
        data={"apikey": OCR_API_KEY, "language": "por", "OCREngine": 2},
    )
    result = response.json()
    if result.get("IsErroredOnProcessing"):
        return None, result.get("ErrorMessage", "Erro desconhecido")
    texto = result["ParsedResults"][0]["ParsedText"]
    return texto, None

st.title("📋 OCR de Ficha SUS via API")

uploaded_file = st.file_uploader("📥 Envie a imagem da ficha SUS", type=["jpg", "jpeg", "png"])

if uploaded_file:
    st.image(uploaded_file, caption="Pré-visualização da ficha", use_container_width=True)

    texto, erro = fazer_ocr_via_api(uploaded_file)
    if erro:
        st.error(f"Erro no OCR: {erro}")
        st.stop()

    st.subheader("🧾 Texto extraído")
    st.text_area("Resultado OCR:", texto, height=200)

    dados = extrair_dados(texto)
    st.subheader("📌 Dados extraídos:")
    for campo, valor in dados.items():
        st.write(f"**{campo.replace('_', ' ').capitalize()}:** {valor or '❌ Não encontrado'}")

    if not dados["id_familia"] or not dados["nome_completo"] or not dados["data_nascimento"]:
        st.warning("Campos obrigatórios ausentes.")
    elif dados["id_familia"] in ids_existentes:
        st.error(f"O ID '{dados['id_familia']}' já existe.")
    else:
        pasta_imagens = "imagens_salvas"
        os.makedirs(pasta_imagens, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        nome_imagem = f"{dados['id_familia']}_{timestamp}_{uploaded_file.name}"
        caminho_imagem = os.path.join(pasta_imagens, nome_imagem)
        with open(caminho_imagem, "wb") as f:
            f.write(uploaded_file.getbuffer())

        planilha.append_row([
            dados["id_familia"],
            dados["nome_completo"],
            dados["data_nascimento"],
            dados["nome_mae"],
            dados["cpf"],
            dados["telefone"],
            dados["cns"],
            nome_imagem
        ])
        st.success("✅ Dados enviados ao Google Sheets!")

        pasta_pdfs = "pdfs_gerados"
        os.makedirs(pasta_pdfs, exist_ok=True)
        caminho_pdf = os.path.join(pasta_pdfs, f"{dados['id_familia']}.pdf")
        gerar_pdf(dados, caminho_imagem, caminho_pdf)

        with open(caminho_pdf, "rb") as f:
            st.download_button("📄 Baixar ficha em PDF", f, file_name=f"{dados['id_familia']}.pdf")
