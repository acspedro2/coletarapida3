import streamlit as st
import requests
import json
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
import io

# --- NOVA IMPORTAÇÃO ---
import google.generativeai as genai

# --- CONFIGURAÇÃO GLOBAL DA API GEMINI ---
MODELO_GEMINI = "gemini-2.5-flash"

# --- MOTOR DE REGRAS: CALENDÁRIO NACIONAL DE IMUNIZAÇÕES (PNI) ---
CALENDARIO_PNI = [
    {"vacina": "BCG", "dose": "Dose Única", "idade_meses": 0, "idade_anos": 0, "detalhe": "Protege contra formas graves de tuberculose."},
    {"vacina": "Hepatite B", "dose": "1ª Dose", "idade_meses": 0, "idade_anos": 0, "detalhe": "Primeira dose, preferencialmente nas primeiras 12-24 horas de vida."},
    {"vacina": "Pentavalente", "dose": "1ª Dose", "idade_meses": 2, "idade_anos": 0, "detalhe": "Protege contra Difteria, Tétano, Coqueluche, Hepatite B e Haemophilus influenzae B."},
    {"vacina": "VIP (Poliomielite inativada)", "dose": "1ª Dose", "idade_meses": 2, "idade_anos": 0, "detalhe": "Protege contra a poliomielite."},
    {"vacina": "Pneumocócica 10V", "dose": "1ª Dose", "idade_meses": 2, "idade_anos": 0, "detalhe": "Protege contra doenças pneumocócicas."},
    {"vacina": "Rotavírus", "dose": "1ª Dose", "idade_meses": 2, "idade_anos": 0, "detalhe": "Idade máxima para iniciar o esquema: 3 meses e 15 dias."},
    {"vacina": "Meningocócica C", "dose": "1ª Dose", "idade_meses": 3, "idade_anos": 0, "detalhe": "Protege contra a meningite C."},
    {"vacina": "Pentavalente", "dose": "2ª Dose", "idade_meses": 4, "idade_anos": 0, "detalhe": "Reforço da proteção."},
    {"vacina": "VIP (Poliomielite inativada)", "dose": "2ª Dose", "idade_meses": 4, "idade_anos": 0, "detalhe": "Reforço da proteção."},
    {"vacina": "Pneumocócica 10V", "dose": "2ª Dose", "idade_meses": 4, "idade_anos": 0, "detalhe": "Reforço da proteção."},
    {"vacina": "Rotavírus", "dose": "2ª Dose", "idade_meses": 4, "idade_anos": 0, "detalhe": "Idade máxima para a última dose: 7 meses e 29 dias."},
    {"vacina": "Meningocócica C", "dose": "2ª Dose", "idade_meses": 5, "idade_anos": 0, "detalhe": "Reforço da proteção."},
    {"vacina": "Pentavalente", "dose": "3ª Dose", "idade_meses": 6, "idade_anos": 0, "detalhe": "Finalização do esquema primário."},
    {"vacina": "VIP (Poliomielite inativada)", "dose": "3ª Dose", "idade_meses": 6, "idade_anos": 0, "detalhe": "Finalização do esquema primário."},
    {"vacina": "Febre Amarela", "dose": "Dose Inicial", "idade_meses": 9, "idade_anos": 0, "detalhe": "Proteção contra a febre amarela. Reforço aos 4 anos."},
    {"vacina": "Tríplice Viral", "dose": "1ª Dose", "idade_meses": 12, "idade_anos": 1, "detalhe": "Protege contra Sarampo, Caxumba e Rubéola."},
    {"vacina": "Pneumocócica 10V", "dose": "Reforço", "idade_meses": 12, "idade_anos": 1, "detalhe": "Dose de reforço."},
    {"vacina": "Meningocócica C", "dose": "Reforço", "idade_meses": 12, "idade_anos": 1, "detalhe": "Dose de reforço."},
    {"vacina": "Hepatite A", "dose": "Dose Única", "idade_meses": 15, "idade_anos": 1, "detalhe": "Dose única aos 15 meses."},
    {"vacina": "DTP", "dose": "1º Reforço", "idade_meses": 15, "idade_anos": 1, "detalhe": "1º reforço da Pentavalente."},
    {"vacina": "VOP (Poliomielite oral)", "dose": "1º Reforço", "idade_meses": 15, "idade_anos": 1, "detalhe": "1º reforço da VIP."},
    {"vacina": "Tríplice Viral", "dose": "2ª Dose", "idade_meses": 24, "idade_anos": 1, "detalhe": "2ª Dose (Sarampo, Caxumba, Rubéola)"},
]

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
    return hoje.year - data_nasc.year - ((hoje.month, hoje.day) < (data_nasc.month, hoje.day))

def calcular_idade_meses(data_nasc):
    if pd.isna(data_nasc): return 0
    hoje = datetime.now()
    r = relativedelta(hoje, data_nasc)
    return r.years * 12 + r.months

def padronizar_telefone(telefone):
    """Limpa e padroniza o número de telefone (remove formatação e 55, se houver)."""
    if pd.isna(telefone) or telefone == "":
        return None
    num_limpo = re.sub(r'\D', '', str(telefone))
    if num_limpo.startswith('55'):
        num_limpo = num_limpo[2:]
    if 10 <= len(num_limpo) <= 11: 
        return num_limpo
    return None 

def gerar_url_whatsapp_proativo(telefone_limpo, nome_paciente, vacina, idade_meses):
    """Gera o link de WhatsApp para um alerta de vacinação proativo."""
    primeiro_nome = nome_paciente.split()[0]
    mensagem = (
        f"Olá, {primeiro_nome}! Notamos que a idade recomendada para a vacina de "
        f"'{vacina}' ({idade_meses} meses) está próxima. Por favor, procure a UBS para garantir a imunização. "
        f"[Saúde Municipal]"
    )
    # Garante que o número está no formato 55DDDXXXXXX
    numero_completo = f"55{telefone_limpo}"
    return f"https://wa.me/{numero_completo}?text={urllib.parse.quote(mensagem)}"

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
        colunas_esperadas = ["ID", "FAMÍLIA", "Nome Completo", "Data de Nascimento", "Telefone", "CPF", "Mãe", "Pai", "Sexo", "CNS", "Município de Nascimento", "Link do Prontuário", "Link da Pasta da Família", "Condição", "Data de Registo", "Raça/Cor", "Medicamentos"]
        for col in colunas_esperadas:
            if col not in df.columns: df[col] = ""
        df['Data de Nascimento DT'] = pd.to_datetime(df['Data de Nascimento'], format='%d/%m/%Y', errors='coerce')
        df['Idade'] = df['Data de Nascimento DT'].apply(lambda dt: calcular_idade(dt) if pd.notnull(dt) else 0)
        df['Idade Meses'] = df['Data de Nascimento DT'].apply(lambda dt: calcular_idade_meses(dt) if pd.notnull(dt) else 0)
        df['Telefone Limpo'] = df['Telefone'].apply(padronizar_telefone) 
        return df
    except Exception as e:
        st.error(f"Erro ao ler os dados da planilha: {e}"); return pd.DataFrame()

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
        st.error(f"Erro ao processar o ficheiro PDF: {e}. Verifique se o ficheiro não está corrompido.")
        return None

