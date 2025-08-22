import streamlit as st
import requests
import json
import cohere
import gspread
from PIL import Image
import time
import re
import pandas as pd
from datetime import datetime

# --- Interface Streamlit ---
st.set_page_config(page_title="Coleta Inteligente", page_icon="🤖", layout="wide")
st.title("🤖 COLETA INTELIGENTE")

# --- Funções de Validação ---
def validar_cpf(cpf: str) -> bool:
    cpf = ''.join(re.findall(r'\d', str(cpf)))
    if not cpf or len(cpf) != 11 or cpf == cpf[0] * 11: return False
    try:
        soma = sum(int(cpf[i]) * (10 - i) for i in range(9)); d1 = (soma * 10 % 11) % 10
        if d1 != int(cpf[9]): return False
        soma = sum(int(cpf[i]) * (11 - i) for i in range(10)); d2 = (soma * 10 % 11) % 10
        if d2 != int(cpf[10]): return False
    except: return False
    return True

def validar_data_nascimento(data_str: str) -> (bool, str):
    try:
        data_obj = datetime.strptime(data_str, '%d/%m/%Y').date()
        if data_obj > datetime.now().date(): return False, "A data de nascimento está no futuro."
        return True, ""
    except ValueError: return False, "O formato da data deve ser DD/MM/AAAA."

# --- Funções de Conexão e API ---

@st.cache_resource
def conectar_planilha():
    try:
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
        sheet = client.open_by_key(st.secrets["SHEETSID"]).sheet1
        return sheet
    except Exception as e:
        st.error(f"Erro ao conectar com o Google Sheets: {e}"); return None

@st.cache_data(ttl=300) # Aumenta o cache para 5 minutos
def ler_dados_da_planilha(_planilha):
    try:
        dados = _planilha.get_all_records()
        df = pd.DataFrame(dados)
        colunas_esperadas = ["ID", "FAMÍLIA", "Nome Completo", "Data de Nascimento", "Telefone", "CPF", "Nome da Mãe", "Nome do Pai", "Sexo", "CNS", "Município de Nascimento"]
        for col in colunas_esperadas:
            if col not in df.columns: df[col] = ""
        df['Data de Nascimento DT'] = pd.to_datetime(df['Data de Nascimento'], format='%d/%m/%Y', errors='coerce')
        df['Idade'] = df['Data de Nascimento DT'].apply(lambda dt: calcular_idade(dt) if pd.notnull(dt) else 0)
        return df
    except Exception as e:
        st.error(f"Erro ao ler os dados da planilha: {e}"); return pd.DataFrame()

def calcular_idade(data_nasc):
    if pd.isna(data_nasc): return 0
    hoje = datetime.now()
    return hoje.year - data_nasc.year - ((hoje.month, hoje.day) < (data_nasc.month, data_nasc.day))

def ocr_space_api(file_bytes, ocr_api_key):
    try:
        url = "https://api.ocr.space/parse/image"
        payload = {"language": "por", "isOverlayRequired": False, "OCREngine": 2}
        files = {"file": ("ficha.jpg", file_bytes, "image/jpeg")}
        headers = {"apikey": ocr_api_key}
        response = requests.post(url, data=payload, files=files, headers=headers)
        response.raise_for_status()
        result = response.json()
        if result.get("IsErroredOnProcessing"): st.error(f"Erro no OCR: {result.get('ErrorMessage')}"); return None
        return result["ParsedResults"][0]["ParsedText"]
    except Exception as e:
        st.error(f"Erro inesperado no OCR: {e}"); return None

