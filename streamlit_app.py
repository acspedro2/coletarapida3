import streamlit as st
import pandas as pd
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import re
import json
import time
from google import genai
import urllib.parse
from io import BytesIO

# --- CONFIGURAÇÃO GLOBAL ---
MODELO_GEMINI = "gemini-2.5-flash"
API_KEY = st.secrets.get("GOOGLE_API_KEY", "CHAVE_NAO_CONFIGURADA")

# --- MOCKS E SIMULAÇÕES (Substituem bibliotecas externas e Sheets) ---

# Mock do Google Sheets e Dados
planilha_mock_data = {
    'ID': [1, 2, 3, 4],
    'FAMÍLIA': ['SANTOS123', 'ALMEIDA456', 'SOUZA789', 'GOMES101'],
    'Nome Completo': ['Maria da Silva Santos', 'João Almeida Junior', 'Carlos Souza', 'Ana Gomes (Criança)'],
    'Data de Nascimento': ['10/03/1965', '20/11/2000', '25/07/1990', '01/05/2023'],
    'Telefone': ['11987654321', '21912345678', '31998765432', '11987654321'],
    'CPF': ['12345678900', '', '98765432100', ''],
    'Mãe': ['Joana Santos', 'Rita Almeida', 'Helena Souza', 'Maria da Silva Santos'],
    'Pai': ['Pedro Santos', 'Jorge Almeida', '', 'João Gomes'],
    'Sexo': ['F', 'M', 'M', 'F'],
    'CNS': ['', '111111111111111', '', ''],
    'Município de Nascimento': ['São Paulo', 'Rio de Janeiro', 'Belo Horizonte', 'São Paulo'],
    'Link do Prontuário': ['-','-','-','-'],
    'Link da Pasta da Família': ['-','-','-','-'],
    'Condição': ['Diabetes tipo 2 | Hipertensão', 'Saudável', 'Asma leve', 'Saudável'],
    'Data de Registo': ['01/01/2024 10:00:00', '01/01/2024 10:05:00', '01/01/2024 10:10:00', '01/01/2024 10:15:00'],
    'Raça/Cor': ['Parda', 'Branca', 'Parda', 'Branca'],
    'Medicamentos': ['Metformina | Losartana', 'Nenhum', 'Salbutamol (SOS)', 'Nenhum'],
    'Risco Clínico': ['ALTO', 'BAIXO', 'MÉDIO', 'BAIXO'],
    'Última Consulta': ['01/09/2025', '15/10/2025', '20/05/2024', '15/09/2025'],
    'Médico Responsável': ['Dr. Silva (Cardiologista)', 'Dra. Ana (Clínica)', 'Dr. Gomes (Clínico)', 'Dra. Ana (Pediatra)'],
}
df_mock = pd.DataFrame(planilha_mock_data)

@st.cache_resource
def conectar_planilha():
    """Simula a conexão com o Google Sheets."""
    return True

@st.cache_data(ttl=300)
def ler_dados_da_planilha(_planilha):
    """Simula a leitura dos dados, adicionando colunas calculadas."""
    df = df_mock.copy()
    
    def calcular_idade(data_nasc_str):
        try:
            data_nasc = datetime.strptime(data_nasc_str, '%d/%m/%Y').date()
            hoje = date.today()
            return hoje.year - data_nasc.year - ((hoje.month, hoje.day) < (data_nasc.month, data_nasc.day))
        except:
            return 0
    
    df['Data de Nascimento DT'] = pd.to_datetime(df['Data de Nascimento'], format='%d/%m/%Y', errors='coerce')
    df['Idade'] = df['Data de Nascimento'].apply(calcular_idade)
    df['CPF_LIMPO'] = df['CPF'].str.replace(r'\D', '', regex=True)
    df['CNS_LIMPO'] = df['CNS'].str.replace(r'\D', '', regex=True)
    df['Telefone Limpo'] = df['Telefone'].str.replace(r'\D', '', regex=True).str.replace('^55', '', regex=True)
    return df

def salvar_no_sheets(dados, planilha, row_index=None):
    """MOCK: Simula a gravação/atualização na planilha."""
    st.success(f"MOCK: Dados de '{dados.get('Nome Completo', 'Desconhecido')}' {'atualizados na linha ' + str(row_index) if row_index else 'salvos como novo registo'}!")
    return True

