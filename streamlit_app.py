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

@st.cache_data
def convert_df_to_csv(df):
    return df.to_csv(index=False).encode('utf-8')

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

# --- PÁGINAS DO APP ---
def pagina_gestantes(client):
    st.title("🤰 Acompanhamento de Gestantes")
    df_pacientes, _ = ler_dados_da_planilha(client)
    df_gestantes, sheet_gestantes = ler_dados_gestantes(client)

    with st.expander("➕ Iniciar Novo Acompanhamento de Gestante"):
        with st.form("form_nova_gestante", clear_on_submit=True):
            if df_pacientes.empty:
                st.warning("Nenhum paciente na base de dados.")
            else:
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

# ... (outras funções de página, como pagina_coleta, pagina_dashboard, etc.)

def main():
    # ... (código completo da função main sem a página de Agendamentos)
    pass

if __name__ == "__main__":
    main()

