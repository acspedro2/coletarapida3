import streamlit as st
import gspread
import pandas as pd
import cohere # Nova biblioteca de IA
from io import BytesIO
from datetime import datetime
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import simpleSplit

# --- Configuração da Página e Título ---
st.set_page_config(page_title="Coleta Inteligente", page_icon="🤖", layout="wide")
st.title("🤖 Coleta Inteligente")

# --- CONEXÃO E VARIÁVEIS DE AMBIENTE ---
try:
    # Pega a chave do Cohere dos segredos
    cohere_api_key = st.secrets["COHEREKEY"]
    co = cohere.Client(cohere_api_key)

    google_sheets_id = st.secrets["SHEETSID"]
    google_credentials_dict = st.secrets["gcp_service_account"]

except KeyError as e:
    st.error(f"Erro de configuração: A chave secreta '{e.args[0]}' não foi encontrada. Verifique os seus segredos no Streamlit Cloud.")
    st.stop()
except Exception as e:
    st.error(f"Erro inesperado ao carregar as chaves secretas. Erro: {e}")
    st.stop()

# --- FUNÇÕES ---

@st.cache_resource
def conectar_planilha():
    """Conecta com o Google Sheets usando as credenciais."""
    try:
        gc = gspread.service_account_from_dict(google_credentials_dict)
        planilha = gc.open_by_key(google_sheets_id).sheet1
        return planilha
    except Exception as e:
        st.error(f"Não foi possível conectar à planilha. Erro: {e}")
        st.stop()

def calcular_idade(data_nasc):
    """Calcula a idade a partir de um objeto datetime."""
    if pd.isna(data_nasc): return 0
    hoje = datetime.now()
    return hoje.year - data_nasc.year - ((hoje.month, hoje.day) < (data_nasc.month, data_nasc.day))

@st.cache_data(ttl=60)
def ler_dados_da_planilha(_planilha):
    """Lê os dados, garante colunas e calcula a idade."""
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

# --- FUNÇÃO DE IA ATUALIZADA PARA USAR COHERE ---
def analisar_dados_com_cohere(pergunta_usuario, dataframe):
    """Usa o Cohere para responder perguntas sobre os dados da planilha."""
    try:
        if dataframe.empty:
            return "Não há dados na planilha para analisar."

        dados_string = dataframe.to_string()

        preamble = f"""
        Você é um assistente de análise de dados. Sua tarefa é responder à pergunta do utilizador com base nos dados da tabela fornecida.
        Seja claro, direto e responda apenas com base nos dados. A data de hoje é {datetime.now().strftime('%d/%m/%Y')}.
        Dados da Tabela:
        {dados_string}
        """

        response = co.chat(
            message=pergunta_usuario,
            preamble=preamble
        )
        return response.text
    except Exception as e:
        return f"Ocorreu um erro ao analisar os dados com a IA (Cohere). Erro: {e}"

# --- PÁGINAS DO APP ---

def pagina_coleta_manual(planilha):
    st.header("1. Coleta Manual de Ficha")
    st.info("A extração de dados por imagem foi temporariamente desativada. Por favor, insira os dados manualmente.")

    with st.form("formulario_manual"):
        id_familia = st.text_input("ID Família"); nome_completo = st.text_input("Nome Completo"); data_nascimento = st.text_input("Data de Nascimento (DD/MM/AAAA)"); telefone = st.text_input("Telefone"); cpf = st.text_input("CPF"); nome_mae = st.text_input("Nome da Mãe"); nome_pai = st.text_input("Nome do Pai"); sexo = st.selectbox("Sexo", ["Masculino", "Feminino", "Outro"]); cns = st.text_input("CNS"); municipio_nascimento = st.text_input("Município de Nascimento")

        submitted = st.form_submit_button("✅ Enviar para a Planilha")
        if submitted:
            with st.spinner("A enviar os dados..."):
                try:
                    timestamp_envio = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                    nova_linha = [id_familia, nome_completo, data_nascimento, telefone, cpf, nome_mae, nome_pai, sexo, cns, municipio_nascimento, timestamp_envio]
                    planilha.append_row(nova_linha)
                    st.success("🎉 Dados enviados para a planilha com sucesso!"); st.balloons()
                    st.rerun()
                except Exception as e:
                    st.error(f"Ocorreu um erro ao enviar os dados para a planilha. Erro: {e}")

def pagina_dashboard(planilha):
    st.header("📊 Dashboard de Dados Coletados")
    df = ler_dados_da_planilha(planilha)

    if not df.empty:
        st.subheader("🤖 Converse com seus Dados (usando a IA da Cohere)")
        pergunta = st.text_area("Faça uma pergunta em português sobre os dados da planilha:")
        if st.button("Analisar com IA"):
            if pergunta:
                with st.spinner("A IA está a pensar..."):
                    resposta = analisar_dados_com_cohere(pergunta, df)
                    st.markdown(resposta)
            else:
                st.warning("Por favor, escreva uma pergunta.")

        st.markdown("---")
        st.subheader("Dados Completos")
        st.dataframe(df, use_container_width=True)
    else:
        st.warning("Ainda não há dados na planilha para exibir.")

# --- LÓGICA PRINCIPAL DE EXECUÇÃO ---
def main():
    """Função principal que organiza e executa o aplicativo."""
    planilha_conectada = conectar_planilha()
    st.sidebar.title("Navegação")
    paginas = {
        "Coletar Fichas (Manual)": pagina_coleta_manual,
        "Dashboard e Análise IA": pagina_dashboard,
    }
    pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas.keys())
    paginas[pagina_selecionada](planilha_conectada)

if __name__ == "__main__":
    main()
