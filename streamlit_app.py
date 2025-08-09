import streamlit as st
import gspread
import json
import os
import cv2
import numpy as np
import pandas as pd
import google.generativeai as genai
from io import BytesIO
from datetime import datetime
from json import JSONDecodeError
from gspread.exceptions import APIError
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.service_account import Credentials

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
    # Carrega as credenciais a partir das variáveis de ambiente
    credenciais_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_CREDENTIALS")
    planilha_id = os.environ.get("GOOGLE_SHEETS_ID")
    gemini_api_key = os.environ.get("GOOGLE_GEMINI_API_KEY")
    drive_folder_id = os.environ.get("GOOGLE_DRIVE_FOLDER_ID")

    # Verifica se todas as variáveis essenciais foram carregadas
    if not all([credenciais_str, planilha_id, gemini_api_key, drive_folder_id]):
        st.error("Erro de configuração: Uma ou mais variáveis de ambiente estão faltando. Verifique GOOGLE_SERVICE_ACCOUNT_CREDENTIALS, GOOGLE_SHEETS_ID, GOOGLE_GEMINI_API_KEY, e GOOGLE_DRIVE_FOLDER_ID.")
        st.stop()

    # Converte a string de credenciais em um dicionário
    credenciais_dict = json.loads(credenciais_str)
    
    # Define os escopos necessários (Sheets e Drive)
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_with_scope = Credentials.from_service_account_info(credenciais_dict, scopes=scopes)

except (JSONDecodeError, TypeError) as e:
    st.error(f"Erro ao carregar as credenciais JSON. Verifique o formato da variável de ambiente. Erro: {e}")
    st.stop()
except Exception as e:
    st.error(f"Erro inesperado ao carregar as configurações. Erro: {e}")
    st.stop()


# --- FUNÇÕES ---

@st.cache_resource
def conectar_cliente_google():
    """Tenta conectar com as APIs do Google e retorna o cliente autorizado."""
    try:
        # Autoriza e cria um cliente gspread
        gc = gspread.authorize(creds_with_scope)
        return gc
    except Exception as e:
        st.error(f"Não foi possível conectar às APIs do Google. Verifique suas credenciais e permissões. Erro: {e}")
        st.stop()

@st.cache_resource
def abrir_planilha(_gc):
    """Abre uma planilha específica do Google Sheets."""
    try:
        return _gc.open_by_key(planilha_id).sheet1
    except APIError:
        st.error("Erro de permissão! Verifique se a planilha e a pasta do Drive foram compartilhadas com o e-mail da conta de serviço.")
        st.stop()
    except Exception as e:
        st.error(f"Não foi possível abrir a planilha. Verifique a ID ({planilha_id}). Erro: {e}")
        st.stop()

@st.cache_data(ttl=120) # Aumenta o tempo de cache para 2 minutos
def ler_dados_da_planilha(planilha_obj):
    """Lê todos os dados da planilha para o dashboard."""
    try:
        dados = planilha_obj.get_all_records()
        df = pd.DataFrame(dados)
        return df
    except Exception as e:
        st.error(f"Erro ao ler dados da planilha. Erro: {e}")
        return pd.DataFrame()

def salvar_imagem_no_drive(gc, nome_arquivo, image_bytes, pasta_id):
    """Faz o upload de uma imagem para uma pasta específica no Google Drive."""
    try:
        drive_service = gc.drive_service
        image_bytes.seek(0)
        media = MediaIoBaseUpload(image_bytes, mimetype='image/jpeg', resumable=True)
        file_metadata = {'name': nome_arquivo, 'parents': [pasta_id]}
        
        file = drive_service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id,webViewLink'
        ).execute()
        
        return file.get('webViewLink')
    except Exception as e:
        st.error(f"Falha ao fazer upload da imagem para o Google Drive. Verifique as permissões da pasta. Erro: {e}")
        return None

def extrair_dados_com_gemini(image_bytes):
    """Extrai dados da imagem usando a API do Google Gemini, com validação de JSON."""
    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel('gemini-pro-vision') # Modelo específico para visão

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
        # Limpa a resposta para garantir que seja um JSON válido
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        dados = json.loads(json_string)
        return dados
    except JSONDecodeError:
        st.error("A IA retornou um formato de dados inválido (não é JSON). Tente uma imagem mais nítida.")
        return None
    except Exception as e:
        st.error(f"Erro ao extrair dados com Gemini. Verifique a chave da API e a imagem. Erro: {e}")
        return None

