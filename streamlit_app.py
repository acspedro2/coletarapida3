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
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
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

# --- CONFIGURAÇÃO DA API E SCHEMAS ---
try:
    import google.genai as genai
    from pydantic import BaseModel, Field
    from google.genai.types import Part
except ImportError:
    st.error("Erro: Instale 'google-genai' e 'pydantic' no seu ambiente.")
    st.stop()

MODELO_GEMINI = "gemini-2.0-flash"

class CadastroSchema(BaseModel):
    ID: str = Field(description="ID único")
    FAMÍLIA: str = Field(description="Código de família (ex: FAM111)")
    nome_completo: str = Field(alias="Nome Completo")
    data_nascimento: str = Field(alias="Data de Nascimento")
    Telefone: str
    CPF: str
    nome_da_mae: str = Field(alias="Nome da Mãe")
    nome_do_pai: str = Field(alias="Nome do Pai")
    Sexo: str
    CNS: str
    municipio_nascimento: str = Field(alias="Município de Nascimento")

class DicaSaude(BaseModel):
    titulo_curto: str = Field(description="Título curto para o card")
    texto_whatsapp: str = Field(description="Texto para a mensagem")

class DicasSaudeSchema(BaseModel):
    dicas: list[DicaSaude]

class VacinaAdministrada(BaseModel):
    vacina: str
    dose: str

class VacinacaoSchema(BaseModel):
    nome_paciente: str
    data_nascimento: str
    vacinas_administradas: list[VacinaAdministrada]

# --- MOTOR DE REGRAS PNI ---
CALENDARIO_PNI = [
    {"vacina": "BCG", "dose": "Dose Única", "idade_meses": 0},
    {"vacina": "Hepatite B", "dose": "1ª Dose", "idade_meses": 0},
    {"vacina": "Pentavalente", "dose": "1ª Dose", "idade_meses": 2},
    {"vacina": "VIP", "dose": "1ª Dose", "idade_meses": 2},
    {"vacina": "Tríplice Viral", "dose": "1ª Dose", "idade_meses": 12},
]

# --- CONSTANTES DE UI ---
EXAMES_COMUNS = ["Hemograma", "Glicemia", "Perfil Lipídico", "EAS", "PSA", "Papanicolau", "ECG", "Raio-X", "USG Geral", "Mamografia"]
ESPECIALIDADES_MEDICAS = ["Clínica Médica", "Pediatria", "Ginecologia", "Cardiologia", "Dermatologia", "Ortopedia", "Psiquiatria"]

# --- FUNÇÕES CORE ---
@st.cache_resource
def conectar_planilha():
    try:
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
        sheet = client.open_by_key(st.secrets["SHEETSID"]).sheet1
        return sheet
    except Exception as e:
        st.error(f"Erro ao conectar Sheets: {e}"); return None

@st.cache_data(ttl=300)
def ler_dados_da_planilha(_planilha):
    try:
        dados = _planilha.get_all_records()
        df = pd.DataFrame(dados)
        if df.empty: return df
        df['Data de Nascimento DT'] = pd.to_datetime(df['Data de Nascimento'], format='%d/%m/%Y', errors='coerce')
        df['Idade'] = df['Data de Nascimento DT'].apply(lambda dt: (datetime.now().year - dt.year) if pd.notnull(dt) else 0)
        return df
    except: return pd.DataFrame()

def padronizar_telefone(tel):
    num = re.sub(r'\D', '', str(tel))
    if num.startswith('55'): num = num[2:]
    return num if 10 <= len(num) <= 11 else None

# --- GERAÇÃO DE PDF (COM CORREÇÃO DE QR CODE) ---
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
        
        can.setStrokeColor(HexColor('#2c3e50'))
        can.rect(x, y, largura_etq, altura_etq)
        
        # Correção do QR Code
        link = dados.get("link_pasta", "https://esfamparo.saude")
        qr = qrcode.QRCode(box_size=10, border=1)
        qr.add_data(link)
        qr.make(fit=True)
        img_qr = qr.make_image(fill_color="black", back_color="white")
        
        qr_temp = BytesIO()
        img_qr.save(qr_temp, format='PNG')
        qr_temp.seek(0)
        
        can.drawImage(ImageReader(qr_temp), x + 0.3*cm, y + 0.5*cm, width=2.6*cm, height=2.6*cm)
        
        can.setFont("Helvetica-Bold", 11)
        can.drawString(x + 3.2*cm, y + altura_etq - 0.8*cm, f"FAMÍLIA: {familia_id}")
        
        can.setFont("Helvetica", 8)
        y_membro = y + altura_etq - 1.4*cm
        for m in dados['membros'][:4]:
            nome = m['Nome Completo'][:28]
            can.drawString(x + 3.2*cm, y_membro, f"• {nome}")
            y_membro -= 0.4*cm
            
        contador += 1
        if contador % (colunas * linhas) == 0: can.showPage()
            
    can.save()
    pdf_buffer.seek(0)
    return pdf_buffer