def buscar_paciente_similar(df_existente, nome_novo, data_nasc_nova):
    """MOCK: Simula a busca de duplicidade (apenas Maria da Silva tem duplicado simulado)."""
    if nome_novo.upper() == "MARIA DA SILVA SANTOS" and data_nasc_nova == "10/03/1965":
        return 2, df_existente.iloc[0] # Simula que encontrou Maria (índice 0 -> linha 2)
    return None, None

def ocr_space_api(file_bytes, ocr_api_key):
    """MOCK: Simula a chamada OCR, retornando texto pré-definido."""
    return """
    FICHA CADASTRAL
    Nome Completo: Ana Beatriz Ferreira
    Data de Nascimento: 15/08/2024
    Mãe: Maria de Fátima Ferreira
    Pai: João Ferreira
    CPF: 000.111.222-33
    CNS: 987654321987654
    Telefone: (31) 99999-0000
    Município: Contagem
    Sexo: F
    FAMÍLIA: FERREIRA0000
    """

def ler_texto_prontuario(file_bytes, ocr_api_key):
    """MOCK: Simula a leitura do PDF."""
    return """
    PRONTUÁRIO MÉDICO - 01/09/2025
    Paciente: Maria da Silva Santos. 60 anos.
    Diagnóstico Principal: Diabetes Mellitus tipo 2. HAS (Hipertensão Arterial Sistêmica)
    Histórico: Paciente com aderência parcial ao tratamento. Glicemia elevada na última medição (250 mg/dL).
    Medicação em uso: Metformina 850mg 2x/dia, Losartana 50mg 1x/dia. Necessita de acompanhamento nutricional urgente.
    Profissional: Dr. Silvio Santos (CRM 123456).
    """

# --- VALIDAÇÕES E UTILS (Mantidas) ---
def limpar_documento(doc):
    return re.sub(r'\D', '', str(doc)) if pd.notna(doc) else ""
def validar_cpf(cpf: str) -> bool:
    cpf = limpar_documento(cpf); return len(cpf) == 11 and cpf != cpf[0] * 11
def validar_cns(cns: str) -> bool:
    cns = limpar_documento(cns); return len(cns) == 15 and cns[0] in ('1', '2', '7', '8', '9')
def validar_data_nascimento(data_str: str) -> (bool, str):
    try:
        data_obj = datetime.strptime(data_str, '%d/%m/%Y').date()
        if data_obj > datetime.now().date(): return False, "Data no futuro."
        return True, ""
    except ValueError: return False, "Formato inválido."
def padronizar_telefone(telefone):
    num_limpo = re.sub(r'\D', '', str(telefone)); return num_limpo[2:] if num_limpo.startswith('55') else num_limpo if 10 <= len(num_limpo) <= 11 else None

# --- MOTOR DE REGRAS: CALENDÁRIO VACINAL (Apenas a estrutura) ---
CALENDARIO_PNI = [
    {"vacina": "BCG", "dose": "Dose Única", "idade_meses": 0, "detalhe": ""},
    {"vacina": "Pentavalente", "dose": "1ª Dose", "idade_meses": 2, "detalhe": ""},
    {"vacina": "Influenza", "dose": "Dose Anual", "idade_meses": 720, "detalhe": ""}, # Idoso > 60 anos
]

def analisar_carteira_vacinacao(data_nascimento_str, vacinas_administradas):
    """MOCK: Simula a análise vacinal para o paciente "Ana Gomes" (criança)."""
    try:
        data_nascimento = datetime.strptime(data_nascimento_str, "%d/%m/%Y")
    except: return {"erro": "Formato da data de nascimento inválido."}
    
    idade = relativedelta(datetime.now(), data_nascimento)
    idade_total_meses = idade.years * 12 + idade.months
    
    relatorio = {"em_dia": [], "em_atraso": [], "proximas_doses": []}

    # Lógica de Mock para o paciente Ana Gomes (Criança de 1 ano e 5 meses, 17 meses)
    if idade_total_meses < 30 and "Ana Gomes (Criança)" in st.session_state.get('paciente_selecionado_nome', ''):
        if idade_total_meses >= 2:
            # Simula atraso na Pentavalente (2 meses)
            relatorio["em_atraso"].append(CALENDARIO_PNI[1])
        relatorio["em_dia"].append(CALENDARIO_PNI[0]) # BCG em dia
        
    return relatorio

