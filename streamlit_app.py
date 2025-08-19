import streamlit as st
import gspread
import json
import pandas as pd
import cohere
import base64
import requests # Importante para o método direto
from io import BytesIO
from datetime import datetime
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import simpleSplit

# --- Configuração da Página e Título ---
st.set_page_config(page_title="Coleta Inteligente", page_icon="🤖", layout="wide")
st.title("🤖 Coleta Inteligente")

# --- CONEXÃO E VARIÁVEIS DE AMBIENTE ---
try:
    cohere_api_key = st.secrets["COHEREKEY"]
    co = cohere.Client(cohere_api_key) # Mantemos para a função de chat de texto
    
    google_sheets_id = st.secrets["SHEETSID"]
    google_credentials_dict = st.secrets["gcp_service_account"]

except KeyError as e:
    st.error(f"Erro de configuração: A chave secreta '{e.args[0]}' não foi encontrada.")
    st.stop()
except Exception as e:
    st.error(f"Erro inesperado ao carregar as chaves secretas. Erro: {e}")
    st.stop()

# --- FUNÇÕES ---

@st.cache_resource
def conectar_planilha():
    try:
        gc = gspread.service_account_from_dict(google_credentials_dict)
        planilha = gc.open_by_key(google_sheets_id).sheet1
        return planilha
    except Exception as e:
        st.error(f"Não foi possível conectar à planilha. Erro: {e}")
        st.stop()

def calcular_idade(data_nasc):
    if pd.isna(data_nasc): return 0
    hoje = datetime.now()
    return hoje.year - data_nasc.year - ((hoje.month, hoje.day) < (hoje.month, hoje.day))

@st.cache_data(ttl=60)
def ler_dados_da_planilha(_planilha):
    try:
        dados = _planilha.get_all_records()
        df = pd.DataFrame(dados)
        colunas_esperadas = ["ID Família", "Nome Completo", "Data de Nascimento", "Telefone", "CPF", "Nome da Mãe", "Nome do Pai", "Sexo", "CNS", "Município de Nascimento", "Timestamp de Envio"]
        for col in colunas_esperadas:
            if col not in df.columns: df[col] = ""
        df['Data de Nascimento DT'] = pd.to_datetime(df['Data de Nascimento'], format='%d/%m/%Y', errors='coerce')
        df['Idade'] = df['Data de Nascimento DT'].apply(lambda dt: calcular_idade(dt) if pd.notnull(dt) else 0)
        return df
    except Exception as e:
        st.error(f"Não foi possível ler os dados da planilha. Erro: {e}")
        return pd.DataFrame()

# --- FUNÇÕES DE IA (VERSÃO FINAL E MISTA) ---

def extrair_dados_com_cohere(image_bytes):
    """Extrai dados da imagem usando a API REST (método direto) do Cohere."""
    try:
        # Prepara a mensagem para a API com o prompt
        prompt = "Analise esta imagem de um formulário e extraia as seguintes informações: ID Família, Nome Completo, Data de Nascimento (DD/MM/AAAA), Telefone, CPF, Nome da Mãe, Nome do Pai, Sexo, CNS, Município de Nascimento. Se um dado não for encontrado, retorne um campo vazio. Retorne os dados estritamente como um objeto JSON, sem nenhum texto ou formatação adicional como ```json."
        
        # Prepara os arquivos para upload
        files = {
            "prompt": (None, prompt),
            "model": (None, "command-r-plus"),
            "attachment": ("image.jpg", image_bytes.getvalue(), "image/jpeg")
        }

        # Prepara os cabeçalhos com a autenticação
        headers = { "Authorization": f"Bearer {cohere_api_key}" }

        # Faz a chamada direta para o servidor da Cohere
        response = requests.post("[https://api.cohere.com/v1/chat](https://api.cohere.com/v1/chat)", headers=headers, files=files)
        response.raise_for_status()
        
        response_json = response.json()
        json_string = response_json['text'].strip()
        return json.loads(json_string)

    except requests.exceptions.HTTPError as http_err:
        st.error(f"Erro de HTTP ao chamar a API Cohere: {http_err} - {response.text}")
        return None
    except Exception as e:
        st.error(f"Erro ao extrair dados com a IA (Método Direto). Erro: {e}")
        return None

