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
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import landscape, A4, letter
from reportlab.lib.units import inch, cm
from io import BytesIO
import urllib.parse
import qrcode
from reportlab.lib.utils import ImageReader
import matplotlib.pyplot as plt
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from dateutil.relativedelta import relativedelta
from pdf2image import convert_from_bytes

# --- MOTOR DE REGRAS: CALENDÁRIO NACIONAL DE IMUNIZAÇÕES (PNI) ---
CALENDARIO_PNI = [
    {"vacina": "BCG", "dose": "Dose Única", "idade_meses": 0, "detalhe": "Protege contra formas graves de tuberculose."},
    {"vacina": "Hepatite B", "dose": "1ª Dose", "idade_meses": 0, "detalhe": "Primeira dose, preferencialmente nas primeiras 12-24 horas de vida."},
    {"vacina": "Pentavalente", "dose": "1ª Dose", "idade_meses": 2, "detalhe": "Protege contra Difteria, Tétano, Coqueluche, Hepatite B e Haemophilus influenzae B."},
    {"vacina": "VIP (Poliomielite inativada)", "dose": "1ª Dose", "idade_meses": 2, "detalhe": "Protege contra a poliomielite."},
    {"vacina": "Pneumocócica 10V", "dose": "1ª Dose", "idade_meses": 2, "detalhe": "Protege contra doenças pneumocócicas."},
    {"vacina": "Rotavírus", "dose": "1ª Dose", "idade_meses": 2, "detalhe": "Idade máxima para iniciar o esquema: 3 meses e 15 dias."},
    {"vacina": "Meningocócica C", "dose": "1ª Dose", "idade_meses": 3, "detalhe": "Protege contra a meningite C."},
    {"vacina": "Pentavalente", "dose": "2ª Dose", "idade_meses": 4, "detalhe": "Reforço da proteção."},
    {"vacina": "VIP (Poliomielite inativada)", "dose": "2ª Dose", "idade_meses": 4, "detalhe": "Reforço da proteção."},
    {"vacina": "Pneumocócica 10V", "dose": "2ª Dose", "idade_meses": 4, "detalhe": "Reforço da proteção."},
    {"vacina": "Rotavírus", "dose": "2ª Dose", "idade_meses": 4, "detalhe": "Idade máxima para a última dose: 7 meses e 29 dias."},
    {"vacina": "Meningocócica C", "dose": "2ª Dose", "idade_meses": 5, "detalhe": "Reforço da proteção."},
    {"vacina": "Pentavalente", "dose": "3ª Dose", "idade_meses": 6, "detalhe": "Finalização do esquema primário."},
    {"vacina": "VIP (Poliomielite inativada)", "dose": "3ª Dose", "idade_meses": 6, "detalhe": "Finalização do esquema primário."},
    {"vacina": "Febre Amarela", "dose": "Dose Inicial", "idade_meses": 9, "detalhe": "Proteção contra a febre amarela. Reforço aos 4 anos."},
    {"vacina": "Tríplice Viral", "dose": "1ª Dose", "idade_meses": 12, "detalhe": "Protege contra Sarampo, Caxumba e Rubéola."},
    {"vacina": "Pneumocócica 10V", "dose": "Reforço", "idade_meses": 12, "detalhe": "Dose de reforço."},
    {"vacina": "Meningocócica C", "dose": "Reforço", "idade_meses": 12, "detalhe": "Dose de reforço."},
]

# --- Interface Streamlit ---
st.set_page_config(page_title="Coleta Inteligente", page_icon="🤖", layout="wide")

# --- Funções de Validação e Utilitárias ---
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

def calcular_idade(data_nasc):
    if pd.isna(data_nasc): return 0
    hoje = datetime.now()
    return hoje.year - data_nasc.year - ((hoje.month, hoje.day) < (data_nasc.month, data_nasc.day))