# --- Funções de Extração e Automação (Gemini) ---

def extrair_dados_com_google_gemini(texto_extraido: str, api_key: str):
    """Extrai dados cadastrais de um texto (ficha) usando Gemini com normalização e validação."""
    try:
        genai.configure(api_key=api_key)
        prompt = f"""
        Sua tarefa é extrair informações de um texto de formulário de saúde e convertê-lo para um JSON.
        Procure por uma anotação à mão que pareça um código de família (ex: 'FAM111'). Este código deve ir para a chave "FAMÍLIA".
        Retorne APENAS um objeto JSON com as chaves: 'ID', 'FAMÍLIA', 'Nome Completo', 'Data de Nascimento', 'Telefone', 'CPF', 'Nome da Mãe', 'Nome do Pai', 'Sexo', 'CNS', 'Município de Nascimento'.
        Se um valor não for encontrado, retorne uma string vazia "".
        Texto para analisar: --- {texto_extraido} ---
        """
        model = genai.GenerativeModel(MODELO_GEMINI)
        response = model.generate_content(prompt)
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        dados_extraidos = json.loads(json_string)

        # --- AUTOMAÇÃO: NORMALIZAÇÃO E VALIDAÇÃO DE DADOS ---
        # 1. Telefone
        telefone = dados_extraidos.get('Telefone')
        if telefone:
            dados_extraidos['Telefone'] = padronizar_telefone(telefone)
            
        # 2. Sexo
        sexo = dados_extraidos.get('Sexo', '').strip().upper()
        if 'M' in sexo and len(sexo) < 3: dados_extraidos['Sexo'] = 'Masculino'
        elif 'F' in sexo and len(sexo) < 3: dados_extraidos['Sexo'] = 'Feminino'
        
        # 3. CPF (Somente números)
        cpf = dados_extraidos.get('CPF', '')
        dados_extraidos['CPF'] = re.sub(r'\D', '', str(cpf))
        
        return dados_extraidos
    except Exception as e:
        st.error(f"Erro ao chamar a API do Google Gemini (Extração de Ficha): {e}"); return None

def extrair_dados_vacinacao_com_google_gemini(texto_extraido: str, api_key: str):
    try:
        genai.configure(api_key=api_key)
        prompt = f"""
        Sua tarefa é atuar como um agente de saúde especializado em analisar textos de cadernetas de vacinação brasileiras.
        O texto fornecido foi extraído por OCR. Sua missão é extrair as informações e retorná-las em um formato JSON estrito.
        Instruções:
        1.  Identifique o Nome do Paciente.
        2.  Identifique a Data de Nascimento no formato DD/MM/AAAA.
        3.  Liste as Vacinas Administradas, normalizando os nomes para um padrão. Ex: "Penta" -> "Pentavalente".
        4.  Para cada vacina, identifique a dose (ex: "1ª Dose", "Reforço").
        5.  Retorne APENAS um objeto JSON com as chaves "nome_paciente", "data_nascimento", "vacinas_administradas" (lista de objetos com "vacina" e "dose").
        Texto para analisar: --- {texto_extraido} ---
        """
        model = genai.GenerativeModel(MODELO_GEMINI)
        response = model.generate_content(prompt)
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        dados_extraidos = json.loads(json_string)
        if "nome_paciente" in dados_extraidos and "data_nascimento" in dados_extraidos and "vacinas_administradas" in dados_extraidos:
            return dados_extraidos
        else: return None
    except Exception as e:
        st.error(f"Erro ao processar a resposta da IA (Gemini - Vacinação): {e}")
        return None

def extrair_dados_clinicos_com_google_gemini(texto_prontuario: str, api_key: str):
    try:
        genai.configure(api_key=api_key)
        prompt = f"""
        Sua tarefa é analisar o texto de um prontuário médico e extrair informações clínicas chave.
        O foco deve ser em Diagnósticos e Medicamentos.
        Instruções:
        1.  Extraia Diagnósticos: Identifique todas as condições médicas. Priorize crónicas (HAS, Diabetes, Asma).
        2.  Extraia Medicamentos: Identifique todos os medicamentos de uso contínuo, incluindo a dosagem, se disponível.
        3.  Retorne APENAS um objeto JSON com as chaves: "diagnosticos" (lista de strings) e "medicamentos" (lista de strings).
        Texto do Prontuário para analisar: --- {texto_prontuario} ---
        """
        model = genai.GenerativeModel(MODELO_GEMINI)
        response = model.generate_content(prompt)
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        dados_extraidos = json.loads(json_string)
        if "diagnosticos" in dados_extraidos and "medicamentos" in dados_extraidos:
            return dados_extraidos
        else: return None
    except Exception as e:
        st.error(f"Erro ao processar a resposta da IA (Gemini - Clínico): {e}")
        return None


def salvar_no_sheets(dados, planilha):
    try:
        cabecalhos = planilha.row_values(1)
        if 'ID' not in dados or not dados['ID']: dados['ID'] = f"ID-{int(time.time())}"
        
        telefone_padronizado = padronizar_telefone(dados.get('Telefone', ''))
        # Garante a formatação para exibição na planilha (ex: (21) 98765-4321)
        if telefone_padronizado:
             if len(telefone_padronizado) == 11:
                dados['Telefone'] = f"({telefone_padronizado[:2]}) {telefone_padronizado[2:7]}-{telefone_padronizado[7:]}"
             else:
                dados['Telefone'] = f"({telefone_padronizado[:2]}) {telefone_padronizado[2:6]}-{telefone_padronizado[6:]}"
        else:
            dados['Telefone'] = ""

        dados['Data de Registo'] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        mapeamento_chaves = {'Nome da Mãe': 'Mãe', 'Nome do Pai': 'Pai'}
        
        nova_linha = []
        for cabecalho in cabecalhos:
            valor = dados.get(cabecalho)
            if valor is None:
                valor = dados.get(mapeamento_chaves.get(cabecalho, cabecalho), "")
            
            nova_linha.append(str(valor))

        planilha.append_row(nova_linha)
        st.success(f"✅ Dados de '{dados.get('Nome Completo', 'Desconhecido')}' salvos com sucesso!")
        st.balloons()
        st.cache_data.clear()
        
    except Exception as e:
        st.error(f"Erro ao salvar na planilha: {e}")

