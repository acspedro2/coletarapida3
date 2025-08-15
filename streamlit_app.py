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
    """Calcula a idade a partir de um objeto datetime."""
    if pd.isna(data_nasc):
        return 0
    hoje = datetime.now()
    return hoje.year - data_nasc.year - ((hoje.month, hoje.day) < (data_nasc.month, data_nasc.day))

@st.cache_data(ttl=60)
def ler_dados_da_planilha(_planilha):
    """Lê os dados, garante colunas e calcula a idade."""
    try:
        dados = _planilha.get_all_records()
        df = pd.DataFrame(dados)
        colunas_esperadas = ["ID Família", "Nome Completo", "Data de Nascimento", "Telefone", "CPF", "Nome da Mãe", "Nome do Pai", "Sexo", "CNS", "Município de Nascimento", "Timestamp de Envio"]
        for col in colunas_esperadas:
            if col not in df.columns:
                df[col] = ""
        
        # Converte a coluna de data e calcula a idade
        df['Data de Nascimento DT'] = pd.to_datetime(df['Data de Nascimento'], format='%d/%m/%Y', errors='coerce')
        df['Idade'] = df['Data de Nascimento DT'].apply(calcular_idade)
        
        return df
    except Exception as e:
        st.error(f"Não foi possível ler os dados da planilha. Erro: {e}")
        return pd.DataFrame()

# --- NOVA FUNÇÃO PARA GERAR A FICHA IVCF-20 ---
def gerar_pdf_ivcf20(paciente):
    """Gera o cabeçalho da ficha IVCF-20 para um paciente específico."""
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    # Desenha o cabeçalho principal
    p.setFont("Helvetica-Bold", 12)
    p.drawCentredString(width / 2.0, height - 50, "ÍNDICE DE VULNERABILIDADE CLÍNICO FUNCIONAL 20 (IVCF-20)")
    
    # Seção de IDENTIFICAÇÃO
    p.setFont("Helvetica-Bold", 10)
    p.drawString(72, height - 80, "IDENTIFICAÇÃO")
    
    y = height - 110
    
    # Campo Nome social
    p.setFont("Helvetica", 8)
    p.drawString(72, y + 5, "Nome social:")
    p.setFont("Helvetica-Bold", 12)
    p.drawString(150, y + 5, str(paciente.get("Nome Completo", "")))
    p.line(148, y, width - 72, y)
    
    # Campo CPF/CNS
    y -= 30
    p.setFont("Helvetica", 8)
    p.drawString(72, y + 5, "CPF/CNS:")
    p.setFont("Helvetica-Bold", 12)
    p.drawString(150, y + 5, str(paciente.get("CPF", ""))) # Assumindo que o campo CPF contenha o que for necessário
    p.line(148, y, 400, y)

    # Campo Data de nascimento
    p.setFont("Helvetica", 8)
    p.drawString(420, y + 5, "Data de nascimento:")
    p.setFont("Helvetica-Bold", 12)
    p.drawString(500, y + 5, str(paciente.get("Data de Nascimento", "")))
    p.line(498, y, width - 72, y)
    
    p.save()
    buffer.seek(0)
    return buffer

# (As outras funções como extrair_dados, validar, etc. permanecem aqui)
# ...

# --- INICIALIZAÇÃO ---
planilha_conectada = conectar_planilha()

# --- NAVEGAÇÃO E PÁGINAS ---
st.sidebar.title("Navegação")
paginas = ["Coletar Fichas", "Dashboard", "Gerar Relatórios", "Gerar Ficha IVCF-20"]
pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas)

# ... (Página de Coletar Fichas e Dashboard permanecem iguais)

# --- PÁGINA 3: GERAR RELATÓRIOS ---
if pagina_selecionada == "Gerar Relatórios":
    st.header("📄 Gerador de Relatórios Personalizados")
    # ... (código da página de relatórios)

# --- PÁGINA 4: GERAR FICHA IVCF-20 (NOVA!) ---
elif pagina_selecionada == "Gerar Ficha IVCF-20":
    st.header("📝 Gerar Ficha de Vulnerabilidade (IVCF-20)")
    st.info("Esta ferramenta gera o cabeçalho da ficha IVCF-20 para pacientes com 60 anos ou mais.")
    
    df_completo = ler_dados_da_planilha(planilha_conectada)
    
    # Filtra o dataframe para incluir apenas pacientes com 60 anos ou mais
    df_idosos = df_completo[df_completo['Idade'] >= 60].copy()
    
    if not df_idosos.empty:
        # Cria uma lista de nomes de pacientes para o utilizador escolher
        lista_pacientes = df_idosos['Nome Completo'].tolist()
        
        paciente_selecionado_nome = st.selectbox(
            "Selecione um paciente para gerar a ficha:",
            options=lista_pacientes,
            index=None,
            placeholder="Escolha um paciente..."
        )
        
        if paciente_selecionado_nome:
            # Encontra os dados completos do paciente selecionado
            dados_paciente = df_idosos[df_idosos['Nome Completo'] == paciente_selecionado_nome].iloc[0].to_dict()
            
            st.write("---")
            st.subheader("Pré-visualização dos Dados")
            st.write(f"**Nome:** {dados_paciente['Nome Completo']}")
            st.write(f"**CPF/CNS:** {dados_paciente.get('CPF', 'Não informado')}")
            st.write(f"**Data de Nascimento:** {dados_paciente['Data de Nascimento']}")
            
            # Gera o PDF em memória
            pdf_ficha = gerar_pdf_ivcf20(dados_paciente)
            
            # Botão de download
            st.download_button(
                label="Descarregar Ficha IVCF-20 em PDF",
                data=pdf_ficha,
                file_name=f"IVCF20_{paciente_selecionado_nome.replace(' ', '_')}.pdf",
                mime="application/pdf"
            )

    else:
        st.warning("Não foram encontrados registos de pacientes com 60 anos ou mais na planilha.")

# O restante do código das outras páginas (Coletar Fichas, Dashboard, etc.) deve ser mantido
# ...
