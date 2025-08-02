import streamlit as st
from datetime import datetime
import os
import uuid
import time
import pandas as pd

# Importa as bibliotecas do Google Cloud Storage
from google.cloud import storage

# Importa as bibliotecas do Google Sheets API
from google.oauth2 import service_account
from googleapiclient.discovery import build
import json # Para carregar as credenciais JSON

# --- Configuração do Streamlit ---
st.set_page_config(page_title="Coleta Rápida", layout="centered", initial_sidebar_state="collapsed")

# --- Inicialização do session_state para resetar o formulário ---
if 'file_uploader_key' not in st.session_state:
    st.session_state.file_uploader_key = 0
if 'form_submitted' not in st.session_state:
    st.session_state.form_submitted = False

# --- Configuração das credenciais e clientes do GCP e Google Sheets ---
# IMPORTANTE: Em produção, NUNCA coloque as credenciais diretamente aqui.
# Use variáveis de ambiente ou o segredo do Streamlit Cloud.

# Caminho para o seu arquivo de chave JSON da conta de serviço
# Se estiver no Streamlit Cloud, você acessaria via st.secrets
# Exemplo para teste local:
SERVICE_ACCOUNT_FILE = "/caminho/para/seu/arquivo-chave-google-sheets.json" # <-- ATENÇÃO: Substitua pelo caminho real!

# ID da Planilha Google (você encontra na URL da planilha)
# Ex: https://docs.google.com/spreadsheets/d/SEU_ID_DA_PLANILHA_AQUI/edit
SPREADSHEET_ID = "SEU_ID_DA_PLANILHA_GOOGLE_AQUI" # <-- ATENÇÃO: Substitua pelo ID real da sua planilha!
SHEET_NAME = "Página1" # Ou o nome da página onde você quer gravar, geralmente "Página1"

# Credenciais para Google Sheets API
try:
    if os.path.exists(SERVICE_ACCOUNT_FILE):
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=['https://www.googleapis.com/auth/spreadsheets'] # Escopo para manipular planilhas
        )
        sheets_service = build('sheets', 'v4', credentials=creds)
    else:
        st.error(f"Erro: Arquivo de credenciais não encontrado em {SERVICE_ACCOUNT_FILE}. Configure a variável GOOGLE_APPLICATION_CREDENTIALS ou o caminho do arquivo.")
        st.stop()
except Exception as e:
    st.error(f"Erro ao inicializar serviço do Google Sheets. Verifique suas credenciais: {e}")
    st.stop()

# Cliente do Google Cloud Storage (GCS)
try:
    # O GCS geralmente usa a mesma GOOGLE_APPLICATION_CREDENTIALS
    storage_client = storage.Client()
except Exception as e:
    st.error(f"Erro ao inicializar cliente do Google Cloud Storage. Verifique suas credenciais: {e}")
    st.stop()

GCS_BUCKET_NAME = "seu-nome-de-bucket-aqui" # <-- Substitua pelo nome do seu bucket GCS!

# --- Interface do Usuário (Seção de Coleta de Fichas) ---
st.header("📋 Coleta Rápida de Fichas")
st.subheader("Envie imagens de fichas preenchidas de forma ágil.")

st.write("---")

nome_ficha = st.text_input(
    "Nome ou ID da Ficha:",
    placeholder="Ex: Ficha Cliente 001, Pedido 12345"
)

tipos_ficha = ["Selecione um tipo", "Ficha de Cliente", "Ficha de Produto", "Ficha de Serviço", "Outro"]
tipo_ficha_selecionado = st.selectbox("Tipo de Ficha:", tipos_ficha)

data_ficha = st.date_input("Data da Ficha:", datetime.now().date())

st.write("---")

st.markdown("### 🖼️ Anexar Imagem da Ficha")
st.write("Envie a imagem da ficha preenchida (foto ou escaneado):")

uploaded_file = st.file_uploader(
    "Selecione o arquivo",
    type=["jpg", "jpeg", "png", "pdf"],
    key=f"file_uploader_{st.session_state.file_uploader_key}"
)

observacoes = st.text_area("Observações adicionais (opcional):", placeholder="Qualquer informação extra sobre a ficha...")

# Variável para armazenar o URL público do arquivo após o upload
file_public_url = None

if uploaded_file:
    st.success("✅ Arquivo carregado com sucesso!")
    st.image(uploaded_file, width=300, caption=f"Pré-visualização de: {uploaded_file.name}")

st.write("---")

col1, col2 = st.columns(2)

