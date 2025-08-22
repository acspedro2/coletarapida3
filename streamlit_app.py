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
    try: # <-- CORREÇÃO: Os dois pontos (:) foram adicionados aqui.
        # Puxa as credenciais diretamente do st.secrets, que já entende o formato de dicionário
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
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except json.JSONDecodeError:
        st.error("A IA não retornou um JSON válido. Tente novamente.")
        return None
    except Exception as e:
        st.error(f"Erro ao chamar a API do Cohere: {e}")
        return None

def salvar_no_sheets(dados, planilha):
    """Salva os dados extraídos no Google Sheets."""
    try:
        # Define a ordem correta das colunas
        colunas = ['ID Familia', 'Nome Completo', 'Data de Nascimento', 'Telefone', 'CPF', 'Nome da Mae', 'Nome do Pai', 'Sexo', 'CNS', 'Municipio de Nascimento']
        # Pega os valores do dicionário na ordem correta
        nova_linha = [dados.get(col, "") for col in colunas]
        planilha.append_row(nova_linha)
        st.success("✅ Dados salvos com sucesso no Google Sheets!")
        st.balloons()
    except Exception as e:
        st.error(f"Erro ao salvar na planilha: {e}")

# --- Lógica Principal da Aplicação ---

# Carrega recursos uma vez
try:
    co_client = cohere.Client(api_key=st.secrets["COHEREKEY"])
    planilha = conectar_planilha()
except Exception as e:
    st.error(f"Não foi possível inicializar os serviços. Verifique seus segredos. Erro: {e}")
    st.stop()


# Seletor de arquivos
uploaded_file = st.file_uploader("Envie a imagem da ficha SUS", type=["jpg", "jpeg", "png"])

# Inicializa o estado da sessão
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

# Formulário para salvar os dados (só aparece se houver dados extraídos)
if st.session_state.dados_extraidos:
    st.markdown("---")
    st.header("Confirme os dados antes de salvar")
    
    # Cria campos de texto pré-preenchidos para edição
    dados = st.session_state.dados_extraidos
    id_familia = st.text_input("ID Família", value=dados.get("ID Familia", ""))
    nome_completo = st.text_input("Nome Completo", value=dados.get("Nome Completo", ""))
    data_nascimento = st.text_input("Data de Nascimento", value=dados.get("Data de Nascimento", ""))
    telefone = st.text_input("Telefone", value=dados.get("Telefone", ""))
    cpf = st.text_input("CPF", value=dados.get("CPF", ""))
    nome_mae = st.text_input("Nome da Mãe", value=dados.get("Nome da Mae", ""))
    nome_pai = st.text_input("Nome do Pai", value=dados.get("Nome do Pai", ""))
    sexo = st.text_input("Sexo", value=dados.get("Sexo", ""))
    cns = st.text_input("CNS", value=dados.get("CNS", ""))
    municipio_nascimento = st.text_input("Município de Nascimento", value=dados.get("Municipio de Nascimento", ""))
    
    if st.button("✅ Salvar Dados na Planilha"):
        if planilha is not None:
            # Recompila os dados a partir dos campos de texto
            dados_para_salvar = {
                'ID Familia': id_familia,
                'Nome Completo': nome_completo,
                'Data de Nascimento': data_nascimento,
                'Telefone': telefone,
                'CPF': cpf,
                'Nome da Mae': nome_mae,
                'Nome do Pai': nome_pai,
                'Sexo': sexo,
                'CNS': cns,
                'Municipio de Nascimento': municipio_nascimento
            }
            salvar_no_sheets(dados_para_salvar, planilha)
            st.session_state.dados_extraidos = None # Limpa o estado para a próxima imagem
            st.rerun() # Recarrega a página para limpar os campos
