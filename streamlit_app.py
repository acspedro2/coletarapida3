import streamlit as st
import gspread
import json
import os
import pandas as pd
import google.generativeai as genai
from io import BytesIO
from datetime import datetime
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch

# --- Configuração da Página e Título ---
st.set_page_config(
    page_title="Coleta Inteligente",
    page_icon="🤖",
    layout="wide"
)

st.title("🤖 Coleta Inteligente")
st.markdown("---")

# --- CONEXÃO E VARIÁVEIS DE AMBIENTE ---
try:
    gemini_api_key = st.secrets["GEMINIKEY"]
    google_sheets_id = st.secrets["SHEETSID"]
    google_credentials_dict = st.secrets["gcp_service_account"]
except KeyError as e:
    st.error(f"Erro de configuração: A chave secreta '{e.args[0]}' não foi encontrada.")
    st.stop()
except Exception as e:
    st.error(f"Erro inesperado ao carregar as chaves secretas: {e}")
    st.stop()

# --- FUNÇÕES ---

@st.cache_resource
def conectar_planilha():
    try:
        gc = gspread.service_account_from_dict(google_credentials_dict)
        return gc.open_by_key(google_sheets_id).sheet1
    except Exception as e:
        st.error(f"Não foi possível conectar à planilha. Erro: {e}")
        st.stop()

def calcular_idade(data_nasc):
    if pd.isna(data_nasc): return 0
    hoje = datetime.now()
    return hoje.year - data_nasc.year - ((hoje.month, hoje.day) < (data_nasc.month, data_nasc.day))

@st.cache_data(ttl=60)
def ler_dados_da_planilha(_planilha):
    try:
        dados = _planilha.get_all_records()
        df = pd.DataFrame(dados)
        colunas_esperadas = ["ID Família", "Nome Completo", "Data de Nascimento", "Telefone", "CPF", "Nome da Mãe", "Nome do Pai", "Sexo", "CNS", "Timestamp de Envio"]
        for col in colunas_esperadas:
            if col not in df.columns: df[col] = ""
        df['Data de Nascimento DT'] = pd.to_datetime(df['Data de Nascimento'], format='%d/%m/%Y', errors='coerce')
        df['Idade'] = df['Data de Nascimento DT'].apply(calcular_idade)
        return df
    except Exception as e:
        st.error(f"Não foi possível ler os dados da planilha. Erro: {e}")
        return pd.DataFrame()