# --- FUNÇÕES COM GOOGLE GEMINI (NÍVEIS 3.0 e 4.0) ---

@st.cache_data(ttl=3600)
def extrair_dados_com_google_gemini(texto_extraido: str, api_key: str):
    """NÍVEL 3.0: Extrai dados cadastrais de um texto (ficha) com foco na qualidade."""
    # O corpo real da IA foi removido e substituído por um MOCK para garantir a execução
    try:
        dados = json.loads("""
            {
                "ID": "", 
                "FAMÍLIA": "FERREIRA0000", 
                "Nome Completo": "ANA BEATRIZ FERREIRA", 
                "Data de Nascimento": "15/08/2024", 
                "Telefone": "31999990000", 
                "CPF": "00011122233", 
                "Nome da Mãe": "Maria de Fátima Ferreira", 
                "Nome do Pai": "João Ferreira", 
                "Sexo": "F", 
                "CNS": "987654321987654", 
                "Município de Nascimento": "Contagem"
            }
        """)
        return dados
    except Exception as e: return None

@st.cache_data(ttl=3600)
def extrair_dados_clinicos_com_google_gemini(texto_prontuario: str, api_key: str):
    """NÍVEL 3.0: Extrai diagnósticos, medicamentos, data e médico do prontuário."""
    # O corpo real da IA foi removido e substituído por um MOCK para garantir a execução
    try:
        dados_extraidos = json.loads("""
            {
                "diagnosticos": ["Diabetes Mellitus tipo 2", "Hipertensão Arterial Sistêmica"],
                "medicamentos": ["Metformina 850mg 2x/dia", "Losartana 50mg 1x/dia"],
                "data_ultima_consulta": "01/09/2025",
                "medico_responsavel": "Dr. Silvio Santos"
            }
        """)
        return dados_extraidos
    except Exception as e: return None

@st.cache_data(ttl=3600)
def calcular_risco_clinico_com_gemini(diagnosticos: list, idade: int, api_key: str):
    """MOCK: Simula a função de classificação de risco."""
    if "Diabetes" in diagnosticos or idade >= 60: return "ALTO"
    if "Asma" in diagnosticos: return "MÉDIO"
    return "BAIXO"

@st.cache_data(ttl=3600)
def sugerir_proxima_acao_acs_com_gemini(risco: str, condicoes: str, idade: int, vacinas_atraso: list, api_key: str):
    """NÍVEL 3.0: Sugere a próxima ação prioritária para o ACS."""
    if vacinas_atraso:
        vacina = vacinas_atraso[0]['vacina']
        return f"Realizar BUSCA ATIVA (Vacina: {vacina}) para evitar a perda do calendário vacinal."
    if risco == 'ALTO' and idade >= 60:
        return "Realizar VISITA DOMICILIAR para checagem de pressão arterial e reforço da adesão medicamentosa."
    if risco == 'MÉDIO':
        return "Ligar para AGENDAR CONSULTA DE ROTINA para reavaliação anual e controle de Asma."
    return "Nenhuma ação urgente. Monitorar através de contato telefônico."

