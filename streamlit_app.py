# Adicione estas duas linhas no TOPO do seu arquivo
from dotenv import load_dotenv
load_dotenv()

import streamlit as st
import json
import os
import pandas as pd
import google.generativeai as genai
from io import BytesIO
from datetime import datetime
from PIL import Image
from supabase import create_client, Client

# --- Configuração da Página e Título ---
st.set_page_config(
    page_title="Aplicativo de Coleta Inteligente",
    page_icon="🤖",
    layout="wide"
)

st.title("🤖 Aplicativo de Coleta Inteligente")
st.markdown("---")

# --- CONEXÃO E VARIÁVEIS DE AMBIENTE ---
try:
    gemini_api_key = os.environ.get("GOOGLE_GEMINI_API_KEY")
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")

    if not all([gemini_api_key, supabase_url, supabase_key]):
        st.error("Erro de configuração: Uma ou mais variáveis de ambiente estão faltando. Verifique seus 'Secrets' no Codespaces.")
        st.stop()

except Exception as e:
    st.error(f"Erro inesperado ao carregar as configurações. Erro: {e}")
    st.stop()


# --- FUNÇÕES ---

@st.cache_resource
def conectar_banco():
    """Conecta com o Supabase e retorna o cliente."""
    try:
        supabase: Client = create_client(supabase_url, supabase_key)
        return supabase
    except Exception as e:
        st.error(f"Não foi possível conectar ao Supabase. Verifique a URL e a Chave. Erro: {e}")
        st.stop()

@st.cache_data(ttl=120)
def ler_dados_do_banco(_db_client):
    """Lê todos os dados da tabela 'pacientes'."""
    try:
        response = _db_client.table('pacientes').select('*').order('id', desc=True).execute()
        df = pd.DataFrame(response.data)
        return df
    except Exception as e:
        st.error(f"Erro ao ler dados do banco. Erro: {e}")
        return pd.DataFrame()

def extrair_dados_com_gemini(image_bytes):

    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel('gemini-pro-vision')

    image_bytes.seek(0)
    image = Image.open(image_bytes)

    prompt = """
    Analise esta imagem de um formulário e extraia as seguintes informações de forma estruturada:
    - ID Família
    - Nome Completo
    - Data de Nascimento (formato DD/MM/AAAA)
    - Telefone (com DDD)
    - CPF (formato 000.000.000-00)
    - Nome da Mãe
    - Nome do Pai
    - Sexo (ex: FEMININO, MASCULINO)
    - CNS (formato 000 0000 0000 0000)
    - Município de Nascimento
    Se algum dado não for encontrado, retorne um campo vazio.
    Retorne os dados estritamente como um objeto JSON válido. Exemplo:
    {"ID Família": "FAM001", "Nome Completo": "NOME DO PACIENTE", ...}
    """

    try:
        response = model.generate_content([prompt, image])
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        dados = json.loads(json_string)
        return dados
    except Exception as e:
        st.error(f"Erro ao extrair dados com Gemini. Erro: {e}")
        return None

def salvar_dados_e_imagem(db_client, dados_paciente, image_bytes, file_name):
    """Faz o upload da imagem e dos dados para o Supabase."""
    try:
        # 1. Upload da imagem para o Storage no bucket 'fichas'
        path_on_storage = f"{datetime.now().strftime('%Y-%m-%d')}/{file_name}"
        image_bytes.seek(0)
        db_client.storage.from_('fichas').upload(path_on_storage, image_bytes.read(), {'content-type': 'image/jpeg', 'x-upsert': 'true'})

        # 2. Obter o link público da imagem
        response_link = db_client.storage.from_('fichas').get_public_url(path_on_storage)
        dados_paciente['link_imagem'] = response_link

        # 3. Inserir os dados na tabela 'pacientes'
        db_client.table('pacientes').insert(dados_paciente).execute()
        return True
    except Exception as e:
        st.error(f"Falha ao salvar no banco de dados ou no storage. Erro: {e}")
        return False

