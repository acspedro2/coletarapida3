import streamlit as st
import gspread
import pandas as pd
import json
import os
import datetime
import pytesseract
from PIL import Image
import re
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet

# --- Configuração da Página ---
st.set_page_config(page_title="OCR Ficha SUS", page_icon=":camera:", layout="centered")

# --- Configurar caminho do Tesseract se necessário ---
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"  # Windows
# pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"  # Linux

# --- Conectar ao Google Sheets ---
try:
    credenciais_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_CREDENTIALS")
    planilha_id = os.environ.get("GOOGLE_SHEETS_ID")

    if not credenciais_json or not planilha_id:
        st.error("Erro: Variáveis de ambiente não definidas.")
        st.stop()

    credenciais = json.loads(credenciais_json)
    gc = gspread.service_account_from_dict(credenciais)
    planilha = gc.open_by_key(planilha_id).sheet1
except Exception as e:
    st.error(f"Erro ao conectar com o Google Sheets: {e}")
    st.stop()

ids_existentes = [row[0] for row in planilha.get_all_values() if row]

# --- Funções de formatação ---
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
    if match:
        return f"{match.group(1)}/{match.group(2)}/{match.group(3)}"
    return data_raw

# --- Função de extração de dados via OCR ---
def extrair_dados(texto):
    def buscar(padrao, texto, grupo=1):
        match = re.search(padrao, texto, re.IGNORECASE)
        return match.group(grupo).strip() if match else ""

    cpf_raw = buscar(r'(\d{3}\.?\d{3}\.?\d{3}-?\d{2})', texto)
    telefone_raw = buscar(r'(\(?\d{2}\)?\s?\d{4,5}-?\d{4})', texto)
    data_raw = buscar(r'(\d{2}[^\d]?\d{2}[^\d]?\d{4})', texto)

    return {
        "id_familia": buscar(r'FAM\d{3,}', texto),
        "nome_completo": buscar(r'(?:Nome completo|Nome)\s*[:\-]?\s*(.+)', texto),
        "data_nascimento": formatar_data(data_raw),
        "nome_mae": buscar(r'Nome da mãe\s*[:\-]?\s*(.+)', texto),
        "cpf": formatar_cpf(cpf_raw),
        "telefone": formatar_telefone(telefone_raw),
        "cns": buscar(r'\b(\d{15})\b', texto)
    }

# --- Geração de PDF da ficha ---
def gerar_pdf(dados, caminho_imagem, caminho_pdf):
    doc = SimpleDocTemplate(caminho_pdf, pagesize=A4)
    estilos = getSampleStyleSheet()
    elementos = []

    elementos.append(Paragraph(f"<b>ID Família:</b> {dados['id_familia']}", estilos['Normal']))
    elementos.append(Paragraph(f"<b>Nome Completo:</b> {dados['nome_completo']}", estilos['Normal']))
    elementos.append(Paragraph(f"<b>Data de Nascimento:</b> {dados['data_nascimento']}", estilos['Normal']))
    elementos.append(Paragraph(f"<b>Nome da Mãe:</b> {dados['nome_mae']}", estilos['Normal']))
    elementos.append(Paragraph(f"<b>CPF:</b> {dados['cpf']}", estilos['Normal']))
    elementos.append(Paragraph(f"<b>Telefone:</b> {dados['telefone']}", estilos['Normal']))
    elementos.append(Paragraph(f"<b>CNS:</b> {dados['cns']}", estilos['Normal']))
    elementos.append(Spacer(1, 12))

    if os.path.exists(caminho_imagem):
        elementos.append(RLImage(caminho_imagem, width=300, height=200))

    doc.build(elementos)

# --- Interface Principal ---
st.title("📋 Coleta Automática de Ficha SUS via OCR")

uploaded_file = st.file_uploader("📥 Envie uma imagem da ficha SUS", type=["jpg", "jpeg", "png"])

if uploaded_file:
    st.image(uploaded_file, caption="Pré-visualização da ficha", use_column_width=True)

    try:
        imagem = Image.open(uploaded_file)
        texto = pytesseract.image_to_string(imagem, lang="por")
        st.subheader("🧾 Texto reconhecido via OCR")
        st.text_area("Texto extraído:", texto, height=200)

        dados = extrair_dados(texto)

        st.subheader("📌 Dados extraídos:")
        for campo, valor in dados.items():
            st.write(f"**{campo.replace('_', ' ').capitalize()}:** {valor or '❌ Não encontrado'}")

        if not dados["id_familia"] or not dados["nome_completo"] or not dados["data_nascimento"]:
            st.warning("Campos obrigatórios não foram identificados.")
        elif dados["id_familia"] in ids_existentes:
            st.error(f"O ID '{dados['id_familia']}' já existe na planilha.")
        else:
            # Salvar imagem
            pasta_imagens = "imagens_salvas"
            os.makedirs(pasta_imagens, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            nome_imagem = f"{dados['id_familia']}_{timestamp}_{uploaded_file.name}"
            caminho_imagem = os.path.join(pasta_imagens, nome_imagem)

            with open(caminho_imagem, "wb") as f:
                f.write(uploaded_file.getbuffer())

            # Enviar para Google Sheets
            try:
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
            except Exception as e:
                st.error(f"Erro ao salvar na planilha: {e}")

            # Gerar PDF
            pasta_pdfs = "pdfs_gerados"
            os.makedirs(pasta_pdfs, exist_ok=True)
            caminho_pdf = os.path.join(pasta_pdfs, f"{dados['id_familia']}.pdf")
            gerar_pdf(dados, caminho_imagem, caminho_pdf)

            with open(caminho_pdf, "rb") as f:
                st.download_button("📄 Baixar ficha em PDF", f, file_name=f"{dados['id_familia']}.pdf")

    except Exception as e:
        st.error(f"Erro ao processar a imagem: {e}")