@st.cache_data(ttl=3600)
def gerar_resumo_narrativo_prontuario(dados_paciente: dict, relatorio_vacinal: dict, api_key: str):
    """NÍVEL 4.0: Usa Gemini para gerar um resumo narrativo para o profissional de saúde."""
    
    if not api_key or api_key == "CHAVE_NAO_CONFIGURADA":
        return "Erro de Configuração: API Key não está disponível. Não é possível chamar o Gemini para o resumo."
        
    try:
        genai.configure(api_key=api_key)
        
        condicoes = dados_paciente.get('Condição', 'Nenhuma registrada')
        medicamentos = dados_paciente.get('Medicamentos', 'Nenhum em uso')
        risco = dados_paciente.get('Risco Clínico', 'Não classificado')
        ultima_consulta = dados_paciente.get('Última Consulta', 'Desconhecida')
        medico_resp = dados_paciente.get('Médico Responsável', 'Não atribuído')
        
        vacinas_atraso = relatorio_vacinal.get("em_atraso", [])
        vacinas_atraso_str = ", ".join([f"{v['vacina']} ({v['dose']})" for v in vacinas_atraso]) if vacinas_atraso else "Nenhum atraso."
        
        acao_prioritaria = sugerir_proxima_acao_acs_com_gemini(
            risco=risco,
            condicoes=condicoes,
            idade=dados_paciente.get('Idade', 0),
            vacinas_atraso=vacinas_atraso,
            api_key=api_key
        )

        prompt = f"""
        Você é um Assistente de Saúde Pública. Sua tarefa é gerar um Relatório Narrativo do Prontuário, focado na próxima ação (Plano de Ação) para o Agente Comunitário de Saúde (ACS).

        Com base nos dados a seguir, crie um relatório curto, profissional e informativo, organizado em três secções. Não use listas, apenas texto corrido em cada seção:

        1. **Resumo Clínico e Risco:** (Máx. 3 linhas). Sintetize as condições, os medicamentos principais e a classificação de risco.
        2. **Status Vacinal:** (Máx. 2 linhas). Relate o atraso vacinal (se houver) e o status geral.
        3. **Plano de Ação ACS (Prioridade):** (Mantenha a ação do ACS sugerida). Use a frase da 'Ação Sugerida' e justifique a necessidade.

        Dados do Paciente:
        - Nome: {dados_paciente.get('Nome Completo', 'Paciente Desconhecido')}
        - Idade: {dados_paciente.get('Idade', 0)} anos
        - Condições: {condicoes}
        - Medicamentos: {medicamentos}
        - Última Consulta: {ultima_consulta} (Médico: {medico_resp})
        - Risco Clínico: {risco}
        - Vacinas em Atraso: {vacinas_atraso_str}
        - Ação Sugerida pelo Sistema: {acao_prioritaria}

        Retorne o resumo estritamente no formato de texto corrido, utilizando os títulos das secções em **negrito**.
        """
        model = genai.GenerativeModel(MODELO_GEMINI)
        response = model.generate_content(prompt)
        return response.text.strip()
        
    except Exception as e:
        return f"Erro ao gerar resumo narrativo com Gemini: {e}. Verifique se a API Key está correta."

# --- PÁGINAS DO APP ---

def pagina_inicial():
    st.title("Sistema de Gestão de Saúde Pública 4.0 (Proativo)")
    st.markdown("""
        Bem-vindo ao sistema de gestão que utiliza Inteligência Artificial para otimizar a Atenção Primária à Saúde (APS).
        
        **Nível Atual (4.0):**
        * **Coleta Inteligente:** Extração e validação de dados cadastrais (OCR + IA).
        * **Gestão de Duplicidade:** Busca por similaridade antes de salvar um novo registo.
        * **Enriquecimento Clínico:** Extração de Diagnósticos, Medicamentos, Última Consulta e Médico Responsável de prontuários em PDF (OCR + IA).
        * **Proatividade (Novo):** Geração automática de Resumo Narrativo e Plano de Ação Prioritário para o Agente Comunitário de Saúde (ACS).
        
        Navegue no menu lateral para acessar as funcionalidades.
    """)
    if API_KEY == "CHAVE_NAO_CONFIGURADA":
        st.error("⚠️ Configure a sua `GOOGLE_API_KEY` nos secrets do Streamlit para usar as funcionalidades de IA.")

def pagina_coleta(planilha):
    st.title("🤖 COLETA INTELIGENTE (Nível 3.0)")
    st.header("1. Envie uma imagem de ficha para extração e gestão de duplicidade")
    
    df_existente = ler_dados_da_planilha(planilha)
    uploaded_file = st.file_uploader("Envie uma imagem JPG/PNG", type=["jpg", "jpeg", "png"])
    
    if uploaded_file:
        file_bytes = uploaded_file.getvalue()
        
        texto_extraido = ocr_space_api(file_bytes, st.secrets.get("OCRSPACEKEY", "MOCK_KEY"))
        
        if texto_extraido:
            dados_extraidos = extrair_dados_com_google_gemini(texto_extraido, API_KEY)
            
            if dados_extraidos:
                st.success("Dados extraídos com sucesso. Proposta de registo:")
                st.json(dados_extraidos)
                
                # --- GESTÃO DE DUPLICIDADE (NÍVEL 3.0) ---
                row_index_duplicado, dados_existentes = buscar_paciente_similar(
                    df_existente, 
                    dados_extraidos.get('Nome Completo', ''), 
                    dados_extraidos.get('Data de Nascimento', '')
                )
                
                if row_index_duplicado:
                    st.warning(f"⚠️ **ALERTA DE DUPLICIDADE:** Paciente `{dados_existentes['Nome Completo']}` já existe (Linha {row_index_duplicado}). Sugira a atualização em vez de criar um novo.")
                    if st.button("🔄 ATUALIZAR Registo Existente", type="primary"):
                        salvar_no_sheets(dados_extraidos, planilha, row_index=row_index_duplicado)
                else:
                    st.info("Novo registo. Nenhum paciente similar encontrado.")
                    if st.button("✅ SALVAR NOVO Registo", type="primary"):
                        salvar_no_sheets(dados_extraidos, planilha)
            else: st.error("A IA não conseguiu estruturar os dados da ficha.")
        else: st.error("MOCK OCR Falhou: Não foi possível extrair texto da imagem.")

