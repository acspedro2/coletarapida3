import streamlit as st
import gspread
import json
import os
import pandas as pd
import google.generativeai as genai
from io import BytesIO
from datetime import datetime
from PIL import Image

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

@st.cache_data(ttl=60)
def ler_dados_da_planilha(_planilha):
    """Lê todos os dados da planilha e retorna como DataFrame do Pandas."""
    try:
        dados = _planilha.get_all_records()
        return pd.DataFrame(dados)
    except Exception as e:
        st.error(f"Não foi possível ler os dados da planilha para o dashboard. Erro: {e}")
        return pd.DataFrame()

def extrair_dados_com_gemini(image_bytes):
    # (Esta função permanece a mesma da versão anterior)
    try:
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel('gemini-pro-vision')
        image_bytes.seek(0)
        image = Image.open(image_bytes)
        prompt = """
        Analise esta imagem de um formulário e extraia as seguintes informações:
        - ID Família, Nome Completo, Data de Nascimento (DD/MM/AAAA), Telefone, CPF, Nome da Mãe, Nome do Pai, Sexo, CNS, Município de Nascimento.
        Se um dado não for encontrado, retorne um campo vazio. Retorne os dados estritamente como um objeto JSON.
        Exemplo: {"ID Família": "FAM001", "Nome Completo": "NOME COMPLETO", ...}
        """
        response = model.generate_content([prompt, image])
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except Exception as e:
        st.error(f"Erro ao extrair dados com Gemini. Verifique a sua chave da API. Erro: {e}")
        return None

def validar_dados_com_gemini(dados_para_validar):
    # (Esta função permanece a mesma da versão anterior)
    try:
        model = genai.GenerativeModel('gemini-pro')
        prompt_validacao = f"""
        Você é um auditor de qualidade de dados de saúde do Brasil. Analise o seguinte JSON e verifique se há inconsistências óbvias (CPF, Data de Nascimento, CNS).
        Responda APENAS com um objeto JSON com uma chave "avisos" que é uma lista de strings em português com os problemas encontrados. Se não houver problemas, a lista deve ser vazia.
        Dados para validar: {json.dumps(dados_para_validar)}
        """
        response = model.generate_content(prompt_validacao)
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except Exception as e:
        print(f"Erro na validação com Gemini: {e}")
        return {"avisos": []}

# --- NOVA FUNÇÃO DE ANÁLISE ---
def analisar_dados_com_gemini(pergunta_usuario, dataframe):
    """Usa o Gemini para responder perguntas sobre os dados da planilha."""
    if dataframe.empty:
        return "Não há dados na planilha para analisar."
    
    # Converte o dataframe para uma string para enviar no prompt
    dados_string = dataframe.to_string()
    
    model = genai.GenerativeModel('gemini-pro')
    
    prompt_analise = f"""
    Você é um assistente de análise de dados. Sua tarefa é responder à pergunta do utilizador com base nos dados da tabela fornecida.
    Seja claro, direto e responda apenas com base nos dados.

    Pergunta do utilizador: "{pergunta_usuario}"

    Dados da Tabela:
    {dados_string}
    """
    
    try:
        response = model.generate_content(prompt_analise)
        return response.text
    except Exception as e:
        return f"Ocorreu um erro ao analisar os dados com a IA. Erro: {e}"


# --- INICIALIZAÇÃO ---
planilha_conectada = conectar_planilha()

# --- NAVEGAÇÃO E PÁGINAS ---