# --- Funções de Manipulação de PDF (ReportLab) ---

def preencher_pdf_formulario(paciente_dados):
    # Simulação de preenchimento de um formulário IVCF-20 (Índice de Vulnerabilidade Clínica e Funcional)
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # Título
    p.setFont("Helvetica-Bold", 14)
    p.drawString(cm, height - 2*cm, "Formulário IVCF-20 (Relatório Inteligente)")
    p.setFont("Helvetica", 10)
    
    # Dados Cadastrais
    y_pos = height - 3*cm
    p.drawString(cm, y_pos, f"Nome: {paciente_dados.get('Nome Completo', 'N/A')}")
    y_pos -= 0.5*cm
    p.drawString(cm, y_pos, f"Nascimento: {paciente_dados.get('Data de Nascimento', 'N/A')}")
    p.drawString(8*cm, y_pos, f"CPF: {paciente_dados.get('CPF', 'N/A')}")
    y_pos -= 0.5*cm
    p.drawString(cm, y_pos, f"Telefone: {paciente_dados.get('Telefone', 'N/A')}")
    p.drawString(8*cm, y_pos, f"Família: {paciente_dados.get('FAMÍLIA', 'N/A')}")
    y_pos -= 1.0*cm
    
    # Seções de Saúde
    p.setFont("Helvetica-Bold", 12)
    p.drawString(cm, y_pos, "Informações Clínicas (Extraídas do Prontuário):")
    p.setFont("Helvetica", 10)
    y_pos -= 0.5*cm
    
    # Diagnósticos (simulados ou extraídos)
    diagnosticos = paciente_dados.get('Condição', 'N/A')
    p.drawString(cm, y_pos, f"Diagnósticos Principais: {diagnosticos}")
    y_pos -= 0.5*cm
    
    # Medicamentos
    medicamentos = paciente_dados.get('Medicamentos', 'N/A')
    p.drawString(cm, y_pos, f"Medicamentos Contínuos: {medicamentos}")
    y_pos -= 0.5*cm
    
    # Espaço para o QR Code de acesso
    y_pos -= 1.0*cm
    qr_url = f"https://seusistema.streamlit.app?id={paciente_dados.get('ID', 'N/A')}"
    img = qrcode.make(qr_url)
    img_buffer = io.BytesIO()
    img.save(img_buffer, format="PNG")
    img_reader = ImageReader(img_buffer)
    p.drawImage(img_reader, 15*cm, height - 7.5*cm, width=3*cm, height=3*cm)
    p.drawString(14*cm, height - 4*cm, "Acesso Rápido (QR Code)")
    
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer

def gerar_etiqueta(paciente_dados):
    buffer = BytesIO()
    # Tamanho da etiqueta 5x8 cm
    p = canvas.Canvas(buffer, pagesize=(5*cm, 8*cm))
    width, height = (5*cm, 8*cm)
    
    p.setFont("Helvetica-Bold", 10)
    p.drawString(0.5*cm, height - 0.7*cm, "FICHA CADASTRO UBS")
    p.setFont("Helvetica", 8)
    
    y_pos = height - 1.5*cm
    p.drawString(0.5*cm, y_pos, f"Nome: {paciente_dados.get('Nome Completo', 'N/A')}")
    y_pos -= 0.4*cm
    p.drawString(0.5*cm, y_pos, f"Família: {paciente_dados.get('FAMÍLIA', 'N/A')}")
    y_pos -= 0.4*cm
    p.drawString(0.5*cm, y_pos, f"Nasc: {paciente_dados.get('Data de Nascimento', 'N/A')}")
    y_pos -= 0.4*cm
    p.drawString(0.5*cm, y_pos, f"ID: {paciente_dados.get('ID', 'N/A')}")
    
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer

def preencher_capa_prontuario(paciente_dados):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    p.setFont("Helvetica-Bold", 16)
    p.drawString(2*cm, height - 2*cm, "CAPA DE PRONTUÁRIO CLÍNICO")
    
    p.setFont("Helvetica", 12)
    y_pos = height - 4*cm
    p.drawString(2*cm, y_pos, f"Nome Completo: {paciente_dados.get('Nome Completo', 'N/A')}")
    y_pos -= 1*cm
    p.drawString(2*cm, y_pos, f"Data de Nascimento: {paciente_dados.get('Data de Nascimento', 'N/A')}")
    p.drawString(12*cm, y_pos, f"CPF: {paciente_dados.get('CPF', 'N/A')}")
    y_pos -= 1*cm
    p.drawString(2*cm, y_pos, f"Família ID: {paciente_dados.get('FAMÍLIA', 'N/A')}")
    p.drawString(12*cm, y_pos, f"ID Único: {paciente_dados.get('ID', 'N/A')}")
    
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer


# --- PÁGINAS DO APP ---

def pagina_inicial():
    st.title("Bem-vindo ao Sistema de Gestão de Pacientes Inteligente")
    st.markdown("""
        Este aplicativo foi desenvolvido para otimizar a gestão de pacientes e a comunicação em unidades de saúde. 
        **A navegação lateral agora inclui ferramentas de automação proativa!**
    """)
    st.write("---")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🤖 Coleta Inteligente de Fichas")
        st.markdown("Extração automática de dados de fichas (digitadas ou manuscritas) com validação.")
    with col2:
        st.subheader("🚨 Automação Proativa de Saúde")
        st.markdown("Identificação automática de pacientes em idade de vacina e geração de links de WhatsApp.")

