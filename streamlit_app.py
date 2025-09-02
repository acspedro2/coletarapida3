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
# st.set_page_config DEVE SER A PRIMEIRA CHAMADA DO STREAMLIT E EXECUTADA APENAS UMA VEZ
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

@st.cache_data(ttl=300)
def ler_dados_da_planilha(_planilha):
    try:
        dados = _planilha.get_all_records()
        df = pd.DataFrame(dados)
        colunas_esperadas = ["ID", "FAMÍLIA", "Nome Completo", "Data de Nascimento", "Telefone", "CPF", "Nome da Mãe", "Nome do Pai", "Sexo", "CNS", "Município de Nascimento", "Link do Prontuário", "Link da Pasta da Família", "Condição", "Data de Registo", "Raça/Cor", "Medicamentos"]
        for col in colunas_esperadas:
            if col not in df.columns: df[col] = ""
        df['Data de Nascimento DT'] = pd.to_datetime(df['Data de Nascimento'], format='%d/%m/%Y', errors='coerce')
        df['Idade'] = df['Data de Nascimento DT'].apply(lambda dt: calcular_idade(dt) if pd.notnull(dt) else 0)
        return df
    except Exception as e:
        st.error(f"Erro ao ler os dados da planilha: {e}"); return pd.DataFrame()

@st.cache_data(ttl=300)
def ler_agendamentos(planilha_key):
    try:
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
        sheet = client.open_by_key(planilha_key).worksheet("Agendamentos")
        dados = sheet.get_all_records()
        df = pd.DataFrame(dados)
        if not df.empty:
            df['Data_Hora_Agendamento'] = pd.to_datetime(df['Data_Agendamento'] + ' ' + df['Hora_Agendamento'], format='%d/%m/%Y %H:%M', errors='coerce')
        return df
    except gspread.exceptions.WorksheetNotFound:
        st.error("A folha 'Agendamentos' não foi encontrada na sua Planilha Google. Por favor, crie-a com os cabeçalhos corretos.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao ler os agendamentos: {e}")
        return pd.DataFrame()

def salvar_agendamento(planilha_key, agendamento_dados):
    try:
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
        sheet = client.open_by_key(planilha_key).worksheet("Agendamentos")
        agendamento_dados['ID_Agendamento'] = f"AG-{int(time.time())}"
        cabecalhos = sheet.row_values(1)
        nova_linha = [agendamento_dados.get(cabecalho, "") for cabecalho in cabecalhos]
        sheet.append_row(nova_linha)
        st.success("Agendamento salvo com sucesso!")
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Ocorreu um erro ao salvar o agendamento: {e}")
        return False

# ... (outras funções de API como ocr_space_api, cohere, etc.)

