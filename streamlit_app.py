import streamlit as st
import gspread
import json
import pandas as pd
import cohere
import requests
from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# --- Configuração da Página ---
st.set_page_config(page_title="Coleta Inteligente", page_icon="🤖", layout="wide")
st.title("🤖 Coleta Inteligente")

# --- Variáveis de Ambiente ---
try:
    cohere_api_key = st.secrets["COHEREKEY"]
    ocr_api_key = st.secrets["OCRSPACEKEY"]
    co = cohere.Client(cohere_api_key)

    google_sheets_id = st.secrets["SHEETSID"]
    google_credentials_dict = st.secrets["gcp_service_account"]

except KeyError as e:
    st.error(f"Erro de configuração: A chave secreta '{e.args[0]}' não foi encontrada.")
    st.stop()
except Exception as e:
    st.error(f"Erro inesperado ao carregar as chaves secretas. Erro: {e}")
    st.stop()

# --- Funções ---
@st.cache_resource
def conectar_planilha():
    try:
        gc = gspread.service_account_from_dict(google_credentials_dict)
        planilha = gc.open_by_key(google_sheets_id).sheet1
        return planilha
    except Exception as e:
        st.error(f"Não foi possível conectar à planilha. Erro: {e}")
        st.stop()

def calcular_idade(data_nasc):
    if pd.isna(data_nasc): return 0
    hoje = datetime.now()
    return hoje.year - data_nasc.year - ((hoje.month, hoje.day) < (data_nasc.month, data_nasc.day))

@st.cache_data(ttl=60)
def ler_dados_da_planilha(_planilha):
    try:
        dados = _planilha.get_all_records()
        df = pd.DataFrame(dados)
        colunas_esperadas = ["ID Família", "Nome Completo", "Data de Nascimento", "Telefone", "CPF", "Nome da Mãe", "Nome do Pai", "Sexo", "CNS", "Município de Nascimento", "Timestamp de Envio"]
        for col in colunas_esperadas:
            if col not in df.columns: df[col] = ""
        df['Data de Nascimento DT'] = pd.to_datetime(df['Data de Nascimento'], format='%d/%m/%Y', errors='coerce')
        df['Idade'] = df['Data de Nascimento DT'].apply(lambda dt: calcular_idade(dt) if pd.notnull(dt) else 0)
        return df
    except Exception as e:
        st.error(f"Não foi possível ler os dados da planilha. Erro: {e}")
        return pd.DataFrame()

def extrair_dados(image_file):
    """Extrai dados da imagem via OCR.Space + Cohere"""
    try:
        # 1) OCR
        url = "https://api.ocr.space/parse/image"
        files = {"file": image_file}
        payload = {"apikey": ocr_api_key, "language": "por"}

        ocr_response = requests.post(url, files=files, data=payload)
        ocr_response.raise_for_status()
        ocr_result = ocr_response.json()

        extracted_text = ocr_result["ParsedResults"][0]["ParsedText"]

        if not extracted_text.strip():
            st.error("OCR não conseguiu ler nada da imagem.")
            return None

        # 2) Cohere
        prompt = f"""
        Analise o seguinte texto de um formulário e extraia as informações:
        - ID Família
        - Nome Completo
        - Data de Nascimento (DD/MM/AAAA)
        - Telefone
        - CPF
        - Nome da Mãe
        - Nome do Pai
        - Sexo
        - CNS
        - Município de Nascimento

        Se um dado não for encontrado, retorne vazio.
        Retorne estritamente em formato JSON.

        Texto extraído:
        {extracted_text}
        """

        response = co.chat(model="command-r-plus", message=prompt)
        return json.loads(response.text.strip())

    except Exception as e:
        st.error(f"Erro ao extrair dados (OCR+IA). Erro: {e}")
        return None

def gerar_pdf(dados):
    """Gera um PDF com os dados e retorna em BytesIO"""
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.setFont("Helvetica", 12)

    y = 750
    c.drawString(50, y, "Ficha Individual - Coleta Inteligente")
    y -= 30

    for campo, valor in dados.items():
        c.drawString(50, y, f"{campo}: {valor}")
        y -= 20

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