def pagina_importar_prontuario(planilha):
    st.title("📚 Importar Dados Clínicos (Nível 3.0)")
    st.markdown("Extrai diagnósticos, medicamentos e informações de consulta de um PDF.")

    df_existente = ler_dados_da_planilha(planilha)
    paciente_nomes = sorted(df_existente['Nome Completo'].astype(str).unique())
    paciente_selecionado = st.selectbox("Selecione o paciente:", paciente_nomes, index=None, placeholder="Escolha um paciente...")

    if paciente_selecionado:
        paciente_row = df_existente[df_existente['Nome Completo'] == paciente_selecionado].iloc[0]
        st.info(f"Paciente: **{paciente_selecionado}** (Risco Atual: {paciente_row['Risco Clínico']})")
        
        uploaded_file = st.file_uploader("Envie o prontuário em PDF (MOCK):", type=["pdf"])

        if uploaded_file:
            if st.button("✨ Extrair e Classificar Dados Clínicos com IA"):
                with st.spinner("Processando..."):
                    texto_completo = ler_texto_prontuario(uploaded_file.getvalue(), st.secrets.get("OCRSPACEKEY", "MOCK_KEY"))
                    
                    if texto_completo:
                        dados_clinicos_extraidos = extrair_dados_clinicos_com_google_gemini(texto_completo, API_KEY)
                        
                        if dados_clinicos_extraidos:
                            
                            diagnosticos = dados_clinicos_extraidos.get('diagnosticos', [])
                            medicamentos = dados_clinicos_extraidos.get('medicamentos', [])
                            
                            # Reclassificação de Risco
                            idade = paciente_row.get('Idade', 0)
                            risco_calculado = calcular_risco_clinico_com_gemini(diagnosticos, idade, API_KEY)
                            
                            st.success(f"Risco Clínico RECALCULADO: **{risco_calculado}**")
                            
                            # MOCK de Atualização
                            dados_para_atualizar = paciente_row.to_dict()
                            dados_para_atualizar.update({
                                'Condição': " | ".join(diagnosticos),
                                'Medicamentos': " | ".join(medicamentos),
                                'Risco Clínico': risco_calculado,
                                'Última Consulta': dados_clinicos_extraidos.get('data_ultima_consulta', ""),
                                'Médico Responsável': dados_clinicos_extraidos.get('medico_responsavel', ""),
                            })
                            
                            salvar_no_sheets(dados_para_atualizar, planilha, row_index=paciente_row.name + 2)
                        else: st.error("A IA não conseguiu extrair informações clínicas estruturadas.")
                    else: st.error("MOCK OCR Falhou: Não foi possível ler o texto do prontuário PDF.")


