import streamlit as st
import requests
import json
import cohere
import gspread
from PIL import Image

# --- Função: Conectar ao Google Sheets ---
@st.cache_resource
def conectar_planilha():
    try:
        # Puxa as credenciais diretamente do st.secrets, que já entende o formato de dicionário
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
        sheet = client.open_by_key(st.secrets["SHEETSID"]).sheet1
        return sheet
    except Exception as e:
        st.error(f"Erro ao conectar com o Google Sheets: {e}")
        return None

# --- Função: OCR com OCR.Space ---
def ocr_space_api(file_bytes, ocr_api_key):
    try:
        url = "https://api.ocr.space/parse/image"
        headers = {"apikey": ocr_api_key}
        files = {"file": ("ficha.jpg", file_bytes, "image/jpeg")}
        
        response = requests.post(url, headers=headers, files=files)
        response.raise_for_status() # Verifica se houve erros de HTTP
        
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

# --- Função: Extração com Cohere ---
def extrair_dados_com_cohere(texto_extraido: str, cohere_client):
    try:
        # Prompt melhorado, pedindo um JSON limpo
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
        # Limpa a resposta para garantir que é apenas o JSON
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except json.JSONDecodeError:
        st.error("A IA não retornou um JSON válido. Tente novamente.")
        return None
    except Exception as e:
        st.error(f"Erro ao chamar a API do Cohere: {e}")
        return None

# --- Interface Streamlit ---
st.set_page_config(page_title="Coleta Rápida SUS", page_icon="📑", layout="centered")
st.title("📑 Coleta Rápida SUS")

# Inicializa o cliente Cohere uma vez
co = cohere.Client(api_key=st.secrets["COHEREKEY"])
planilha = conectar_planilha()

uploaded_file = st.file_uploader("Envie a imagem da ficha SUS", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    st.image(Image.open(uploaded_file), caption="Imagem enviada", use_column_width=True)
    
    # Usa st.session_state para guardar os dados entre os cliques
    if 'dados_extraidos' not in st.session_state:
        st.session_state.dados_extraidos = None

    if st.button("1. Processar Imagem"):
        file_bytes = uploaded_file.getvalue()
        
        with st.spinner("Lendo o texto da imagem (OCR)..."):
            texto_extraido = ocr_space_api(file_bytes, st.secrets["OCRSPACEKEY"])
        
        if texto_extraido:
            st.text_area("📄 Texto Extraído (OCR):", texto_extraido, height=200)
            
            with st.spinner("Estruturando os dados com a IA..."):
                st.session_state.dados_extraidos = extrair_dados_com_cohere(texto_extraido, co)
            
            if st.session_state.dados_extraidos:
                st.success("Dados estruturados com sucesso!")
                st.json(st.session_state.dados_extraidos)

    if st.session_state.dados_extraidos:
        st.markdown("---")
        if st.button("2. ✅ Salvar Dados na Planilha"):
            if planilha is not None:
                with st.spinner("Salvando..."):
                    try:
                        # Define a ordem correta das colunas
                        colunas = ['ID Familia', 'Nome Completo', 'Data de Nascimento', 'Telefone', 'CPF', 'Nome da Mae', 'Nome do Pai', 'Sexo', 'CNS', 'Municipio de Nascimento']
                        # Pega os valores do dicionário na ordem correta
                        nova_linha = [st.session_state.dados_extraidos.get(col, "") for col in colunas]
                        planilha.append_row(nova_linha)
                        st.success("Dados salvos com sucesso no Google Sheets!")
                        st.balloons()
                        st.session_state.dados_extraidos = None # Limpa o estado para a próxima imagem
                    except Exception as e:
                        st.error(f"Erro ao salvar na planilha: {e}")