def analisar_carteira_vacinacao(data_nascimento_str, vacinas_administradas):
    try:
        data_nascimento = datetime.strptime(data_nascimento_str, "%d/%m/%Y")
    except ValueError:
        return {"erro": "Formato da data de nascimento inválido. Utilize DD/MM/AAAA."}
    hoje = datetime.now()
    idade = relativedelta(hoje, data_nascimento)
    idade_total_meses = idade.years * 12 + idade.months
    vacinas_tomadas_set = {(v['vacina'], v['dose']) for v in vacinas_administradas}
    relatorio = {"em_dia": [], "em_atraso": [], "proximas_doses": []}
    for regra in CALENDARIO_PNI:
        vacina_requerida = (regra['vacina'], regra['dose'])
        idade_recomendada_meses = regra['idade_meses']
        if idade_total_meses >= idade_recomendada_meses:
            if vacina_requerida in vacinas_tomadas_set:
                relatorio["em_dia"].append(regra)
            else:
                relatorio["em_atraso"].append(regra)
        else:
            relatorio["proximas_doses"].append(regra)
    return relatorio

def ler_texto_prontuario(file_bytes, ocr_api_key):
    try:
        imagens_pil = convert_from_bytes(file_bytes)
        texto_completo = ""
        progress_bar = st.progress(0, text="A processar páginas do PDF...")
        for i, imagem in enumerate(imagens_pil):
            with BytesIO() as output:
                imagem.save(output, format="JPEG")
                img_bytes = output.getvalue()
            texto_da_pagina = ocr_space_api(img_bytes, ocr_api_key)
            if texto_da_pagina:
                texto_completo += f"\n--- PÁGINA {i+1} ---\n" + texto_da_pagina
            progress_bar.progress((i + 1) / len(imagens_pil), text=f"Página {i+1} de {len(imagens_pil)} processada.")
        progress_bar.empty()
        return texto_completo.strip()
    except Exception as e:
        st.error(f"Erro ao processar o ficheiro PDF: {e}. Verifique se o ficheiro não está corrompido e se as dependências (pdf2image/Poppler) estão instaladas.")
        return None

def calcular_dados_gestacionais(dum):
    hoje = datetime.now().date()
    delta = hoje - dum
    idade_gestacional_dias_total = delta.days
    semanas = idade_gestacional_dias_total // 7
    dias = idade_gestacional_dias_total % 7
    dpp = dum + relativedelta(months=-3, days=+7, years=+1)
    if semanas <= 13: trimestre = 1
    elif semanas <= 26: trimestre = 2
    else: trimestre = 3
    return {"ig_semanas": semanas, "ig_dias": dias, "dpp": dpp, "trimestre": trimestre}

# --- Funções de Conexão e API ---
@st.cache_resource
def conectar_planilha():
    try:
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
        return client
    except Exception as e:
        st.error(f"Erro ao conectar com o Google Sheets: {e}"); return None

@st.cache_data(ttl=300)
def ler_dados_da_planilha(_client):
    try:
        sheet = _client.open_by_key(st.secrets["SHEETSID"]).sheet1
        dados = sheet.get_all_records()
        df = pd.DataFrame(dados)
        colunas_esperadas = ["ID", "FAMÍLIA", "Nome Completo", "Data de Nascimento", "Telefone", "CPF", "Nome da Mãe", "Nome do Pai", "Sexo", "CNS", "Município de Nascimento", "Link do Prontuário", "Link da Pasta da Família", "Condição", "Data de Registo", "Raça/Cor", "Medicamentos"]
        for col in colunas_esperadas:
            if col not in df.columns: df[col] = ""
        df['Data de Nascimento DT'] = pd.to_datetime(df['Data de Nascimento'], format='%d/%m/%Y', errors='coerce')
        df['Idade'] = df['Data de Nascimento DT'].apply(lambda dt: calcular_idade(dt) if pd.notnull(dt) else 0)
        return df, sheet
    except Exception as e:
        st.error(f"Erro ao ler os dados da planilha: {e}"); return pd.DataFrame(), None

@st.cache_data(ttl=300)
def ler_agendamentos(_client):
    try:
        sheet = _client.open_by_key(st.secrets["SHEETSID"]).worksheet("Agendamentos")
        dados = sheet.get_all_records()
        df = pd.DataFrame(dados)
        if not df.empty:
            df['Data_Hora_Agendamento'] = pd.to_datetime(df['Data_Agendamento'] + ' ' + df['Hora_Agendamento'], format='%d/%m/%Y %H:%M', errors='coerce')
        return df, sheet
    except gspread.exceptions.WorksheetNotFound:
        st.error("A folha 'Agendamentos' não foi encontrada. Por favor, crie-a com os cabeçalhos corretos.")
        return pd.DataFrame(), None
    except Exception as e:
        st.error(f"Erro ao ler os agendamentos: {e}")
        return pd.DataFrame(), None

