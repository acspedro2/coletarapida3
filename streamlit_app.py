import streamlit as st
import requests
import json
import cohere
import gspread
from PIL import Image

# --- Interface Streamlit ---
st.set_page_config(page_title="Coleta Inteligente", page_icon="🤖", layout="centered")
st.title("🤖 COLETA INTELIGENTE")

# --- Funções ---

@st.cache_resource
def conectar_planilha():
    """Conecta com o Google Sheets usando as credenciais."""
    try:
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
        sheet = client.open_by_key(st.secrets["SHEETSID"]).sheet1
        return sheet
    except Exception as e:
        st.error(f"Erro ao conectar com o Google Sheets: {e}")
        return None

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
        Analise o texto extraído de um formulário de saúde e retorne APENAS um objeto JSON com as seguintes chaves: 'ID', 'FAMÍLIA', 'Nome Completo', 'Data de Nascimento', 'Telefone', 'CPF', 'Nome da Mãe', 'Nome do Pai', 'Sexo', 'CNS', 'Município de Nascimento'.
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
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except json.JSONDecodeError:
        st.error("A IA não retornou um JSON válido. Tente novamente.")
        return None
    except Exception as e:
        st.error(f"Erro ao chamar a API do Cohere: {e}")
        return None

# --- FUNÇÃO DE SALVAR CORRIGIDA ---
def salvar_no_sheets(dados, planilha):
    """Salva os dados extraídos no Google Sheets, respeitando a ordem das colunas."""
    try:
        # Passo 1: Lê os cabeçalhos da primeira linha da planilha
        cabecalhos = planilha.row_values(1)
        
        # Passo 2: Cria uma lista de valores na ordem correta dos cabeçalhos
        nova_linha = [dados.get(cabecalho, "") for cabecalho in cabecalhos]
        
        # Passo 3: Adiciona a nova linha
        planilha.append_row(nova_linha)
        st.success("✅ Dados salvos com sucesso no Google Sheets!")
        st.balloons()
    except Exception as e:
        st.error(f"Erro ao salvar na planilha: {e}")

# --- Lógica Principal da Aplicação ---

try:
    co_client = cohere.Client(api_key=st.secrets["COHEREKEY"])
    planilha = conectar_planilha()
except Exception as e:
    st.error(f"Não foi possível inicializar os serviços. Verifique seus segredos. Erro: {e}")
    st.stop()

uploaded_file = st.file_uploader("Envie a imagem da ficha SUS", type=["jpg", "jpeg", "png"])

if 'dados_extraidos' not in st.session_state:
    st.session_state.dados_extraidos = None

if uploaded_file is not None:
    st.image(Image.open(uploaded_file), caption="Imagem enviada", use_container_width=True)
    
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
    st.header("Confirme os dados antes de salvar")
    
    dados = st.session_state.dados_extraidos
    
    # Adapta os campos de texto para usarem as chaves que a IA retorna
    id_familia = st.text_input("ID", value=dados.get("ID", ""))
    familia = st.text_input("FAMÍLIA", value=dados.get("FAMÍLIA", ""))
    nome_completo = st.text_input("Nome Completo", value=dados.get("Nome Completo", ""))
    data_nascimento = st.text_input("Data de Nascimento", value=dados.get("Data de Nascimento", ""))
    telefone = st.text_input("Telefone", value=dados.get("Telefone", ""))
    cpf = st.text_input("CPF", value=dados.get("CPF", ""))
    nome_mae = st.text_input("Nome da Mãe", value=dados.get("Nome da Mãe", ""))
    nome_pai = st.text_input("Nome do Pai", value=dados.get("Nome do Pai", ""))
    sexo = st.text_input("Sexo", value=dados.get("Sexo", ""))
    cns = st.text_input("CNS", value=dados.get("CNS", ""))
    municipio_nascimento = st.text_input("Município de Nascimento", value=dados.get("Município de Nascimento", ""))
    
    if st.button("✅ Salvar Dados na Planilha"):
        if planilha is not None:
            dados_para_salvar = {
                'ID': id_familia,
                'FAMÍLIA': familia,
                'Nome Completo': nome_completo,
                'Data de Nascimento': data_nascimento,
                'Telefone': telefone,
                'CPF': cpf,
                'Nome da Mãe': nome_mae,
                'Nome do Pai': nome_pai,
                'Sexo': sexo,
                'CNS': cns,
                'Município de Nascimento': municipio_nascimento
            }
            salvar_no_sheets(dados_para_salvar, planilha)
            st.session_state.dados_extraidos = None
            st.rerun()