def extrair_dados_com_cohere(texto_extraido: str, cohere_client):
    try:
        prompt = f"""
        Sua tarefa é extrair informações de um texto de formulário de saúde e convertê-lo para um JSON.
        Instrução Crítica: Procure por uma anotação à mão que pareça um código de família (ex: 'FAM111'). Este código deve ir para a chave "FAMÍLIA".
        Retorne APENAS um objeto JSON com as chaves: 'ID', 'FAMÍLIA', 'Nome Completo', 'Data de Nascimento', 'Telefone', 'CPF', 'Nome da Mãe', 'Nome do Pai', 'Sexo', 'CNS', 'Município de Nascimento'.
        Se um valor não for encontrado, retorne uma string vazia "".
        Texto para analisar: --- {texto_extraido} ---
        """
        response = cohere_client.chat(model="command-r-plus", message=prompt, temperature=0.1)
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except Exception as e:
        st.error(f"Erro ao chamar a API do Cohere: {e}"); return None

def salvar_no_sheets(dados, planilha):
    try:
        cabecalhos = planilha.row_values(1)
        nova_linha = [dados.get(cabecalho, "") for cabecalho in cabecalhos]
        planilha.append_row(nova_linha)
        st.success(f"✅ Dados de '{dados.get('Nome Completo', 'Desconhecido')}' salvos com sucesso!")
        st.balloons()
    except Exception as e:
        st.error(f"Erro ao salvar na planilha: {e}")

# --- PÁGINAS DO APP ---

def pagina_coleta(planilha):
    st.header("1. Envie uma ou mais imagens de fichas")
    uploaded_files = st.file_uploader("Pode selecionar vários arquivos de uma vez", type=["jpg", "jpeg", "png"], accept_multiple_files=True)

    if 'processados' not in st.session_state:
        st.session_state.processados = []

    if uploaded_files:
        for uploaded_file in uploaded_files:
            if uploaded_file.file_id in st.session_state.processados:
                continue

            st.subheader(f"Processando Ficha: `{uploaded_file.name}`")
            st.image(Image.open(uploaded_file), width=400)
            
            file_bytes = uploaded_file.getvalue()
            with st.spinner("Lendo o texto (OCR)..."):
                texto_extraido = ocr_space_api(file_bytes, st.secrets["OCRSPACEKEY"])
            
            if texto_extraido:
                with st.spinner("Estruturando os dados (IA)..."):
                    dados_extraidos = extrair_dados_com_cohere(texto_extraido, st.session_state.co_client)
                
                if dados_extraidos:
                    with st.form(key=f"form_{uploaded_file.file_id}"):
                        st.subheader("2. Confirme e salve os dados")
                        
                        id_val = st.text_input("ID", value=dados_extraidos.get("ID", "")); familia_val = st.text_input("FAMÍLIA", value=dados_extraidos.get("FAMÍLIA", ""))
                        nome_completo = st.text_input("Nome Completo", value=dados_extraidos.get("Nome Completo", ""))
                        
                        data_nascimento = st.text_input("Data de Nascimento", value=dados_extraidos.get("Data de Nascimento", ""))
                        is_data_valida, erro_data = validar_data_nascimento(data_nascimento)
                        if not is_data_valida and data_nascimento: st.warning(f"⚠️ {erro_data}")
                        
                        cpf = st.text_input("CPF", value=dados_extraidos.get("CPF", ""))
                        if not validar_cpf(cpf) and cpf: st.warning("⚠️ O CPF parece ser inválido.")
                        
                        telefone = st.text_input("Telefone", value=dados_extraidos.get("Telefone", "")); nome_mae = st.text_input("Nome da Mãe", value=dados_extraidos.get("Nome da Mãe", "")); nome_pai = st.text_input("Nome do Pai", value=dados_extraidos.get("Nome do Pai", "")); sexo = st.text_input("Sexo", value=dados_extraidos.get("Sexo", "")); cns = st.text_input("CNS", value=dados_extraidos.get("CNS", "")); municipio_nascimento = st.text_input("Município de Nascimento", value=dados_extraidos.get("Município de Nascimento", ""))
                        
                        submitted = st.form_submit_button("✅ Salvar Dados Desta Ficha")
                        
                        if submitted:
                            dados_para_salvar = {
                                'ID': id_val, 'FAMÍLIA': familia_val, 'Nome Completo': nome_completo,
                                'Data de Nascimento': data_nascimento, 'Telefone': telefone, 'CPF': cpf,
                                'Nome da Mãe': nome_mae, 'Nome do Pai': nome_pai, 'Sexo': sexo, 'CNS': cns,
                                'Município de Nascimento': municipio_nascimento
                            }
                            salvar_no_sheets(dados_para_salvar, planilha)
                            st.session_state.processados.append(uploaded_file.file_id)
                            st.rerun()
            else: st.error("A IA não conseguiu extrair dados deste texto.")
            with st.spinner("Aguardando 20 segundos antes da próxima ficha..."): time.sleep(20)
            break
        else: st.error("Não foi possível extrair texto desta imagem.")
        break

