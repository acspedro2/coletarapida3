import streamlit as st
import requests
import json
import cohere
import gspread
from PIL import Image
import time # Importa a biblioteca para o atraso (delay)
import re
from datetime import datetime

# --- Interface Streamlit ---
st.set_page_config(page_title="Coleta Inteligente", page_icon="🤖", layout="centered")
st.title("🤖 COLETA INTELIGENTE")

# --- Funções de Validação ---
def validar_cpf(cpf: str) -> bool:
    cpf = ''.join(re.findall(r'\d', str(cpf)))
    if not cpf or len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    try:
        soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
        d1 = (soma * 10 % 11) % 10
        if d1 != int(cpf[9]):
            return False
        soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
        d2 = (soma * 10 % 11) % 10
        if d2 != int(cpf[10]):
            return False
    except (ValueError, IndexError):
        return False
    return True

def validar_data_nascimento(data_str: str) -> (bool, str):
    try:
        data_obj = datetime.strptime(data_str, '%d/%m/%Y').date()
        if data_obj > datetime.now().date():
            return False, "A data de nascimento está no futuro."
        return True, ""
    except ValueError:
        return False, "O formato da data deve ser DD/MM/AAAA."

# --- Funções de Conexão e API ---

@st.cache_resource
def conectar_planilha():
    """Conecta com o Google Sheets."""
    try:
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
        sheet = client.open_by_key(st.secrets["SHEETSID"]).sheet1
        return sheet
    except Exception as e:
        st.error(f"Erro ao conectar com o Google Sheets: {e}")
        return None

def ocr_space_api(file_bytes, ocr_api_key):
    """Faz OCR na imagem usando o motor otimizado."""
    try:
        url = "https://api.ocr.space/parse/image"
        payload = {"language": "por", "isOverlayRequired": False, "OCREngine": 2}
        files = {"file": ("ficha.jpg", file_bytes, "image/jpeg")}
        headers = {"apikey": ocr_api_key}
        response = requests.post(url, data=payload, files=files, headers=headers)
        response.raise_for_status()
        result = response.json()
        if result.get("IsErroredOnProcessing"):
            st.error(f"Erro no OCR: {result.get('ErrorMessage')}")
            return None
        return result["ParsedResults"][0]["ParsedText"]
    except Exception as e:
        st.error(f"Erro inesperado no OCR: {e}")
        return None

