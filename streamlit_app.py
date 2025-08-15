import streamlit as st
import gspread
import json
import os
import pandas as pd
import google.generativeai as genai
from io import BytesIO
from datetime import datetime
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch

# --- Configuração da Página e Título ---
st.set_page_config(
    page_title="Coleta Inteligente",
    page_icon="🤖",
    layout="wide"
)

st.title("🤖 Coleta Inteligente")

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

def calcular_idade(data_nasc):
    """Calcula a idade a partir de um objeto datetime."""
    if pd.isna(data_nasc):
        return 0
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
            if col not in df.columns:
                df[col] = ""
        
        df['Data de Nascimento DT'] = pd.to_datetime(df['Data de Nascimento'], format='%d/%m/%Y', errors='coerce')
        df['Idade'] = df['Data de Nascimento DT'].apply(lambda dt: calcular_idade(dt) if pd.notnull(dt) else 0)
        
        return df
    except Exception as e:
        st.error(f"Não foi possível ler os dados da planilha. Erro: {e}")
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

def atualizar_linha(planilha, timestamp, novos_dados):
    """Encontra uma linha pelo timestamp e atualiza seus valores."""
    try:
        cell = planilha.find(timestamp)
        if cell:
            valores_atualizados = list(novos_dados.values())
            range_to_update = f'A{cell.row}:{chr(ord("A") + len(valores_atualizados) - 1)}{cell.row}'
            planilha.update(range_to_update, [valores_atualizados])
            return True
        return False
    except Exception as e:
        st.error(f"Ocorreu um erro ao tentar atualizar a linha. Erro: {e}")
        return False

def extrair_dados_com_gemini(image_bytes):
    """Extrai dados da imagem usando a API do Google Gemini."""
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
    """Envia os dados extraídos para o Gemini para uma verificação de qualidade."""
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
    """Usa o Gemini para responder perguntas sobre os dados da planilha."""
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
        
def gerar_pdf_relatorio(dataframe, titulo):
    """Gera um PDF a partir de um DataFrame do Pandas."""
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    margin = 0.75 * inch
    y = height - margin
    p.setFont("Helvetica-Bold", 16)
    p.drawString(margin, y, titulo)
    y -= 0.5 * inch
    if dataframe.empty:
        p.setFont("Helvetica", 12)
        p.drawString(margin, y, "Nenhum dado encontrado para os filtros selecionados.")
    else:
        p.setFont("Helvetica-Bold", 8)
        colunas = dataframe.columns.tolist()
        col_widths = [(width - 2 * margin) / len(colunas)] * len(colunas)
        x = margin
        for i, header in enumerate(colunas):
            p.drawString(x, y, str(header))
            x += col_widths[i]
        y -= 0.25 * inch
        p.setFont("Helvetica", 7)
        for index, row in dataframe.iterrows():
            if y < margin:
                p.showPage()
                p.setFont("Helvetica", 7)
                y = height - margin
            x = margin
            for i, value in enumerate(row):
                p.drawString(x, y, str(value)[:30]) # Limita o texto
                x += col_widths[i]
            y -= 0.2 * inch
            
    p.save()
    buffer.seek(0)
    return buffer

def gerar_pdf_ivcf20_completo(paciente):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    margin = 0.75 * inch
    
    # (Código completo para desenhar o PDF do IVCF-20)
    # ...

    p.save()
    buffer.seek(0)
    return buffer

# --- ESTRUTURA DAS PÁGINAS DO APP ---

def pagina_coleta(planilha):
    st.header("1. Envie a imagem da ficha")
    uploaded_file = st.file_uploader("Escolha uma imagem", type=['jpg', 'jpeg', 'png'], key="uploader_coleta")
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
        st.header("2. Confirme e corrija os dados antes de enviar")
        with st.form("formulario_de_correcao"):
            dados = st.session_state.dados_extraidos
            id_familia = st.text_input("ID Família", value=dados.get("ID Família", "")); nome_completo = st.text_input("Nome Completo", value=dados.get("Nome Completo", "")); data_nascimento = st.text_input("Data de Nascimento", value=dados.get("Data de Nascimento", "")); telefone = st.text_input("Telefone", value=dados.get("Telefone", "")); cpf = st.text_input("CPF", value=dados.get("CPF", "")); nome_mae = st.text_input("Nome da Mãe", value=dados.get("Nome da Mãe", "")); nome_pai = st.text_input("Nome do Pai", value=dados.get("Nome do Pai", "")); sexo = st.text_input("Sexo", value=dados.get("Sexo", "")); cns = st.text_input("CNS", value=dados.get("CNS", "")); municipio_nascimento = st.text_input("Município de Nascimento", value=dados.get("Município de Nascimento", ""))
            submitted = st.form_submit_button("✅ Enviar para a Planilha")
            if submitted:
                with st.spinner("A enviar os dados..."):
                    try:
                        timestamp_envio = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                        nova_linha = [id_familia, nome_completo, data_nascimento, telefone, cpf, nome_mae, nome_pai, sexo, cns, municipio_nascimento, timestamp_envio]
                        planilha_conectada.append_row(nova_linha)
                        st.success("🎉 Dados enviados para a planilha com sucesso!"); st.balloons()
                        st.session_state.dados_extraidos = None
                        st.experimental_rerun()
                    except Exception as e:
                        st.error(f"Ocorreu um erro ao enviar os dados para a planilha. Erro: {e}")

