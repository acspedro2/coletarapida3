import streamlit as st
import gspread
import json
import os
import pandas as pd
import google.generativeai as genai
from io import BytesIO
from datetime import datetime
from PIL import Image

# --- Configuração da Página e Título ---
st.set_page_config(
    page_title="Coleta Inteligente",
    page_icon="🤖",
    layout="wide"
)

st.title("🤖 Coleta Inteligente")
st.markdown("---")

# --- CONEXÃO E VARIÁVEIS DE AMBIENTE ---
try:
    gemini_api_key = st.secrets["GEMINIKEY"]
    google_sheets_id = st.secrets["SHEETSID"]
    google_credentials_dict = st.secrets["gcp_service_account"]
except KeyError as e:
    st.error(f"Erro de configuração: A chave secreta '{e.args[0]}' não foi encontrada. Verifique o nome no painel de Secrets do Streamlit Cloud.")
    st.stop()
except Exception as e:
    st.error(f"Erro inesperado ao carregar as chaves secretas. Verifique a formatação no painel de Secrets. Erro: {e}")
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
        st.error(f"Não foi possível conectar à planilha. Verifique a ID, as permissões de partilha e o formato das credenciais. Erro: {e}")
        st.stop()

@st.cache_data(ttl=60)
def ler_dados_da_planilha(_planilha):
    """Lê todos os dados da planilha e retorna como DataFrame do Pandas."""
    try:
        dados = _planilha.get_all_records()
        df = pd.DataFrame(dados)
        # Garante que todas as colunas esperadas existam, preenchendo com vazio se necessário
        colunas_esperadas = ["ID Família", "Nome Completo", "Data de Nascimento", "Telefone", "CPF", "Nome da Mãe", "Nome do Pai", "Sexo", "CNS", "Município de Nascimento", "Timestamp de Envio"]
        for col in colunas_esperadas:
            if col not in df.columns:
                df[col] = ""
        return df
    except Exception as e:
        st.error(f"Não foi possível ler os dados da planilha para o dashboard. Erro: {e}")
        return pd.DataFrame()

def apagar_linha_por_timestamp(planilha, timestamp):
    """Encontra uma linha pelo timestamp e a apaga."""
    try:
        cell = planilha.find(timestamp)
        if cell:
            planilha.delete_rows(cell.row)
            return True
        return False
    except Exception as e:
        st.error(f"Ocorreu um erro ao tentar apagar a linha. Erro: {e}")
        return False
        
# --- NOVA FUNÇÃO PARA ATUALIZAR LINHA ---
def atualizar_linha(planilha, timestamp, novos_dados):
    """Encontra uma linha pelo timestamp e atualiza seus valores."""
    try:
        cell = planilha.find(timestamp)
        if cell:
            # gspread espera uma lista de valores para atualizar a linha
            # A ordem deve corresponder exatamente à ordem das colunas na planilha
            valores_atualizados = list(novos_dados.values())
            planilha.update(f'A{cell.row}:K{cell.row}', [valores_atualizados])
            return True
        return False
    except Exception as e:
        st.error(f"Ocorreu um erro ao tentar atualizar a linha. Erro: {e}")
        return False

def extrair_dados_com_gemini(image_bytes):
    try:
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel('gemini-1.5-pro-latest')
        image_bytes.seek(0)
        image = Image.open(image_bytes)
        prompt = "Analise esta imagem de um formulário e extraia as seguintes informações: ID Família, Nome Completo, Data de Nascimento (DD/MM/AAAA), Telefone, CPF, Nome da Mãe, Nome do Pai, Sexo, CNS, Município de Nascimento. Se um dado não for encontrado, retorne um campo vazio. Retorne os dados estritamente como um objeto JSON."
        response = model.generate_content([prompt, image])
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except Exception as e:
        st.error(f"Erro ao extrair dados com Gemini. Verifique a sua chave da API. Erro: {e}")
        return None

def validar_dados_com_gemini(dados_para_validar):
    try:
        model = genai.GenerativeModel('gemini-1.5-pro-latest')
        prompt_validacao = f'Você é um auditor de qualidade de dados de saúde do Brasil. Analise o seguinte JSON e verifique se há inconsistências óbvias (CPF, Data de Nascimento, CNS). Responda APENAS com um objeto JSON com uma chave "avisos" que é uma lista de strings em português com os problemas encontrados. Se não houver problemas, a lista deve ser vazia. Dados para validar: {json.dumps(dados_para_validar)}'
        response = model.generate_content(prompt_validacao)
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except Exception as e:
        print(f"Erro na validação com Gemini: {e}")
        return {"avisos": []}