def validar_e_formatar_dados(dados):
    """Valida e formata os dados extraídos antes de exibi-los."""
    # Valida Data de Nascimento
    try:
        datetime.strptime(dados.get('Data de Nascimento', ''), '%d/%m/%Y')
    except ValueError:
        dados['Data de Nascimento'] = '' # Limpa se for inválida

    # Valida CPF (verificação simples de comprimento)
    cpf = dados.get('CPF', '').strip()
    if not (11 <= len(cpf) <= 14): # Permite com ou sem pontuação
        dados['CPF'] = ''
        
    return dados

def calcular_idade(data_nascimento):
    """Calcula a idade a partir da data de nascimento."""
    if not data_nascimento: return None
    try:
        data_nasc = datetime.strptime(data_nascimento, '%d/%m/%Y')
        hoje = datetime.now()
        return hoje.year - data_nasc.year - ((hoje.month, hoje.day) < (data_nasc.month, data_nasc.day))
    except (ValueError, TypeError):
        return None

# --- INICIALIZAÇÃO DO APP ---
cliente_google = conectar_cliente_google()
planilha_conectada = abrir_planilha(cliente_google)

# --- NAVEGAÇÃO E PÁGINAS ---
st.sidebar.title("Navegação")
page = st.sidebar.radio("Escolha uma página:", ["Coletar Fichas", "Dashboard de Dados"])

# Limpa o estado da sessão se o usuário navegar
if 'last_page' not in st.session_state or st.session_state.last_page != page:
    st.session_state.clear()
    st.session_state.last_page = page

if page == "Coletar Fichas":
    st.header("1. Envie a(s) imagem(ns) da(s) ficha(s)")
    uploaded_files = st.file_uploader("Escolha uma ou mais imagens", type=['jpg', 'jpeg', 'png'], accept_multiple_files=True)

    if 'dados_fichas' not in st.session_state:
        st.session_state.dados_fichas = {}

    if uploaded_files:
        if st.button("🔎 Extrair Dados das Imagens"):
            st.session_state.dados_fichas = {} # Limpa dados anteriores
            with st.spinner("Analisando imagens... Por favor, aguarde."):
                for i, uploaded_file in enumerate(uploaded_files):
                    with st.status(f"Processando arquivo {i+1}/{len(uploaded_files)}: {uploaded_file.name}", expanded=True):
                        st.image(uploaded_file, width=300)
                        image_bytes = BytesIO(uploaded_file.getvalue())
                        dados = extrair_dados_com_gemini(image_bytes)
                        
                        if dados:
                            dados_validados = validar_e_formatar_dados(dados)
                            # Armazena os dados e a imagem na sessão
                            st.session_state.dados_fichas[uploaded_file.name] = {
                                "dados": dados_validados,
                                "imagem": image_bytes
                            }
                            st.success("Dados extraídos com sucesso!")
                        else:
                            st.error("Falha ao extrair dados.")
        
        if st.session_state.dados_fichas:
            st.markdown("---")
            st.header("2. Revise, corrija e salve os dados")
            st.info("Verifique os dados extraídos abaixo. Você pode corrigir qualquer campo antes de salvar na planilha.")

            for file_name, file_info in st.session_state.dados_fichas.items():
                if file_info.get("status") != "salvo":
                    with st.expander(f"**Revisar Ficha: {file_name}**", expanded=True):
                        
                        with st.form(key=f"form_{file_name}"):
                            dados_atuais = file_info['dados']
                            
                            # Layout em colunas para melhor visualização
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                dados_atuais['Nome Completo'] = st.text_input("Nome Completo", value=dados_atuais.get('Nome Completo'), key=f"nome_{file_name}")
                                dados_atuais['Data de Nascimento'] = st.text_input("Data de Nascimento (DD/MM/AAAA)", value=dados_atuais.get('Data de Nascimento'), key=f"nasc_{file_name}")
                                dados_atuais['CPF'] = st.text_input("CPF", value=dados_atuais.get('CPF'), key=f"cpf_{file_name}")
                                dados_atuais['CNS'] = st.text_input("CNS", value=dados_atuais.get('CNS'), key=f"cns_{file_name}")
                                dados_atuais['Sexo'] = st.selectbox("Sexo", ["MASCULINO", "FEMININO", "OUTRO"], index=0 if dados_atuais.get('Sexo','').upper() == 'MASCULINO' else 1, key=f"sexo_{file_name}")

                            with col2:
                                dados_atuais['Nome da Mãe'] = st.text_input("Nome da Mãe", value=dados_atuais.get('Nome da Mãe'), key=f"mae_{file_name}")
                                dados_atuais['Nome do Pai'] = st.text_input("Nome do Pai", value=dados_atuais.get('Nome do Pai'), key=f"pai_{file_name}")
                                dados_atuais['Telefone'] = st.text_input("Telefone", value=dados_atuais.get('Telefone'), key=f"tel_{file_name}")
                                dados_atuais['Município de Nascimento'] = st.text_input("Município de Nascimento", value=dados_atuais.get('Município de Nascimento'), key=f"mun_{file_name}")
                                dados_atuais['ID Família'] = st.text_input("ID Família", value=dados_atuais.get('ID Família'), key=f"fam_{file_name}")

                            submitted = st.form_submit_button("✅ Confirmar e Salvar na Planilha")

                            if submitted:
                                with st.spinner(f"Salvando dados e imagem de {file_name}..."):
                                    # 1. Salvar imagem no Google Drive
                                    link_imagem = salvar_imagem_no_drive(cliente_google, file_name, file_info['imagem'], drive_folder_id)
                                    
                                    if link_imagem:
                                        # 2. Preparar dados para a planilha
                                        idade = calcular_idade(dados_atuais.get('Data de Nascimento'))
                                        nova_linha = [
                                            dados_atuais.get('ID Família', ''),
                                            dados_atuais.get('Nome Completo', ''),
                                            dados_atuais.get('Data de Nascimento', ''),
                                            str(idade) if idade is not None else '',
                                            dados_atuais.get('Sexo', ''),
                                            dados_atuais.get('Nome da Mãe', ''),
                                            dados_atuais.get('Nome do Pai', ''),
                                            dados_atuais.get('Município de Nascimento', ''),
                                            dados_atuais.get('CPF', ''),
                                            dados_atuais.get('CNS', ''),
                                            dados_atuais.get('Telefone', ''),
                                            datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
                                            link_imagem # Nova coluna com o link
                                        ]
                                        
                                        # 3. Salvar na planilha
                                        planilha_conectada.append_row(nova_linha, value_input_option='USER_ENTERED')
                                        st.success(f"Dados de '{file_name}' salvos com sucesso na planilha e imagem no Drive!")
                                        file_info['status'] = 'salvo' # Marca como salvo
                                        st.rerun() # Recarrega para limpar o formulário
                                    else:
                                        st.error("Não foi possível salvar na planilha pois o upload da imagem falhou.")