def extrair_dados_com_cohere(texto_extraido: str, cohere_client):
    """Usa o Cohere para extrair dados estruturados do texto."""
    try:
        prompt = f"""
        Sua tarefa é extrair informações de um texto de formulário de saúde e convertê-lo para um JSON.
        Instrução Crítica: Procure por uma anotação à mão que pareça um código de família (ex: 'FAM111'). Este código deve ir para a chave "FAMÍLIA".
        Retorne APENAS um objeto JSON com as chaves: 'ID', 'FAMÍLIA', 'Nome Completo', 'Data de Nascimento', 'Telefone', 'CPF', 'Nome da Mãe', 'Nome do Pai', 'Sexo', 'CNS', 'Município de Nascimento'.
        Se um valor não for encontrado, retorne uma string vazia "".
        Texto para analisar:
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
    """Salva os dados no Google Sheets, respeitando a ordem das colunas."""
    try:
        cabecalhos = planilha.row_values(1)
        nova_linha = [dados.get(cabecalho, "") for cabecalho in cabecalhos]
        planilha.append_row(nova_linha)
        st.success(f"✅ Dados de '{dados.get('Nome Completo', 'Desconhecido')}' salvos com sucesso!")
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

# --- NOVA LÓGICA PARA PROCESSAMENTO EM LOTE ---
st.header("1. Envie uma ou mais imagens de fichas")
# Altera o uploader para aceitar múltiplos arquivos
uploaded_files = st.file_uploader(
    "Pode selecionar vários arquivos de uma vez", 
    type=["jpg", "jpeg", "png"], 
    accept_multiple_files=True
)

if 'processados' not in st.session_state:
    st.session_state.processados = []

if uploaded_files:
    for uploaded_file in uploaded_files:
        # Verifica se o arquivo já foi processado e salvo
        if uploaded_file.id in st.session_state.processados:
            continue

        st.markdown("---")
        st.subheader(f"Processando Ficha: `{uploaded_file.name}`")
        st.image(Image.open(uploaded_file), caption="Imagem Carregada.", width=400)
        
        # Processa a imagem atual
        file_bytes = uploaded_file.getvalue()
        with st.spinner("Lendo o texto da imagem (OCR Otimizado)..."):
            texto_extraido = ocr_space_api(file_bytes, st.secrets["OCRSPACEKEY"])
        
        if texto_extraido:
            with st.expander("Ver texto extraído pelo OCR"):
                st.text_area("Texto", texto_extraido, height=150, key=f"ocr_{uploaded_file.id}")
            
            with st.spinner("Estruturando os dados com a IA..."):
                dados_extraidos = extrair_dados_com_cohere(texto_extraido, co_client)
            
            if dados_extraidos:
                st.success("Dados estruturados com sucesso!")
                
                # Cria um formulário único para cada imagem
                with st.form(key=f"form_{uploaded_file.id}"):
                    st.subheader("2. Confirme e salve os dados")
                    
                    dados = dados_extraidos
                    id_val = st.text_input("ID", value=dados.get("ID", ""), key=f"id_{uploaded_file.id}")
                    familia_val = st.text_input("FAMÍLIA", value=dados.get("FAMÍLIA", ""), key=f"fam_{uploaded_file.id}")
                    nome_completo = st.text_input("Nome Completo", value=dados.get("Nome Completo", ""), key=f"nome_{uploaded_file.id}")
                    
                    data_nascimento = st.text_input("Data de Nascimento", value=dados.get("Data de Nascimento", ""), key=f"data_{uploaded_file.id}")
                    is_data_valida, erro_data = validar_data_nascimento(data_nascimento)
                    if not is_data_valida and data_nascimento:
                        st.warning(f"⚠️ {erro_data}")
                    
                    cpf = st.text_input("CPF", value=dados.get("CPF", ""), key=f"cpf_{uploaded_file.id}")
                    if not validar_cpf(cpf) and cpf:
                        st.warning("⚠️ O CPF parece ser inválido.")
                    
                    # Restante dos campos...
                    telefone = st.text_input("Telefone", value=dados.get("Telefone", ""), key=f"tel_{uploaded_file.id}")
                    nome_mae = st.text_input("Nome da Mãe", value=dados.get("Nome da Mãe", ""), key=f"mae_{uploaded_file.id}")
                    nome_pai = st.text_input("Nome do Pai", value=dados.get("Nome do Pai", ""), key=f"pai_{uploaded_file.id}")
                    sexo = st.text_input("Sexo", value=dados.get("Sexo", ""), key=f"sexo_{uploaded_file.id}")
                    cns = st.text_input("CNS", value=dados.get("CNS", ""), key=f"cns_{uploaded_file.id}")
                    municipio_nascimento = st.text_input("Município de Nascimento", value=dados.get("Município de Nascimento", ""), key=f"mun_{uploaded_file.id}")
                    
                    submitted = st.form_submit_button("✅ Salvar Dados Desta Ficha na Planilha")
                    
                    if submitted:
                        if planilha is not None:
                            dados_para_salvar = {
                                'ID': id_val, 'FAMÍLIA': familia_val, 'Nome Completo': nome_completo,
                                'Data de Nascimento': data_nascimento, 'Telefone': telefone, 'CPF': cpf,
                                'Nome da Mãe': nome_mae, 'Nome do Pai': nome_pai, 'Sexo': sexo, 'CNS': cns,
                                'Município de Nascimento': municipio_nascimento
                            }
                            salvar_no_sheets(dados_para_salvar, planilha)
                            # Marca o arquivo como processado
                            st.session_state.processados.append(uploaded_file.id)
                            st.rerun()
                        else:
                            st.error("Não foi possível conectar à planilha para salvar.")
        else:
            st.error("Não foi possível extrair texto desta imagem.")

        # Pausa para respeitar os limites da API antes de processar a próxima imagem
        with st.spinner("Aguardando 20 segundos antes de processar a próxima ficha..."):
            time.sleep(20)
        
        # Para o loop para processar uma de cada vez
        break
