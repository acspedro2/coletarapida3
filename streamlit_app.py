import streamlit as st
import requests
import json
import cohere
import gspread
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

# --- Configurações de API e credenciais ---
# Lembre-se de colocar estes valores nos "Secrets" do Streamlit Cloud
# e não diretamente no código como aqui.
# COHEREKEY = st.secrets["COHEREKEY"]
# OCRSPACEKEY = st.secrets["OCRSPACEKEY"]
# SHEETSID = st.secrets["SHEETSID"]
# gcp_service_account_dict = st.secrets["gcp_service_account"]

# --- Funções ---

def ocr_space_api(file_bytes, ocr_api_key):
    """Faz OCR na imagem usando a API do OCR.space"""
    try:
        url = "https://api.ocr.space/parse/image"
        headers = {"apikey": ocr_api_key}
        files = {"file": ("ficha.jpg", file_bytes, "image/jpeg")}

        response = requests.post(url, headers=headers, files=files)
        response.raise_for_status()

        result = response.json()
        if result.get("IsErroredOnProcessing"):
            st.error(f"Erro no servidor do OCR: {result.get('ErrorMessage')}")
            return None

        return result["ParsedResults"][0]["ParsedText"]
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de conexão com a API do OCR.space: {e}")
        return None
    except Exception as e:
        st.error(f"Erro inesperado no OCR: {e}")
        return None

def extrair_dados_com_cohere(texto_extraido: str, cohere_client):
    """Usa o Cohere para extrair dados estruturados do texto."""
    try:
        prompt = f"""
        Analise o texto extraído de um formulário de saúde e retorne APENAS um objeto JSON com as seguintes chaves: 'ID Familia', 'Nome Completo', 'Data de Nascimento', 'Telefone', 'CPF', 'Nome da Mae', 'Nome do Pai', 'Sexo', 'CNS', 'Municipio de Nascimento'.
        Se um valor não for encontrado, retorne uma string vazia "".
        Texto para analisar:
        ---
        {texto_extraido}
        ---
        """
        response = cohere_client.chat(
            model="command-r-plus",
            message=prompt
        )
        json_string = response.text.replace('````json', '').replace('````', '').strip()
        return json.loads(json_string)
    except json.JSONDecodeError:
        st.error("A IA não retornou um JSON válido. Tente novamente.")
        return None
    except Exception as e:
        st.error(f"Erro ao chamar a API do Cohere: {e}")
        return None

def salvar_no_sheets(dados):
    """Salva os dados extraídos no Google Sheets."""
    try:
        creds = st.secrets["gcp_service_account"]
        sheet_id = st.secrets["SHEETSID"]

        client = gspread.service_account_from_dict(creds)
        sheet = client.open_by_key(sheet_id).sheet1

        colunas = ['ID Familia', 'Nome Completo', 'Data de Nascimento', 'Telefone', 'CPF', 'Nome da Mae', 'Nome do Pai', 'Sexo', 'CNS', 'Municipio de Nascimento']
        nova_linha = [dados.get(col, "") for col in colunas]

        sheet.append_row(nova_linha)
        return "✅ Dados salvos com sucesso no Google Sheets!"
    except Exception as e:
        return f"Erro ao salvar no Sheets: {e}"

# --- Interface Streamlit ---
# --- ALTERAÇÃO DO ÍCONE AQUI ---
st.set_page_config(page_title="Coleta Inteligente", page_icon="🤖", layout="centered")
st.title("📑 COLETA INTELIGENTE")

# Inicializa o cliente Cohere
co_client = cohere.Client(api_key=st.secrets["COHEREKEY"])

uploaded_file = st.file_uploader("Envie a imagem da ficha SUS", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    st.image(Image.open(uploaded_file), caption="Imagem enviada", use_container_width=True)

    if 'dados_extraidos' not in st.session_state:
        st.session_state.dados_extraidos = None

    if st.button("Processar Imagem"):
        file_bytes = uploaded_file.getvalue()

        with st.spinner("Lendo o texto da imagem (OCR)..."):
            texto_extraido = ocr_space_api(file_bytes, st.secrets["OCRSPACEKEY"])

        if texto_extraido:
            st.text_area("📄 Texto Extraído (OCR):", texto_extraido, height=200)

            with st.spinner("Estruturando os dados com a IA..."):
                st.session_state.dados_extraidos = extrair_dados_com_cohere(texto_extraido, co_client)

            if st.session_state.dados_extraidos:
                st.success("Dados estruturados com sucesso!")
                st.json(st.session_state.dados_extraidos)

    if st.session_state.dados_extraidos:
        st.markdown("---")
        if st.button("Salvar Dados na Planilha"):
            resultado = salvar_no_sheets(st.session_state.dados_extraidos)
            st.success(resultado)
            st.balloons()
            st.session_state.dados_extraidos = None