@st.cache_data(ttl=300)
def ler_dados_gestantes(_client):
    try:
        sheet = _client.open_by_key(st.secrets["SHEETSID"]).worksheet("Gestantes")
        dados = sheet.get_all_records()
        return pd.DataFrame(dados), sheet
    except gspread.exceptions.WorksheetNotFound:
        st.error("A folha 'Gestantes' não foi encontrada. Por favor, crie-a com os cabeçalhos corretos.")
        return pd.DataFrame(), None
    except Exception as e:
        st.error(f"Erro ao ler os dados de gestantes: {e}")
        return pd.DataFrame(), None

def salvar_agendamento(_sheet, agendamento_dados):
    try:
        agendamento_dados['ID_Agendamento'] = f"AG-{int(time.time())}"
        cabecalhos = _sheet.row_values(1)
        nova_linha = [agendamento_dados.get(cabecalho, "") for cabecalho in cabecalhos]
        _sheet.append_row(nova_linha)
        st.success("Agendamento salvo com sucesso!")
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Ocorreu um erro ao salvar o agendamento: {e}")
        return False

def salvar_nova_gestante(_sheet, dados_gestante):
    try:
        dados_gestante['ID_Gestante'] = f"GEST-{int(time.time())}"
        cabecalhos = _sheet.row_values(1)
        nova_linha = [dados_gestante.get(cabecalho, "") for cabecalho in cabecalhos]
        _sheet.append_row(nova_linha)
        st.success("Acompanhamento de gestante iniciado com sucesso!")
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Ocorreu um erro ao salvar o registo da gestante: {e}")
        return False

# ... (outras funções de API e PDF)
def ocr_space_api(file_bytes, ocr_api_key):
    try:
        url = "https://api.ocr.space/parse/image"
        payload = {"language": "por", "isOverlayRequired": False, "OCREngine": 2}
        files = {"file": ("ficha.jpg", file_bytes, "image/jpeg")}
        headers = {"apikey": ocr_api_key}
        response = requests.post(url, data=payload, files=files, headers=headers)
        response.raise_for_status()
        result = response.json()
        if result.get("IsErroredOnProcessing"): return None
        return result["ParsedResults"][0]["ParsedText"]
    except Exception as e:
        return None

def extrair_dados_com_cohere(texto_extraido: str, cohere_client):
    # ...
    pass
def extrair_dados_vacinacao_com_cohere(texto_extraido: str, cohere_client):
    # ...
    pass
def extrair_dados_clinicos_com_cohere(texto_prontuario: str, cohere_client):
    # ...
    pass
def salvar_no_sheets(sheet, dados):
    # ...
    pass

# --- FUNÇÕES DE GERAÇÃO DE PDF ---
def preencher_pdf_formulario(paciente_dados):
    # ...
    pass
def gerar_pdf_etiquetas(familias_para_gerar):
    # ...
    pass
def gerar_pdf_capas_prontuario(pacientes_df):
    # ...
    pass
def gerar_pdf_relatorio_vacinacao(nome_paciente, data_nascimento, relatorio):
    # ...
    pass

