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
        df['Idade'] = df['Data de Nascimento DT'].apply(lambda dt: calcular_idade(dt) if pd.notnull(dt) else 0)
        
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
            range_to_update = f'A{cell.row}:{chr(ord("A") + len(valores_atualizados) - 1)}{cell.row}'
            planilha.update(range_to_update, [valores_atualizados])
            return True
        return False
    except Exception as e:
        st.error(f"Ocorreu um erro ao tentar atualizar a linha. Erro: {e}")
        return False

def extrair_dados_com_gemini(image_bytes):
    """Extrai dados da imagem usando a API do Google Gemini."""
    try:
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel('gemini-1.5-pro-latest')
        image_bytes.seek(0)
        image = Image.open(image_bytes)
        prompt = "Analise esta imagem de um formulário e extraia as seguintes informações: ID Família, Nome Completo, Data de Nascimento (DD/MM/AAAA), Telefone, CPF, Nome da Mãe, Nome do Pai, Sexo, CNS, Município de Nascimento. Se um dado não for encontrado, retorne um campo vazio. Retorne os dados estritamente como um objeto JSON."
        response = model.generate_content([prompt, image])
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except Exception as e:
        st.error(f"Erro ao extrair dados com Gemini. Verifique a sua chave da API. Erro: {e}")
        return None

def validar_dados_com_gemini(dados_para_validar):
    """Envia os dados extraídos para o Gemini para uma verificação de qualidade."""
    try:
        model = genai.GenerativeModel('gemini-1.5-pro-latest')
        prompt_validacao = f'Você é um auditor de qualidade de dados de saúde do Brasil. Analise o seguinte JSON e verifique se há inconsistências óbvias (CPF, Data de Nascimento, CNS). Responda APENAS com um objeto JSON com uma chave "avisos" que é uma lista de strings em português com os problemas encontrados. Se não houver problemas, a lista deve ser vazia. Dados para validar: {json.dumps(dados_para_validar)}'
        response = model.generate_content(prompt_validacao)
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except Exception as e:
        print(f"Erro na validação com Gemini: {e}")
        return {"avisos": []}

def analisar_dados_com_gemini(pergunta_usuario, dataframe):
    """Usa o Gemini para responder perguntas sobre os dados da planilha."""
    if dataframe.empty:
        return "Não há dados na planilha para analisar."
    dados_string = dataframe.to_string()
    model = genai.GenerativeModel('gemini-1.5-pro-latest')
    prompt_analise = f'Você é um assistente de análise de dados. Sua tarefa é responder à pergunta do utilizador com base nos dados da tabela fornecida. Seja claro, direto e responda apenas com base nos dados. Pergunta do utilizador: "{pergunta_usuario}". Dados da Tabela:\n{dados_string}'
    try:
        response = model.generate_content(prompt_analise)
        return response.text
    except Exception as e:
        return f"Ocorreu um erro ao analisar os dados com a IA. Erro: {e}"
        
def gerar_pdf_relatorio(dataframe, titulo):
    """Gera um PDF a partir de um DataFrame do Pandas."""
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    margin = 0.75 * inch
    y = height - margin
    
    p.setFont("Helvetica-Bold", 16)
    p.drawString(margin, y, titulo)
    y -= 0.5 * inch
    
    if dataframe.empty:
        p.setFont("Helvetica", 12)
        p.drawString(margin, y, "Nenhum dado encontrado para os filtros selecionados.")
    else:
        p.setFont("Helvetica-Bold", 10)
        colunas = dataframe.columns
        x_positions = [margin + (i * ((width - 2 * margin) / len(colunas))) for i in range(len(colunas))]
        for i, header in enumerate(colunas):
            p.drawString(x_positions[i], y, str(header))
        y -= 0.25 * inch
        p.setFont("Helvetica", 8)
        for index, row in dataframe.iterrows():
            if y < margin:
                p.showPage()
                p.setFont("Helvetica", 8)
                y = height - margin
            for i, value in enumerate(row):
                p.drawString(x_positions[i], y, str(value))
            y -= 0.2 * inch
            
    p.save()
    buffer.seek(0)
    return buffer

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
    
    # Corpo do formulário
    # (O código para desenhar as 20 perguntas e o rodapé vai aqui)
    # ...

    p.save()
    buffer.seek(0)
    return buffer

# --- ESTRUTURA PRINCIPAL DO APP ---

