import streamlit as st
import requests
import json
import cohere
import gspread
from PIL import Image
import time
import re
import pandas as pd
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from io import BytesIO
import urllib.parse

# --- Interface Streamlit ---
st.set_page_config(page_title="Coleta Inteligente", page_icon="🤖", layout="wide")

# --- Funções de Validação e Utilitárias ---
def validar_cpf(cpf: str) -> bool:
    cpf = ''.join(re.findall(r'\d', str(cpf)))
    if not cpf or len(cpf) != 11 or cpf == cpf[0] * 11: return False
    try:
        soma = sum(int(cpf[i]) * (10 - i) for i in range(9)); d1 = (soma * 10 % 11) % 10
        if d1 != int(cpf[9]): return False
        soma = sum(int(cpf[i]) * (11 - i) for i in range(10)); d2 = (soma * 10 % 11) % 10
        if d2 != int(cpf[10]): return False
    except: return False
    return True

def validar_data_nascimento(data_str: str) -> (bool, str):
    try:
        data_obj = datetime.strptime(data_str, '%d/%m/%Y').date()
        if data_obj > datetime.now().date(): return False, "A data de nascimento está no futuro."
        return True, ""
    except ValueError: return False, "O formato da data deve ser DD/MM/AAAA."

def calcular_idade(data_nasc):
    if pd.isna(data_nasc): return 0
    hoje = datetime.now()
    return hoje.year - data_nasc.year - ((hoje.month, hoje.day) < (hoje.month, hoje.day))

# --- Funções de Conexão e API ---
@st.cache_resource
def conectar_planilha():
    try:
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
        sheet = client.open_by_key(st.secrets["SHEETSID"]).sheet1
        return sheet
    except Exception as e:
        st.error(f"Erro ao conectar com o Google Sheets: {e}"); return None

@st.cache_data(ttl=300)
def ler_dados_da_planilha(_planilha):
    try:
        dados = _planilha.get_all_records()
        df = pd.DataFrame(dados)
        colunas_esperadas = ["ID", "FAMÍLIA", "Nome Completo", "Data de Nascimento", "Telefone", "CPF", "Nome da Mãe", "Nome do Pai", "Sexo", "CNS", "Município de Nascimento"]
        for col in colunas_esperadas:
            if col not in df.columns: df[col] = ""
        df['Data de Nascimento DT'] = pd.to_datetime(df['Data de Nascimento'], format='%d/%m/%Y', errors='coerce')
        df['Idade'] = df['Data de Nascimento DT'].apply(lambda dt: calcular_idade(dt) if pd.notnull(dt) else 0)
        return df
    except Exception as e:
        st.error(f"Erro ao ler os dados da planilha: {e}"); return pd.DataFrame()

def ocr_space_api(file_bytes, ocr_api_key):
    try:
        url = "https://api.ocr.space/parse/image"
        payload = {"language": "por", "isOverlayRequired": False, "OCREngine": 2}
        files = {"file": ("ficha.jpg", file_bytes, "image/jpeg")}
        headers = {"apikey": ocr_api_key}
        response = requests.post(url, data=payload, files=files, headers=headers)
        response.raise_for_status()
        result = response.json()
        if result.get("IsErroredOnProcessing"): st.error(f"Erro no OCR: {result.get('ErrorMessage')}"); return None
        return result["ParsedResults"][0]["ParsedText"]
    except Exception as e:
        st.error(f"Erro inesperado no OCR: {e}"); return None

def extrair_dados_com_cohere(texto_extraido: str, cohere_client):
    try:
        prompt = f"""
        Sua tarefa é extrair informações de um texto de formulário de saúde e convertê-lo para um JSON.
        Instrução Crítica: Procure por uma anotação à mão que pareça um código de família (ex: 'FAM111'). Este código deve ir para a chave "FAMÍLIA".
        Retorne APENAS um objeto JSON com as chaves: 'ID', 'FAMÍLIA', 'Nome Completo', 'Data de Nascimento', 'Telefone', 'CPF', 'Nome da Mãe', 'Nome do Pai', 'Sexo', 'CNS', 'Município de Nascimento'.
        Se um valor não for encontrado, retorne uma string vazia "".
        Texto para analisar: --- {texto_extraido} ---
        """
        response = cohere_client.chat(model="command-r-plus", message=prompt, temperature=0.1)
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except Exception as e:
        st.error(f"Erro ao chamar a API do Cohere: {e}"); return None