def analisar_dados_com_gemini(pergunta_usuario, dataframe):
    if dataframe.empty:
        return "Não há dados na planilha para analisar."
    dados_string = dataframe.to_string()
    model = genai.GenerativeModel('gemini-1.5-pro-latest')
    prompt_analise = f'Você é um assistente de análise de dados. Sua tarefa é responder à pergunta do utilizador com base nos dados da tabela fornecida. Seja claro, direto e responda apenas com base nos dados. Pergunta do utilizador: "{pergunta_usuario}". Dados da Tabela:\n{dados_string}'
    try:
        response = model.generate_content(prompt_analise)
        return response.text
    except Exception as e:
        return f"Ocorreu um erro ao analisar os dados com a IA. Erro: {e}"

# --- INICIALIZAÇÃO ---
planilha_conectada = conectar_planilha()

# --- NAVEGAÇÃO E PÁGINAS ---
st.sidebar.title("Navegação")
pagina_selecionada = st.sidebar.radio("Escolha uma página:", ["Coletar Fichas", "Dashboard"])

# --- PÁGINA 1: COLETAR FICHAS ---
if pagina_selecionada == "Coletar Fichas":
    st.header("Envie a imagem da ficha")
    uploaded_file = st.file_uploader("Escolha uma imagem", type=['jpg', 'jpeg', 'png'])
    if 'dados_extraidos' not in st.session_state:
        st.session_state.dados_extraidos = None
    if uploaded_file is not None:
        st.image(uploaded_file, caption="Imagem Carregada.", use_container_width=True)
        if st.button("🔎 Extrair e Validar Dados"):
            with st.spinner("A IA está a analisar a imagem..."):
                st.session_state.dados_extraidos = extrair_dados_com_gemini(uploaded_file)
            if st.session_state.dados_extraidos:
                st.success("Dados extraídos!")
                with st.spinner("A IA está a verificar a qualidade dos dados..."):
                    resultado_validacao = validar_dados_com_gemini(st.session_state.dados_extraidos)
                if resultado_validacao and resultado_validacao.get("avisos"):
                    st.warning("Atenção! A IA encontrou os seguintes possíveis problemas:")
                    for aviso in resultado_validacao["avisos"]: st.write(f"- {aviso}")
            else:
                st.error("Não foi possível extrair dados da imagem.")
    if st.session_state.dados_extraidos:
        st.markdown("---")
        st.header("Confirme e corrija os dados antes de enviar")
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
                with st.spinner("A enviar os dados..."):
                    try:
                        timestamp_envio = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                        nova_linha = [id_familia, nome_completo, data_nascimento, telefone, cpf, nome_mae, nome_pai, sexo, cns, municipio_nascimento, timestamp_envio]
                        planilha_conectada.append_row(nova_linha)
                        st.success("🎉 Dados enviados para a planilha com sucesso!")
                        st.balloons()
                        st.session_state.dados_extraidos = None
                        st.experimental_rerun()
                    except Exception as e:
                        st.error(f"Ocorreu um erro ao enviar os dados para a planilha. Erro: {e}")

