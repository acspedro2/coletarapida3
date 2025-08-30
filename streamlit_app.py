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

# --- Funções de Relatórios ---
def gerar_relatorio_status_vacinal(df_pacientes):
    criancas = df_pacientes[df_pacientes['Idade'].between(0, 5)].copy()
    if "Status_Vacinal" in criancas.columns:
        criancas_pendentes = criancas[criancas['Status_Vacinal'].astype(str).str.strip() == '']
        return criancas_pendentes[['Nome Completo', 'Idade', 'Nome da Mãe', 'Telefone', 'FAMÍLIA']]
    else:
        st.warning("A coluna 'Status_Vacinal' não foi encontrada na planilha. O relatório não pode ser gerado.")
        return pd.DataFrame()

def gerar_relatorio_condicoes_cronicas(df_pacientes, condicao_filtro):
    if "Condição" in df_pacientes.columns:
        pacientes_filtrados = df_pacientes[df_pacientes['Condição'].str.contains(condicao_filtro, case=False, na=False)]
        return pacientes_filtrados[['Nome Completo', 'Idade', 'Telefone', 'Condição', 'Medicamentos']]
    else:
        st.warning("A coluna 'Condição' não foi encontrada na planilha.")
        return pd.DataFrame()

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
        colunas_esperadas = ["ID", "FAMÍLIA", "Nome Completo", "Data de Nascimento", "Telefone", "CPF", "Nome da Mãe", "Nome do Pai", "Sexo", "CNS", "Município de Nascimento", "Link do Prontuário", "Link da Pasta da Família", "Condição", "Data de Registo", "Raça/Cor", "Medicamentos", "Status_Vacinal"]
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
    except Exception:
        return None

def extrair_dados_com_cohere(texto_extraido: str, cohere_client):
    try:
        prompt = f"""
        Sua tarefa é extrair informações de um texto de formulário de saúde e convertê-lo para um JSON.
        Procure por uma anotação à mão que pareça um código de família (ex: 'FAM111'). Este código deve ir para a chave "FAMÍLIA".
        Retorne APENAS um objeto JSON com as chaves: 'ID', 'FAMÍLIA', 'Nome Completo', 'Data de Nascimento', 'Telefone', 'CPF', 'Nome da Mãe', 'Nome do Pai', 'Sexo', 'CNS', 'Município de Nascimento'.
        Se um valor não for encontrado, retorne uma string vazia "".
        Texto para analisar: --- {texto_extraido} ---
        """
        response = cohere_client.chat(model="command-r-plus", message=prompt, temperature=0.1)
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except Exception:
        return None

def extrair_dados_vacinacao_com_cohere(texto_extraido: str, cohere_client):
    prompt = f"""
    Sua tarefa é atuar como um agente de saúde especializado em analisar textos de cadernetas de vacinação brasileiras.
    O texto fornecido foi extraído por OCR e pode conter erros. Sua missão é extrair as informações e retorná-las em um formato JSON estrito.
    Instruções:
    1.  Identifique o Nome do Paciente.
    2.  Identifique a Data de Nascimento no formato DD/MM/AAAA.
    3.  Liste as Vacinas Administradas, normalizando os nomes para um padrão. Exemplos: "Penta" -> "Pentavalente"; "Polio" ou "VIP" -> "VIP (Poliomielite inativada)"; "Meningo C" -> "Meningocócica C"; "Sarampo, Caxumba, Rubéola" -> "Tríplice Viral".
    4.  Para cada vacina, identifique a dose (ex: "1ª Dose", "Reforço"). Se não for clara, infira pela ordem.
    5.  Retorne APENAS um objeto JSON com as chaves "nome_paciente", "data_nascimento", "vacinas_administradas" (lista de objetos com "vacina" e "dose").
    Se uma informação não for encontrada, retorne um valor vazio ("") ou uma lista vazia ([]).
    Texto para analisar: --- {texto_extraido} ---
    """
    try:
        response = cohere_client.chat(model="command-r-plus", message=prompt, temperature=0.2)
        json_string = response.text.strip()
        if json_string.startswith("```json"): json_string = json_string[7:]
        if json_string.endswith("```"): json_string = json_string[:-3]
        dados_extraidos = json.loads(json_string.strip())
        if "nome_paciente" in dados_extraidos and "data_nascimento" in dados_extraidos and "vacinas_administradas" in dados_extraidos:
            return dados_extraidos
        else: return None
    except Exception:
        return None

def extrair_dados_clinicos_com_cohere(texto_prontuario: str, cohere_client):
    prompt = f"""
    Sua tarefa é analisar o texto de um prontuário médico e extrair informações clínicas chave.
    O seu foco deve ser em duas categorias: Diagnósticos (especialmente condições crónicas) e Medicamentos.
    Instruções:
    1.  Analise o texto completo para compreender o contexto clínico do paciente.
    2.  Extraia Diagnósticos: Identifique todas as condições médicas e diagnósticos mencionados. Dê prioridade a doenças crónicas como 'Diabetes' (Tipo 1 ou 2), 'Hipertensão Arterial Sistêmica (HAS)', 'Asma', 'DPOC'.
    3.  Extraia Medicamentos: Identifique todos os medicamentos de uso contínuo ou relevante mencionados, incluindo a dosagem, se disponível (ex: 'Metformina 500mg', 'Losartana 50mg').
    4.  Formato de Saída: Retorne APENAS um objeto JSON com as seguintes chaves:
        -   "diagnosticos": (uma lista de strings com os diagnósticos encontrados)
        -   "medicamentos": (uma lista de strings com os medicamentos encontrados)
    Se nenhuma informação de uma categoria for encontrada, retorne uma lista vazia para essa chave.
    Texto do Prontuário para analisar:
    ---
    {texto_prontuario}
    ---
    """
    try:
        response = cohere_client.chat(model="command-r-plus", message=prompt, temperature=0.2)
        json_string = response.text.strip()
        if json_string.startswith("```json"): json_string = json_string[7:]
        if json_string.endswith("```"): json_string = json_string[:-3]
        dados_extraidos = json.loads(json_string.strip())
        if "diagnosticos" in dados_extraidos and "medicamentos" in dados_extraidos:
            return dados_extraidos
        else: return None
    except Exception:
        return None

def salvar_no_sheets(_sheet, dados):
    try:
        cabecalhos = _sheet.row_values(1)
        if 'ID' not in dados or not dados['ID']: dados['ID'] = f"ID-{int(time.time())}"
        dados['Data de Registo'] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        nova_linha = [dados.get(cabecalho, "") for cabecalho in cabecalhos]
        _sheet.append_row(nova_linha)
        st.success(f"✅ Dados de '{dados.get('Nome Completo', 'Desconhecido')}' salvos com sucesso!")
        st.balloons()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao salvar na planilha: {e}")

# --- FUNÇÕES DE GERAÇÃO DE PDF ---
# (O corpo completo de todas as funções de PDF está aqui)

# --- PÁGINAS DO APP ---
# (O corpo completo de todas as funções de página está aqui)

def main():
    # ... (código completo da função main)
    pass

if __name__ == "__main__":
    main()