def calcular_idade(data_nascimento):
    if not data_nascimento: return None
    try:
        data_nasc = datetime.strptime(data_nascimento, '%d/%m/%Y')
        hoje = datetime.now()
        return hoje.year - data_nasc.year - ((hoje.month, hoje.day) < (data_nasc.month, data_nasc.day))
    except (ValueError, TypeError): return None


# --- INICIALIZAÇÃO DO APP ---
db_client = conectar_banco()

# --- NAVEGAÇÃO E PÁGINAS ---
st.sidebar.title("Navegação")
page = st.sidebar.radio("Escolha uma página:", ["Coletar Fichas", "Dashboard de Dados"])

if page == "Coletar Fichas":
    st.header("1. Envie a(s) imagem(ns) da(s) ficha(s)")
    uploaded_files = st.file_uploader("Escolha uma ou mais imagens", type=['jpg', 'jpeg', 'png'], accept_multiple_files=True)

    if 'dados_fichas' not in st.session_state:
        st.session_state.dados_fichas = {}

    if uploaded_files:
        if st.button("🔎 Extrair Dados das Imagens"):
            st.session_state.dados_fichas = {}
            with st.spinner("Analisando imagens..."):
                for i, uploaded_file in enumerate(uploaded_files):
                    dados = extrair_dados_com_gemini(uploaded_file)
                    if dados:
                        st.session_state.dados_fichas[uploaded_file.name] = {"dados": dados, "imagem": BytesIO(uploaded_file.getvalue())}

        if st.session_state.dados_fichas:
            st.markdown("---")
            st.header("2. Revise, corrija e salve os dados")
            for file_name, file_info in st.session_state.dados_fichas.items():
                if file_info.get("status") != "salvo":
                    with st.expander(f"**Revisar Ficha: {file_name}**", expanded=True):
                        with st.form(key=f"form_{file_name}"):
                            dados_atuais = file_info['dados']
                            col1, col2 = st.columns(2)
                            with col1:
                                dados_atuais['nome_completo'] = st.text_input("Nome Completo", value=dados_atuais.get('Nome Completo'), key=f"nome_{file_name}")
                                dados_atuais['data_nascimento'] = st.text_input("Data de Nascimento", value=dados_atuais.get('Data de Nascimento'), key=f"nasc_{file_name}")
                                dados_atuais['cpf'] = st.text_input("CPF", value=dados_atuais.get('CPF'), key=f"cpf_{file_name}")
                            with col2:
                                dados_atuais['telefone'] = st.text_input("Telefone", value=dados_atuais.get('Telefone'), key=f"tel_{file_name}")

                            submitted = st.form_submit_button("✅ Confirmar e Salvar")
                            if submitted:
                                idade = calcular_idade(dados_atuais.get('data_nascimento'))
                                dados_para_banco = {
                                    'id_familia': dados_atuais.get('ID Família'),
                                    'nome_completo': dados_atuais.get('nome_completo'),
                                    'data_nascimento': dados_atuais.get('data_nascimento') or None,
                                    'idade': idade,
                                    'sexo': dados_atuais.get('Sexo'),
                                    'nome_mae': dados_atuais.get('Nome da Mãe'),
                                    'nome_pai': dados_atuais.get('Nome do Pai'),
                                    'municipio_nascimento': dados_atuais.get('Município de Nascimento'),
                                    'cpf': dados_atuais.get('cpf'),
                                    'cns': dados_atuais.get('CNS'),
                                    'telefone': dados_atuais.get('telefone'),
                                    'data_de_envio': datetime.now().isoformat()
                                }
                                sucesso = salvar_dados_e_imagem(db_client, dados_para_banco, file_info['imagem'], file_name)
                                if sucesso:
                                    st.success(f"Dados de '{file_name}' salvos com sucesso!")
                                    file_info['status'] = 'salvo'
                                    st.rerun()

elif page == "Dashboard de Dados":
    st.header("📊 Dashboard de Fichas Coletadas")
    df = ler_dados_do_banco(db_client)
    if not df.empty:
        st.info(f"Total de Fichas no Banco de Dados: **{len(df)}**")
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Nenhuma ficha encontrada no banco de dados para exibir.")
