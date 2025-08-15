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

@st.cache_data(ttl=60) # Cache de 1 minuto para os dados do dashboard
def ler_dados_da_planilha(_planilha):
    """Lê todos os dados da planilha e retorna como DataFrame do Pandas."""
    try:
        dados = _planilha.get_all_records()
        return pd.DataFrame(dados)
    except Exception as e:
        st.error(f"Não foi possível ler os dados da planilha para o dashboard. Erro: {e}")
        return pd.DataFrame()


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
        Responda APENAS com um objeto JSON com uma chave "avisos" que é uma lista de strings em português com os problemas encontrados. Se não houver problemas, a lista de avisos deve ser vazia.
        Dados para validar: {json.dumps(dados_para_validar)}
        """
        response = model.generate_content(prompt_validacao)
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except Exception as e:
        print(f"Erro na validação com Gemini: {e}")
        return {"avisos": []}

# --- INICIALIZAÇÃO ---
planilha_conectada = conectar_planilha()

# --- NAVEGAÇÃO E PÁGINAS ---
st.sidebar.title("Navegação")
pagina_selecionada = st.sidebar.radio(
    "Escolha uma página:",
    ["Coletar Fichas", "Dashboard"]
)

# --- PÁGINA 1: COLETAR FICHAS ---
if pagina_selecionada == "Coletar Fichas":
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
        
        with st.form("formulario_de_correcao"):
            dados = st.session_state.dados_extraidos
            
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

            submitted = st.form_submit_button("✅ Enviar para a Planilha")
            
            if submitted:
                with st.spinner("A enviar os dados..."):
                    try:
                        nova_linha = [
                            id_familia, nome_completo, data_nascimento, telefone, cpf,
                            nome_mae, nome_pai, sexo, cns, municipio_nascimento,
                            datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                        ]
                        planilha_conectada.append_row(nova_linha)
                        st.success("🎉 Dados enviados para a planilha com sucesso!")
                        st.balloons()
                        st.session_state.dados_extraidos = None
                        st.experimental_rerun() # Limpa o formulário e a página
                    except Exception as e:
                        st.error(f"Ocorreu um erro ao enviar os dados para a planilha. Erro: {e}")

# --- PÁGINA 2: DASHBOARD ---
elif pagina_selecionada == "Dashboard":
    st.header("📊 Dashboard de Dados Coletados")
    
    df = ler_dados_da_planilha(planilha_conectada)
    
    if not df.empty:
        st.info(f"Total de Fichas na Planilha: **{len(df)}**")
        
        # Barra de pesquisa para filtrar o DataFrame
        termo_pesquisa = st.text_input("Pesquisar por Nome Completo:")
        
        if termo_pesquisa:
            # Filtra o dataframe. A opção `case=False` ignora maiúsculas/minúsculas
            df_filtrado = df[df['Nome Completo'].str.contains(termo_pesquisa, case=False, na=False)]
            st.dataframe(df_filtrado, use_container_width=True)
        else:
            # Mostra o dataframe completo se a pesquisa estiver vazia
            st.dataframe(df, use_container_width=True)

    else:
        st.warning("Ainda não há dados na planilha para exibir.")