def pagina_automacao_vacinacao(planilha):
    st.title("🚨 Automação Proativa: Alerta de Vacinação")
    st.info("Esta ferramenta verifica a base de dados e identifica crianças que estão **na idade exata ou até 1 mês antes** para uma dose no Calendário PNI.")
    df = ler_dados_da_planilha(planilha)
    df_criancas = df[(df['Idade Meses'] >= 0) & (df['Idade Meses'] <= 72) & (df['Telefone Limpo'].notna())].copy()
    if df_criancas.empty:
        st.warning("Não há crianças com telefone válido (0-6 anos) para checagem proativa.")
        return

    st.subheader(f"Total de Crianças com Telefone Válido: {len(df_criancas)}")
    dados_alerta = []
    
    for index, paciente in df_criancas.iterrows():
        idade_atual_meses = paciente['Idade Meses']
        
        for regra in CALENDARIO_PNI:
            idade_recomendada_meses = regra['idade_meses']
            
            # Checa se o paciente está no 'timing' certo (agora ou até 1 mês antes)
            if idade_recomendada_meses == idade_atual_meses or idade_recomendada_meses == idade_atual_meses + 1:
                
                if idade_recomendada_meses == idade_atual_meses + 1:
                    status = f"PRÓXIMO (falta 1 mês para {idade_recomendada_meses} meses)"
                else:
                    status = f"NA IDADE (exatamente {idade_recomendada_meses} meses)"
                
                # Assume que precisa de alerta se não tivermos informação de vacinações na planilha
                dados_alerta.append({
                    "Nome Completo": paciente['Nome Completo'],
                    "Telefone": paciente['Telefone'],
                    "Idade Atual (Meses)": idade_atual_meses,
                    "Vacina/Dose": f"{regra['vacina']} ({regra['dose']})",
                    "Idade Recomendada (Meses)": idade_recomendada_meses,
                    "Status do Alerta": status,
                    "Telefone Limpo": paciente['Telefone Limpo']
                })
    
    if dados_alerta:
        df_alerta = pd.DataFrame(dados_alerta)
        df_alerta.drop_duplicates(subset=['Nome Completo', 'Idade Recomendada (Meses)'], inplace=True)

        st.markdown("---")
        st.subheader(f"Pacientes Identificados para Alerta Proativo ({len(df_alerta)})")
        
        for index, row in df_alerta.iterrows():
            col1, col2, col3 = st.columns([3, 1, 1])
            col1.write(f"**{row['Nome Completo']}** | {row['Vacina/Dose']}")
            col2.write(f"Idade Atual: {row['Idade Atual (Meses)']}m")
            col3.write(f"Alerta: **{row['Status do Alerta']}**")
            
            link_whatsapp = gerar_url_whatsapp_proativo(
                row['Telefone Limpo'], 
                row['Nome Completo'], 
                row['Vacina/Dose'], 
                row['Idade Recomendada (Meses)']
            )
            st.link_button("Abrir WhatsApp e Enviar Alerta ↗️", link_whatsapp, use_container_width=False, type="primary")
            st.markdown("---")
            
    else:
        st.info("Nenhuma criança identificada na faixa etária exata para vacinas no próximo mês.")

def pagina_coleta(planilha):
    st.title("🤖 COLETA INTELIGENTE DE FICHAS")
    st.header("1. Envie uma ou mais imagens de fichas")
    df_existente = ler_dados_da_planilha(planilha)
    uploaded_files = st.file_uploader("Pode selecionar vários arquivos de uma vez", type=["jpg", "jpeg", "png"], accept_multiple_files=True)
    if 'processados' not in st.session_state: st.session_state.processados = []
    
    if uploaded_files:
        proximo_arquivo = next((f for f in uploaded_files if f.file_id not in st.session_state.processados), None)
        
        if proximo_arquivo:
            st.subheader(f"Processando Ficha: `{proximo_arquivo.name}`")
            st.image(Image.open(proximo_arquivo), width=400)
            file_bytes = proximo_arquivo.getvalue()
            
            with st.spinner("Extraindo texto via OCR..."):
                texto_extraido = ocr_space_api(file_bytes, st.secrets["OCRSPACEKEY"])
            
            if texto_extraido:
                with st.spinner("Analisando dados com Gemini e normalizando..."):
                    dados_extraidos = extrair_dados_com_google_gemini(texto_extraido, st.secrets["GOOGLE_API_KEY"])
                
                duplicado_cpf, duplicado_cns = False, False
                if dados_extraidos and df_existente is not None and not df_existente.empty:
                    # Checagem de duplicidade (Melhoria de Automação)
                    cpf_a_verificar = dados_extraidos.get('CPF')
                    cns_a_verificar = dados_extraidos.get('CNS')
                    if cpf_a_verificar and any(df_existente['CPF'].astype(str).str.replace(r'\D', '', regex=True) == cpf_a_verificar):
                        duplicado_cpf = True
                    if cns_a_verificar and any(df_existente['CNS'].astype(str).str.replace(r'\D', '', regex=True) == cns_a_verificar):
                        duplicado_cns = True

                    if duplicado_cpf or duplicado_cns:
                        st.error("⚠️ Alerta de Duplicado: Paciente já registado com este CPF/CNS.")
                
                if dados_extraidos:
                    with st.form(key=f"form_{proximo_arquivo.file_id}"):
                        st.subheader("2. Confirme e salve os dados (Normalizados)")
                        dados_para_salvar = {}
                        
                        col_id, col_fam = st.columns(2)
                        dados_para_salvar['ID'] = col_id.text_input("ID (Gerado automaticamente se vazio)", value=dados_extraidos.get("ID", ""))
                        dados_para_salvar['FAMÍLIA'] = col_fam.text_input("FAMÍLIA", value=dados_extraidos.get("FAMÍLIA", ""))
                        dados_para_salvar['Nome Completo'] = st.text_input("Nome Completo", value=dados_extraidos.get("Nome Completo", ""))
                        
                        col_nasc, col_sexo = st.columns(2)
                        dados_para_salvar['Data de Nascimento'] = col_nasc.text_input("Data de Nascimento (DD/MM/AAAA)", value=dados_extraidos.get("Data de Nascimento", ""))
                        dados_para_salvar['Sexo'] = col_sexo.text_input("Sexo (Masculino/Feminino)", value=dados_extraidos.get("Sexo", ""))

                        col_cpf, col_cns = st.columns(2)
                        dados_para_salvar['CPF'] = col_cpf.text_input("CPF (Somente números)", value=dados_extraidos.get("CPF", ""))
                        dados_para_salvar['CNS'] = col_cns.text_input("CNS (Somente números)", value=dados_extraidos.get("CNS", ""))
                        
                        dados_para_salvar['Telefone'] = st.text_input("Telefone (Padrão: DDD + Número)", value=dados_extraidos.get("Telefone", ""))
                        dados_para_salvar['Mãe'] = st.text_input("Nome da Mãe", value=dados_extraidos.get("Nome da Mãe", "")) 
                        dados_para_salvar['Pai'] = st.text_input("Nome do Pai", value=dados_extraidos.get("Nome do Pai", ""))
                        dados_para_salvar['Município de Nascimento'] = st.text_input("Município de Nascimento", value=dados_extraidos.get("Município de Nascimento", ""))

                        if st.form_submit_button("✅ Salvar Dados Desta Ficha"):
                            if duplicado_cpf or duplicado_cns:
                                st.error("⚠️ Registo não salvo: Duplicidade encontrada.")
                            else:
                                salvar_no_sheets(dados_para_salvar, planilha)
                                st.session_state.processados.append(proximo_arquivo.file_id)
                                st.rerun()
                else: st.error("A IA não conseguiu extrair dados desta ficha.")
            else: st.error("Não foi possível extrair texto desta imagem via OCR.")
        elif len(uploaded_files) > 0:
            st.success("🎉 Todas as fichas enviadas foram processadas!")
            if st.button("Limpar lista para enviar novas imagens"):
                st.session_state.processados = []; st.rerun()