# --- Páginas ---
def pagina_coleta(planilha):
    st.header("1. Envie a imagem da ficha")
    uploaded_file = st.file_uploader("Escolha uma imagem", type=['jpg', 'jpeg', 'png'], key="uploader_coleta")
    if 'dados_extraidos' not in st.session_state:
        st.session_state.dados_extraidos = None

    if uploaded_file is not None:
        st.image(uploaded_file, caption="Imagem Carregada.", use_container_width=True)
        if st.button("🔎 Extrair Dados da Imagem"):
            with st.spinner("Executando OCR e IA..."):
                st.session_state.dados_extraidos = extrair_dados(uploaded_file)
            if st.session_state.dados_extraidos:
                st.success("Dados extraídos!")
            else:
                st.error("Não foi possível extrair dados da imagem.")

    if st.session_state.dados_extraidos:
        st.markdown("---")
        st.header("2. Confirme e corrija os dados antes de enviar")
        with st.form("formulario_de_correcao"):
            dados = st.session_state.dados_extraidos
            id_familia = st.text_input("ID Família", value=dados.get("ID Família", ""))
            nome_completo = st.text_input("Nome Completo", value=dados.get("Nome Completo", ""))
            data_nascimento = st.text_input("Data de Nascimento", value=dados.get("Data de Nascimento", ""))
            telefone = st.text_input("Telefone", value=dados.get("Telefone", ""))
            cpf = st.text_input("CPF", value=dados.get("CPF", ""))
            nome_mae = st.text_input("Nome da Mãe", value=dados.get("Nome da Mãe", ""))
            nome_pai = st.text_input("Nome do Pai", value=dados.get("Nome do Pai", ""))
            sexo = st.text_input("Sexo", value=dados.get("Sexo", ""))
            cns = st.text_input("CNS", value=dados.get("CNS", ""))
            municipio_nascimento = st.text_input("Município de Nascimento", value=dados.get("Município de Nascimento", ""))

            submitted = st.form_submit_button("✅ Enviar para a Planilha")
            if submitted:
                with st.spinner("Enviando dados..."):
                    try:
                        timestamp_envio = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                        nova_linha = [id_familia, nome_completo, data_nascimento, telefone, cpf, nome_mae, nome_pai, sexo, cns, municipio_nascimento, timestamp_envio]
                        planilha.append_row(nova_linha)

                        # Monta dicionário para PDF
                        dados_pdf = {
                            "ID Família": id_familia,
                            "Nome Completo": nome_completo,
                            "Data de Nascimento": data_nascimento,
                            "Telefone": telefone,
                            "CPF": cpf,
                            "Nome da Mãe": nome_mae,
                            "Nome do Pai": nome_pai,
                            "Sexo": sexo,
                            "CNS": cns,
                            "Município de Nascimento": municipio_nascimento,
                            "Timestamp de Envio": timestamp_envio
                        }
                        pdf_buffer = gerar_pdf(dados_pdf)

                        st.success("🎉 Dados enviados com sucesso!")
                        st.download_button(
                            label="📄 Baixar Ficha em PDF",
                            data=pdf_buffer,
                            file_name=f"ficha_{id_familia or nome_completo}.pdf",
                            mime="application/pdf"
                        )
                        st.balloons()
                        st.session_state.dados_extraidos = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ocorreu um erro ao enviar os dados para a planilha. Erro: {e}")

def pagina_dashboard(planilha):
    st.header("📊 Dashboard")
    df = ler_dados_da_planilha(planilha)
    if not df.empty:
        st.subheader("Dados Coletados")
        st.dataframe(df, use_container_width=True)
    else:
        st.warning("Ainda não há dados na planilha para exibir.")

# --- Main ---
def main():
    planilha_conectada = conectar_planilha()
    st.sidebar.title("Navegação")
    paginas = {
        "Coletar Fichas por Imagem": pagina_coleta,
        "Dashboard": pagina_dashboard,
    }
    pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas.keys())
    paginas[pagina_selecionada](planilha_conectada)

if __name__ == "__main__":
    main()