def pagina_coleta():
    st.header("Envie a imagem da ficha")
    uploaded_file = st.file_uploader("Escolha uma imagem", type=['jpg', 'jpeg', 'png'], key="uploader_coleta")
    if 'dados_extraidos' not in st.session_state:
        st.session_state.dados_extraidos = None
    if uploaded_file is not None:
        st.image(uploaded_file, caption="Imagem Carregada.", use_container_width=True)
        if st.button("🔎 Extrair e Validar Dados"):
            with st.spinner("A IA está a analisar a imagem..."):
                st.session_state.dados_extraidos = extrair_dados_com_gemini(uploaded_file)
            if st.session_state.dados_extraidos:
                st.success("Dados extraídos!")
                with st.spinner("A IA está a verificar a qualidade dos dados..."):
                    resultado_validacao = validar_dados_com_gemini(st.session_state.dados_extraidos)
                if resultado_validacao and resultado_validacao.get("avisos"):
                    st.warning("Atenção! A IA encontrou os seguintes possíveis problemas:")
                    for aviso in resultado_validacao["avisos"]: st.write(f"- {aviso}")
            else:
                st.error("Não foi possível extrair dados da imagem.")
    if st.session_state.dados_extraidos:
        st.markdown("---")
        st.header("Confirme e corrija os dados antes de enviar")
        with st.form("formulario_de_correcao"):
            dados = st.session_state.dados_extraidos
            # (Campos do formulário)
            id_familia = st.text_input("ID Família", value=dados.get("ID Família", "")); nome_completo = st.text_input("Nome Completo", value=dados.get("Nome Completo", "")); data_nascimento = st.text_input("Data de Nascimento", value=dados.get("Data de Nascimento", "")); telefone = st.text_input("Telefone", value=dados.get("Telefone", "")); cpf = st.text_input("CPF", value=dados.get("CPF", "")); nome_mae = st.text_input("Nome da Mãe", value=dados.get("Nome da Mãe", "")); nome_pai = st.text_input("Nome do Pai", value=dados.get("Nome do Pai", "")); sexo = st.text_input("Sexo", value=dados.get("Sexo", "")); cns = st.text_input("CNS", value=dados.get("CNS", "")); municipio_nascimento = st.text_input("Município de Nascimento", value=dados.get("Município de Nascimento", ""))
            submitted = st.form_submit_button("✅ Enviar para a Planilha")
            if submitted:
                with st.spinner("A enviar os dados..."):
                    try:
                        timestamp_envio = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                        nova_linha = [id_familia, nome_completo, data_nascimento, telefone, cpf, nome_mae, nome_pai, sexo, cns, municipio_nascimento, timestamp_envio]
                        planilha_conectada.append_row(nova_linha)
                        st.success("🎉 Dados enviados para a planilha com sucesso!"); st.balloons()
                        st.session_state.dados_extraidos = None
                        st.experimental_rerun()
                    except Exception as e:
                        st.error(f"Ocorreu um erro ao enviar os dados para a planilha. Erro: {e}")

def pagina_dashboard():
    st.header("📊 Dashboard de Dados Coletados")
    planilha_conectada = conectar_planilha()
    df = ler_dados_da_planilha(planilha_conectada)
    if not df.empty:
        st.subheader("Resumo Geral")
        # (código das métricas e gráficos) ...
        st.markdown("---")
        st.subheader("⚙️ Gerir Registos")
        # (código de apagar e editar) ...
        st.markdown("---")
        st.subheader("🤖 Converse com seus Dados")
        # (código da pesquisa com IA) ...
        st.markdown("---")
        st.subheader("Dados Completos")
        st.dataframe(df, use_container_width=True)
        # (código do botão de exportação) ...
    else:
        st.warning("Ainda não há dados na planilha para exibir.")

def pagina_relatorios():
    st.header("📄 Gerador de Relatórios Personalizados")
    planilha_conectada = conectar_planilha()
    df_completo = ler_dados_da_planilha(planilha_conectada)
    if not df_completo.empty:
        # (código da página de relatórios) ...
        pass
    else:
        st.warning("Não há dados na planilha para gerar relatórios.")

def pagina_ficha_ivcf20():
    st.header("📝 Gerar Ficha de Vulnerabilidade (IVCF-20)")
    planilha_conectada = conectar_planilha()
    df_completo = ler_dados_da_planilha(planilha_conectada)
    df_idosos = df_completo[df_completo['Idade'] >= 60].copy()
    if not df_idosos.empty:
        lista_pacientes = df_idosos['Nome Completo'].tolist()
        paciente_selecionado_nome = st.selectbox("Selecione um paciente:", options=lista_pacientes, index=None)
        if paciente_selecionado_nome:
            dados_paciente = df_idosos[df_idosos['Nome Completo'] == paciente_selecionado_nome].iloc[0].to_dict()
            st.write(f"A gerar ficha para: **{dados_paciente['Nome Completo']}**")
            pdf_ficha = gerar_pdf_ivcf20_completo(dados_paciente)
            st.download_button(label="Descarregar Ficha IVCF-20 Completa em PDF", data=pdf_ficha, file_name=f"IVCF20_{paciente_selecionado_nome.replace(' ', '_')}.pdf", mime="application/pdf")
    else:
        st.warning("Não foram encontrados registos de pacientes com 60 anos ou mais.")

# --- LÓGICA PRINCIPAL DE EXECUÇÃO ---
st.sidebar.title("Navegação")
paginas = {
    "Coletar Fichas": pagina_coleta,
    "Dashboard": pagina_dashboard,
    "Gerar Relatórios": pagina_relatorios,
    "Gerar Ficha IVCF-20": pagina_ficha_ivcf20
}
pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas.keys())

# Executa a função da página selecionada
paginas[pagina_selecionada]()