with col1:
    if st.button("Enviar Ficha", type="primary"):
        # --- Validações ---
        if not nome_ficha:
            st.warning("⚠️ Por favor, preencha o **Nome ou ID da Ficha**.")
        elif tipo_ficha_selecionado == "Selecione um tipo":
            st.warning("⚠️ Por favor, selecione um **Tipo de Ficha**.")
        elif not uploaded_file:
            st.warning("⚠️ Por favor, envie uma **imagem** da ficha antes de confirmar.")
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()

            with st.spinner("🚀 Enviando dados e processando..."):
                try:
                    # --- 1. Upload do Arquivo para o Google Cloud Storage ---
                    status_text.text("Enviando arquivo para o Cloud Storage...")
                    percent_complete = 20
                    progress_bar.progress(percent_complete)
                    time.sleep(0.5)

                    file_extension = os.path.splitext(uploaded_file.name)[1]
                    gcs_path = f"fichas/{datetime.now().strftime('%Y/%m/%d')}/{uuid.uuid4().hex}{file_extension}"

                    bucket = storage_client.bucket(GCS_BUCKET_NAME)
                    blob = bucket.blob(gcs_path)
                    # Não precisamos salvar localmente, upload_from_file aceita o objeto FileUploader
                    blob.upload_from_file(uploaded_file, content_type=uploaded_file.type)
                    blob.make_public() # Tornar público para visualização
                    file_public_url = blob.public_url

                    st.success(f"✅ Arquivo '{uploaded_file.name}' enviado para o Cloud Storage!")

                    # --- 2. Salvando Metadados na Planilha Google Sheets ---
                    status_text.text("Salvando metadados na Planilha Google Sheets...")
                    percent_complete = 70
                    progress_bar.progress(percent_complete)
                    time.sleep(0.5)

                    # Prepare os dados para a nova linha
                    row_data = [
                        nome_ficha,
                        tipo_ficha_selecionado,
                        data_ficha.isoformat(), # Formato 'YYYY-MM-DD'
                        uploaded_file.name,
                        file_public_url,
                        observacoes,
                        datetime.now().isoformat() # Timestamp de envio (Python local)
                    ]

                    # Range onde os dados serão adicionados (após a última linha)
                    # "SHEET_NAME!A:G" significa todas as colunas de A a G na página SHEET_NAME
                    range_name = f"{SHEET_NAME}!A:G"
                    
                    # Corpo da requisição
                    body = {
                        'values': [row_data]
                    }

                    # Executa a requisição para adicionar a linha
                    sheets_service.spreadsheets().values().append(
                        spreadsheetId=SPREADSHEET_ID,
                        range=range_name,
                        valueInputOption='USER_ENTERED', # Para que o Google Sheets interprete os valores (ex: datas)
                        body=body
                    ).execute()

                    st.success("🎉 Ficha e dados enviados com sucesso para a Planilha Google Sheets!")
                    st.balloons()
                    st.session_state.form_submitted = True

                except Exception as e:
                    st.error(f"❌ Erro ao enviar os dados ou arquivo: {e}")
                    st.exception(e) # Exibe o erro completo para debug
                finally:
                    progress_bar.empty()
                    status_text.empty()

with col2:
    if st.button("Limpar Formulário"):
        st.session_state.file_uploader_key += 1
        st.session_state.form_submitted = False
        st.rerun()

if st.session_state.form_submitted:
    st.info("Para enviar uma nova ficha, clique em 'Limpar Formulário' acima.")

st.write("---")
st.write("---")

# --- NOVA SEÇÃO: VISUALIZAÇÃO DOS DADOS COLETADOS (AGORA DA PLANILHA GOOGLE) ---
st.header("📊 Dados de Fichas Coletadas (Google Sheets)")
st.write("Visualize todas as fichas que foram enviadas para a Planilha Google Sheets:")

@st.cache_data(ttl=60)
def get_fichas_data_from_sheets():
    """Busca os dados de fichas na Planilha Google Sheets e retorna um DataFrame."""
    try:
        # Pega todos os valores da planilha
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=SHEET_NAME # Pega todos os dados da página
        ).execute()
        
        values = result.get('values', [])
        
        if not values:
            return pd.DataFrame() # Retorna DataFrame vazio se não houver dados
        
        # A primeira linha são os cabeçalhos
        headers = values[0]
        data_rows = values[1:] # O restante são os dados
        
        df = pd.DataFrame(data_rows, columns=headers)
        
        # Adicionar coluna de links clicáveis para o st.dataframe
        if 'URL Arquivo GCS' in df.columns:
            df['Link do Arquivo'] = df['URL Arquivo GCS'].apply(lambda x: f"[Ver Arquivo]({x})" if x else "N/A")
            # Ocultar a coluna URL Arquivo GCS original se você usar a nova coluna de link
            # df = df.drop(columns=['URL Arquivo GCS'])
            
        return df

    except Exception as e:
        st.error(f"Erro ao buscar dados da Planilha Google Sheets: {e}")
        st.exception(e) # Exibe o erro completo para debug
        return pd.DataFrame()

# Botão para recarregar os dados da planilha
if st.button("Atualizar Dados da Planilha"):
    st.cache_data.clear() # Limpa o cache para forçar uma nova leitura
    fichas_df = get_fichas_data_from_sheets()
else:
    fichas_df = get_fichas_data_from_sheets()

if not fichas_df.empty:
    st.write(f"Total de Fichas Encontradas: **{len(fichas_df)}**")
    
    # Exibir o DataFrame
    # Verifique quais colunas você quer mostrar
    cols_to_display = [
        'Nome Ficha',
        'Tipo Ficha',
        'Data Ficha',
        'Nome Arquivo Original',
        'Link do Arquivo', # Usar a coluna de link formatada
        'Observacoes',
        'Timestamp Envio'
    ]
    
    # Garante que apenas colunas existentes sejam exibidas
    display_df = fichas_df[[col for col in cols_to_display if col in fichas_df.columns]]
    
    st.dataframe(display_df)

    st.markdown("---")
    st.markdown("Clique nos links na coluna 'Link do Arquivo' para visualizar a imagem original.")
    st.markdown("_Nota: Para que os links sejam clicáveis no `st.dataframe`, o Streamlit renderiza a string Markdown. Se desejar uma renderização HTML mais robusta com ícones, seria necessário usar `st.markdown` com iterações ou bibliotecas de tabelas mais avançadas._")

else:
    st.info("Nenhuma ficha encontrada na Planilha Google Sheets ainda. Envie uma ficha para começar!")

st.write("---")
st.markdown("_Desenvolvido com Streamlit, Google Cloud Storage e Google Sheets API_")