def salvar_no_sheets(dados, planilha):
    try:
        cabecalhos = planilha.row_values(1)
        nova_linha = [dados.get(cabecalho, "") for cabecalho in cabecalhos]
        planilha.append_row(nova_linha)
        st.success(f"✅ Dados de '{dados.get('Nome Completo', 'Desconhecido')}' salvos com sucesso!")
        st.balloons()
    except Exception as e:
        st.error(f"Erro ao salvar na planilha: {e}")
        
def gerar_pdf_etiquetas(familias_agrupadas):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    x_pos = inch; y_pos = height - inch; line_height = 20
    
    for familia_id, membros in familias_agrupadas.items():
        if not familia_id: continue
        p.setFont("Helvetica-Bold", 14)
        p.drawString(x_pos, y_pos, f"Família: {familia_id}")
        y_pos -= line_height
        p.setFont("Helvetica", 12)
        for membro in membros:
            p.drawString(x_pos + 20, y_pos, f"- {membro}")
            y_pos -= line_height
            if y_pos < inch:
                p.showPage()
                y_pos = height - inch
        y_pos -= line_height * 1.5
        if y_pos < inch:
            p.showPage()
            y_pos = height - inch
            
    p.save()
    buffer.seek(0)
    return buffer
    
# --- FUNÇÃO DE GERAR CAPAS COM NOVO DESIGN ---
def gerar_pdf_capas_prontuario(pacientes_selecionados):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    for index, paciente in pacientes_selecionados.iterrows():
        # --- Cabeçalho e Título ---
        p.setFont("Helvetica-Bold", 14)
        p.drawRightString(width - inch, height - 0.75 * inch, "PB01")
        p.setFont("Helvetica-Bold", 24)
        p.drawCentredString(width / 2.0, height - 1.5 * inch, "PRONTUÁRIO DO PACIENTE")
        
        # --- Caixa Principal de Informações ---
        box_x = inch
        box_y = height - 6 * inch # Posição vertical da caixa
        box_width = width - 2 * inch
        box_height = 4 * inch
        p.setStrokeColorRGB(0.2, 0.2, 0.2)
        p.setLineWidth(1)
        p.roundRect(box_x, box_y, box_width, box_height, 10) # Desenha a caixa com cantos arredondados

        # --- Conteúdo Dentro da Caixa ---
        # Nome do Paciente (com destaque)
        y_pos = box_y + box_height - 0.75 * inch
        p.setFont("Helvetica-Bold", 22)
        p.setFillColorRGB(0, 0, 0) # Cor do texto preta
        p.drawString(box_x + 0.3 * inch, y_pos, str(paciente.get("Nome Completo", "")))
        
        # Linha divisória abaixo do nome
        y_pos -= 0.25 * inch
        p.line(box_x + 0.3 * inch, y_pos, box_x + box_width - 0.3 * inch, y_pos)
        
        # Layout de duas colunas para os outros dados
        y_pos -= 0.6 * inch
        x_col1_label = box_x + 0.3 * inch
        x_col1_value = x_col1_label + 1.3 * inch
        x_col2_label = box_x + box_width / 2
        x_col2_value = x_col2_label + 0.8 * inch
        line_height = 0.4 * inch

        # Coluna 1
        p.setFont("Helvetica", 12)
        p.drawString(x_col1_label, y_pos, "Data de Nasc.:")
        p.setFont("Helvetica-Bold", 12)
        p.drawString(x_col1_value, y_pos, str(paciente.get("Data de Nascimento", "")))
        y_pos -= line_height
        p.setFont("Helvetica", 12)
        p.drawString(x_col1_label, y_pos, "CPF:")
        p.setFont("Helvetica-Bold", 12)
        p.drawString(x_col1_value, y_pos, str(paciente.get("CPF", "")))

        # Coluna 2
        y_pos = box_y + box_height - 1.6 * inch # Reseta a posição Y para a segunda coluna
        p.setFont("Helvetica", 12)
        p.drawString(x_col2_label, y_pos, "Família:")
        p.setFont("Helvetica-Bold", 12)
        p.drawString(x_col2_value, y_pos, str(paciente.get("FAMÍLIA", "")))
        y_pos -= line_height
        p.setFont("Helvetica", 12)
        p.drawString(x_col2_label, y_pos, "CNS:")
        p.setFont("Helvetica-Bold", 12)
        p.drawString(x_col2_value, y_pos, str(paciente.get("CNS", "")))
        
        # Adiciona uma nova página para o próximo paciente (se houver)
        if not index == pacientes_selecionados.index[-1]:
            p.showPage()
            
    p.save()
    buffer.seek(0)
    return buffer

