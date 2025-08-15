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
    page_title="Aplicativo de Coleta Rápida",
    page_icon="📄",
    layout="wide"
)

st.title("📄 Aplicativo de Coleta Rápida")
st.markdown("---")

# --- CONEXÃO E VARIÁVEIS DE AMBIENTE ---
try:
    # Carrega os segredos do Streamlit Cloud
    gemini_api_key = st.secrets["GEMINIKEY"]
    google_sheets_id = st.secrets["SHEETSID"]
    
    # Carrega as credenciais da seção [gcp_service_account] que definimos nos segredos
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

def extrair_dados_com_gemini(image_bytes):
    """Extrai dados da imagem usando a API do Google Gemini."""
    try:
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel('gemini-pro-vision')

        image_bytes.seek(0)
        image = Image.open(image_bytes)

        prompt = """
        Analise esta imagem de um formulário e extraia as seguintes informações:
        - ID Família, Nome Completo, Data de Nascimento (DD/MM/AAAA), Telefone, CPF, Nome da Mãe, Nome do Pai, Sexo, CNS, Município de Nascimento.
        Se um dado não for encontrado, retorne um campo vazio.
        Retorne os dados estritamente como um objeto JSON.
        Exemplo: {"ID Família": "FAM001", "Nome Completo": "NOME COMPLETO", ...}
        """
        
        response = model.generate_content([prompt, image])
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        dados = json.loads(json_string)
        return dados
    except Exception as e:
        st.error(f"Erro ao extrair dados com Gemini. Verifique a sua chave da API. Erro: {e}")
        return None
        
# --- INICIALIZAÇÃO E INTERFACE DO APP ---
planilha_conectada = conectar_planilha()

st.header("Envie a imagem da ficha")
uploaded_file = st.file_uploader("Escolha uma imagem", type=['jpg', 'jpeg', 'png'])

if uploaded_file is not None:
    st.image(uploaded_file, caption="Imagem Carregada.", use_column_width=True)
    
    if st.button("🔎 Processar e Enviar Dados"):
        with st.spinner("A IA está a analisar a imagem..."):
            dados_extraidos = extrair_dados_com_gemini(uploaded_file)

            if dados_extraidos:
                st.success("Dados extraídos com sucesso!")
                st.json(dados_extraidos)

                try:
                    # Prepara a linha para ser inserida na planilha
                    # A ordem deve ser a mesma das colunas na sua planilha
                    nova_linha = [
                        dados_extraidos.get("ID Família", ""),
                        dados_extraidos.get("Nome Completo", ""),
                        dados_extraidos.get("Data de Nascimento", ""),
                        dados_extraidos.get("Telefone", ""),
                        dados_extraidos.get("CPF", ""),
                        dados_extraidos.get("Nome da Mãe", ""),
                        dados_extraidos.get("Nome do Pai", ""),
                        dados_extraidos.get("Sexo", ""),
                        dados_extraidos.get("CNS", ""),
                        dados_extraidos.get("Município de Nascimento", ""),
                        datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                    ]
                    
                    planilha_conectada.append_row(nova_linha)
                    st.success("🎉 Dados enviados para a planilha com sucesso!")
                    st.balloons()
                except Exception as e:
                    st.error(f"Ocorreu um erro ao enviar os dados para a planilha. Verifique as colunas da sua planilha. Erro: {e}")

            else:
                st.error("Não foi possível extrair dados da imagem.")

