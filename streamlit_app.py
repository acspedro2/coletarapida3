import streamlit as st
import gspread
import requests
import json
import os
import re
from io import BytesIO
from datetime import datetime
from gspread.exceptions import APIError

# --- Configuração da Página e Título ---
st.set_page_config(
    page_title="Aplicativo de Coleta Rápida",
    page_icon=":camera:",
    layout="centered"
)

st.title("Aplicativo de Coleta Rápida")
st.markdown("---")

# --- CONEXÃO E VARIÁVEIS DE AMBIENTE ---
# Usa os.environ.get() para compatibilidade com o Render
try:
    credenciais_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_CREDENTIALS")
    planilha_id = os.environ.get("GOOGLE_SHEETS_ID")
    ocr_api_key = os.environ.get("OCR_SPACE_API_KEY")

    if not credenciais_json or not planilha_id or not ocr_api_key:
        st.error("Erro de configuração: Variáveis de ambiente faltando no Render. Verifique a configuração.")
        st.stop()

    credenciais = json.loads(credenciais_json)
    
except Exception as e:
    st.error(f"Erro ao carregar as variáveis de ambiente. Verifique se os nomes e valores estão corretos. Erro: {e}")
    st.stop()

# --- FUNÇÕES ---

@st.cache_resource
def conectar_planilha():
    """
    Tenta conectar com o Google Sheets e retorna o objeto da planilha.
    Usa caching para evitar múltiplas conexões.
    """
    try:
        gc = gspread.service_account_from_dict(credenciais)
        planilha = gc.open_by_key(planilha_id).sheet1 
        return planilha
    except APIError as e:
        st.error("Erro de permissão! Verifique se a planilha foi compartilhada com a conta de serviço.")
        st.stop()
    except Exception as e:
        st.error(f"Não foi possível conectar à planilha. Verifique a ID e as permissões. Erro: {e}")
        st.stop()

def extrair_texto_ocr(image_bytes):
    """Tenta extrair texto de uma imagem usando o serviço de OCR."""
    try:
        response = requests.post(
            'https://api.ocr.space/parse/image',
            headers={'apikey': ocr_api_key},
            files={'filename': image_bytes},
            data={'language': 'por', 'isOverlayRequired': False},
            timeout=15 # Aumentado o tempo limite para 15 segundos
        )
        response.raise_for_status() # Lança um erro se o status HTTP for um erro
        result = response.json()
        
        if result['OCRExitCode'] == 1:
            return result['ParsedResults'][0]['ParsedText']
        else:
            st.warning("O OCR não conseguiu extrair texto da imagem. Tente uma imagem mais clara.")
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de conexão com o serviço OCR. Verifique sua chave de API ou tente novamente mais tarde. Erro: {e}")
        return None
    except Exception as e:
        st.error(f"Erro inesperado ao processar a imagem. Erro: {e}")
        return None

def extrair_dados(texto):
    """Extrai dados específicos do texto usando expressões regulares aprimoradas."""
    
    # As expressões foram ajustadas com base no documento que você enviou
    dados = {
        'ID Família': re.search(r"FAM[\s\n]*(\d{3,})", texto, re.IGNORECASE),
        'Nome': re.search(r"(Nome:)\n([A-ZÇ\s]+)", texto, re.IGNORECASE),
        'Data de Nascimento': re.search(r"Nascimento\s*:\s*(\d{2}/\d{2}/\d{4})", texto, re.IGNORECASE),
        'Telefone': re.search(r"CELULAR\n\((\d{2})\)\s?(\d{4,5})[-]?(\d{4})", texto, re.IGNORECASE),
        'CPF': re.search(r"CPF:\n(\d{3}\.\d{3}\.\d{3}-\d{2})", texto, re.IGNORECASE)
    }

    return {
        'ID Família': dados['ID Família'].group(0) if dados['ID Família'] else '',
        'Nome': dados['Nome'].group(2).strip() if dados['Nome'] else '',
        'Data de Nascimento': dados['Data de Nascimento'].group(1) if dados['Data de Nascimento'] else '',
        'Telefone': f"({dados['Telefone'].group(1)}) {dados['Telefone'].group(2)}-{dados['Telefone'].group(3)}" if dados['Telefone'] else '',
        'CPF': dados['CPF'].group(1) if dados['CPF'] else '',
        'Data de Envio': datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    }

# --- STREAMLIT APP ---

# Conecta à planilha uma única vez quando o aplicativo é iniciado
planilha_conectada = conectar_planilha()

st.subheader("Envie a imagem da ficha SUS")

uploaded_file = st.file_uploader("Escolha uma imagem", type=['jpg', 'jpeg', 'png'])

if uploaded_file is not None:
    st.image(uploaded_file, caption="Pré-visualização", use_container_width=True)
    
    with st.spinner("Analisando imagem via OCR..."):
        image_bytes = BytesIO(uploaded_file.getvalue())
        texto = extrair_texto_ocr(image_bytes)

    if not texto:
        st.error("Erro ao processar imagem. Verifique a imagem e tente novamente.")
    else:
        st.success("Texto extraído com sucesso!")
        
        dados = extrair_dados(texto)
        
        st.subheader("Dados Extraídos:")
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**ID Família:** {dados['ID Família']}")
            st.write(f"**Nome:** {dados['Nome']}")
            st.write(f"**Data de Nascimento:** {dados['Data de Nascimento']}")
        with col2:
            st.write(f"**CPF:** {dados['CPF']}")
            st.write(f"**Telefone:** {dados['Telefone']}")
            st.write(f"**Data de Envio:** {dados['Data de Envio']}")

        if st.button("✅ Enviar para Google Sheets"):
            # Verifica se os dados principais foram extraídos
            if not dados['ID Família'] or not dados['Nome']:
                st.warning("Dados principais (ID e Nome) não foram encontrados. Envio cancelado.")
            else:
                try:
                    nova_linha = [
                        dados['ID Família'],
                        dados['Nome'],
                        dados['Data de Nascimento'],
                        dados['Telefone'],
                        dados['CPF'],
                        dados['Data de Envio']
                    ]
                    
                    planilha_conectada.append_row(nova_linha)
                    st.success("Dados enviados para a planilha com sucesso!")
                except Exception as e:
                    st.error(f"Erro ao enviar dados para a planilha. Verifique se as colunas estão corretas. Erro: {e}")

