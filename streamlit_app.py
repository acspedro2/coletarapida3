import streamlit as st
import requests
import json
import gspread
from PIL import Image
import time
import re
import pandas as pd
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import landscape, A4, letter
from reportlab.lib.units import inch, cm
from io import BytesIO
import urllib.parse
import qrcode
from reportlab.lib.utils import ImageReader
import matplotlib.pyplot as plt
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from dateutil.relativedelta import relativedelta
from pdf2image import convert_from_bytes
import os

# --- IMPORTAÇÃO GOOGLE GENAI ---
try:
    import google.genai as genai
    from pydantic import BaseModel, Field
    from google.genai.types import Part
except ImportError:
    st.error("Erro de importação: Verifique se 'google-genai' e 'pydantic' estão no seu requirements.txt.")
    st.stop()

# --- CONFIGURAÇÕES GLOBAIS ---
MODELO_GEMINI = "gemini-2.0-flash" # Atualizado para versão estável recomendada

EXAMES_COMUNS = [
    "Hemograma Completo", "Glicemia em Jejum", "Perfil Lipídico", "Exame de Urina (EAS)",
    "Ureia e Creatinina", "TSH e T4 Livre", "PSA", "Papanicolau", "Eletrocardiograma (ECG)",
    "Teste Ergométrico", "Holter 24h", "MAPA", "USG Geral", "Radiografia (Raio-X)",
    "Mamografia Digital", "Densitometria Óssea", "Tomografia (TC)", "Ressonância (RM)"
]

ESPECIALIDADES_MEDICAS = [
    "Clínica Médica", "Pediatria", "Ginecologia", "Cardiologia", "Dermatologia",
    "Oftalmologia", "Ortopedia", "Neurologia", "Psiquiatria", "Urologia", "Endocrinologia"
]

# --- ESQUEMAS PYDANTIC PARA IA ---
class CadastroSchema(BaseModel):
    ID: str = Field(description="ID único")
    FAMÍLIA: str = Field(description="Código de família")
    nome_completo: str = Field(alias="Nome Completo")
    data_nascimento: str = Field(alias="Data de Nascimento")
    Telefone: str
    CPF: str
    nome_da_mae: str = Field(alias="Nome da Mãe")
    nome_do_pai: str = Field(alias="Nome do Pai")
    Sexo: str
    CNS: str
    municipio_nascimento: str = Field(alias="Município de Nascimento")

class VacinaAdministrada(BaseModel):
    vacina: str
    dose: str

class VacinacaoSchema(BaseModel):
    nome_paciente: str
    data_nascimento: str
    vacinas_administradas: list[VacinaAdministrada]

class ClinicoSchema(BaseModel):
    diagnosticos: list[str]
    medicamentos: list[str]

class DicaSaude(BaseModel):
    titulo_curto: str
    texto_whatsapp: str

class DicasSaudeSchema(BaseModel):
    dicas: list[DicaSaude]

# --- FUNÇÕES DE APOIO ---
@st.cache_resource
def conectar_planilha():
    try:
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
        sheet = client.open_by_key(st.secrets["SHEETSID"]).sheet1
        return sheet
    except Exception as e:
        st.error(f"Erro no Google Sheets: {e}"); return None

def calcular_idade(data_nasc):
    if pd.isna(data_nasc): return 0
    hoje = datetime.now()
    return hoje.year - data_nasc.year - ((hoje.month, hoje.day) < (data_nasc.month, data_nasc.day))

def padronizar_telefone(tel):
    num = re.sub(r'\D', '', str(tel))
    if num.startswith('55'): num = num[2:]
    return num if 10 <= len(num) <= 11 else None