# --- PÁGINA 2: DASHBOARD (COM GESTÃO COMPLETA) ---
elif pagina_selecionada == "Dashboard":
    st.header("📊 Dashboard de Dados Coletados")
    df = ler_dados_da_planilha(planilha_conectada)
    
    if not df.empty:
        # (Seção de Métricas e Gráficos)
        st.subheader("Resumo Geral")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total de Fichas", len(df))
        try:
            fichas_masculinas = df[df['Sexo'].str.strip().str.upper() == 'MASCULINO'].shape[0]
            col2.metric("Pacientes Masculinos", fichas_masculinas)
            fichas_femininas = df[df['Sexo'].str.strip().str.upper() == 'FEMININO'].shape[0]
            col3.metric("Pacientes Femininos", fichas_femininas)
        except (KeyError, AttributeError):
            col2.metric("Pacientes Masculinos", "N/A"); col3.metric("Pacientes Femininos", "N/A")
        st.markdown("---")
        st.subheader("Fichas por Município de Nascimento")
        try:
            municipio_counts = df['Município de Nascimento'].value_counts()
            st.bar_chart(municipio_counts)
        except (KeyError, AttributeError):
            st.warning("A coluna 'Município de Nascimento' não foi encontrada ou está vazia.")

        # --- SEÇÃO DE GESTÃO DE REGISTOS (APAGAR E EDITAR) ---
        st.markdown("---")
        st.subheader("⚙️ Gerir Registos")
        
        aba_apagar, aba_editar = st.tabs(["Apagar Registo", "Editar Registo"])

        with aba_apagar:
            try:
                opcoes_apagar = [f"{nome} ({timestamp})" for nome, timestamp in zip(df['Nome Completo'], df['Timestamp de Envio'])]
                registo_para_apagar = st.selectbox("Selecione o registo a apagar:", options=opcoes_apagar, index=None, placeholder="Escolha um registo...")
                
                if st.button("Apagar Registo Selecionado"):
                    if registo_para_apagar:
                        st.session_state.confirmacao_apagar = registo_para_apagar
                
                if st.session_state.get('confirmacao_apagar') == registo_para_apagar and registo_para_apagar is not None:
                    st.warning(f"Tem a CERTEZA de que quer apagar o registo de **{registo_para_apagar.split(' (')[0]}**?")
                    if st.button("Sim, tenho a certeza. Apagar."):
                        with st.spinner("A apagar..."):
                            timestamp_selecionado = registo_para_apagar.split('(')[-1].replace(')', '')
                            if apagar_linha_por_timestamp(planilha_conectada, timestamp_selecionado):
                                st.success("Registo apagado com sucesso!")
                                st.cache_data.clear()
                                st.session_state.confirmacao_apagar = None
                                st.experimental_rerun()
            except (KeyError, AttributeError):
                st.error("As colunas 'Nome Completo' ou 'Timestamp de Envio' não foram encontradas na planilha.")

        with aba_editar:
            try:
                opcoes_editar = [f"{nome} ({timestamp})" for nome, timestamp in zip(df['Nome Completo'], df['Timestamp de Envio'])]
                registo_para_editar = st.selectbox("Selecione o registo a editar:", options=opcoes_editar, index=None, placeholder="Escolha um registo...", key="sb_editar")

                if registo_para_editar:
                    timestamp_selecionado = registo_para_editar.split('(')[-1].replace(')', '')
                    dados_atuais = df[df['Timestamp de Envio'] == timestamp_selecionado].iloc[0].to_dict()

                    with st.form("formulario_de_edicao"):
                        st.subheader(f"A editar: {dados_atuais['Nome Completo']}")
                        
                        id_familia_edit = st.text_input("ID Família", value=dados_atuais.get("ID Família", ""))
                        nome_completo_edit = st.text_input("Nome Completo", value=dados_atuais.get("Nome Completo", ""))
                        data_nascimento_edit = st.text_input("Data de Nascimento", value=dados_atuais.get("Data de Nascimento", ""))
                        telefone_edit = st.text_input("Telefone", value=dados_atuais.get("Telefone", ""))
                        cpf_edit = st.text_input("CPF", value=dados_atuais.get("CPF", ""))
                        nome_mae_edit = st.text_input("Nome da Mãe", value=dados_atuais.get("Nome da Mãe", ""))
                        nome_pai_edit = st.text_input("Nome do Pai", value=dados_atuais.get("Nome do Pai", ""))
                        sexo_edit = st.text_input("Sexo", value=dados_atuais.get("Sexo", ""))
                        cns_edit = st.text_input("CNS", value=dados_atuais.get("CNS", ""))
                        municipio_nascimento_edit = st.text_input("Município de Nascimento", value=dados_atuais.get("Município de Nascimento", ""))

                        submitted_edit = st.form_submit_button("Salvar Alterações")

                        if submitted_edit:
                            dados_atualizados = {
                                "ID Família": id_familia_edit, "Nome Completo": nome_completo_edit,
                                "Data de Nascimento": data_nascimento_edit, "Telefone": telefone_edit,
                                "CPF": cpf_edit, "Nome da Mãe": nome_mae_edit,
                                "Nome do Pai": nome_pai_edit, "Sexo": sexo_edit,
                                "CNS": cns_edit, "Município de Nascimento": municipio_nascimento_edit,
                                "Timestamp de Envio": timestamp_selecionado
                            }
                            with st.spinner("A salvar alterações..."):
                                if atualizar_linha(planilha_conectada, timestamp_selecionado, dados_atualizados):
                                    st.success("Registo atualizado com sucesso!")
                                    st.cache_data.clear()
                                    st.experimental_rerun()
            except (KeyError, AttributeError):
                st.error("As colunas 'Nome Completo' ou 'Timestamp de Envio' não foram encontradas na planilha.")


        # (Seção de Pesquisa e Dados)
        st.markdown("---")
        st.subheader("🤖 Converse com seus Dados")
        pergunta = st.text_area("Faça uma pergunta em português sobre os dados da planilha abaixo:")
        if st.button("Analisar com IA"):
            if pergunta:
                with st.spinner("A IA está a pensar..."):
                    resposta = analisar_dados_com_gemini(pergunta, df)
                    st.markdown(resposta)
            else:
                st.warning("Por favor, escreva uma pergunta.")
        
        st.markdown("---")
        st.subheader("Dados Completos")
        st.dataframe(df, use_container_width=True)
    else:
        st.warning("Ainda não há dados na planilha para exibir.")

