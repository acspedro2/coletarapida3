import streamlit as st
import requests
import json
import cohere
import gspread
from PIL import Image
import re
from datetime import datetime

# --- Interface Streamlit ---
st.set_page_config(page_title="Coleta Inteligente", page_icon="🤖", layout="centered")
st.title("🤖 COLETA INTELIGENTE")

# --- NOVAS FUNÇÕES DE VALIDAÇÃO ---

def validar_cpf(cpf: str) -> bool:
    """Verifica se um CPF é matematicamente válido."""
    cpf = ''.join(re.findall(r'\d', str(cpf)))

    if not cpf or len(cpf) != 11 or cpf == cpf[0] * 11:
        return False

    # Validação do primeiro dígito
    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    d1 = (soma * 10 % 11) % 10
    if d1 != int(cpf[9]):
        return False

    # Validação do segundo dígito
    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    d2 = (soma * 10 % 11) % 10
    if d2 != int(cpf[10]):
        return False

    return True

def validar_data_nascimento(data_str: str) -> (bool, str):
    """Verifica o formato (DD/MM/AAAA) e se a data não está no futuro."""
    try:
        data_obj = datetime.strptime(data_str, '%d/%m/%Y').date()
        if data_obj > datetime.now().date():
            return False, "A data de nascimento está no futuro."
        return True, ""
    except ValueError:
        return False, "O formato da data deve ser DD/MM/AAAA."

# --- FUNÇÕES EXISTENTES ---

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
    """Faz OCR na imagem usando a API do OCR.space com o motor otimizado."""
    try:
        url = "https://api.ocr.space/parse/image"
        payload = {"language": "por", "isOverlayRequired": False, "OCREngine": 2}
        files = {"file": ("ficha.jpg", file_bytes, "image/jpeg")}
        headers = {"apikey": ocr_api_key}
        
        response = requests.post(url, data=payload, files=files, headers=headers)
        response.raise_for_status()
        
        result = response.json()
        if result.get("IsErroredOnProcessing"):
            st.error(f"Erro no servidor do OCR: {result.get('ErrorMessage')}")
            return None
        
        return result["ParsedResults"][0]["ParsedText"]
    except Exception as e:
        st.error(f"Erro inesperado no OCR: {e}")
        return None

def extrair_dados_com_cohere(texto_extraido: str, cohere_client):
    """Usa o Cohere para extrair dados estruturados do texto, com foco em anotações."""
    try:
        prompt = f"""
        Sua tarefa é extrair informações de um texto obtido por OCR de um formulário de saúde e convertê-lo para um formato JSON.

        **Instrução Crítica:** Primeiro, procure em todo o texto por uma anotação escrita à mão que se pareça com um código de família (ex: 'FAM111', 'Familia 02', 'F-123'). Este código é a informação mais importante e deve ser atribuído à chave "FAMÍLIA". Frequentemente, ele está num dos cantos do documento. Depois de encontrar o código da família, processe o resto do texto para preencher os outros campos.

        **EXEMPLO:**
        **Texto de Entrada (OCR):** "CONSULTA AO CADASTRO DE PACIENTES SUS FAM111 NOME JHENIFER DA SILVA COSTA DOS SANTOS 19/07/2004 CNS 700004848298395 Mãe: MARIA APARECIDA COSTA Pai: JOÃO BATISTA DOS SANTOS CPF: 123.456.789-00"
        **Saída JSON Esperada:**
        ```json
        {{
            "ID": "", "FAMÍLIA": "FAM111", "Nome Completo": "JHENIFER DA SILVA COSTA DOS SANTOS", "Data de Nascimento": "19/07/2004", "Telefone": "", "CPF": "123.456.789-00", "Nome da Mãe": "MARIA APARECIDA COSTA", "Nome do Pai": "JOÃO BATISTA DOS SANTOS", "Sexo": "Feminino", "CNS": "700004848298395", "Município de Nascimento": ""
        }}
        ```
        **FIM DO EXEMPLO.**

        Agora, analise o seguinte texto e retorne APENAS o objeto JSON correspondente. Se um valor não for encontrado, retorne uma string vazia "".

        **Texto para analisar:**
        ---
        {texto_extraido}
        ---
        """
        response = cohere_client.chat(model="command-r-plus", message=prompt, temperature=0.1)
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
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
        
        with st.spinner("Lendo o texto da imagem (OCR Otimizado)..."):
            texto_extraido = ocr_space_api(file_bytes, st.secrets["OCRSPACEKEY"])
        
        if texto_extraido:
            st.text_area("📄 Texto Extraído (OCR):", texto_extraido, height=200)
            
            with st.spinner("Estruturando os dados com a IA (Instruções Avançadas)..."):
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
    # --- LÓGICA DE VALIDAÇÃO DA DATA ---
    is_data_valida, erro_data = validar_data_nascimento(data_nascimento)
    if not is_data_valida and data_nascimento:
        st.warning(f"⚠️ Atenção: {erro_data}")
        
    telefone = st.text_input("Telefone", value=dados.get("Telefone", ""))
    cpf = st.text_input("CPF", value=dados.get("CPF", ""))
    # --- LÓGICA DE VALIDAÇÃO DO CPF ---
    if not validar_cpf(cpf) and cpf:
        st.warning("⚠️ Atenção: O CPF parece ser inválido.")

    nome_mae = st.text_input("Nome da Mãe", value=dados.get("Nome da Mãe", ""))
    nome_pai = st.text_input("Nome do Pai", value=dados.get("Nome do Pai", ""))
    sexo = st.text_input("Sexo", value=dados.get("Sexo", ""))
    cns = st.text_input("CNS", value=dados.get("CNS", ""))
    municipio_nascimento = st.text_input("Município de Nascimento", value=dados.get("Município de Nascimento", ""))
    
    if st.button("✅ Salvar Dados na Planilha"):
        if planilha is not None:
            dados_para_salvar = {
                'ID': id_val, 'FAMÍLIA': familia_val, 'Nome Completo': nome_completo,
                'Data de Nascimento': data_nascimento, 'Telefone': telefone, 'CPF': cpf,
                'Nome da Mãe': nome_mae, 'Nome do Pai': nome_pai, 'Sexo': sexo, 'CNS': cns,
                'Município de Nascimento': municipio_nascimento
            }
            salvar_no_sheets(dados_para_salvar, planilha)
            st.session_state.dados_extraidos = None
            st.rerun()
