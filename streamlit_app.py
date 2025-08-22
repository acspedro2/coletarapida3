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

# --- FUNÇÃO DE EXTRAÇÃO COM PROMPT MELHORADO ---
def extrair_dados_com_cohere(texto_extraido: str, cohere_client):
    """Usa o Cohere para extrair dados estruturados do texto, usando a técnica Few-Shot."""
    try:
        # Prompt melhorado com instruções claras e um exemplo de alta qualidade.
        prompt = f"""
        Sua tarefa é extrair informações de um texto obtido por OCR de um formulário de saúde e convertê-lo para um formato JSON. Preste atenção especial a textos escritos à mão.

        **EXEMPLO:**

        **Texto de Entrada (OCR):**
        "CONSULTA AO CADASTRO DE PACIENTES SUS FAM111 NOME JHENIFER DA SILVA COSTA DOS SANTOS 19/07/2004 CNS 700004848298395 Endereco RUA JOAQUIM DA SILVA COSTA Mãe: MARIA APARECIDA COSTA Pai: JOÃO BATISTA DOS SANTOS CPF: 123.456.789-00 Telefone: (22) 99999-8888 Sexo: Feminino Município de Nascimento: BOM JARDIM"

        **Saída JSON Esperada:**
        ```json
        {{
            "ID": "",
            "FAMÍLIA": "FAM111",
            "Nome Completo": "JHENIFER DA SILVA COSTA DOS SANTOS",
            "Data de Nascimento": "19/07/2004",
            "Telefone": "(22) 99999-8888",
            "CPF": "123.456.789-00",
            "Nome da Mãe": "MARIA APARECIDA COSTA",
            "Nome do Pai": "JOÃO BATISTA DOS SANTOS",
            "Sexo": "Feminino",
            "CNS": "700004848298395",
            "Município de Nascimento": "BOM JARDIM"
        }}
        ```

        **FIM DO EXEMPLO.**

        Agora, analise o seguinte texto e retorne APENAS o objeto JSON correspondente. Se um valor não for encontrado, retorne uma string vazia "".

        **Texto para analisar:**
        ---
        {texto_extraido}
        ---
        """
        response = cohere_client.chat(
            model="command-r-plus",
            message=prompt,
            temperature=0.1  # Baixa a temperatura para respostas mais focadas e menos "criativas"
        )
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except json.JSONDecodeError:
        st.error("A IA não retornou um JSON válido após o prompt melhorado. Verifique o texto do OCR.")
        return None
    except Exception as e:
        st.error(f"Erro ao chamar a API do Cohere: {e}")
        return None

def salvar_no_sheets(dados, planilha):
    """Salva os dados extraídos no Google Sheets, respeitando a ordem das colunas."""
    try:
        cabecalhos = planilha.row_values(1)
        nova_linha = [dados.get(cabecalho, "") for cabecalho in cabecalhos]
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
            
            with st.spinner("Estruturando os dados com a IA (com novas instruções)..."):
                st.session_state.dados_extraidos = extrair_dados_com_cohere(texto_extraido, co_client)
            
            if st.session_state.dados_extraidos:
                st.success("Dados estruturados com sucesso!")
                st.json(st.session_state.dados_extraidos)

if st.session_state.dados_extraidos:
    st.markdown("---")
    st.header("Confirme os dados antes de salvar")
    
    dados = st.session_state.dados_extraidos
    
    id_val = st.text_input("ID", value=dados.get("ID", ""))
    familia_val = st.text_input("FAMÍLIA", value=dados.get("FAMÍLIA", ""))
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
                'ID': id_val,
                'FAMÍLIA': familia_val,
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
