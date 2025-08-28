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

# --- Funções de Conexão e API ---
@st.cache_resource
def conectar_planilha(nome_aba='Página1'):
    try:
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
        spreadsheet = client.open_by_key(st.secrets["SHEETSID"])
        worksheet = spreadsheet.worksheet(nome_aba)
        return worksheet
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"Erro: A aba '{nome_aba}' não foi encontrada na sua Planilha Google. Por favor, verifique o nome.")
        return None
    except Exception as e:
        st.error(f"Erro ao conectar com o Google Sheets: {e}")
        return None

@st.cache_data(ttl=300)
def ler_dados_da_planilha(_planilha):
    try:
        if _planilha is None: return pd.DataFrame()
        dados = _planilha.get_all_records()
        df = pd.DataFrame(dados)
        colunas_esperadas = ["ID", "FAMÍLIA", "Nome Completo", "Data de Nascimento", "Telefone", "CPF", "Nome da Mãe", "Nome do Pai", "Sexo", "CNS", "Município de Nascimento", "Link do Prontuário", "Link da Pasta da Família", "Condição", "Data de Registo", "Raça/Cor"]
        for col in colunas_esperadas:
            if col not in df.columns: df[col] = ""
        df['Data de Nascimento DT'] = pd.to_datetime(df['Data de Nascimento'], format='%d/%m/%Y', errors='coerce')
        df['Idade'] = df['Data de Nascimento DT'].apply(lambda dt: calcular_idade(dt) if pd.notnull(dt) else 0)
        return df
    except Exception as e:
        st.error(f"Erro ao ler os dados da planilha de pacientes: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def ler_dados_vacinas(_planilha_vacinas):
    try:
        if _planilha_vacinas is None: return pd.DataFrame()
        dados = _planilha_vacinas.get_all_records()
        df = pd.DataFrame(dados)
        colunas_esperadas = ["ID_do_Paciente", "Nome_da_Vacina", "Data_de_Aplicação", "Dose", "Lote", "Unidade_de_Saúde"]
        for col in colunas_esperadas:
            if col not in df.columns: df[col] = ""
        return df
    except Exception as e:
        st.error(f"Erro ao ler os dados da planilha de vacinas: {e}")
        return pd.DataFrame()

def salvar_no_sheets(dados, planilha):
    try:
        cabecalhos = planilha.row_values(1)
        if 'ID' not in dados or not dados['ID']:
            dados['ID'] = f"ID-{int(time.time())}"
        dados['Data de Registo'] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        nova_linha = [dados.get(cabecalho, "") for cabecalho in cabecalhos]
        planilha.append_row(nova_linha)
        st.success(f"✅ Dados de '{dados.get('Nome Completo', 'Desconhecido')}' salvos com sucesso!")
        st.balloons()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao salvar na planilha: {e}")

def salvar_vacina_no_sheets(dados, planilha_vacinas):
    try:
        cabecalhos = planilha_vacinas.row_values(1)
        nova_linha = [dados.get(cabecalho, "") for cabecalho in cabecalhos]
        planilha_vacinas.append_row(nova_linha)
        st.success(f"✅ Vacina '{dados.get('Nome_da_Vacina')}' registada com sucesso!")
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao salvar na planilha de vacinas: {e}")

def preencher_pdf_formulario(paciente_dados):
    try:
        template_pdf_path = "Formulario_2IndiceDeVulnerabilidadeClinicoFuncional20IVCF20_ImpressoraPDFPreenchivel_202404-2.pdf"
        
        packet = BytesIO()
        can = canvas.Canvas(packet, pagesize=A4)
        
        can.setFont("Helvetica", 10)
        can.drawString(3.2 * cm, 23.8 * cm, str(paciente_dados.get("Nome Completo", "")))
        can.drawString(15 * cm, 23.8 * cm, str(paciente_dados.get("CPF", "")))
        can.drawString(16.5 * cm, 23 * cm, str(paciente_dados.get("Data de Nascimento", "")))
        
        sexo = str(paciente_dados.get("Sexo", "")).strip().upper()
        can.setFont("Helvetica-Bold", 12)
        if sexo.startswith('F'):
            can.drawString(12.1 * cm, 22.9 * cm, "X")
        elif sexo.startswith('M'):
            can.drawString(12.6 * cm, 22.9 * cm, "X")
        
        raca_cor = str(paciente_dados.get("Raça/Cor", "")).strip().upper()
        if raca_cor.startswith('BRANCA'):
            can.drawString(3.1 * cm, 23 * cm, "X")
        elif raca_cor.startswith('PRETA'):
            can.drawString(4.4 * cm, 23 * cm, "X")
        elif raca_cor.startswith('AMARELA'):
            can.drawString(5.5 * cm, 23 * cm, "X")
        elif raca_cor.startswith('PARDA'):
            can.drawString(7.0 * cm, 23 * cm, "X")
        elif raca_cor.startswith('INDÍGENA') or raca_cor.startswith('INDIGENA'):
            can.drawString(8.2 * cm, 23 * cm, "X")
        elif raca_cor.startswith('IGNORADO'):
            can.drawString(9.7 * cm, 23 * cm, "X")

        can.save()
        packet.seek(0)
        
        new_pdf = PdfReader(packet)
        existing_pdf = PdfReader(open(template_pdf_path, "rb"))
        output = PdfWriter()
        
        page = existing_pdf.pages[0]
        page.merge_page(new_pdf.pages[0])
        output.add_page(page)
        
        final_buffer = BytesIO()
        output.write(final_buffer)
        final_buffer.seek(0)
        
        return final_buffer

    except FileNotFoundError:
        st.error(f"Erro: O arquivo modelo '{template_pdf_path}' não foi encontrado no repositório GitHub.")
        return None
    except Exception as e:
        st.error(f"Ocorreu um erro ao gerar o PDF: {e}")
        return None

# --- PÁGINAS DO APP ---

def pagina_vacinacao(planilha_pacientes, planilha_vacinas):
    st.title("💉 Carteira de Vacinação Digital")

    df_pacientes = ler_dados_da_planilha(planilha_pacientes)
    df_vacinas = ler_dados_vacinas(planilha_vacinas)
    
    if df_pacientes.empty:
        st.warning("Não há pacientes na base de dados.")
        return

    st.subheader("1. Selecione o Paciente")
    lista_pacientes = sorted(df_pacientes['Nome Completo'].tolist())
    paciente_selecionado_nome = st.selectbox("Escolha um paciente:", lista_pacientes, index=None, placeholder="Selecione...")

    if paciente_selecionado_nome:
        paciente_id = df_pacientes[df_pacientes['Nome Completo'] == paciente_selecionado_nome].iloc[0]['ID']
        
        st.markdown("---")
        st.subheader(f"Histórico de Vacinas de {paciente_selecionado_nome}")
        
        historico_paciente = df_vacinas[df_vacinas['ID_do_Paciente'].astype(str) == str(paciente_id)]
        
        if historico_paciente.empty:
            st.info("Nenhuma vacina registada para este paciente.")
        else:
            st.dataframe(historico_paciente, hide_index=True)
            
        st.markdown("---")
        with st.expander("➕ Adicionar Novo Registo de Vacina"):
            with st.form(key="vacina_form", clear_on_submit=True):
                st.write(f"A registar vacina para: **{paciente_selecionado_nome}** (ID: {paciente_id})")
                
                nome_vacina = st.text_input("Nome da Vacina")
                data_aplicacao = st.text_input("Data de Aplicação (DD/MM/AAAA)")
                dose = st.text_input("Dose (ex: 1ª, Reforço)")
                lote = st.text_input("Lote")
                unidade = st.text_input("Unidade de Saúde")
                
                submit_button = st.form_submit_button(label="Salvar Registo")
                
                if submit_button:
                    if not nome_vacina or not data_aplicacao:
                        st.warning("Nome da Vacina e Data de Aplicação são obrigatórios.")
                    else:
                        novo_registo = {
                            "ID_do_Paciente": paciente_id,
                            "Nome_da_Vacina": nome_vacina,
                            "Data_de_Aplicação": data_aplicacao,
                            "Dose": dose,
                            "Lote": lote,
                            "Unidade_de_Saúde": unidade
                        }
                        salvar_vacina_no_sheets(novo_registo, planilha_vacinas)
                        st.rerun()

def main():
    st.sidebar.title("Navegação")
    
    try:
        planilha_pacientes = conectar_planilha(nome_aba='Página1')
        planilha_vacinas = conectar_planilha(nome_aba='Vacinas')
    except Exception as e:
        st.error(f"Não foi possível inicializar os serviços. Verifique seus segredos e nomes das abas. Erro: {e}")
        st.stop()

    if planilha_pacientes is None or planilha_vacinas is None:
        st.error("A conexão com uma das abas da planilha falhou. Verifique se as abas 'Página1' e 'Vacinas' existem.")
        st.stop()
        
    co_client = None
    try:
        co_client = cohere.Client(api_key=st.secrets["COHEREKEY"])
    except Exception as e:
        st.warning(f"Não foi possível conectar ao serviço de IA. A página de coleta pode não funcionar. Erro: {e}")

    paginas = {
        "Coletar Fichas": lambda: pagina_coleta(planilha_pacientes, co_client),
        "Gestão de Pacientes": lambda: pagina_pesquisa(planilha_pacientes),
        "Carteira de Vacinação": lambda: pagina_vacinacao(planilha_pacientes, planilha_vacinas),
        "Dashboard": lambda: pagina_dashboard(planilha_pacientes),
        "Gerar Etiquetas": lambda: pagina_etiquetas(planilha_pacientes),
        "Gerar Capas de Prontuário": lambda: pagina_capas_prontuario(planilha_pacientes),
        "Gerar Documentos": lambda: pagina_gerar_documentos(planilha_pacientes),
        "Enviar WhatsApp": lambda: pagina_whatsapp(planilha_pacientes),
    }
    
    pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas.keys())
    
    paginas[pagina_selecionada]()

if __name__ == "__main__":
    main()