# --- GERAÇÃO DE PDF E ETIQUETAS ---
def gerar_pdf_etiquetas(familias_para_gerar):
    pdf_buffer = BytesIO()
    can = canvas.Canvas(pdf_buffer, pagesize=A4)
    largura_pag, altura_pag = A4
    
    colunas, linhas = 2, 5
    largura_etq = (largura_pag - 1*cm) / colunas
    altura_etq = (altura_pag - 2*cm) / linhas
    
    contador = 0
    for familia_id, dados in familias_para_gerar.items():
        col = contador % colunas
        lin = (contador // colunas) % linhas
        
        x = 0.5*cm + (col * largura_etq)
        y = altura_pag - 1*cm - ((lin + 1) * altura_etq)
        
        can.rect(x, y, largura_etq, altura_etq)
        
        # QR Code com Correção ImageReader
        link = dados.get("link_pasta", "https://google.com")
        qr = qrcode.QRCode(box_size=10, border=1)
        qr.add_data(link)
        qr.make(fit=True)
        img_qr = qr.make_image(fill_color="black", back_color="white")
        
        temp_img = BytesIO()
        img_qr.save(temp_img, format='PNG')
        temp_img.seek(0)
        
        can.drawImage(ImageReader(temp_img), x + 0.2*cm, y + 0.5*cm, width=2.5*cm, height=2.5*cm)
        
        can.setFont("Helvetica-Bold", 10)
        can.drawString(x + 3*cm, y + altura_etq - 0.8*cm, f"Família: {familia_id}")
        
        can.setFont("Helvetica", 7)
        y_membro = y + altura_etq - 1.5*cm
        for m in dados['membros'][:4]:
            nome = m['Nome Completo'][:25]
            can.drawString(x + 3*cm, y_membro, f"• {nome}")
            y_membro -= 0.4*cm
            
        contador += 1
        if contador % (colunas * linhas) == 0: can.showPage()
            
    can.save()
    pdf_buffer.seek(0)
    return pdf_buffer

# --- PÁGINAS DO SISTEMA ---
def pagina_gerador_cards(client):
    st.title("🤖 Gerador de Cards de Saúde (IA)")
    tema = st.selectbox("Tema das Dicas:", ["Alimentação Saudável", "Prevenção Hipertensão", "Saúde Mental", "Diabetes"])
    
    if st.button("✨ Gerar Dicas"):
        prompt = f"Crie 5 dicas curtas sobre {tema} baseadas no Guia Alimentar Brasileiro."
        res = client.models.generate_content(
            model=MODELO_GEMINI, contents=[prompt],
            config={"response_mime_type": "application/json", "response_schema": DicasSaudeSchema}
        )
        dicas = DicasSaudeSchema.model_validate_json(res.text).dicas
        for d in dicas:
            st.info(f"**{d.titulo_curto}**\n\n{d.texto_whatsapp}")

def pagina_whatsapp(planilha):
    st.title("📱 WhatsApp para Pacientes")
    df = ler_dados_da_planilha(planilha)
    df_zap = df[df['Telefone'].apply(padronizar_telefone).notnull()]
    
    paciente = st.selectbox("Selecione o Paciente:", sorted(df_zap['Nome Completo']))
    tipo = st.selectbox("Tipo:", ["Exames", "Marcação Médica", "Aviso"])
    
    if tipo == "Exames":
        exame = st.selectbox("Exame:", EXAMES_COMUNS)
        data = st.text_input("Data/Hora:", "Amanhã às 08:00")
        msg = f"Olá! Seu exame de {exame} está marcado para {data}. Atenciosamente, ESF AMPARO."
    else:
        msg = st.text_area("Mensagem:", "Olá! Temos um aviso importante...")
        
    if st.button("Enviar"):
        tel = padronizar_telefone(df_zap[df_zap['Nome Completo'] == paciente]['Telefone'].values[0])
        url = f"https://wa.me/55{tel}?text={urllib.parse.quote(msg)}"
        st.link_button("Abrir WhatsApp", url)

def ler_dados_da_planilha(_sheet):
    try:
        data = _sheet.get_all_records()
        df = pd.DataFrame(data)
        df['Data de Nascimento DT'] = pd.to_datetime(df['Data de Nascimento'], format='%d/%m/%Y', errors='coerce')
        df['Idade'] = df['Data de Nascimento DT'].apply(lambda dt: calcular_idade(dt) if pd.notnull(dt) else 0)
        return df
    except: return pd.DataFrame()

# --- MAIN ---
def main():
    try:
        client = genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
        sheet = conectar_planilha()
    except:
        st.error("Erro de configuração de API/Planilha"); st.stop()

    st.sidebar.title("🩺 Gestão ESF Amparo")
    menu = {
        "🏠 Início": lambda: st.write("Selecione uma opção no menu."),
        "Gerar Cards (IA)": lambda: pagina_gerador_cards(client),
        "WhatsApp": lambda: pagina_whatsapp(sheet),
        "Etiquetas": lambda: pagina_etiquetas(sheet),
        "Coletar Fichas": lambda: pagina_coleta(sheet, client)
    }
    
    choice = st.sidebar.radio("Navegação", list(menu.keys()))
    menu[choice]()

# Lógicas repetidas (pagina_coleta, pagina_etiquetas) devem ser mantidas conforme seu código original
# mas sempre usando o 'ImageReader(buffer)' para os QR Codes.

if __name__ == "__main__":
    main()