# --- NOVA FUNÇÃO DE PDF COMPLETO ---
def gerar_pdf_ivcf20_completo(paciente):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    margin = 0.75 * inch
    
    # Função auxiliar para desenhar uma pergunta com checkboxes
    def draw_question(y, question_number, question_text, options=["Sim (1)", "Não (0)"]):
        p.setFont("Helvetica", 9)
        p.drawString(margin, y, f"{question_number}. {question_text}")
        
        # Desenha as opções com checkboxes
        x_offset = margin + 350
        for option in options:
            p.rect(x_offset, y - 2, 8, 8) # Checkbox
            p.drawString(x_offset + 12, y, option)
            x_offset += 80
        return y - 25 # Retorna a nova posição Y

    # Cabeçalho principal
    p.setFont("Helvetica-Bold", 12)
    p.drawCentredString(width / 2.0, height - 50, "ÍNDICE DE VULNERABILIDADE CLÍNICO FUNCIONAL 20 (IVCF-20)")
    
    # Secção de IDENTIFICAÇÃO (como antes)
    p.setFont("Helvetica-Bold", 10)
    p.drawString(margin, height - 80, "IDENTIFICAÇÃO")
    y = height - 110
    p.setFont("Helvetica", 8)
    p.drawString(margin, y + 5, "Nome social:")
    p.setFont("Helvetica-Bold", 11)
    p.drawString(margin + 75, y + 5, str(paciente.get("Nome Completo", "")))
    p.line(margin + 73, y, width - margin, y)
    y -= 25
    p.setFont("Helvetica", 8)
    p.drawString(margin, y + 5, "CPF/CNS:")
    p.setFont("Helvetica-Bold", 11)
    p.drawString(margin + 75, y + 5, str(paciente.get("CPF", "")))
    p.line(margin + 73, y, 400, y)
    p.setFont("Helvetica", 8)
    p.drawString(420, y + 5, "Data de nascimento:")
    p.setFont("Helvetica-Bold", 11)
    p.drawString(500, y + 5, str(paciente.get("Data de Nascimento", "")))
    p.line(498, y, width - margin, y)
    y -= 30

    # Corpo do Formulário
    p.setFont("Helvetica-Bold", 10)
    p.drawString(margin, y, "IDADE")
    y = draw_question(y-15, 1, "Qual é a sua idade?", options=["60 a 74 anos (0)", "75 a 84 anos (1)", "≥ 85 anos (3)"])

    p.setFont("Helvetica-Bold", 10)
    p.drawString(margin, y, "PERCEPÇÃO DA SAÚDE")
    y = draw_question(y-15, 2, "Em geral, comparando com outras pessoas de sua idade, você diria que sua saúde é:", options=["Excelente (0)", "Boa (0)", "Regular (1)"])
    y -= 10

    p.setFont("Helvetica-Bold", 10)
    p.drawString(margin, y, "AVD INSTRUMENTAL")
    y = draw_question(y-15, 3, "Por causa de sua saúde ou condição física, você deixou de fazer compras?", options=["Sim (4)", "Não (0)"])
    y = draw_question(y, 4, "Por causa de sua saúde ou condição física, você deixou de controlar seu dinheiro, gasto ou pagar suas contas?", options=["Sim (4)", "Não (0)"])
    y = draw_question(y, 5, "Por causa de sua saúde ou condição física, você deixou de realizar pequenos trabalhos domésticos?", options=["Sim (4)", "Não (0)"])
    y -= 10

    p.setFont("Helvetica-Bold", 10)
    p.drawString(margin, y, "AVD BÁSICA")
    y = draw_question(y-15, 6, "Por causa de sua saúde ou condição física, você deixou de tomar banho sozinho?", options=["Sim (6)", "Não (0)"])
    y -= 10
    
    p.setFont("Helvetica-Bold", 10)
    p.drawString(margin, y, "COGNIÇÃO")
    y = draw_question(y-15, 7, "Alguém (amigo ou parente) falou que você está ficando esquecido?", options=["Sim (1)", "Não (0)"])
    y = draw_question(y, 8, "Este esquecimento está piorando nos últimos meses?", options=["Sim (1)", "Não (0)"])
    y = draw_question(y, 9, "Este esquecimento está impedindo a realização de alguma atividade do cotidiano?", options=["Sim (2)", "Não (0)"])
    y -= 10

    p.setFont("Helvetica-Bold", 10)
    p.drawString(margin, y, "HUMOR")
    y = draw_question(y-15, 10, "No último mês, você ficou com desânimo, tristeza ou desesperança?", options=["Sim (2)", "Não (0)"])
    y = draw_question(y, 11, "No último mês, você perdeu o interesse ou prazer em atividades anteriormente prazerosas?", options=["Sim (2)", "Não (0)"])
    y -= 10

    p.setFont("Helvetica-Bold", 10)
    p.drawString(margin, y, "MOBILIDADE")
    
    # Inicia a segunda coluna
    p.saveState()
    y2 = y
    
    y = draw_question(y-15, 12, "Você é incapaz de elevar os braços acima do nível do ombro?", options=["Sim (1)", "Não (0)"])
    y = draw_question(y, 13, "Você é incapaz de manusear ou segurar pequenos objetos?", options=["Sim (1)", "Não (0)"])
    y = draw_question(y, 14, "Você tem alguma das três condições abaixo relacionadas?", options=["Sim (2)", "Não (0)"])
    p.setFont("Helvetica", 8)
    p.drawString(margin + 15, y, "Perda de peso não intencional de 4,5Kg ou 5% do peso corporal no último ano...")
    y -= 25
    y = draw_question(y, 15, "Você tem dificuldades para caminhar capaz