# --- PÁGINAS DO APP ---

def pagina_coleta(planilha, co_client):
    st.title("🤖 COLETA INTELIGENTE")
    st.header("1. Envie uma ou mais imagens de fichas")
    # ... (código da página de coleta continua igual) ...

def pagina_dashboard(planilha):
    st.title("📊 Dashboard de Dados")
    # ... (código da página de dashboard continua igual) ...

def pagina_pesquisa(planilha):
    st.title("🔎 Ferramenta de Pesquisa")
    # ... (código da página de pesquisa continua igual) ...

def pagina_etiquetas(planilha):
    st.title("🏷️ Gerador de Etiquetas por Família")
    # ... (código da página de etiquetas continua igual) ...

def pagina_capas_prontuario(planilha):
    st.title("📇 Gerador de Capas de Prontuário")
    df = ler_dados_da_planilha(planilha)
    if df.empty: st.warning("Ainda não há dados na planilha para gerar capas."); return

    st.subheader("1. Selecione os pacientes")
    lista_pacientes = df['Nome Completo'].tolist()
    pacientes_selecionados_nomes = st.multiselect("Escolha um ou mais pacientes para gerar as capas:", sorted(lista_pacientes))

    if pacientes_selecionados_nomes:
        pacientes_df = df[df['Nome Completo'].isin(pacientes_selecionados_nomes)]
        
        st.subheader("2. Pré-visualização")
        st.dataframe(pacientes_df[["Nome Completo", "Data de Nascimento", "FAMÍLIA", "CPF", "CNS"]])
        
        if st.button("📥 Gerar PDF das Capas"):
            pdf_bytes = gerar_pdf_capas_prontuario(pacientes_df)
            st.download_button(label="Descarregar PDF das Capas", data=pdf_bytes, file_name=f"capas_prontuario_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf")
    else:
        st.info("Selecione pelo menos um paciente para gerar as capas.")

def pagina_whatsapp(planilha):
    st.title("📱 Enviar Mensagens de WhatsApp")
    # ... (código da página de whatsApp continua igual) ...
            
# --- LÓGICA PRINCIPAL DE EXECUÇÃO (com menu) ---
def main():
    try:
        st.session_state.co_client = cohere.Client(api_key=st.secrets["COHEREKEY"])
        planilha_conectada = conectar_planilha()
    except Exception as e:
        st.error(f"Não foi possível inicializar os serviços. Verifique seus segredos. Erro: {e}"); st.stop()
    
    st.sidebar.title("Navegação")
    paginas = {
        "Coletar Fichas": lambda: pagina_coleta(planilha_conectada, st.session_state.co_client),
        "Dashboard": lambda: pagina_dashboard(planilha_conectada),
        "Pesquisar Paciente": lambda: pagina_pesquisa(planilha_conectada),
        "Gerar Etiquetas": lambda: pagina_etiquetas(planilha_conectada),
        "Gerar Capas de Prontuário": lambda: pagina_capas_prontuario(planilha_conectada),
        "Enviar WhatsApp": lambda: pagina_whatsapp(planilha_conectada),
    }
    pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas.keys())
    
    if planilha_conectada is not None:
        paginas[pagina_selecionada]()
    else:
        st.error("A conexão com a planilha falhou. Não é possível carregar a página.")

if __name__ == "__main__":
    # O código das páginas que não foram mostradas em detalhe permanece o mesmo das versões anteriores
    # Por favor, copie e cole o código completo para garantir que todas as funções estejam presentes.
    main()
