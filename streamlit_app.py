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

# --- Configuração do Streamlit ---
st.set_page_config(page_title="Coleta Rápida", layout="centered", initial_sidebar_state="collapsed")

# --- Inicialização do session_state para resetar o formulário ---
if 'file_uploader_key' not in st.session_state:
    st.session_state.file_uploader_key = 0
if 'form_submitted' not in st.session_state:
    st.session_state.form_submitted = False

# --- Configurações Específicas do Seu Aplicativo ---
# ATENÇÃO: Substitua estes valores pelos seus dados!
GCS_BUCKET_NAME = "seu-nome-de-bucket-aqui" # <-- Nome do seu bucket GCS!
SPREADSHEET_ID = "SEU_ID_DA_PLANILHA_GOOGLE_AQUI" # <-- ID da sua planilha do Google Sheets!
SHEET_NAME = "Página1" # <-- Nome da página (aba) na sua planilha

# --- Configuração das credenciais e clientes do GCP e Google Sheets ---
# As credenciais são lidas de forma segura através do Streamlit Secrets
try:
    gcp_credentials_dict = dict(st.secrets["gcp_service_account"])
    
    # Inicializa o cliente do Google Cloud Storage (GCS)
    storage_client = storage.Client(credentials=service_account.Credentials.from_service_account_info(
        gcp_credentials_dict
    ))

    # Inicializa o serviço do Google Sheets API
    creds = service_account.Credentials.from_service_account_info(
        gcp_credentials_dict,
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    sheets_service = build('sheets', 'v4', credentials=creds)

except Exception as e:
    st.error(f"Erro ao inicializar serviços do Google. Verifique seus segredos no Streamlit Cloud: {e}")
    st.stop()

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

file_public_url = None

if uploaded_file:
    st.success("✅ Arquivo carregado com sucesso!")
    st.image(uploaded_file, width=300, caption=f"Pré-visualização de: {uploaded_file.name}")

st.write("---")

col1, col2 = st.columns(2)

with col1:
    if st.button("Enviar Ficha", type="primary"):
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
                    blob.upload_from_file(uploaded_file, content_type=uploaded_file.type)
                    blob.make_public()
                    file_public_url = blob.public_url

                    st.success(f"✅ Arquivo '{uploaded_file.name}' enviado para o Cloud Storage!")

                    # --- 2. Salvando Metadados na Planilha Google Sheets ---
                    status_text.text("Salvando metadados na Planilha Google Sheets...")
                    percent_complete = 70
                    progress_bar.progress(percent_complete)
                    time.sleep(0.5)

                    row_data = [
                        nome_ficha,
                        tipo_ficha_selecionado,
                        data_ficha.isoformat(),
                        uploaded_file.name,
                        file_public_url,
                        observacoes,
                        datetime.now().isoformat()
                    ]

                    range_name = f"{SHEET_NAME}!A:G"
                    body = {'values': [row_data]}

                    sheets_service.spreadsheets().values().append(
                        spreadsheetId=SPREADSHEET_ID,
                        range=range_name,
                        valueInputOption='USER_ENTERED',
                        body=body
                    ).execute()

                    st.success("🎉 Ficha e dados enviados com sucesso para a Planilha Google Sheets!")
                    st.balloons()
                    st.session_state.form_submitted = True

                except Exception as e:
                    st.error(f"❌ Erro ao enviar os dados ou arquivo: {e}")
                    st.exception(e)
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

# --- SEÇÃO: VISUALIZAÇÃO DOS DADOS COLETADOS (DA PLANILHA GOOGLE) ---
st.header("📊 Dados de Fichas Coletadas (Google Sheets)")
st.write("Visualize todas as fichas que foram enviadas:")

@st.cache_data(ttl=60)
def get_fichas_data_from_sheets():
    try:
        result = sheets_service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range=SHEET_NAME
        ).execute()
        
        values = result.get('values', [])
        
        if not values:
            return pd.DataFrame()
        
        headers = values[0]
        data_rows = values[1:]
        
        df = pd.DataFrame(data_rows, columns=headers)
        
        if 'URL Arquivo GCS' in df.columns:
            df['Link do Arquivo'] = df['URL Arquivo GCS'].apply(lambda x: f"[Ver Arquivo]({x})" if x else "N/A")
            
        return df

    except Exception as e:
        st.error(f"Erro ao buscar dados da Planilha Google Sheets: {e}")
        st.exception(e)
        return pd.DataFrame()

if st.button("Atualizar Dados da Planilha"):
    st.cache_data.clear()
    fichas_df = get_fichas_data_from_sheets()
else:
    fichas_df = get_fichas_data_from_sheets()

if not fichas_df.empty:
    st.write(f"Total de Fichas Encontradas: **{len(fichas_df)}**")
    
    cols_to_display = [
        'Nome Ficha',
        'Tipo Ficha',
        'Data Ficha',
        'Nome Arquivo Original',
        'Link do Arquivo',
        'Observacoes',
        'Timestamp Envio'
    ]
    
    display_df = fichas_df[[col for col in cols_to_display if col in fichas_df.columns]]
    
    st.dataframe(display_df, use_container_width=True)

    st.markdown("---")
    st.markdown("Clique nos links na coluna 'Link do Arquivo' para visualizar a imagem original.")

else:
    st.info("Nenhuma ficha encontrada na Planilha Google Sheets ainda. Envie uma ficha para começar!")

st.write("---")
st.markdown("_Desenvolvido com Streamlit, Google Cloud Storage e Google Sheets API_")