elif page == "Dashboard de Dados":
    st.header("📊 Dashboard de Fichas Coletadas")
    
    df_original = ler_dados_da_planilha(planilha_conectada)

    if not df_original.empty:
        # Garante que as colunas de data e idade são numéricas para filtros e gráficos
        df_original['Data de Envio'] = pd.to_datetime(df_original['Data de Envio'], format='%d/%m/%Y %H:%M:%S', errors='coerce')
        df_original['Idade'] = pd.to_numeric(df_original['Idade'], errors='coerce')

        # --- FILTROS NA SIDEBAR ---
        st.sidebar.header("Filtros do Dashboard")
        
        # Filtro por Município
        municipios_disponiveis = df_original['Município de Nascimento'].dropna().unique()
        municipios_selecionados = st.sidebar.multiselect("Filtrar por Município", options=municipios_disponiveis, default=municipios_disponiveis)

        # Filtro por Data
        min_date = df_original['Data de Envio'].min().date()
        max_date = df_original['Data de Envio'].max().date()
        data_selecionada = st.sidebar.date_input(
            "Filtrar por Data de Envio",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date
        )

        # Aplica os filtros
        df_filtrado = df_original[
            (df_original['Município de Nascimento'].isin(municipios_selecionados)) &
            (df_original['Data de Envio'].dt.date >= data_selecionada[0]) &
            (df_original['Data de Envio'].dt.date <= data_selecionada[1])
        ]
        
        st.write(f"Exibindo **{len(df_filtrado)}** de **{len(df_original)}** registros totais.")
        st.dataframe(df_filtrado, use_container_width=True, hide_index=True)

        # --- GRÁFICOS ---
        col1, col2 = st.columns(2)

        with col1:
            if 'Município de Nascimento' in df_filtrado.columns:
                st.subheader("Distribuição por Município")
                municipio_counts = df_filtrado['Município de Nascimento'].value_counts()
                st.bar_chart(municipio_counts)

        with col2:
            if 'Idade' in df_filtrado.columns:
                st.subheader("Distribuição de Idades")
                # Cria faixas etárias para melhor visualização
                bins = [0, 10, 20, 30, 40, 50, 60, 70, 80, 120]
                labels = ['0-10', '11-20', '21-30', '31-40', '41-50', '51-60', '61-70', '71-80', '80+']
                df_filtrado['Faixa Etária'] = pd.cut(df_filtrado['Idade'], bins=bins, labels=labels, right=False)
                idade_counts = df_filtrado['Faixa Etária'].value_counts().sort_index()
                st.bar_chart(idade_counts)

    else:
        st.info("Nenhuma ficha encontrada na planilha para exibir.")