def pagina_analise_vacinacao(planilha):
    st.title("💉 Análise de Caderneta de Vacinação")
    uploaded_file = st.file_uploader("Envie a imagem ou PDF da caderneta de vacinação (parte das doses)", type=["jpg", "jpeg", "png", "pdf"])
    if 'dados_vacina' not in st.session_state: st.session_state.dados_vacina = {}
    
    if uploaded_file:
        file_bytes = uploaded_file.getvalue()
        if uploaded_file.type == "application/pdf":
            with st.spinner("Lendo PDF e extraindo texto com OCR (pode levar tempo)..."):
                texto_extraido = ler_texto_prontuario(file_bytes, st.secrets["OCRSPACEKEY"])
        else:
            with st.spinner("Extraindo texto via OCR..."):
                texto_extraido = ocr_space_api(file_bytes, st.secrets["OCRSPACEKEY"])
        
        if texto_extraido:
            with st.expander("Ver Texto Bruto Extraído"):
                st.text(texto_extraido)
                
            with st.spinner("Analisando vacinas com Gemini..."):
                dados_extraidos = extrair_dados_vacinacao_com_google_gemini(texto_extraido, st.secrets["GOOGLE_API_KEY"])
            
            if dados_extraidos:
                st.session_state.dados_vacina = dados_extraidos
                st.subheader("1. Confirme os Dados Extraídos")
                
                # Edição dos dados
                nome_paciente = st.text_input("Nome do Paciente", value=dados_extraidos.get('nome_paciente', ''))
                data_nascimento = st.text_input("Data de Nascimento (DD/MM/AAAA)", value=dados_extraidos.get('data_nascimento', ''))
                st.markdown("**Vacinas Administradas:**")
                vacinas_lista = dados_extraidos.get('vacinas_administradas', [])
                for i, v in enumerate(vacinas_lista):
                    col1, col2 = st.columns(2)
                    col1.text_input(f"Vacina {i+1}", value=v.get('vacina', ''), key=f"vacina_{i}")
                    col2.text_input(f"Dose {i+1}", value=v.get('dose', ''), key=f"dose_{i}")

                if st.button("Analisar Situação Vacinal"):
                    # Recria a lista de vacinas após edição manual
                    vacinas_administradas = []
                    for i in range(len(vacinas_lista)):
                        vacinas_administradas.append({
                            "vacina": st.session_state[f"vacina_{i}"],
                            "dose": st.session_state[f"dose_{i}"]
                        })

                    relatorio = analisar_carteira_vacinacao(data_nascimento, vacinas_administradas)
                    
                    st.subheader("2. Resultado da Análise (PNI)")
                    if "erro" in relatorio:
                        st.error(relatorio["erro"])
                        return
                    
                    st.success(f"✅ Em Dia: {len(relatorio['em_dia'])} doses tomadas no prazo.")
                    st.warning(f"⚠️ **Em Atraso/Pendentes**: {len(relatorio['em_atraso'])} doses para a idade de {calcular_idade_meses(datetime.strptime(data_nascimento, '%d/%m/%Y'))} meses.")
                    st.info(f"➡️ Próximas Doses: {len(relatorio['proximas_doses'])} doses futuras.")
                    
                    st.markdown("---")
                    st.markdown("#### Detalhes das Doses em Atraso/Pendentes")
                    for pendente in relatorio['em_atraso']:
                        st.error(f"- **{pendente['vacina']}** ({pendente['dose']}) | Idade Recomendada: {pendente['idade_meses']} meses.")
            else:
                st.error("Falha ao extrair nome/data/vacinas. Tente ajustar a imagem ou o formato.")

