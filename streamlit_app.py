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
        return json.loads(json_string)
    except Exception as e:
        st.error(f"Erro ao extrair dados com Gemini. Verifique a sua chave da API. Erro: {e}")
        return None

def validar_dados_com_gemini(dados_para_validar):
    """Envia os dados extraídos para o Gemini para uma verificação de qualidade."""
    try:
        model = genai.GenerativeModel('gemini-pro')
        prompt_validacao = f"""
        Você é um auditor de qualidade de dados de saúde do Brasil. Analise o seguinte JSON de uma ficha de paciente e verifique se há inconsistências óbvias.
        Especificamente, verifique:
        1. Se o CPF tem um formato que parece válido (11 dígitos, com ou sem pontuação).
        2. Se a Data de Nascimento é uma data que existe (ex: não é 30/02/2023) e está no passado.
        3. Se o CNS (Cartão Nacional de Saúde) tem 15 dígitos.
        Responda APENAS com um objeto JSON. O JSON deve ter uma chave "status_geral" ('Válido' ou 'Inválido com avisos') e uma chave "avisos" que é uma lista de strings em português com os problemas encontrados. Se não houver problemas, a lista de avisos deve ser vazia.
        Dados para validar: {json.dumps(dados_para_validar)}
        """
        response = model.generate_content(prompt_validacao)
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except Exception as e:
        print(f"Erro na validação com Gemini: {e}")
        return {"status_geral": "Válido", "avisos": []}

# --- INICIALIZAÇÃO E INTERFACE DO APP ---
planilha_conectada = conectar_planilha()

st.header("Envie a imagem da ficha")
uploaded_file = st.file_uploader("Escolha uma imagem", type=['jpg', 'jpeg', 'png'])

if 'dados_extraidos' not in st.session_state:
    st.session_state.dados_extraidos = None

if uploaded_file is not None:
    st.image(uploaded_file, caption="Imagem Carregada.", use_column_width=True)
    
    if st.button("🔎 Extrair e Validar Dados"):
        with st.spinner("A IA está a analisar a imagem..."):
            st.session_state.dados_extraidos = extrair_dados_com_gemini(uploaded_file)
        
        if st.session_state.dados_extraidos:
            st.success("Dados extraídos!")
            with st.spinner("A IA está a verificar a qualidade dos dados..."):
                resultado_validacao = validar_dados_com_gemini(st.session_state.dados_extraidos)
            
            if resultado_validacao and resultado_validacao.get("avisos"):
                st.warning("Atenção! A IA encontrou os seguintes possíveis problemas:")
                for aviso in resultado_validacao["avisos"]:
                    st.write(f"- {aviso}")
        else:
            st.error("Não foi possível extrair dados da imagem.")

if st.session_state.dados_extraidos:
    st.markdown("---")
    st.header("Confirme e corrija os dados antes de enviar")
    
    # Usamos um formulário para agrupar os campos e o botão de envio
    with st.form("formulario_de_correcao"):
        dados = st.session_state.dados_extraidos
        
        # Criamos campos de texto editáveis, pré-preenchidos com os dados extraídos
        id_familia = st.text_input("ID Família", value=dados.get("ID Família", ""))
        nome_completo = st.text_input("Nome Completo", value=dados.get("Nome Completo", ""))
        data_nascimento = st.text_input("Data de Nascimento", value=dados.get("Data de Nascimento", ""))
        telefone = st.text_input("Telefone", value=dados.get("Telefone", ""))
        cpf = st.text_input("CPF", value=dados.get("CPF", ""))
        nome_mae = st.text_input("Nome da Mãe", value=dados.get("Nome da Mãe", ""))
        nome_pai = st.text_input("Nome do Pai", value=dados.get("Nome do Pai", ""))
        sexo = st.text_input("Sexo", value=dados.get("Sexo", ""))
        cns = st.text_input("CNS", value=dados.get("CNS", ""))
        municipio_nascimento = st.text_input("Município de Nascimento", value=dados.get("Município de Nascimento", ""))

        # O botão de envio fica dentro do formulário
        submitted = st.form_submit_button("✅ Enviar para a Planilha")
        
        if submitted:
            with st.spinner("A enviar os dados..."):
                try:
                    # Prepara a linha com os dados ATUALIZADOS do formulário
                    nova_linha = [
                        id_familia, nome_completo, data_nascimento, telefone, cpf,
                        nome_mae, nome_pai, sexo, cns, municipio_nascimento,
                        datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                    ]
                    
                    planilha_conectada.append_row(nova_linha)
                    st.success("🎉 Dados enviados para a planilha com sucesso!")
                    st.balloons()
                    # Limpa o estado para permitir um novo envio
                    st.session_state.dados_extraidos = None
                except Exception as e:
                    st.error(f"Ocorreu um erro ao enviar os dados para a planilha. Erro: {e}")
