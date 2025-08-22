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
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.units import inch, cm
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

# --- FUNÇÃO DE ETIQUETAS COM LINHA PONTILHADA ---
def gerar_pdf_etiquetas(familias_agrupadas):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=landscape(A4))
    width, height = landscape(A4)

    margin = 1 * cm
    etiqueta_width = (width - 3 * margin) / 2
    etiqueta_height = (height - 3 * margin) / 2
    
    posicoes = [
        (margin, height - margin - etiqueta_height),
        (margin * 2 + etiqueta_width, height - margin - etiqueta_height),
        (margin, margin),
        (margin * 2 + etiqueta_width, margin),
    ]
    
    etiqueta_count = 0
    
    for familia_id, membros in familias_agrupadas.items():
        if not familia_id: continue

        if etiqueta_count % 4 == 0 and etiqueta_count > 0:
            p.showPage()
        
        idx_posicao = etiqueta_count % 4
        x, y = posicoes[idx_posicao]
        
        # --- BORDA PONTILHADA ADICIONADA AQUI ---
        p.setStrokeColorRGB(0.5, 0.5, 0.5)
        p.setDash(6, 3) # Define o padrão do pontilhado: 6 pontos de linha, 3 pontos de espaço
        p.rect(x, y, etiqueta_width, etiqueta_height)
        p.setDash([]) # Remove o pontilhado para os textos seguintes
        
        y_pos = y + etiqueta_height - (0.7 * cm)
        x_pos = x + (0.5 * cm)
        
        p.setFont("Helvetica-Bold", 12)
        p.drawString(x_pos, y_pos, f"Família: {familia_id}")
        y_pos -= 0.5 * cm
        p.line(x_pos, y_pos, x + etiqueta_width - (0.5 * cm), y_pos)
        y_pos -= 0.5 * cm

        for membro in membros:
            if y_pos < y + (1 * cm): break
            
            p.setFont("Helvetica-Bold", 9)
            p.drawString(x_pos, y_pos, str(membro.get("Nome Completo", "")))
            y_pos -= 0.4 * cm
            
            p.setFont("Helvetica", 8)
            p.drawString(x_pos + (0.5*cm), y_pos, f"DN: {membro.get('Data de Nascimento', 'N/A')}  |  CNS: {membro.get('CNS', 'N/A')}")
            y_pos -= 0.6 * cm
            
        etiqueta_count += 1
            
    p.save()
    buffer.seek(0)
    return buffer
    
def gerar_pdf_capas_prontuario(pacientes_selecionados):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    for index, paciente in pacientes_selecionados.iterrows():
        p.setFont("Helvetica-Bold", 14); p.drawRightString(width - inch, height - 0.75 * inch, "PB01")
        p.setFont("Helvetica-Bold", 24); p.drawCentredString(width / 2.0, height - 1.5 * inch, "PRONTUÁRIO DO PACIENTE")
        
        p.line(inch, height - 2.2 * inch, width - inch, height - 2.2 * inch)
        
        box_x = inch; box_y = height - 6 * inch
        box_width = width - 2 * inch; box_height = 4 * inch
        p.setStrokeColorRGB(0.2, 0.2, 0.2); p.setLineWidth(1)
        p.roundRect(box_x, box_y, box_width, box_height, 10)

        y_pos = box_y + box_height - 0.75 * inch
        p.setFont("Helvetica-Bold", 22); p.setFillColorRGB(0, 0, 0)
        p.drawString(box_x + 0.3 * inch, y_pos, str(paciente.get("Nome Completo", "")))
        
        y_pos -= 0.25 * inch
        p.line(box_x + 0.3 * inch, y_pos, box_x + box_width - 0.3 * inch, y_pos)
        
        y_pos -= 0.6 * inch
        x_col1_label = box_x + 0.3 * inch; x_col1_value = x_col1_label + 1.3 * inch
        x_col2_label = box_x + box_width / 2; x_col2_value = x_col2_label + 0.8 * inch
        line_height = 0.4 * inch

        p.setFont("Helvetica", 12); p.drawString(x_col1_label, y_pos, "Data de Nasc.:")
        p.setFont("Helvetica-Bold", 12); p.drawString(x_col1_value, y_pos, str(paciente.get("Data de Nascimento", "")))
        y_pos -= line_height
        p.setFont("Helvetica", 12); p.drawString(x_col1_label, y_pos, "CPF:")
        p.setFont("Helvetica-Bold", 12); p.drawString(x_col1_value, y_pos, str(paciente.get("CPF", "")))

        y_pos = box_y + box_height - 1.6 * inch
        p.setFont("Helvetica", 12); p.drawString(x_col2_label, y_pos, "Família:")
        p.setFont("Helvetica-Bold", 12); p.drawString(x_col2_value, y_pos, str(paciente.get("FAMÍLIA", "")))
        y_pos -= line_height
        p.setFont("Helvetica", 12); p.drawString(x_col2_label, y_pos, "CNS:")
        p.setFont("Helvetica-Bold", 12); p.drawString(x_col2_value, y_pos, str(paciente.get("CNS", "")))
        
        if not index == pacientes_selecionados.index[-1]: p.showPage()
            
    p.save()
    buffer.seek(0)
    return buffer

# --- PÁGINAS DO APP ---
def pagina_coleta(planilha, co_client):
    st.title("🤖 COLETA INTELIGENTE")
    # ... (código inalterado) ...

def pagina_dashboard(planilha):
    st.title("📊 Dashboard de Dados")
    # ... (código inalterado) ...

def pagina_pesquisa(planilha):
    st.title("🔎 Ferramenta de Pesquisa")
    # ... (código inalterado) ...

def pagina_etiquetas(planilha):
    st.title("🏷️ Gerador de Etiquetas por Família")
    df = ler_dados_da_planilha(planilha)
    if df.empty: st.warning("Ainda não há dados na planilha para gerar etiquetas."); return
        
    familias_dict = df.groupby('FAMÍLIA')[['Nome Completo', 'Data de Nascimento', 'CNS']].apply(lambda x: x.to_dict('records')).to_dict()
    
    lista_familias = [f for f in familias_dict.keys() if f]
    st.subheader("1. Selecione as famílias")
    familias_selecionadas = st.multiselect("Deixe em branco para selecionar todas as famílias:", sorted(lista_familias))

    if not familias_selecionadas: familias_para_gerar = familias_dict
    else: familias_para_gerar = {fid: familias_dict[fid] for fid in familias_selecionadas}

    st.subheader("2. Pré-visualização e Geração do PDF")
    if not familias_para_gerar: st.warning("Nenhuma família para exibir."); return

    for familia_id, membros in familias_para_gerar.items():
        if familia_id:
            with st.expander(f"**Família: {familia_id}** ({len(membros)} membro(s))"):
                for membro in membros:
                    st.write(f"**{membro['Nome Completo']}**")
                    st.caption(f"DN: {membro['Data de Nascimento']} | CNS: {membro['CNS']}")
    
    if st.button("📥 Gerar PDF das Etiquetas"):
        pdf_bytes = gerar_pdf_etiquetas(familias_para_gerar)
        st.download_button(label="Descarregar PDF", data=pdf_bytes, file_name=f"etiquetas_{'selecionadas' if familias_selecionadas else 'todas'}_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf")

def pagina_capas_prontuario(planilha):
    st.title("📇 Gerador de Capas de Prontuário")
    # ... (código inalterado) ...

def pagina_whatsapp(planilha):
    st.title("📱 Enviar Mensagens de WhatsApp")
    # ... (código inalterado) ...
            
# --- LÓGICA PRINCIPAL DE EXECUÇÃO (com menu completo) ---
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