# --- PÁGINAS ---
def pagina_gerador_cards(client):
    st.title("🤖 Gerador de Dicas de Saúde (IA)")
    tema = st.selectbox("Escolha o tema:", ["Alimentação Saudável", "Hipertensão", "Diabetes", "Atividade Física", "Pré-Natal"])
    
    if st.button("✨ Gerar 5 Dicas para WhatsApp"):
        with st.spinner("IA criando conteúdo..."):
            prompt = f"Gere 5 dicas curtas sobre {tema} para saúde pública. Use o Guia Alimentar como base."
            response = client.models.generate_content(
                model=MODELO_GEMINI, contents=[prompt],
                config={"response_mime_type": "application/json", "response_schema": DicasSaudeSchema}
            )
            dicas = DicasSaudeSchema.model_validate_json(response.text).dicas
            for i, d in enumerate(dicas):
                st.subheader(f"{i+1}. {d.titulo_curto}")
                st.code(d.texto_whatsapp)

def pagina_whatsapp(planilha):
    st.title("📱 Comunicação via WhatsApp")
    df = ler_dados_da_planilha(planilha)
    df_zap = df[df['Telefone'].apply(padronizar_telefone).notnull()].copy()
    
    if df_zap.empty: st.warning("Sem contatos válidos."); return

    paciente_nome = st.selectbox("Para quem?", sorted(df_zap['Nome Completo']))
    tipo = st.radio("Tipo de Mensagem:", ["Exame", "Consulta", "Geral"])
    
    assinatura = "\n\nAtenciosamente, ESF AMPARO."
    
    if tipo == "Exame":
        ex = st.selectbox("Qual exame?", EXAMES_COMUNS)
        dt = st.text_input("Data/Hora:", "dd/mm às 08:00")
        msg = f"Olá! Seu exame de {ex} está marcado para {dt}. Não esqueça o jejum."
    elif tipo == "Consulta":
        esp = st.selectbox("Especialidade:", ESPECIALIDADES_MEDICAS)
        dt = st.text_input("Data/Hora:", "dd/mm às 10:00")
        msg = f"Olá! Sua consulta com {esp} foi agendada para {dt}."
    else:
        msg = st.text_area("Mensagem:", "Olá! Gostaria de informar que...")

    msg_final = msg + assinatura
    
    if st.button("🚀 Gerar Link e Enviar"):
        tel = padronizar_telefone(df_zap[df_zap['Nome Completo'] == paciente_nome]['Telefone'].values[0])
        url = f"https://wa.me/55{tel}?text={urllib.parse.quote(msg_final)}"
        st.link_button("Abrir WhatsApp Web/App", url)

def pagina_etiquetas(planilha):
    st.title("🏷️ Etiquetas Familiares")
    df = ler_dados_da_planilha(planilha)
    if df.empty: return
    
    df_f = df[df['FAMÍLIA'] != ""]
    familias = df_f.groupby('FAMÍLIA').apply(lambda x: {
        "membros": x[['Nome Completo', 'CNS']].to_dict('records'),
        "link_pasta": x.get('Link da Pasta da Família', [""])[0]
    }).to_dict()
    
    selecionadas = st.multiselect("Filtrar Famílias:", list(familias.keys()))
    gerar = {k: familias[k] for k in selecionadas} if selecionadas else familias
    
    if st.button("📥 Gerar PDF das Etiquetas"):
        pdf = gerar_pdf_etiquetas(gerar)
        st.download_button("Baixar Etiquetas", pdf, "etiquetas.pdf", "application/pdf")

# --- MAIN ENGINE ---
def main():
    try:
        api_key = st.secrets["GOOGLE_API_KEY"]
        client = genai.Client(api_key=api_key)
        sheet = conectar_planilha()
    except:
        st.error("Configuração de API ou Planilha pendente."); st.stop()

    st.sidebar.title("🩺 ESF Amparo v3.0")
    paginas = {
        "🏠 Início": lambda: st.write("Bem-vindo ao Sistema de Gestão ESF Amparo."),
        "📢 Gerador de Cards (IA)": lambda: pagina_gerador_cards(client),
        "📱 WhatsApp": lambda: pagina_whatsapp(sheet),
        "🏷️ Etiquetas": lambda: pagina_etiquetas(sheet),
        "🔍 Gestão de Pacientes": lambda: st.write("Módulo de Pesquisa e Edição") # Reutilizar lógica original aqui
    }
    
    sel = st.sidebar.radio("Menu", list(paginas.keys()))
    paginas[sel]()

if __name__ == "__main__":
    main()