def pagina_importar_prontuario(planilha):
    st.title("📑 Importação e Resumo de Prontuário Clínico")
    st.info("Envie um PDF de prontuário (digitalizado ou de texto) para que a IA extraia diagnósticos e medicamentos.")
    df = ler_dados_da_planilha(planilha)
    
    st.subheader("1. Selecione o Paciente e Envie o Prontuário")
    lista_pacientes = sorted(df['Nome Completo'].tolist())
    paciente_selecionado_nome = st.selectbox("Paciente para o qual o prontuário será importado:", lista_pacientes, index=None, placeholder="Selecione...")
    uploaded_file = st.file_uploader("Envie o ficheiro PDF do Prontuário", type=["pdf"])
    
    if paciente_selecionado_nome and uploaded_file:
        paciente_dados = df[df['Nome Completo'] == paciente_selecionado_nome].iloc[0].to_dict()
        file_bytes = uploaded_file.getvalue()
        
        with st.spinner("Extraindo texto do PDF (pode levar tempo)..."):
            texto_extraido = ler_texto_prontuario(file_bytes, st.secrets["OCRSPACEKEY"])
            
        if texto_extraido:
            with st.expander("Ver Texto Bruto Extraído"):
                st.text(texto_extraido)
                
            with st.spinner("Analisando dados clínicos com Gemini..."):
                dados_clinicos = extrair_dados_clinicos_com_google_gemini(texto_extraido, st.secrets["GOOGLE_API_KEY"])
            
            if dados_clinicos:
                st.subheader("2. Confirme o Resumo Clínico")
                
                diagnosticos_str = "\n".join(dados_clinicos.get('diagnosticos', []))
                medicamentos_str = "\n".join(dados_clinicos.get('medicamentos', []))
                
                # Campos de Confirmação
                diagnosticos_confirmados = st.text_area("Diagnósticos Principais (Condição):", value=diagnosticos_str, height=150)
                medicamentos_confirmados = st.text_area("Medicamentos de Uso Contínuo:", value=medicamentos_str, height=150)
                
                if st.button(f"Salvar Resumo Clínico no Registo de {paciente_selecionado_nome}"):
                    try:
                        planilha_sheet = conectar_planilha() # Re-conecta para operações de update
                        if planilha_sheet:
                            paciente_id = paciente_dados['ID']
                            cell = planilha_sheet.find(str(paciente_id))
                            row_index = cell.row
                            
                            # Atualizar colunas específicas
                            cabecalhos = planilha_sheet.row_values(1)
                            condicao_col = cabecalhos.index('Condição') + 1 if 'Condição' in cabecalhos else -1
                            medicamentos_col = cabecalhos.index('Medicamentos') + 1 if 'Medicamentos' in cabecalhos else -1
                            
                            if condicao_col != -1:
                                planilha_sheet.update_cell(row_index, condicao_col, diagnosticos_confirmados)
                            if medicamentos_col != -1:
                                planilha_sheet.update_cell(row_index, medicamentos_col, medicamentos_confirmados)
                                
                            st.success(f"✅ Dados clínicos de {paciente_selecionado_nome} atualizados com sucesso!")
                            st.cache_data.clear(); st.rerun()
                        
                    except Exception as e:
                        st.error(f"Erro ao salvar dados clínicos: {e}")
            else:
                st.error("A IA não conseguiu extrair diagnósticos ou medicamentos de forma estruturada.")
        else:
            st.error("Não foi possível extrair texto do prontuário. Tente um ficheiro com melhor qualidade.")

def pagina_pesquisa(planilha):
    # ... (Conteúdo da página de pesquisa/gestão, incluindo o formulário de edição)
    st.title("🔎 Gestão de Pacientes")
    # ... (Lógica de navegação para dashboard de família) ...
    if 'familia_selecionada_id' in st.session_state and st.session_state.familia_selecionada_id:
        if st.button("⬅️ Voltar para a Pesquisa"):
            del st.session_state.familia_selecionada_id
            st.rerun()
    df = ler_dados_da_planilha(planilha)
    if df.empty:
        st.warning("Ainda não há dados na planilha para pesquisar."); return
    if 'familia_selecionada_id' in st.session_state and st.session_state.familia_selecionada_id:
        desenhar_dashboard_familia(st.session_state.familia_selecionada_id, df)
        return
    st.info("Use a pesquisa para encontrar um paciente e depois expandir para ver detalhes, editar, apagar ou ver o dashboard da família.", icon="ℹ️")
    colunas_pesquisaveis = ["Nome Completo", "CPF", "CNS", "Mãe", "ID", "FAMÍLIA"]
    coluna_selecionada = st.selectbox("Pesquisar por:", colunas_pesquisaveis)
    termo_pesquisa = st.text_input("Digite o termo de pesquisa:")
    if termo_pesquisa:
        resultados = df[df[coluna_selecionada].astype(str).str.contains(termo_pesquisa, case=False, na=False)]
        st.markdown(f"**{len(resultados)}** resultado(s) encontrado(s):")
        for index, row in resultados.iterrows():
            id_paciente = row['ID']
            with st.expander(f"**{row['Nome Completo']}** (ID: {id_paciente})"):
                st.dataframe(row.to_frame().T, hide_index=True)
                botoes = st.columns(3)
                with botoes[0]:
                    if st.button("✏️ Editar Dados", key=f"edit_{id_paciente}"):
                        st.session_state['patient_to_edit'] = row.to_dict(); st.rerun()
                with botoes[1]:
                    if st.button("🗑️ Apagar Registo", key=f"delete_{id_paciente}"):
                        try:
                            cell = planilha.find(str(id_paciente))
                            planilha.delete_rows(cell.row)
                            st.success(f"Registo de {row['Nome Completo']} apagado com sucesso!")
                            st.cache_data.clear(); time.sleep(1); st.rerun()
                        except gspread.exceptions.CellNotFound:
                            st.error(f"Erro: Não foi possível encontrar o paciente com ID {id_paciente} para apagar.")
                        except Exception as e:
                            st.error(f"Ocorreu um erro ao apagar: {e}")
                with botoes[2]:
                    familia_id = row.get('FAMÍLIA')
                    if familia_id:
                        if st.button("👨‍👩‍👧 Ver Dashboard da Família", key=f"fam_{id_paciente}"):
                            st.session_state.familia_selecionada_id = familia_id; st.rerun()
    if 'patient_to_edit' in st.session_state:
        st.markdown("---")
        st.subheader("Editando Paciente")
        patient_data = st.session_state['patient_to_edit']
        with st.form(key="edit_form"):
            edited_data = {}
            for key, value in patient_data.items():
                if key not in ['Data de Nascimento DT', 'Idade', 'Idade Meses', 'Telefone Limpo']:
                    display_key = 'Nome da Mãe' if key == 'Mãe' else ('Nome do Pai' if key == 'Pai' else key)
                    edited_data[key] = st.text_input(f"{display_key}", value=value, key=f"edit_{key}")
            
            if st.form_submit_button("Salvar Alterações"):
                try:
                    cell = planilha.find(str(patient_data['ID']))
                    cabecalhos = planilha.row_values(1)
                    
                    if 'Telefone' in edited_data:
                        telefone_padronizado = padronizar_telefone(edited_data['Telefone'])
                        if telefone_padronizado:
                            if len(telefone_padronizado) == 11:
                                edited_data['Telefone'] = f"({telefone_padronizado[:2]}) {telefone_padronizado[2:7]}-{telefone_padronizado[7:]}"
                            else:
                                edited_data['Telefone'] = f"({telefone_padronizado[:2]}) {telefone_padronizado[2:6]}-{telefone_padronizado[6:]}"
                        else:
                            edited_data['Telefone'] = ""

                    update_values = []
                    for h in cabecalhos:
                        valor = edited_data.get(h)
                        if h == 'Mãe': valor = edited_data.get('Mãe', patient_data.get('Mãe', ''))
                        elif h == 'Pai': valor = edited_data.get('Pai', patient_data.get('Pai', ''))
                        
                        update_values.append(str(valor if valor is not None else ""))
                    
                    planilha.update(f'A{cell.row}', [update_values])
                    st.success("Dados do paciente atualizados com sucesso!")
                    del st.session_state['patient_to_edit']
                    st.cache_data.clear(); time.sleep(1); st.rerun()
                except Exception as e:
                    st.error(f"Ocorreu um erro ao salvar: {e}")