# --- NOVA PÁGINA: DASHBOARD ---
def pagina_dashboard(planilha):
    st.header("📊 Dashboard de Dados")
    df = ler_dados_da_planilha(planilha)

    if df.empty:
        st.warning("Ainda não há dados na planilha para exibir.")
        return

    st.markdown("### Métricas Gerais")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total de Fichas", len(df))
    # Calcula idade média apenas para idades válidas (>0)
    idade_media = df[df['Idade'] > 0]['Idade'].mean()
    col2.metric("Idade Média", f"{idade_media:.1f} anos" if idade_media > 0 else "N/A")
    
    # Contagem por sexo
    sexo_counts = df['Sexo'].str.capitalize().value_counts()
    col3.metric("Sexo (Moda)", sexo_counts.index[0] if not sexo_counts.empty else "N/A")

    st.markdown("### Pacientes por Município")
    municipio_counts = df['Município de Nascimento'].value_counts()
    if not municipio_counts.empty:
        st.bar_chart(municipio_counts)
    else:
        st.info("Não há dados de município para exibir.")

    st.markdown("### Distribuição de Idades")
    idades_validas = df[df['Idade'] > 0]['Idade']
    if not idades_validas.empty:
        st.bar_chart(idades_validas.value_counts().sort_index())
    else:
        st.info("Não há dados de idade para exibir.")

# --- NOVA PÁGINA: PESQUISA ---
def pagina_pesquisa(planilha):
    st.header("🔎 Ferramenta de Pesquisa")
    df = ler_dados_da_planilha(planilha)

    if df.empty:
        st.warning("Ainda não há dados na planilha para pesquisar.")
        return

    colunas_pesquisaveis = ["Nome Completo", "CPF", "CNS", "Nome da Mãe"]
    coluna_selecionada = st.selectbox("Pesquisar em:", colunas_pesquisaveis)

    termo_pesquisa = st.text_input("Digite o termo que deseja procurar:")

    if termo_pesquisa:
        # Filtra o DataFrame, garantindo que a coluna é do tipo string e tratando valores nulos
        resultados = df[df[coluna_selecionada].astype(str).str.contains(termo_pesquisa, case=False, na=False)]
        st.markdown(f"**{len(resultados)}** resultado(s) encontrado(s):")
        st.dataframe(resultados)
    else:
        st.markdown("Todos os registos:")
        st.dataframe(df)

# --- LÓGICA PRINCIPAL DE EXECUÇÃO (com menu) ---
def main():
    try:
        st.session_state.co_client = cohere.Client(api_key=st.secrets["COHEREKEY"])
        planilha_conectada = conectar_planilha()
    except Exception as e:
        st.error(f"Não foi possível inicializar os serviços. Verifique seus segredos. Erro: {e}")
        st.stop()
    
    st.sidebar.title("Navegação")
    paginas = {
        "Coletar Fichas": pagina_coleta,
        "Dashboard": pagina_dashboard,
        "Pesquisar Paciente": pagina_pesquisa,
    }
    pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas.keys())
    
    if planilha_conectada is not None:
        paginas[pagina_selecionada](planilha_conectada)
    else:
        st.error("A conexão com a planilha falhou. Não é possível carregar a página.")

if __name__ == "__main__":
    main()