# --- PÁGINAS DO APP ---
def pagina_agendamentos(client):
    st.title("🗓️ Gestão de Agendamentos")
    df_pacientes, _ = ler_dados_da_planilha(client)
    df_agendamentos, sheet_agendamentos = ler_agendamentos(client)

    with st.expander("➕ Adicionar Novo Agendamento"):
        with st.form("form_novo_agendamento", clear_on_submit=True):
            if df_pacientes.empty:
                st.warning("Nenhum paciente na base de dados para agendar.")
                st.stop()
            lista_pacientes = df_pacientes.sort_values('Nome Completo')['Nome Completo'].tolist()
            paciente_selecionado = st.selectbox("Paciente:", lista_pacientes, index=None, placeholder="Selecione um paciente...")
            col1, col2 = st.columns(2)
            data_agendamento = col1.date_input("Data:")
            hora_agendamento = col2.time_input("Hora:")
            tipo_agendamento = st.selectbox("Tipo de Agendamento:", ["Consulta", "Vacinação", "Exame", "Retorno", "Visita Domiciliar"])
            descricao = st.text_area("Descrição (Opcional):")
            if st.form_submit_button("Salvar Agendamento") and paciente_selecionado:
                paciente_info = df_pacientes[df_pacientes['Nome Completo'] == paciente_selecionado].iloc[0]
                novo_agendamento = {
                    "ID_Paciente": paciente_info.get("ID", ""), "Nome_Paciente": paciente_selecionado,
                    "Telefone_Paciente": paciente_info.get("Telefone", ""), "Data_Agendamento": data_agendamento.strftime("%d/%m/%Y"),
                    "Hora_Agendamento": hora_agendamento.strftime("%H:%M"), "Tipo_Agendamento": tipo_agendamento,
                    "Descricao": descricao, "Status": "Agendado", "Lembrete_Enviado": "Não"
                }
                if sheet_agendamentos is not None:
                    salvar_agendamento(sheet_agendamentos, novo_agendamento)
                    st.rerun()

    st.markdown("---")
    st.subheader("📅 Próximos Agendamentos")
    if not df_agendamentos.empty:
        hoje = pd.to_datetime(datetime.now().date())
        proximos_agendamentos = df_agendamentos[df_agendamentos['Data_Hora_Agendamento'] >= hoje].sort_values("Data_Hora_Agendamento")
        st.dataframe(proximos_agendamentos[['Nome_Paciente', 'Data_Agendamento', 'Hora_Agendamento', 'Tipo_Agendamento', 'Status']], use_container_width=True)
    else:
        st.info("Nenhum agendamento futuro encontrado.")
    st.markdown("---")
    st.subheader("📱 Lembretes para Enviar (Próximas 48 horas)")
    if not df_agendamentos.empty:
        hoje_com_hora = pd.to_datetime(datetime.now())
        limite_48h = hoje_com_hora + pd.Timedelta(days=2)
        agendamentos_para_lembrete = df_agendamentos[
            (df_agendamentos['Data_Hora_Agendamento'] >= hoje_com_hora) &
            (df_agendamentos['Data_Hora_Agendamento'] <= limite_48h) &
            (df_agendamentos['Lembrete_Enviado'] != 'Sim')
        ]
        if not agendamentos_para_lembrete.empty:
            for index, row in agendamentos_para_lembrete.iterrows():
                nome_paciente, telefone = row['Nome_Paciente'], re.sub(r'\D', '', str(row['Telefone_Paciente']))
                if len(telefone) >= 10:
                    mensagem = f"Olá, {nome_paciente.split()[0]}. Gostaríamos de lembrar do seu agendamento de '{row['Tipo_Agendamento']}' no dia {row['Data_Agendamento']} às {row['Hora_Agendamento']}. Por favor, confirme a sua presença. Obrigado!"
                    whatsapp_url = f"https://wa.me/55{telefone}?text={urllib.parse.quote(mensagem)}"
                    col1, col2 = st.columns([3, 1])
                    col1.write(f"**{nome_paciente}** - {row['Tipo_Agendamento']} em {row['Data_Agendamento']} às {row['Hora_Agendamento']}")
                    col2.link_button("Enviar Lembrete ↗️", whatsapp_url, use_container_width=True)
        else:
            st.info("Nenhum lembrete a ser enviado nas próximas 48 horas.")

