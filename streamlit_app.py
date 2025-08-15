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
    st.error(f"Erro de configuração: A chave secreta '{e.args[0]}' não foi encontrada. Verifique o nome no painel de Secrets do Streamlit Cloud.")
    st.stop()
except Exception as e:
    st.error(f"Erro inesperado ao carregar as chaves secretas. Verifique a formatação no painel de Secrets. Erro: {e}")
    st.stop()

# --- FUNÇÕES ---

@st.cache_resource
def conectar_planilha():
    """Conecta com o Google Sheets usando as credenciais."""
    try:
        gc = gspread.service_account_from_dict(google_credentials_dict)
        planilha = gc.open_by_key(google_sheets_id).sheet1
        return planilha
    except Exception as e:
        st.error(f"Não foi possível conectar à planilha. Verifique a ID, as permissões de partilha e o formato das credenciais. Erro: {e}")
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
        
        df['Data de Nascimento DT'] = pd.to_datetime(df['Data de Nascimento'], format='%d/%m/%Y', errors='coerce')
        df['Idade'] = df['Data de Nascimento DT'].apply(calcular_idade)
        
        return df
    except Exception as e:
        st.error(f"Não foi possível ler os dados da planilha. Erro: {e}")
        return pd.DataFrame()

def apagar_linha_por_timestamp(planilha, timestamp):
    """Encontra uma linha pelo timestamp e a apaga."""
    try:
        cell = planilha.find(timestamp)
        if cell:
            planilha.delete_rows(cell.row)
            return True
        return False
    except Exception as e:
        st.error(f"Ocorreu um erro ao tentar apagar a linha. Erro: {e}")
        return False

def atualizar_linha(planilha, timestamp, novos_dados):
    """Encontra uma linha pelo timestamp e atualiza seus valores."""
    try:
        cell = planilha.find(timestamp)
        if cell:
            valores_atualizados = list(novos_dados.values())
            # A atualização deve abranger o número exato de colunas
            range_to_update = f'A{cell.row}:{chr(ord("A") + len(valores_atualizados) - 1)}{cell.row}'
            planilha.update(range_to_update, [valores_atualizados])
            return True
        return False
    except Exception as e:
        st.error(f"Ocorreu um erro ao tentar atualizar a linha. Erro: {e}")
        return False

def gerar_pdf_ivcf20_completo(paciente):
    """Gera o formulário completo da ficha IVCF-20."""
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    margin = 0.75 * inch

    def draw_question(y_start, question_number, question_text, options, text_width=350, options_x_offset=420, option_spacing=80):
        p.setFont("Helvetica", 9)
        lines = []
        words = question_text.split()
        current_line = f"{question_number}. "
        for word in words:
            if p.stringWidth(current_line + word + " ") < text_width:
                current_line += word + " "
            else:
                lines.append(current_line)
                current_line = "   " + word + " "
        lines.append(current_line)
        
        line_height = 12
        y = y_start
        for line in lines:
            p.drawString(margin, y, line)
            y -= line_height
        
        option_y = y_start
        x_offset = options_x_offset
        for option in options:
            p.rect(x_offset, option_y - 2, 8, 8)
            p.drawString(x_offset + 12, option_y, option)
            x_offset += option_spacing
        
        return y - 15

    # (Funções de IA permanecem as mesmas)
    # ...

    p.setFont("Helvetica-Bold", 12)
    p.drawCentredString(width / 2.0, height - 50, "ÍNDICE DE VULNERABILIDADE CLÍNICO FUNCIONAL 20 (IVCF-20)")
    
    p.setFont("Helvetica-Bold", 10)
    p.drawString(margin, height - 80, "IDENTIFICAÇÃO")
    y = height - 110
    p.setFont("Helvetica", 8); p.drawString(margin, y + 5, "Nome social:")
    p.setFont("Helvetica-Bold", 11); p.drawString(margin + 75, y + 5, str(paciente.get("Nome Completo", "")))
    p.line(margin + 73, y, width - margin, y)
    y -= 25
    p.setFont("Helvetica", 8); p.drawString(margin, y + 5, "CPF/CNS:")
    p.setFont("Helvetica-Bold", 11); p.drawString(margin + 75, y + 5, str(paciente.get("CPF", "")))
    p.line(margin + 73, y, 400, y)
    p.setFont("Helvetica", 8); p.drawString(420, y + 5, "Data de nascimento:")
    p.setFont("Helvetica-Bold", 11); p.drawString(500, y + 5, str(paciente.get("Data de Nascimento", "")))
    p.line(498, y, width - margin, y)
    y -= 30

    # (O resto do desenho do PDF permanece o mesmo...)
    # ...
    
    p.save()
    buffer.seek(0)
    return buffer

# (O resto das funções de extração, validação e análise permanecem as mesmas)
# ...

# --- INICIALIZAÇÃO ---
planilha_conectada = conectar_planilha()

# --- NAVEGAÇÃO E PÁGINAS ---
st.sidebar.title("Navegação")
paginas = ["Coletar Fichas", "Dashboard", "Gerar Relatórios", "Gerar Ficha IVCF-20"]
pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas)

# (As páginas de Coleta e Dashboard permanecem as mesmas)
# ...

# --- PÁGINA 4: GERAR FICHA IVCF-20 ---
if pagina_selecionada == "Gerar Ficha IVCF-20":
    st.header("📝 Gerar Ficha de Vulnerabilidade (IVCF-20)")
    st.info("Esta ferramenta gera o formulário completo da ficha IVCF-20 para pacientes com 60 anos ou mais.")
    
    df_completo = ler_dados_da_planilha(planilha_conectada)
    df_idosos = df_completo[df_completo['Idade'] >= 60].copy()
    
    if not df_idosos.empty:
        lista_pacientes = df_idosos['Nome Completo'].tolist()
        
        paciente_selecionado_nome = st.selectbox(
            "Selecione um paciente para gerar a ficha:",
            options=lista_pacientes,
            index=None,
            placeholder="Escolha um paciente..."
        )
        
        if paciente_selecionado_nome:
            dados_paciente = df_idosos[df_idosos['Nome Completo'] == paciente_selecionado_nome].iloc[0].to_dict()
            
            st.write("---")
            st.subheader("Dados que serão preenchidos no cabeçalho:")
            st.write(f"**Nome:** {dados_paciente['Nome Completo']}")
            st.write(f"**CPF/CNS:** {dados_paciente.get('CPF', 'Não informado')}")
            st.write(f"**Data de Nascimento:** {dados_paciente['Data de Nascimento']}")
            
            pdf_ficha = gerar_pdf_ivcf20_completo(dados_paciente)
            
            st.download_button(
                label="Descarregar Ficha IVCF-20 Completa em PDF",
                data=pdf_ficha,
                file_name=f"IVCF20_COMPLETO_{paciente_selecionado_nome.replace(' ', '_')}.pdf",
                mime="application/pdf"
            )
    else:
        st.warning("Não foram encontrados registos de pacientes com 60 anos ou mais na planilha.")