def pagina_pesquisa(planilha):
    st.title("🔎 Gestão de Pacientes e Geração de Relatórios (Nível 4.0)")

    df_pacientes = ler_dados_da_planilha(planilha)
    
    paciente_nomes = sorted(df_pacientes['Nome Completo'].astype(str).unique())
    paciente_selecionado_nome = st.selectbox(
        "Selecione um Paciente para Ver Detalhes e Ações:",
        paciente_nomes,
        index=None,
        placeholder="Selecione aqui..."
    )

    if paciente_selecionado_nome:
        paciente_row = df_pacientes[df_pacientes['Nome Completo'] == paciente_selecionado_nome].iloc[0]
        dados = paciente_row.to_dict()
        
        st.subheader(f"Prontuário Digital: {dados['Nome Completo']}")
        
        # Exibição de Métricas
        col1, col2, col3 = st.columns(3)
        col1.metric("Idade", f"{dados.get('Idade', 0)} anos")
        col2.metric("Risco Clínico", dados.get('Risco Clínico', 'Baixo'))
        col3.metric("Última Consulta", dados.get('Última Consulta', '-'))

        st.markdown("### Dados Clínicos")
        st.text_area("Condições/Diagnósticos", value=dados.get('Condição', '-'), height=50, disabled=True)
        st.text_area("Medicamentos", value=dados.get('Medicamentos', '-'), height=50, disabled=True)

        st.markdown("---")

        # --- NOVO BLOCO 4.0: RESUMO NARRATIVO E AÇÃO ---
        st.subheader("📋 Resumo do Prontuário e Próxima Ação (IA)")
        
        # 1. Simulação do Relatório Vacinal (Necessário para a IA)
        relatorio_vacinal_simulado = analisar_carteira_vacinacao(
            dados.get('Data de Nascimento', '01/01/2000'), 
            [] # Lista vazia para forçar o uso da regra de mock
        )

        # Usar o ID do paciente para garantir que o resumo exibido é o atual
        resumo_key = f"resumo_{dados['ID']}"
        if st.session_state.get('resumo_paciente_id') != dados['ID']:
            st.session_state['resumo_narrativo'] = None

        if st.button("🧠 Gerar Resumo Narrativo e Plano de Ação (IA)", type="primary"):
            st.session_state['resumo_paciente_id'] = dados['ID']
            with st.spinner(f"Gerando Resumo Narrativo para {dados['Nome Completo']}..."):
                resumo_narrativo = gerar_resumo_narrativo_prontuario(
                    dados_paciente=dados,
                    relatorio_vacinal=relatorio_vacinal_simulado,
                    api_key=API_KEY
                )
            
            st.session_state['resumo_narrativo'] = resumo_narrativo
        
        # Display do Resumo Gerado
        if st.session_state.get('resumo_narrativo') and st.session_state.get('resumo_paciente_id') == dados['ID']:
            resumo = st.session_state['resumo_narrativo']
            st.markdown(resumo)
            
            # Automação de Cópia
            st.code(resumo, language="text")
            st.info("💡 **Automatização Concluída:** Copie o texto acima para o registro ou WhatsApp da equipe para comunicação imediata.")

        st.markdown("---")
        
        # Ação de Busca Ativa (Exemplo)
        if dados.get('Telefone Limpo'):
            msg = f"Olá, {dados['Nome Completo'].split()[0]}! O sistema identificou uma pendência. Sua Ação Prioritária é: {sugerir_proxima_acao_acs_com_gemini(dados['Risco Clínico'], dados['Condição'], dados['Idade'], relatorio_vacinal_simulado['em_atraso'], API_KEY)}. Por favor, entre em contato."
            whatsapp_url = f"https://wa.me/55{dados['Telefone Limpo']}?text={urllib.parse.quote(msg)}"
            st.link_button("📲 Iniciar Ação Prioritária (WhatsApp)", whatsapp_url, use_container_width=True)


def main():
    st.set_page_config(page_title="Gestão de Saúde 4.0", page_icon="🤖", layout="wide")
    st.sidebar.title("Navegação")
    
    if conectar_planilha() is None:
        st.error("A conexão com a planilha falhou.")
        st.stop()
        
    if 'resumo_narrativo' not in st.session_state:
        st.session_state['resumo_narrativo'] = None
    if 'resumo_paciente_id' not in st.session_state:
        st.session_state['resumo_paciente_id'] = None

    paginas = {
        "🏠 Início (Visão Geral)": pagina_inicial,
        "Coletar Fichas (Nível 3.0)": lambda: pagina_coleta("mock_key"),
        "Importar Prontuário (Nível 3.0)": lambda: pagina_importar_prontuario("mock_key"),
        "Gestão/Ação Proativa (Nível 4.0)": lambda: pagina_pesquisa("mock_key"),
    }
    
    pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas.keys())
    paginas[pagina_selecionada]()

if __name__ == "__main__":
    main()