def desenhar_dashboard_familia(familia_id, df):
    st.title(f"👨‍👩‍👧 Dashboard da Família: {familia_id}")
    df_familia = df[df['FAMÍLIA'] == familia_id].copy()
    st.dataframe(df_familia.drop(columns=['Telefone Limpo', 'Data de Nascimento DT', 'Idade Meses']), hide_index=True)
    
    st.subheader("Idades e Gênero na Família")
    col1, col2 = st.columns(2)
    with col1:
        fig, ax = plt.subplots()
        ax.hist(df_familia['Idade'], bins=5, edgecolor='black', color=HexColor('#0072b2'))
        ax.set_title("Distribuição de Idades")
        ax.set_xlabel("Idade (anos)")
        ax.set_ylabel("Nº de Membros")
        st.pyplot(fig)
    with col2:
        fig, ax = plt.subplots()
        sexo_counts = df_familia['Sexo'].str.strip().str.capitalize().value_counts()
        sexo_counts.plot.pie(ax=ax, autopct='%1.1f%%', startangle=90, colors=['#f05b5b','#00a65a', '#f39c12'])
        ax.axis('equal')
        ax.set_ylabel('')
        ax.set_title("Membros por Gênero")
        st.pyplot(fig)

def pagina_dashboard(planilha):
    # ... (Conteúdo do dashboard)
    st.title("📊 Dashboard de Dados")
    df_original = ler_dados_da_planilha(planilha)
    if df_original.empty: st.warning("Ainda não há dados na planilha."); return
    
    st.sidebar.header("Filtros do Dashboard")
    municipios = sorted(df_original['Município de Nascimento'].astype(str).unique())
    municipios_selecionados = st.sidebar.multiselect("Filtrar por Município:", options=municipios, default=municipios)
    idade_max = int(df_original['Idade'].max()) if not df_original['Idade'].empty else 100
    faixa_etaria = st.sidebar.slider("Filtrar por Faixa Etária:", min_value=0, max_value=idade_max, value=(0, idade_max))
    df_filtrado = df_original[
        (df_original['Município de Nascimento'].isin(municipios_selecionados)) &
        (df_original['Idade'] >= faixa_etaria[0]) &
        (df_original['Idade'] <= faixa_etaria[1])
    ]
    if df_filtrado.empty: st.warning("Nenhum dado encontrado."); return
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total de Fichas", len(df_filtrado))
    idades_validas = df_filtrado.loc[df_filtrado['Idade'] > 0, 'Idade']
    idade_media = idades_validas.mean() if not idades_validas.empty else 0
    col2.metric("Idade Média", f"{idade_media:.1f} anos" if idade_media > 0 else "N/A")
    sexo_counts = df_filtrado['Sexo'].str.strip().str.capitalize().value_counts()
    col3.metric("Sexo (Moda)", sexo_counts.index[0] if not sexo_counts.empty else "N/A")
    st.markdown("---")
    
    gcol1, gcol2 = st.columns(2)
    with gcol1:
        st.markdown("### Pacientes por Município")
        st.bar_chart(df_filtrado['Município de Nascimento'].value_counts())
    with gcol2:
        st.markdown("### Distribuição por Sexo")
        fig, ax = plt.subplots(figsize=(5, 3))
        sexo_counts.plot.pie(ax=ax, autopct='%1.1f%%', startangle=90, colors=['#66b3ff','#ff9999', '#99ff99'])
        ax.axis('equal'); st.pyplot(fig)

    st.markdown("---")
    st.markdown("### Tabela de Dados (com filtros aplicados)")
    st.dataframe(df_filtrado)

def pagina_whatsapp(planilha):
    st.title("📱 Enviar Mensagens de WhatsApp (Manual)")
    df = ler_dados_da_planilha(planilha)
    if df.empty: st.warning("Ainda não há dados na planilha."); return
    
    st.subheader("1. Escreva a sua mensagem")
    mensagem_padrao = st.text_area("Mensagem:", "Olá, [NOME]! Sua solicitação foi atendida. Por favor, entre em contato para mais detalhes.", height=150)
    st.subheader("2. Escolha o paciente e envie")
    df_com_telefone = df[df['Telefone Limpo'].notna()].copy() 
    for index, row in df_com_telefone.iterrows():
        nome = row['Nome Completo']
        telefone = row['Telefone Limpo']
        if telefone is None: continue
        mensagem_personalizada = mensagem_padrao.replace("[NOME]", nome.split()[0])
        whatsapp_url = f"https://wa.me/55{telefone}?text={urllib.parse.quote(mensagem_personalizada)}"
        col1, col2 = st.columns([3, 1])
        col1.text(f"{nome} - ({row['Telefone']})")
        col2.link_button("Enviar Mensagem ↗️", whatsapp_url, use_container_width=True)