def analisar_dados_com_cohere(pergunta_usuario, dataframe):
    """Usa a biblioteca Cohere para responder perguntas sobre texto."""
    try:
        if dataframe.empty:
            return "Não há dados na planilha para analisar."
        dados_string = dataframe.to_string()
        preamble = f"Você é um assistente de análise de dados. Responda à pergunta do utilizador com base nos dados da tabela fornecida. Dados da Tabela:\n{dados_string}"
        response = co.chat(message=pergunta_usuario, preamble=preamble, model="command-r-plus")
        return response.text
    except Exception as e:
        return f"Ocorreu um erro ao analisar os dados com a IA (Cohere). Erro: {e}"

# --- PÁGINAS DO APP ---
def pagina_coleta(planilha):
    st.header("1. Envie a imagem da ficha")
    uploaded_file = st.file_uploader("Escolha uma imagem", type=['jpg', 'jpeg', 'png'], key="uploader_coleta")
    if 'dados_extraidos' not in st.session_state:
        st.session_state.dados_extraidos = None
    if uploaded_file is not None:
        st.image(uploaded_file, caption="Imagem Carregada.", use_container_width=True)
        if st.button("🔎 Extrair Dados da Imagem"):
            with st.spinner("A IA está a analisar a imagem..."):
                st.session_state.dados_extraidos = extrair_dados_com_cohere(uploaded_file)
            if st.session_state.dados_extraidos:
                st.success("Dados extraídos!")
            else:
                st.error("Não foi possível extrair dados da imagem.")
    
    if st.session_state.dados_extraidos:
        st.markdown("---")
        st.header("2. Confirme e corrija os dados antes de enviar")
        with st.form("formulario_de_correcao"):
            dados = st.session_state.dados_extraidos
            id_familia = st.text_input("ID Família", value=dados.get("ID Família", "")); nome_completo = st.text_input("Nome Completo", value=dados.get("Nome Completo", "")); data_nascimento = st.text_input("Data de Nascimento", value=dados.get("Data de Nascimento", "")); telefone = st.text_input("Telefone", value=dados.get("Telefone", "")); cpf = st.text_input("CPF", value=dados.get("CPF", "")); nome_mae = st.text_input("Nome da Mãe", value=dados.get("Nome da Mãe", "")); nome_pai = st.text_input("Nome do Pai", value=dados.get("Nome do Pai", "")); sexo = st.text_input("Sexo", value=dados.get("Sexo", "")); cns = st.text_input("CNS", value=dados.get("CNS", "")); municipio_nascimento = st.text_input("Município de Nascimento", value=dados.get("Município de Nascimento", ""))
            submitted = st.form_submit_button("✅ Enviar para a Planilha")
            if submitted:
                with st.spinner("A enviar os dados..."):
                    try:
                        timestamp_envio = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                        nova_linha = [id_familia, nome_completo, data_nascimento, telefone, cpf, nome_mae, nome_pai, sexo, cns, municipio_nascimento, timestamp_envio]
                        planilha.append_row(nova_linha)
                        st.success("🎉 Dados enviados para a planilha com sucesso!"); st.balloons()
                        st.session_state.dados_extraidos = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ocorreu um erro ao enviar os dados para a planilha. Erro: {e}")

def pagina_dashboard(planilha):
    st.header("📊 Dashboard e Análise com IA")
    df = ler_dados_da_planilha(planilha)
    if not df.empty:
        st.subheader("🤖 Converse com seus Dados")
        pergunta = st.text_area("Faça uma pergunta em português sobre os dados da planilha:")
        if st.button("Analisar com IA"):
            if pergunta:
                with st.spinner("A IA está a pensar..."):
                    resposta = analisar_dados_com_cohere(pergunta, df)
                    st.markdown(resposta)
            else:
                st.warning("Por favor, escreva uma pergunta.")
        st.markdown("---")
        st.subheader("Dados Completos na Planilha")
        st.dataframe(df, use_container_width=True)
    else:
        st.warning("Ainda não há dados na planilha para exibir.")

# --- LÓGICA PRINCIPAL DE EXECUÇÃO ---
def main():
    planilha_conectada = conectar_planilha()
    st.sidebar.title("Navegação")
    paginas = {
        "Coletar Fichas por Imagem": pagina_coleta,
        "Dashboard e Análise IA": pagina_dashboard,
    }
    pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas.keys())
    paginas[pagina_selecionada](planilha_conectada)

if __name__ == "__main__":
    main()