def pagina_dashboard(planilha):
    st.header("📊 Dashboard de Dados Coletados")
    df = ler_dados_da_planilha(planilha)
    if not df.empty:
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

        st.markdown("---")
        st.subheader("⚙️ Gerir Registos")
        aba_apagar, aba_editar = st.tabs(["Apagar Registo", "Editar Registo"])
        with aba_apagar:
            # (Código para apagar)
            pass
        with aba_editar:
            # (Código para editar)
            pass

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
        st.subheader("Dados Completos e Exportação")
        st.dataframe(df, use_container_width=True)
        @st.cache_data
        def converter_df_para_csv(dataframe):
            return dataframe.to_csv(index=False).encode('utf-8')
        csv = converter_df_para_csv(df)
        st.download_button(label="Descarregar tabela como CSV", data=csv, file_name='dados_coleta_inteligente.csv', mime='text/csv')
    else:
        st.warning("Ainda não há dados na planilha para exibir.")

def pagina_relatorios(planilha):
    st.header("📄 Gerador de Relatórios Personalizados")
    df_completo = ler_dados_da_planilha(planilha)
    if not df_completo.empty:
        df_filtrado = df_completo.copy()
        st.subheader("1. Filtre os Pacientes")
        col1, col2, col3 = st.columns(3)
        with col1:
            idade_min = st.number_input("Idade maior que:", min_value=0, max_value=120, value=0)
            if idade_min > 0:
                df_filtrado = df_filtrado[df_filtrado['Idade'] > idade_min]
        with col2:
            sexos = ["Todos"] + df_filtrado['Sexo'].unique().tolist()
            sexo_selecionado = st.selectbox("Filtrar por Sexo:", sexos)
            if sexo_selecionado != "Todos":
                df_filtrado = df_filtrado[df_filtrado['Sexo'] == sexo_selecionado]
        with col3:
            municipios = ["Todos"] + df_filtrado['Município de Nascimento'].unique().tolist()
            municipio_selecionado = st.selectbox("Filtrar por Município:", municipios)
            if municipio_selecionado != "Todos":
                df_filtrado = df_filtrado[df_filtrado['Município de Nascimento'] == municipio_selecionado]
        st.markdown("---")
        st.subheader("2. Selecione as Colunas para o Relatório")
        todas_as_colunas = df_completo.columns.tolist()
        if 'Data de Nascimento DT' in todas_as_colunas:
            todas_as_colunas.remove('Data de Nascimento DT')
        colunas_selecionadas = st.multiselect("Escolha as informações que deseja incluir:", options=todas_as_colunas, default=["Nome Completo", "CPF", "Telefone"])
        st.markdown("---")
        st.subheader("3. Visualize e Descarregue o Relatório")
        if not colunas_selecionadas:
            st.warning("Por favor, selecione pelo menos uma coluna para gerar o relatório.")
        else:
            df_relatorio = df_filtrado[colunas_selecionadas]
            st.write(f"**Pré-visualização do Relatório ({len(df_relatorio)} registos):**")
            st.dataframe(df_relatorio, use_container_width=True)
            pdf_buffer = gerar_pdf_relatorio(df_relatorio, "Relatório de Pacientes")
            st.download_button(label="Descarregar Relatório em PDF", data=pdf_buffer, file_name=f"relatorio_pacientes_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf")
    else:
        st.warning("Não há dados na planilha para gerar relatórios.")

def pagina_ficha_ivcf20(planilha):
    st.header("📝 Gerar Ficha de Vulnerabilidade (IVCF-20)")
    df_completo = ler_dados_da_planilha(planilha)
    df_idosos = df_completo[df_completo['Idade'] >= 60].copy()
    if not df_idosos.empty:
        lista_pacientes = df_idosos['Nome Completo'].tolist()
        paciente_selecionado_nome = st.selectbox("Selecione um paciente:", options=lista_pacientes, index=None, placeholder="Escolha um paciente...")
        if paciente_selecionado_nome:
            dados_paciente = df_idosos[df_idosos['Nome Completo'] == paciente_selecionado_nome].iloc[0].to_dict()
            st.write(f"A gerar ficha para: **{dados_paciente['Nome Completo']}**")
            pdf_ficha = gerar_pdf_ivcf20_completo(dados_paciente)
            st.download_button(label="Descarregar Ficha IVCF-20 Completa em PDF", data=pdf_ficha, file_name=f"IVCF20_{paciente_selecionado_nome.replace(' ', '_')}.pdf", mime="application/pdf")
    else:
        st.warning("Não foram encontrados registos de pacientes com 60 anos ou mais.")

# --- LÓGICA PRINCIPAL DE EXECUÇÃO ---
def main():
    """Função principal que organiza e executa o aplicativo."""
    planilha_conectada = conectar_planilha()
    st.sidebar.title("Navegação")
    paginas = {
        "Coletar Fichas": pagina_coleta,
        "Dashboard": pagina_dashboard,
        "Gerar Relatórios": pagina_relatorios,
        "Gerar Ficha IVCF-20": pagina_ficha_ivcf20
    }
    pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas.keys())
    # Executa a função da página selecionada, passando a conexão da planilha
    paginas[pagina_selecionada](planilha_conectada)

if __name__ == "__main__":
    main()