def pagina_gestantes(client):
    st.title("🤰 Acompanhamento de Gestantes")
    df_pacientes, _ = ler_dados_da_planilha(client)
    df_gestantes, sheet_gestantes = ler_dados_gestantes(client)

    with st.expander("➕ Iniciar Novo Acompanhamento de Gestante"):
        with st.form("form_nova_gestante", clear_on_submit=True):
            pacientes_mulheres = df_pacientes[df_pacientes['Sexo'].str.upper().isin(['F', 'FEMININO'])]
            lista_pacientes = pacientes_mulheres.sort_values('Nome Completo')['Nome Completo'].tolist()
            paciente_selecionado = st.selectbox("Paciente:", lista_pacientes, index=None, placeholder="Selecione uma paciente...")
            data_dum = st.date_input("Data da Última Menstruação (DUM):")
            observacoes = st.text_area("Observações Iniciais:")
            if st.form_submit_button("Iniciar Acompanhamento") and paciente_selecionado and data_dum:
                paciente_info = df_pacientes[df_pacientes['Nome Completo'] == paciente_selecionado].iloc[0]
                dados_gestacionais = calcular_dados_gestacionais(data_dum)
                novo_registo = {
                    "ID_Paciente": paciente_info.get("ID", ""), "Nome_Paciente": paciente_selecionado,
                    "DUM": data_dum.strftime("%d/%m/%Y"), "DPP": dados_gestacionais['dpp'].strftime("%d/%m/%Y"),
                    "Observacoes": observacoes
                }
                if sheet_gestantes is not None:
                    salvar_nova_gestante(sheet_gestantes, novo_registo)
                    st.rerun()

    st.markdown("---")
    st.subheader("Gestantes em Acompanhamento")
    if not df_gestantes.empty:
        for index, gestante in df_gestantes.iterrows():
            with st.expander(f"**{gestante['Nome_Paciente']}**"):
                try:
                    dum = datetime.strptime(gestante['DUM'], "%d/%m/%Y").date()
                    dados_gestacionais = calcular_dados_gestacionais(dum)
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Última Menstruação (DUM)", dum.strftime("%d/%m/%Y"))
                    col2.metric("Idade Gestacional (IG)", f"{dados_gestacionais['ig_semanas']}s {dados_gestacionais['ig_dias']}d")
                    col3.metric("Trimestre Atual", f"{dados_gestacionais['trimestre']}º")
                    col4.metric("Data Provável do Parto (DPP)", dados_gestacionais['dpp'].strftime("%d/%m/%Y"))
                    st.info(f"**Observações:** {gestante.get('Observacoes', 'Nenhuma')}")
                    st.write("**Marcos Importantes do Pré-Natal:**")
                    if dados_gestacionais['trimestre'] == 1: st.success("✅ **1º Trimestre:** Foco em exames iniciais e primeiro ultrassom.")
                    if dados_gestacionais['trimestre'] == 2: st.success("✅ **2º Trimestre:** Foco em ultrassom morfológico e vacina dTpa.")
                    if dados_gestacionais['trimestre'] == 3: st.success("✅ **3º Trimestre:** Foco em monitoramento final e preparação para o parto.")
                except Exception as e:
                    st.error(f"Não foi possível calcular os dados para {gestante['Nome_Paciente']}. Verifique a data DUM. Erro: {e}")
    else:
        st.info("Nenhum acompanhamento de gestante iniciado.")

# ... (outras funções de página, completas)

def main():
    query_params = st.query_params
    if query_params.get("page") == "resumo":
        st.set_page_config(page_title="Resumo de Pacientes", layout="centered") # Re-config for special page
        st.html("<meta http-equiv='refresh' content='60'>")
        gspread_client = conectar_planilha()
        if gspread_client:
            df_pacientes, sheet_pacientes = ler_dados_da_planilha(gspread_client)
            pagina_dashboard_resumo(df_pacientes)
        else: st.error("Falha na conexão com a base de dados.")
    else:
        st.set_page_config(page_title="Coleta Inteligente", page_icon="🤖", layout="wide") # Main config
        st.sidebar.title("Navegação")
        gspread_client = conectar_planilha()
        if gspread_client is None: st.stop()
        
        co_client = None
        try:
            co_client = cohere.Client(api_key=st.secrets["COHEREKEY"])
        except Exception as e:
            st.warning(f"Não foi possível conectar ao serviço de IA. Funcionalidades limitadas. Erro: {e}")
        
        paginas = {
            "Agendamentos": lambda: pagina_agendamentos(gspread_client),
            "Acompanhamento de Gestantes": lambda: pagina_gestantes(gspread_client),
            "Análise de Vacinação": lambda: pagina_analise_vacinacao(gspread_client, co_client),
            "Importar Dados de Prontuário": lambda: pagina_importar_prontuario(gspread_client, co_client),
            "Coletar Fichas": lambda: pagina_coleta(gspread_client, co_client),
            "Gestão de Pacientes": lambda: pagina_pesquisa(gspread_client),
            "Dashboard": lambda: pagina_dashboard(gspread_client),
            "Gerar Etiquetas": lambda: pagina_etiquetas(gspread_client),
            "Gerar Capas de Prontuário": lambda: pagina_capas_prontuario(gspread_client),
            "Gerar Documentos": lambda: pagina_gerar_documentos(gspread_client),
            "Enviar WhatsApp": lambda: pagina_whatsapp(gspread_client),
            "Gerador de QR Code": lambda: pagina_gerador_qrcode(gspread_client),
        }
        pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas.keys())
        paginas[pagina_selecionada]()

if __name__ == "__main__":
    main()