def pagina_gerar_documentos(planilha):
    st.title("📄 Gerador de Documentos")
    df = ler_dados_da_planilha(planilha)
    if df.empty: st.warning("Não há pacientes na base de dados para gerar documentos."); return
    
    lista_pacientes = sorted(df['Nome Completo'].tolist())
    paciente_selecionado_nome = st.selectbox("Escolha um paciente:", lista_pacientes, index=None, placeholder="Selecione...")
    
    if paciente_selecionado_nome:
        paciente_dados = df[df['Nome Completo'] == paciente_selecionado_nome].iloc[0]
        
        st.markdown("---")
        st.subheader("Escolha o Documento e Gere")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("Gerar Formulário IVCF-20 (Simulado)", use_container_width=True):
                pdf_buffer = preencher_pdf_formulario(paciente_dados.to_dict())
                if pdf_buffer:
                    st.download_button(
                        label="📥 Descarregar Formulário (PDF)",
                        data=pdf_buffer,
                        file_name=f"formulario_ivcf20_{paciente_selecionado_nome.replace(' ', '_')}.pdf",
                        mime="application/pdf"
                    )
        with col2:
            if st.button("Gerar Capa de Prontuário", use_container_width=True):
                pdf_buffer = preencher_capa_prontuario(paciente_dados.to_dict())
                if pdf_buffer:
                    st.download_button(
                        label="📥 Descarregar Capa (PDF)",
                        data=pdf_buffer,
                        file_name=f"capa_prontuario_{paciente_selecionado_nome.replace(' ', '_')}.pdf",
                        mime="application/pdf"
                    )
        with col3:
            if st.button("Gerar Etiqueta de Arquivo (5x8cm)", use_container_width=True):
                pdf_buffer = gerar_etiqueta(paciente_dados.to_dict())
                if pdf_buffer:
                    st.download_button(
                        label="📥 Descarregar Etiqueta (PDF)",
                        data=pdf_buffer,
                        file_name=f"etiqueta_{paciente_selecionado_nome.replace(' ', '_')}.pdf",
                        mime="application/pdf"
                    )

def pagina_gerador_qrcode(planilha):
    st.title("🔗 Gerador de QR Code de Acesso")
    st.info("Gera um QR Code que pode ser colado no prontuário ou documento, contendo um link para o ID do paciente.")
    df = ler_dados_da_planilha(planilha)
    if df.empty: st.warning("Não há pacientes."); return
    
    lista_pacientes = sorted(df['Nome Completo'].tolist())
    paciente_selecionado_nome = st.selectbox("Escolha um paciente:", lista_pacientes, index=None, placeholder="Selecione...")
    
    if paciente_selecionado_nome:
        paciente_dados = df[df['Nome Completo'] == paciente_selecionado_nome].iloc[0]
        paciente_id = paciente_dados.get('ID', 'N/A')
        
        # Link de destino (simulado - deve ser o link de acesso ao sistema com o ID)
        qr_url = f"https://seusistema.streamlit.app/resumo?id={paciente_id}"
        
        st.markdown(f"**ID:** `{paciente_id}`")
        st.markdown(f"**URL:** `{qr_url}`")
        
        # Geração do QR Code
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(qr_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Converte para bytes para exibição e download
        img_buffer = BytesIO()
        img.save(img_buffer, format="PNG")
        img_buffer.seek(0)
        
        col1, col2 = st.columns([1, 2])
        with col1:
            st.image(img_buffer, caption="QR Code", width=200)
            
            img_buffer.seek(0) # Volta para o início para o download
            st.download_button(
                label="📥 Descarregar QR Code (PNG)",
                data=img_buffer,
                file_name=f"qrcode_{paciente_id}.png",
                mime="image/png"
            )

# --- Função de Página de Resumo (para uso em QR Code) ---
def pagina_dashboard_resumo(planilha):
    # Esta é a página de visualização pública, acessada via URL/QR Code
    st.title("🔍 Resumo de Paciente")
    query_params = st.query_params
    paciente_id = query_params.get("id")
    
    if not paciente_id:
        st.warning("Nenhum ID de paciente fornecido na URL.")
        return
        
    df = ler_dados_da_planilha(planilha)
    if df.empty:
        st.error("Falha ao carregar a base de dados.")
        return
        
    paciente_data = df[df['ID'] == paciente_id]
    if paciente_data.empty:
        st.error(f"Paciente com ID '{paciente_id}' não encontrado.")
        return
        
    paciente = paciente_data.iloc[0].to_dict()
    
    st.header(paciente['Nome Completo'])
    st.markdown(f"**ID:** `{paciente['ID']}` | **Família:** `{paciente['FAMÍLIA']}`")
    st.markdown(f"**Nascimento:** `{paciente['Data de Nascimento']}` ({paciente['Idade']} anos)")
    st.markdown(f"**Telefone:** `{paciente['Telefone']}`")
    
    st.subheader("Informações Clínicas")
    st.markdown(f"**Condição/Diagnósticos:** {paciente.get('Condição', 'Não Registrado')}")
    st.markdown(f"**Medicamentos:** {paciente.get('Medicamentos', 'Não Registrado')}")
    
    # Adicionar um link de retorno para o sistema principal, se necessário


# --- FUNÇÃO MAIN ---
def main():
    # Verifica se a página de resumo está sendo chamada via query params
    query_params = st.query_params
    if query_params.get("page") == "resumo":
        st.set_page_config(page_title="Resumo de Pacientes", layout="centered")
        try:
            planilha_conectada = conectar_planilha()
            if planilha_conectada:
                pagina_dashboard_resumo(planilha_conectada)
            else:
                st.error("Falha na conexão com a base de dados.")
        except Exception as e:
            st.error(f"Ocorreu um erro crítico: {e}")
            st.stop()
        return

    # Configuração da página principal (App Completo)
    st.set_page_config(page_title="Coleta Inteligente - Central de Saúde", page_icon="🤖", layout="wide")
    st.sidebar.title("Navegação")
    
    try:
        planilha_conectada = conectar_planilha()
    except Exception as e:
        st.error(f"Não foi possível inicializar os serviços. Verifique seus segredos. Erro: {e}")
        st.stop()
        
    if planilha_conectada is None:
        st.error("A conexão com a planilha falhou.")
        st.stop()
    
    paginas = {
        "🏠 Início": pagina_inicial,
        "🚨 Alerta Proativo Vacinação": lambda: pagina_automacao_vacinacao(planilha_conectada),
        "Importar Fichas (OCR/IA)": lambda: pagina_coleta(planilha_conectada),
        "Análise de Vacinação (IA)": lambda: pagina_analise_vacinacao(planilha_conectada),
        "Importar Prontuário (IA)": lambda: pagina_importar_prontuario(planilha_conectada),
        "🔎 Gestão de Pacientes": lambda: pagina_pesquisa(planilha_conectada),
        "📊 Dashboard": lambda: pagina_dashboard(planilha_conectada),
        "Gerar Documentos (PDF)": lambda: pagina_gerar_documentos(planilha_conectada),
        "Gerador de QR Code": lambda: pagina_gerador_qrcode(planilha_conectada),
        "Enviar WhatsApp (Manual)": lambda: pagina_whatsapp(planilha_conectada),
    }
    
    pagina_selecionada = st.sidebar.radio("Escolha uma funcionalidade:", paginas.keys())
    paginas[pagina_selecionada]()

if __name__ == "__main__":
    main()