# --- FUNÇÕES DE PÁGINA ---
# ... (todas as suas funções de página: pagina_coleta, pagina_dashboard, etc.)
# (As funções de geração de PDF e outras páginas estão aqui, completas)
# (Para brevidade, apenas a função 'main' e as páginas mais recentes/modificadas são mostradas aqui)
# (MAS O SEU FICHEIRO FINAL DEVE CONTER TODAS AS FUNÇÕES COMPLETAS)
def pagina_agendamentos(planilha, co_client):
    st.title("🗓️ Gestão de Agendamentos")

    df_pacientes = ler_dados_da_planilha(planilha)
    df_agendamentos = ler_agendamentos(st.secrets["SHEETSID"])

    # --- Formulário para Novo Agendamento ---
    with st.expander("➕ Adicionar Novo Agendamento"):
        with st.form("form_novo_agendamento", clear_on_submit=True):
            lista_pacientes = df_pacientes.sort_values('Nome Completo')['Nome Completo'].tolist()
            paciente_selecionado = st.selectbox("Paciente:", lista_pacientes, index=None, placeholder="Selecione um paciente...")
            
            col1, col2 = st.columns(2)
            data_agendamento = col1.date_input("Data:")
            hora_agendamento = col2.time_input("Hora:")
            
            tipo_agendamento = st.selectbox("Tipo de Agendamento:", ["Consulta", "Vacinação", "Exame", "Retorno", "Visita Domiciliar"])
            descricao = st.text_area("Descrição (Opcional):")
            
            submit_button = st.form_submit_button("Salvar Agendamento")

            if submit_button and paciente_selecionado:
                paciente_info = df_pacientes[df_pacientes['Nome Completo'] == paciente_selecionado].iloc[0]
                
                novo_agendamento = {
                    "ID_Paciente": paciente_info.get("ID", ""), "Nome_Paciente": paciente_selecionado,
                    "Telefone_Paciente": paciente_info.get("Telefone", ""), "Data_Agendamento": data_agendamento.strftime("%d/%m/%Y"),
                    "Hora_Agendamento": hora_agendamento.strftime("%H:%M"), "Tipo_Agendamento": tipo_agendamento,
                    "Descricao": descricao, "Status": "Agendado", "Lembrete_Enviado": "Não"
                }
                salvar_agendamento(st.secrets["SHEETSID"], novo_agendamento)
                st.rerun()

    st.markdown("---")

    # --- Visualização de Próximos Agendamentos ---
    st.subheader("📅 Próximos Agendamentos")
    if not df_agendamentos.empty:
        hoje = pd.to_datetime(datetime.now().date())
        proximos_agendamentos = df_agendamentos[df_agendamentos['Data_Hora_Agendamento'] >= hoje].sort_values("Data_Hora_Agendamento")
        
        st.dataframe(proximos_agendamentos[['Nome_Paciente', 'Data_Agendamento', 'Hora_Agendamento', 'Tipo_Agendamento', 'Status']], use_container_width=True)
    else:
        st.info("Nenhum agendamento futuro encontrado.")

    st.markdown("---")
    
    # --- Painel de Envio de Lembretes ---
    st.subheader("📱 Lembretes para Enviar (Próximas 48 horas)")
    if not df_agendamentos.empty:
        amanha = pd.to_datetime((datetime.now() + pd.Timedelta(days=2)).date())
        proximos_agendamentos = df_agendamentos[df_agendamentos['Data_Hora_Agendamento'] >= pd.to_datetime(datetime.now().date())].sort_values("Data_Hora_Agendamento")
        agendamentos_para_lembrete = proximos_agendamentos[
            (proximos_agendamentos['Data_Hora_Agendamento'] < amanha) & 
            (proximos_agendamentos['Lembrete_Enviado'] == 'Não')
        ]

        if not agendamentos_para_lembrete.empty:
            for index, row in agendamentos_para_lembrete.iterrows():
                nome_paciente = row['Nome_Paciente']
                telefone = re.sub(r'\D', '', str(row['Telefone_Paciente']))
                
                if len(telefone) >= 10:
                    mensagem = f"Olá, {nome_paciente.split()[0]}. Gostaríamos de lembrar do seu agendamento de '{row['Tipo_Agendamento']}' no dia {row['Data_Agendamento']} às {row['Hora_Agendamento']}. Por favor, confirme a sua presença respondendo a esta mensagem. Obrigado!"
                    whatsapp_url = f"https://wa.me/55{telefone}?text={urllib.parse.quote(mensagem)}"
                    
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write(f"**{nome_paciente}** - {row['Tipo_Agendamento']} em {row['Data_Agendamento']} às {row['Hora_Agendamento']}")
                    with col2:
                        st.link_button("Enviar Lembrete ↗️", whatsapp_url, use_container_width=True)
        else:
            st.info("Nenhum lembrete a ser enviado nas próximas 48 horas.")
    else:
        st.info("Nenhum agendamento futuro encontrado.")

# ... (todas as outras funções de página completas)

def main():
    query_params = st.query_params
    if query_params.get("page") == "resumo":
        try:
            # Não chamar set_page_config aqui
            st.html("<meta http-equiv='refresh' content='60'>")
            planilha_conectada = conectar_planilha()
            if planilha_conectada:
                pagina_dashboard_resumo(planilha_conectada)
            else:
                st.error("Falha na conexão com a base de dados.")
        except Exception as e:
            st.error(f"Ocorreu um erro crítico: {e}")
    else:
        # A configuração da página principal já está no topo do script
        st.sidebar.title("Navegação")
        try:
            planilha_conectada = conectar_planilha()
        except Exception as e:
            st.error(f"Não foi possível inicializar os serviços. Verifique seus segredos. Erro: {e}")
            st.stop()
        if planilha_conectada is None:
            st.error("A conexão com a planilha falhou.")
            st.stop()
        co_client = None
        try:
            co_client = cohere.Client(api_key=st.secrets["COHEREKEY"])
        except Exception as e:
            st.warning(f"Não foi possível conectar ao serviço de IA. Funcionalidades limitadas. Erro: {e}")
        paginas = {
            "Agendamentos": lambda: pagina_agendamentos(planilha_conectada, co_client),
            "Análise de Vacinação": lambda: pagina_analise_vacinacao(planilha_conectada, co_client),
            "Importar Dados de Prontuário": lambda: pagina_importar_prontuario(planilha_conectada, co_client),
            "Coletar Fichas": lambda: pagina_coleta(planilha_conectada, co_client),
            "Gestão de Pacientes": lambda: pagina_pesquisa(planilha_conectada),
            "Dashboard": lambda: pagina_dashboard(planilha_conectada),
            "Gerar Etiquetas": lambda: pagina_etiquetas(planilha_conectada),
            "Gerar Capas de Prontuário": lambda: pagina_capas_prontuario(planilha_conectada),
            "Gerar Documentos": lambda: pagina_gerar_documentos(planilha_conectada),
            "Enviar WhatsApp": lambda: pagina_whatsapp(planilha_conectada),
            "Gerador de QR Code": lambda: pagina_gerador_qrcode(planilha_conectada),
        }
        pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas.keys())
        paginas[pagina_selecionada]()

if __name__ == "__main__":
    main()
