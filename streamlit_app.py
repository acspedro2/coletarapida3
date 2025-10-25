Import streamlit as st
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

# --- NOVA IMPORTAÇÃO ---
import google.generativeai as genai

# --- CONFIGURAÇÃO GLOBAL DA API GEMINI ---
# Definir o nome do modelo como uma constante. 
# 'gemini-2.5-flash' substitui o modelo anterior para evitar o erro 404.
MODELO_GEMINI = "gemini-2.5-flash"


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
# O st.set_page_config é chamado dentro da função main para permitir o roteamento de página

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
        # AQUI VOCÊ DEVE TER CONFIGURADO CORRETAMENTE SEUS SECRETS NO STREAMLIT CLOUD
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

# --- FUNÇÃO DE PADRONIZAÇÃO DE TELEFONE (NECESSÁRIA PARA A NOVA PÁGINA) ---
def padronizar_telefone(telefone):
    """Limpa e padroniza o número de telefone (remove formatação e 55, se houver)."""
    if pd.isna(telefone) or telefone == "":
        return None
    num_limpo = re.sub(r'\D', '', str(telefone))
    # Remove o 55 inicial se já existir
    if num_limpo.startswith('55'):
        num_limpo = num_limpo[2:]
    # Um número válido (DDD + 8 ou 9 dígitos) deve ter 10 ou 11 dígitos
    if 10 <= len(num_limpo) <= 11: 
        return num_limpo
    return None 

# --- NOVAS FUNÇÕES COM GOOGLE GEMINI (MODELO ATUALIZADO) ---
def extrair_dados_com_google_gemini(texto_extraido: str, api_key: str):
    """Extrai dados cadastrais de um texto (ficha) usando Gemini."""
    try:
        # Configura a chave API
        genai.configure(api_key=api_key)
        
        prompt = f"""
        Sua tarefa é extrair informações de um texto de formulário de saúde e convertê-lo para um JSON.
        Procure por uma anotação à mão que pareça um código de família (ex: 'FAM111'). Este código deve ir para a chave "FAMÍLIA".
        Retorne APENAS um objeto JSON com as chaves: 'ID', 'FAMÍLIA', 'Nome Completo', 'Data de Nascimento', 'Telefone', 'CPF', 'Nome da Mãe', 'Nome do Pai', 'Sexo', 'CNS', 'Município de Nascimento'.
        Se um valor não for encontrado, retorne uma string vazia "".
        Texto para analisar: --- {texto_extraido} ---
        """
        # Utiliza o modelo corrigido
        model = genai.GenerativeModel(MODELO_GEMINI)
        response = model.generate_content(prompt)
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except Exception as e:
        st.error(f"Erro ao chamar a API do Google Gemini (Extração de Ficha): {e}"); return None

def extrair_dados_vacinacao_com_google_gemini(texto_extraido: str, api_key: str):
    """Extrai nome, data de nascimento e vacinas administradas de um texto de caderneta."""
    try:
        # Configura a chave API
        genai.configure(api_key=api_key)
        
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
        # Utiliza o modelo corrigido
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
    """Extrai diagnósticos e medicamentos de um texto de prontuário clínico."""
    try:
        # Configura a chave API
        genai.configure(api_key=api_key)
        
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
        # Utiliza o modelo corrigido
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
        dados['Data de Registo'] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        # Padroniza as chaves do dicionário para casar com os cabeçalhos da planilha (se necessário)
        nova_linha = [dados.get(cabecalho, "") for cabecalho in cabecalhos]
        planilha.append_row(nova_linha)
        st.success(f"✅ Dados de '{dados.get('Nome Completo', 'Desconhecido')}' salvos com sucesso!")
        st.balloons()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao salvar na planilha: {e}")

# --- FUNÇÕES DE GERAÇÃO DE PDF (sem alterações) ---
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
        if sexo.startswith('F'): can.drawString(12.1 * cm, 22.9 * cm, "X")
        elif sexo.startswith('M'): can.drawString(12.6 * cm, 22.9 * cm, "X")
        raca_cor = str(paciente_dados.get("Raça/Cor", "")).strip().upper()
        if raca_cor.startswith('BRANCA'): can.drawString(3.1 * cm, 23 * cm, "X")
        elif raca_cor.startswith('PRETA'): can.drawString(4.4 * cm, 23 * cm, "X")
        elif raca_cor.startswith('AMARELA'): can.drawString(5.5 * cm, 23 * cm, "X")
        elif raca_cor.startswith('PARDA'): can.drawString(7.0 * cm, 23 * cm, "X")
        elif raca_cor.startswith('INDÍGENA') or raca_cor.startswith('INDIGENA'): can.drawString(8.2 * cm, 23 * cm, "X")
        elif raca_cor.startswith('IGNORADO'): can.drawString(9.7 * cm, 23 * cm, "X")
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
        st.error(f"Erro: O arquivo modelo '{template_pdf_path}' não foi encontrado.")
        return None
    except Exception as e:
        st.error(f"Ocorreu um erro ao gerar o PDF: {e}")
        return None

def gerar_pdf_etiquetas(familias_para_gerar):
    pdf_buffer = BytesIO()
    can = canvas.Canvas(pdf_buffer, pagesize=A4)
    largura_pagina, altura_pagina = A4
    num_colunas, num_linhas = 2, 5
    etiquetas_por_pagina = num_colunas * num_linhas
    margem_esquerda, margem_superior = 0.5 * cm, 1 * cm
    largura_etiqueta = (largura_pagina - 2 * margem_esquerda) / num_colunas
    altura_etiqueta = (altura_pagina - 2 * margem_superior) / num_linhas
    contador_etiquetas = 0
    lista_familias = list(familias_para_gerar.items())
    for i, (familia_id, dados_familia) in enumerate(lista_familias):
        linha_atual = (contador_etiquetas % etiquetas_por_pagina) // num_colunas
        coluna_atual = (contador_etiquetas % etiquetas_por_pagina) % num_colunas
        x_base = margem_esquerda + coluna_atual * largura_etiqueta
        y_base = altura_pagina - margem_superior - (linha_atual + 1) * altura_etiqueta
        can.rect(x_base, y_base, largura_etiqueta, altura_etiqueta)
        link_pasta = dados_familia.get("link_pasta", "")
        if link_pasta:
            qr = qrcode.QRCode(version=1, box_size=8, border=2)
            qr.add_data(link_pasta)
            qr.make(fit=True)
            img_qr = qr.make_image(fill_color="black", back_color="white")
            qr_buffer = BytesIO()
            img_qr.save(qr_buffer, format='PNG')
            qr_buffer.seek(0)
            can.drawImage(ImageReader(qr_buffer), x_base + 0.5 * cm, y_base + 0.5 * cm, width=2.5*cm, height=2.5*cm)
        x_texto = x_base + 3.5 * cm
        y_texto = y_base + altura_etiqueta - 0.8 * cm
        can.setFont("Helvetica-Bold", 12)
        can.drawString(x_texto, y_texto, f"Família: {familia_id} PB01")
        y_texto -= 0.6 * cm
        for membro in dados_familia['membros']:
            can.setFont("Helvetica-Bold", 8)
            nome = membro.get('Nome Completo', '')
            if len(nome) > 35: nome = nome[:32] + "..."
            can.drawString(x_texto, y_texto, nome)
            y_texto -= 0.4 * cm
            can.setFont("Helvetica", 7)
            dn = membro.get('Data de Nascimento', 'N/D')
            cns = membro.get('CNS', 'N/D')
            info_str = f"DN: {dn} | CNS: {cns}"
            can.drawString(x_texto, y_texto, info_str)
            y_texto -= 0.5 * cm
            if y_texto < (y_base + 0.5 * cm): break
        contador_etiquetas += 1
        if contador_etiquetas % etiquetas_por_pagina == 0 and (i + 1) < len(lista_familias):
            can.showPage()
    can.save()
    pdf_buffer.seek(0)
    return pdf_buffer

def gerar_pdf_capas_prontuario(pacientes_df):
    pdf_buffer = BytesIO()
    can = canvas.Canvas(pdf_buffer, pagesize=A4)
    largura_pagina, altura_pagina = A4
    COR_PRINCIPAL, COR_SECUNDARIA, COR_FUNDO_CABECALHO = HexColor('#2c3e50'), HexColor('#7f8c8d'), HexColor('#ecf0f1')
    for index, paciente in pacientes_df.iterrows():
        can.setFont("Helvetica", 9)
        can.setFillColor(COR_SECUNDARIA)
        can.drawRightString(largura_pagina - 2 * cm, altura_pagina - 2 * cm, "PB01")
        can.setFont("Helvetica-Bold", 16)
        can.setFillColor(COR_PRINCIPAL)
        can.drawCentredString(largura_pagina / 2, altura_pagina - 3.5 * cm, "PRONTUÁRIO DO PACIENTE")
        margem_caixa = 2 * cm
        largura_caixa = largura_pagina - (2 * margem_caixa)
        altura_caixa = 5 * cm
        x_caixa, y_caixa = margem_caixa, altura_pagina - 10 * cm
        can.setStrokeColor(COR_FUNDO_CABECALHO)
        can.setLineWidth(1)
        can.rect(x_caixa, y_caixa, largura_caixa, altura_caixa, stroke=1, fill=0)
        altura_cabecalho_interno = 1.5 * cm
        y_cabecalho_interno = y_caixa + altura_caixa - altura_cabecalho_interno
        can.setFillColor(COR_FUNDO_CABECALHO)
        can.rect(x_caixa, y_cabecalho_interno, largura_caixa, altura_cabecalho_interno, stroke=0, fill=1)
        nome_paciente = str(paciente.get("Nome Completo", "")).upper()
        y_texto_nome = y_cabecalho_interno + (altura_cabecalho_interno / 2) - (0.2 * cm)
        can.setFont("Helvetica-Bold", 14)
        can.setFillColor(COR_PRINCIPAL)
        can.drawCentredString(largura_pagina / 2, y_texto_nome, nome_paciente)
        y_inicio_dados = y_cabecalho_interno - 1.2 * cm
        x_label_esq, x_valor_esq = x_caixa + 1 * cm, x_caixa + 4.5 * cm
        can.setFont("Helvetica", 10)
        can.setFillColor(COR_SECUNDARIA)
        can.drawString(x_label_esq, y_inicio_dados, "Data de Nasc.:")
        can.setFont("Helvetica-Bold", 11)
        can.setFillColor(COR_PRINCIPAL)
        can.drawString(x_valor_esq, y_inicio_dados, str(paciente.get("Data de Nascimento", "")))
        y_segunda_linha = y_inicio_dados - 1 * cm
        can.setFont("Helvetica", 10)
        can.setFillColor(COR_SECUNDARIA)
        can.drawString(x_label_esq, y_segunda_linha, "CPF:")
        can.setFont("Helvetica-Bold", 11)
        can.setFillColor(COR_PRINCIPAL)
        can.drawString(x_valor_esq, y_segunda_linha, str(paciente.get("CPF", "")))
        x_label_dir, x_valor_dir = x_caixa + (largura_caixa / 2) + 1 * cm, x_caixa + (largura_caixa / 2) + 3.5 * cm
        can.setFont("Helvetica", 10)
        can.setFillColor(COR_SECUNDARIA)
        can.drawString(x_label_dir, y_inicio_dados, "Família:")
        can.setFont("Helvetica-Bold", 11)
        can.setFillColor(COR_PRINCIPAL)
        can.drawString(x_valor_dir, y_inicio_dados, str(paciente.get("FAMÍLIA", "")))
        can.setFont("Helvetica", 10)
        can.setFillColor(COR_SECUNDARIA)
        can.drawString(x_label_dir, y_segunda_linha, "CNS:")
        can.setFont("Helvetica-Bold", 11)
        can.setFillColor(COR_PRINCIPAL)
        can.drawString(x_valor_dir, y_segunda_linha, str(paciente.get("CNS", "")))
        can.showPage()
    can.save()
    pdf_buffer.seek(0)
    return pdf_buffer

def gerar_pdf_relatorio_vacinacao(nome_paciente, data_nascimento, relatorio):
    pdf_buffer = BytesIO()
    can = canvas.Canvas(pdf_buffer, pagesize=A4)
    largura_pagina, altura_pagina = A4
    COR_PRINCIPAL, COR_SECUNDARIA, COR_SUCESSO, COR_ALERTA, COR_INFO = HexColor('#2c3e50'), HexColor('#7f8c8d'), HexColor('#27ae60'), HexColor('#e67e22'), HexColor('#3498db')
    can.setFont("Helvetica-Bold", 16)
    can.setFillColor(COR_PRINCIPAL)
    can.drawCentredString(largura_pagina / 2, altura_pagina - 3 * cm, "Relatório de Situação Vacinal")
    can.setFont("Helvetica", 10)
    can.setFillColor(COR_SECUNDARIA)
    can.drawString(2 * cm, altura_pagina - 4.5 * cm, f"Paciente: {nome_paciente}")
    can.drawString(2 * cm, altura_pagina - 5 * cm, f"Data de Nascimento: {data_nascimento}")
    data_emissao = datetime.now().strftime("%d/%m/%Y às %H:%M")
    can.drawRightString(largura_pagina - 2 * cm, altura_pagina - 4.5 * cm, f"Emitido em: {data_emissao}")
    can.setStrokeColor(HexColor('#dddddd'))
    can.line(2 * cm, altura_pagina - 5.5 * cm, largura_pagina - 2 * cm, altura_pagina - 5.5 * cm)
    def desenhar_secao(titulo, cor_titulo, lista_vacinas, y_inicial):
        can.setFont("Helvetica-Bold", 12)
        can.setFillColor(cor_titulo)
        y_atual = y_inicial
        can.drawString(2 * cm, y_atual, titulo)
        y_atual -= 0.7 * cm
        if not lista_vacinas:
            can.setFont("Helvetica-Oblique", 10)
            can.setFillColor(COR_SECUNDARIA)
            can.drawString(2.5 * cm, y_atual, "Nenhuma vacina nesta categoria.")
            y_atual -= 0.7 * cm
            return y_atual
        can.setFont("Helvetica", 10)
        can.setFillColor(COR_PRINCIPAL)
        for vac in lista_vacinas:
            texto = f"• {vac['vacina']} ({vac['dose']}) - Idade recomendada: {vac['idade_meses']} meses."
            can.drawString(2.5 * cm, y_atual, texto)
            y_atual -= 0.6 * cm
        y_atual -= 0.5 * cm
        return y_atual
    y_corpo = altura_pagina - 6.5 * cm
    y_corpo = desenhar_secao("⚠️ Vacinas com Pendência (Atraso)", COR_ALERTA, relatorio["em_atraso"], y_corpo)
    proximas_ordenadas = sorted(relatorio["proximas_doses"], key=lambda x: x['idade_meses'])
    y_corpo = desenhar_secao("🗓️ Próximas Doses Recomendadas", COR_INFO, proximas_ordenadas, y_corpo)
    y_corpo = desenhar_secao("✅ Vacinas em Dia", COR_SUCESSO, relatorio["em_dia"], y_corpo)
    can.save()
    pdf_buffer.seek(0)
    return pdf_buffer

# --- PÁGINAS DO APP ---

# --- NOVA PÁGINA INICIAL ---
def pagina_inicial():
    st.title("Bem-vindo ao Sistema de Gestão de Pacientes Inteligente")
    st.markdown("""
        Este aplicativo foi desenvolvido para otimizar a gestão de pacientes e a comunicação em unidades de saúde. 
        Com ele, você pode:
    """)
    st.write("---")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🤖 Coleta Inteligente de Fichas")
        st.markdown("""
            Utilize a inteligência artificial para extrair automaticamente dados de fichas de pacientes 
            (digitadas ou manuscritas) e registrá-los na sua base de dados.
            """)
        # ALTERAÇÃO: use_column_width=True -> use_container_width=True
        st.image("https://images.unsplash.com/photo-1587351021759-4001a145873d?q=80&w=2070&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D", caption="Coleta automatizada de dados", use_container_width=True)
        
        st.subheader("💉 Análise de Vacinação")
        st.markdown("""
            Envie uma foto da caderneta de vacinação e receba um relatório detalhado sobre as vacinas 
            em dia, em atraso e as próximas doses recomendadas, tudo de forma automática.
            """)
        # ALTERAÇÃO: use_column_width=True -> use_container_width=True
        st.image("https://images.unsplash.com/photo-1629891392650-db7e8340d1df?q=80&w=2070&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D", caption="Análise de caderneta de vacinação", use_container_width=True)

    with col2:
        st.subheader("🔎 Gestão Completa de Pacientes")
        st.markdown("""
            Pesquise, visualize, edite e apague registos de pacientes. 
            Acesse dashboards familiares para uma visão integrada da saúde de cada núcleo.
            """)
        # ALTERAÇÃO: use_column_width=True -> use_container_width=True
        st.image("https://images.unsplash.com/photo-1579684385133-722a0df8d0b2?q=80&w=2070&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D", caption="Gestão e visão familiar", use_container_width=True)
        
        st.subheader("📱 Alertas e Comunicação via WhatsApp")
        st.markdown("""
            Envie mensagens personalizadas de WhatsApp para pacientes individualmente 
            ou use a verificação rápida para localizar um paciente e enviar alertas.
            """)
        # ALTERAÇÃO: use_column_width=True -> use_container_width=True
        st.image("https://images.unsplash.com/photo-1596701072971-fec1256b7c52?q=80&w=2070&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D", caption="Comunicação eficiente", use_container_width=True)

    st.write("---")
    st.markdown("""
        Explore as opções no menu lateral para começar a utilizar as funcionalidades do sistema.
    """)

# --- FIM NOVA PÁGINA INICIAL ---

def pagina_gerar_documentos(planilha):
    st.title("📄 Gerador de Documentos")
    df = ler_dados_da_planilha(planilha)
    if df.empty:
        st.warning("Não há pacientes na base de dados para gerar documentos.")
        return
    st.subheader("1. Selecione o Paciente")
    lista_pacientes = sorted(df['Nome Completo'].tolist())
    paciente_selecionado_nome = st.selectbox("Escolha um paciente:", lista_pacientes, index=None, placeholder="Selecione...")
    if paciente_selecionado_nome:
        paciente_dados = df[df['Nome Completo'] == paciente_selecionado_nome].iloc[0]
        st.markdown("---")
        st.subheader("2. Escolha o Documento e Gere")
        if st.button("Gerar Formulário de Vulnerabilidade"):
            pdf_buffer = preencher_pdf_formulario(paciente_dados.to_dict())
            if pdf_buffer:
                st.download_button(
                    label="📥 Descarregar Formulário Preenchido (PDF)",
                    data=pdf_buffer,
                    file_name=f"formulario_{paciente_selecionado_nome.replace(' ', '_')}.pdf",
                    mime="application/pdf"
                )

def pagina_coleta(planilha):
    st.title("🤖 COLETA INTELIGENTE")
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
            texto_extraido = ocr_space_api(file_bytes, st.secrets["OCRSPACEKEY"])
            if texto_extraido:
                # --- CHAMADA ATUALIZADA PARA O GEMINI ---
                dados_extraidos = extrair_dados_com_google_gemini(texto_extraido, st.secrets["GOOGLE_API_KEY"])
                if dados_extraidos:
                    with st.form(key=f"form_{proximo_arquivo.file_id}"):
                        st.subheader("2. Confirme e salve os dados")
                        dados_para_salvar = {}
                        dados_para_salvar['ID'] = st.text_input("ID", value=dados_extraidos.get("ID", ""))
                        dados_para_salvar['FAMÍLIA'] = st.text_input("FAMÍLIA", value=dados_extraidos.get("FAMÍLIA", ""))
                        dados_para_salvar['Nome Completo'] = st.text_input("Nome Completo", value=dados_extraidos.get("Nome Completo", ""))
                        dados_para_salvar['Data de Nascimento'] = st.text_input("Data de Nascimento", value=dados_extraidos.get("Data de Nascimento", ""))
                        dados_para_salvar['CPF'] = st.text_input("CPF", value=dados_extraidos.get("CPF", ""))
                        dados_para_salvar['CNS'] = st.text_input("CNS", value=dados_extraidos.get("CNS", ""))
                        dados_para_salvar['Telefone'] = st.text_input("Telefone", value=dados_extraidos.get("Telefone", ""))
                        dados_para_salvar['Nome da Mãe'] = st.text_input("Nome da Mãe", value=dados_extraidos.get("Nome da Mãe", ""))
                        dados_para_salvar['Nome do Pai'] = st.text_input("Nome do Pai", value=dados_extraidos.get("Nome do Pai", ""))
                        dados_para_salvar['Sexo'] = st.text_input("Sexo", value=dados_extraidos.get("Sexo", ""))
                        dados_para_salvar['Município de Nascimento'] = st.text_input("Município de Nascimento", value=dados_extraidos.get("Município de Nascimento", ""))
                        if st.form_submit_button("✅ Salvar Dados Desta Ficha"):
                            cpf_a_verificar = ''.join(re.findall(r'\d', dados_para_salvar['CPF']))
                            cns_a_verificar = ''.join(re.findall(r'\d', dados_para_salvar['CNS']))
                            duplicado_cpf = False
                            if cpf_a_verificar and not df_existente.empty:
                                duplicado_cpf = any(df_existente['CPF'].astype(str).str.replace(r'\D', '', regex=True) == cpf_a_verificar)
                            duplicado_cns = False
                            if cns_a_verificar and not df_existente.empty:
                                duplicado_cns = any(df_existente['CNS'].astype(str).str.replace(r'\D', '', regex=True) == cns_a_verificar)
                            if duplicado_cpf or duplicado_cns:
                                st.error("⚠️ Alerta de Duplicado: Já existe um paciente registado com este CPF ou CNS. O registo não foi salvo.")
                            else:
                                salvar_no_sheets(dados_para_salvar, planilha)
                                st.session_state.processados.append(proximo_arquivo.file_id)
                                st.rerun()
                else: st.error("A IA não conseguiu extrair dados deste texto.")
            else: st.error("Não foi possível extrair texto desta imagem.")
        elif len(uploaded_files) > 0:
            st.success("🎉 Todas as fichas enviadas foram processadas e salvas!")
            if st.button("Limpar lista para enviar novas imagens"):
                st.session_state.processados = []; st.rerun()

def pagina_dashboard(planilha):
    st.title("📊 Dashboard de Dados")
    df_original = ler_dados_da_planilha(planilha)
    if df_original.empty:
        st.warning("Ainda não há dados na planilha para exibir.")
        return
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
    if df_filtrado.empty:
        st.warning("Nenhum dado encontrado com os filtros selecionados.")
        return
    st.markdown("### Métricas Gerais (com filtros aplicados)")
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
        municipio_counts = df_filtrado['Município de Nascimento'].value_counts()
        st.bar_chart(municipio_counts)
    with gcol2:
        st.markdown("### Distribuição por Sexo")
        fig, ax = plt.subplots(figsize=(5, 3))
        sexo_counts.plot.pie(ax=ax, autopct='%1.1f%%', startangle=90, colors=['#66b3ff','#ff9999', '#99ff99'])
        ax.axis('equal')
        st.pyplot(fig)
    st.markdown("---")
    st.markdown("### Evolução de Novos Registos por Mês")
    if 'Data de Registo' in df_filtrado.columns and df_filtrado['Data de Registo'].notna().any():
        df_filtrado['Data de Registo DT'] = pd.to_datetime(df_filtrado['Data de Registo'], format='%d/%m/%Y %H:%M:%S', errors='coerce')
        df_filtrado.dropna(subset=['Data de Registo DT'], inplace=True)
        if not df_filtrado.empty:
            registos_por_mes = df_filtrado.set_index('Data de Registo DT').resample('M').size().rename('Novos Pacientes')
            st.line_chart(registos_por_mes)
        else: st.info("Não há dados de registo válidos para exibir a evolução.")
    else: st.info("Adicione a coluna 'Data de Registo' para ver a evolução histórica.")
    st.markdown("---")
    st.markdown("### Tabela de Dados (com filtros aplicados)")
    st.dataframe(df_filtrado)
    @st.cache_data
    def convert_df_to_csv(df):
        return df.to_csv(index=False).encode('utf-8')
    csv = convert_df_to_csv(df_filtrado)
    st.download_button(label="📥 Descarregar Dados Filtrados (CSV)", data=csv, file_name='dados_filtrados.csv', mime='text/csv')

def desenhar_dashboard_familia(familia_id, df_completo):
    st.header(f"Dashboard da Família: {familia_id}")
    df_familia = df_completo[df_completo['FAMÍLIA'] == familia_id].copy()
    st.subheader("Membros da Família")
    st.dataframe(df_familia[['Nome Completo', 'Data de Nascimento', 'Idade', 'Sexo', 'CPF', 'CNS']])
    st.markdown("---")
    st.subheader("Acompanhamento Individual")
    cols = st.columns(len(df_familia))
    for i, (index, membro) in enumerate(df_familia.iterrows()):
        with cols[i]:
            st.info(f"**{membro['Nome Completo'].split()[0]}** ({membro['Idade']} anos)")
            condicoes = membro.get('Condição', '')
            if condicoes:
                st.write("**Condições:**"); st.warning(f"{condicoes}")
            else:
                st.write("**Condições:** Nenhuma registada.")
            medicamentos = membro.get('Medicamentos', '')
            if medicamentos:
                st.write("**Medicamentos:**"); st.warning(f"{medicamentos}")
            else:
                st.write("**Medicamentos:** Nenhum registado.")
            if membro['Idade'] >= 0 and membro['Idade'] <= 11:
                st.write("**Vacinação Infantil:**"); st.info("Verificar caderneta.")

def pagina_pesquisa(planilha):
    st.title("🔎 Gestão de Pacientes")
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
    colunas_pesquisaveis = ["Nome Completo", "CPF", "CNS", "Nome da Mãe", "ID", "FAMÍLIA"]
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
                if key not in ['Data de Nascimento DT', 'Idade']:
                    edited_data[key] = st.text_input(f"{key}", value=value, key=f"edit_{key}")
            if st.form_submit_button("Salvar Alterações"):
                try:
                    cell = planilha.find(str(patient_data['ID']))
                    cabecalhos = planilha.row_values(1)
                    update_values = [edited_data.get(h, '') for h in cabecalhos]
                    planilha.update(f'A{cell.row}', [update_values])
                    st.success("Dados do paciente atualizados com sucesso!")
                    del st.session_state['patient_to_edit']
                    st.cache_data.clear(); time.sleep(1); st.rerun()
                except gspread.exceptions.CellNotFound:
                    st.error(f"Erro: Não foi possível encontrar o paciente com ID {patient_data['ID']} para atualizar.")
                except Exception as e:
                    st.error(f"Ocorreu um erro ao salvar: {e}")

def pagina_etiquetas(planilha):
    st.title("🏷️ Gerador de Etiquetas por Família")
    df = ler_dados_da_planilha(planilha)
    if df.empty: st.warning("Ainda não há dados na planilha para gerar etiquetas."); return
    def agregador(x):
        return {"membros": x[['Nome Completo', 'Data de Nascimento', 'CNS']].to_dict('records'), "link_pasta": x['Link da Pasta da Família'].iloc[0] if 'Link da Pasta da Família' in x.columns and not x['Link da Pasta da Família'].empty else ""}
    df_familias = df[df['FAMÍLIA'].astype(str).str.strip() != '']
    if df_familias.empty:
        st.warning("Não há famílias para exibir."); return
    familias_dict = df_familias.groupby('FAMÍLIA').apply(agregador).to_dict()
    lista_familias = sorted([f for f in familias_dict.keys() if f])
    st.subheader("1. Selecione as famílias")
    familias_selecionadas = st.multiselect("Deixe em branco para selecionar todas as famílias:", lista_familias)
    familias_para_gerar = familias_dict if not familias_selecionadas else {fid: familias_dict[fid] for fid in familias_selecionadas}
    st.subheader("2. Pré-visualização e Geração do PDF")
    if not familias_para_gerar: st.warning("Nenhuma família para exibir."); return
    for familia_id, dados_familia in familias_para_gerar.items():
        if familia_id:
            with st.expander(f"**Família: {familia_id}** ({len(dados_familia['membros'])} membro(s))"):
                for membro in dados_familia['membros']:
                    st.write(f"**{membro['Nome Completo']}**"); st.caption(f"DN: {membro['Data de Nascimento']} | CNS: {membro['CNS']}")
    if st.button("📥 Gerar PDF das Etiquetas com QR Code"):
        pdf_bytes = gerar_pdf_etiquetas(familias_para_gerar)
        st.download_button(label="Descarregar PDF", data=pdf_bytes, file_name=f"etiquetas_qrcode_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf")

def pagina_capas_prontuario(planilha):
    st.title("📇 Gerador de Capas de Prontuário")
    df = ler_dados_da_planilha(planilha)
    if df.empty: st.warning("Ainda não há dados na planilha para gerar capas."); return
    st.subheader("1. Selecione os pacientes")
    lista_pacientes = df['Nome Completo'].tolist()
    pacientes_selecionados_nomes = st.multiselect("Escolha um ou mais pacientes para gerar as capas:", sorted(lista_pacientes))
    if pacientes_selecionados_nomes:
        pacientes_df = df[df['Nome Completo'].isin(pacientes_selecionados_nomes)]
        st.subheader("2. Pré-visualização")
        st.dataframe(pacientes_df[["Nome Completo", "Data de Nascimento", "FAMÍLIA", "CPF", "CNS"]])
        if st.button("📥 Gerar PDF das Capas"):
            pdf_bytes = gerar_pdf_capas_prontuario(pacientes_df)
            st.download_button(label="Descarregar PDF das Capas", data=pdf_bytes, file_name=f"capas_prontuario_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf")
    else: st.info("Selecione pelo menos um paciente para gerar as capas.")

def pagina_whatsapp(planilha):
    st.title("📱 Enviar Mensagens de WhatsApp (Manual)")
    df = ler_dados_da_planilha(planilha)
    if df.empty: st.warning("Ainda não há dados na planilha para enviar mensagens."); return
    st.subheader("1. Escreva a sua mensagem")
    mensagem_padrao = st.text_area("Mensagem:", "Olá, [NOME]! A sua autorização de exame para [ESCREVA AQUI O NOME DO EXAME] foi liberada. Por favor, entre em contato para mais detalhes.", height=150)
    st.subheader("2. Escolha o paciente e envie")
    df_com_telefone = df[df['Telefone'].astype(str).str.strip() != ''].copy()
    for index, row in df_com_telefone.iterrows():
        nome = row['Nome Completo']
        telefone = padronizar_telefone(row['Telefone']) # Usando a função padronizar_telefone
        if telefone is None: continue
        mensagem_personalizada = mensagem_padrao.replace("[NOME]", nome.split()[0])
        whatsapp_url = f"https://wa.me/55{telefone}?text={urllib.parse.quote(mensagem_personalizada)}"
        col1, col2 = st.columns([3, 1])
        col1.text(f"{nome} - ({row['Telefone']})")
        col2.link_button("Enviar Mensagem ↗️", whatsapp_url, use_container_width=True)

# --- NOVA PÁGINA: BUSCA AUTOMÁTICA E WHATSAPP ---
def pagina_ocr_e_alerta_whatsapp(planilha):
    st.title("📸 Verificação Rápida e Alerta WhatsApp")
    st.warning("Fluxo: Foto/Documento ➡️ Simulação da Extração do Nome ➡️ Busca Automática ➡️ Notificação WhatsApp")
    
    # Lendo os dados da planilha
    df = ler_dados_da_planilha(planilha)
    if df.empty:
        st.error("A planilha não possui dados para busca.")
        return

    # 1. Simulação da Captura do Documento
    st.subheader("1. Capturar ou Carregar a Imagem do Documento")
    foto_paciente = st.camera_input("Tire uma foto do documento do paciente:")
    
    st.markdown("---")
    st.subheader("2. Simulação da Seleção/Extração do Nome")
    
    nome_para_buscar = None
    
    if foto_paciente is not None:
        # AQUI VAMOS SIMULAR A ETAPA DO OCR/IA EXTRAINDO O NOME DA FOTO
        # Criamos a lista de nomes válidos para o SelectBox
        
        # Cria uma coluna padronizada de telefone para filtrar apenas pacientes que podem receber o alerta
        df['Telefone Limpo'] = df['Telefone'].apply(padronizar_telefone)
        lista_pacientes_validos = df[df['Telefone Limpo'].notna()]['Nome Completo'].tolist()

        if not lista_pacientes_validos:
            st.error("Nenhum paciente na planilha tem um número de telefone válido para receber alertas.")
            return

        nome_para_buscar = st.selectbox(
            "Selecione o nome que a IA 'extraiu' da imagem:", 
            options=sorted(lista_pacientes_validos),
            index=None,
            placeholder="Selecione o nome do paciente para que o sistema possa buscá-lo..."
        )
    
    if nome_para_buscar:
        # 3. Execução da Busca (O sistema procura!)
        
        # Prepara o nome do input para busca (Remove espaços e converte para maiúsculo)
        nome_limpo_busca = nome_para_buscar.strip().upper()
        
        # Prepara a coluna para busca no DataFrame (Remove espaços e converte para maiúsculo)
        df['Nome Limpo'] = df['Nome Completo'].astype(str).str.strip().str.upper()
        
        # Filtra o DataFrame (O coração da busca, com correspondência exata)
        resultado_busca = df[df['Nome Limpo'] == nome_limpo_busca]
        
        if not resultado_busca.empty:
            paciente_data = resultado_busca.iloc[0]
            telefone_limpo = padronizar_telefone(paciente_data['Telefone'])
            telefone_completo = paciente_data['Telefone']
            primeiro_nome = paciente_data['Nome Completo'].split()[0]
            
            # Garante que o telefone ainda é válido após a busca (redundância)
            if telefone_limpo is None:
                 st.error(f"❌ Paciente '{paciente_data['Nome Completo']}' encontrado, mas o telefone ({telefone_completo}) é inválido.")
                 return

            st.success(f"✅ Paciente '{paciente_data['Nome Completo']}' **CONSTA** na planilha!")
            
            # 4. Alerta e Ação (WhatsApp)
            st.subheader("3. Alerta e Envio da Notificação")
            
            # Mensagem de notificação (Pré-preenchida)
            mensagem_default = (
                f"Olá, {primeiro_nome}! Seu procedimento foi LIBERADO/AUTORIZADO. "
                f"Entre em contato com seu ACS/UBS para agendar. [SAÚDE MUNICIPAL]"
            )
            
            mensagem_padrao = st.text_area(
                f"Mensagem para {primeiro_nome}:", 
                mensagem_default, 
                height=100
            )
            
            st.warning(f"A notificação será enviada para: **{telefone_completo}**.")
            
            # Geração do link
            whatsapp_url = f"https://wa.me/55{telefone_limpo}?text={urllib.parse.quote(mensagem_padrao)}"
            
            col1, col2 = st.columns([1, 1])
            with col1:
                st.link_button("Abrir WhatsApp e Enviar ↗️", whatsapp_url, type="primary", use_container_width=True)
            with col2:
                st.write(f"Dados do Paciente:")
                st.dataframe(paciente_data[['Nome Completo', 'Telefone', 'ID']].to_frame().T, hide_index=True)

        else:
            st.error(f"❌ Erro: O nome '{nome_para_buscar}' **NÃO CONSTA** na planilha de pacientes.")
# --- FIM NOVA PÁGINA ---

def pagina_analise_vacinacao(planilha):
    st.title("💉 Análise Automatizada de Caderneta de Vacinação")
    if 'uploaded_file_id' not in st.session_state:
        st.session_state.dados_extraidos = None
        st.session_state.relatorio_final = None
    uploaded_file = st.file_uploader("Envie a foto da caderneta de vacinação:", type=["jpg", "jpeg", "png"])
    if uploaded_file is not None:
        st.session_state.uploaded_file_id = uploaded_file.id
        if st.session_state.get('dados_extraidos') is None:
            with st.spinner("Processando imagem e extraindo dados com IA..."):
                texto_extraido = ocr_space_api(uploaded_file.getvalue(), st.secrets["OCRSPACEKEY"])
                if texto_extraido:
                    # --- CHAMADA ATUALIZADA PARA O GEMINI ---
                    dados = extrair_dados_vacinacao_com_google_gemini(texto_extraido, st.secrets["GOOGLE_API_KEY"])
                    if dados:
                        st.session_state.dados_extraidos = dados
                        st.rerun()
                    else: st.error("A IA não conseguiu estruturar os dados. Tente uma imagem melhor.")
                else: st.error("O OCR não conseguiu extrair texto da imagem.")
        if st.session_state.get('dados_extraidos') is not None and st.session_state.get('relatorio_final') is None:
            st.markdown("---")
            st.subheader("2. Validação dos Dados Extraídos")
            st.warning("Verifique e corrija os dados extraídos pela IA antes de prosseguir.")
            with st.form(key="validation_form"):
                dados = st.session_state.dados_extraidos
                nome_validado = st.text_input("Nome do Paciente:", value=dados.get("nome_paciente", ""))
                dn_validada = st.text_input("Data de Nascimento:", value=dados.get("data_nascimento", ""))
                st.write("Vacinas Administradas (edite se necessário):")
                vacinas_validadas_df = pd.DataFrame(dados.get("vacinas_administradas", []))
                vacinas_editadas = st.data_editor(vacinas_validadas_df, num_rows="dynamic")
                if st.form_submit_button("✅ Confirmar Dados e Analisar"):
                    with st.spinner("Analisando..."):
                        relatorio = analisar_carteira_vacinacao(dn_validada, vacinas_editadas.to_dict('records'))
                        st.session_state.relatorio_final = relatorio
                        st.session_state.nome_paciente_final = nome_validado
                        st.session_state.data_nasc_final = dn_validada
                        st.rerun()
        if st.session_state.get('relatorio_final') is not None:
            relatorio = st.session_state.relatorio_final
            st.markdown("---")
            st.subheader(f"3. Relatório de Situação Vacinal para: {st.session_state.nome_paciente_final}")
            if "erro" in relatorio: st.error(relatorio["erro"])
            else:
                st.success("✅ Vacinas em Dia")
                if relatorio["em_dia"]:
                    for vac in relatorio["em_dia"]: st.write(f"- **{vac['vacina']} ({vac['dose']})**")
                else: st.write("Nenhuma vacina registrada como em dia.")
                st.warning("⚠️ Vacinas em Atraso")
                if relatorio["em_atraso"]:
                    for vac in relatorio["em_atraso"]: st.write(f"- **{vac['vacina']} ({vac['dose']})** - Recomendada aos {vac['idade_meses']} meses.")
                else: st.write("Nenhuma vacina em atraso identificada.")
                st.info("🗓️ Próximas Doses")
                if relatorio["proximas_doses"]:
                    proximas_ordenadas = sorted(relatorio["proximas_doses"], key=lambda x: x['idade_meses'])
                    for vac in proximas_ordenadas: st.write(f"- **{vac['vacina']} ({vac['dose']})** - Recomendada aos **{vac['idade_meses']} meses**.")
                else: st.write("Nenhuma próxima dose identificada.")
                pdf_bytes = gerar_pdf_relatorio_vacinacao(st.session_state.nome_paciente_final, st.session_state.data_nasc_final, st.session_state.relatorio_final)
                file_name = f"relatorio_vacinacao_{st.session_state.nome_paciente_final.replace(' ', '_')}.pdf"
                st.download_button(label="📥 Descarregar Relatório (PDF)", data=pdf_bytes, file_name=file_name, mime="application/pdf")
    if st.button("Analisar Nova Caderneta"):
        st.session_state.clear()
        st.rerun()

def pagina_importar_prontuario(planilha):
    st.title("📄 Importar Dados de Prontuário Clínico")
    st.info("Esta funcionalidade extrai diagnósticos e medicamentos de um ficheiro de prontuário (PDF digitalizado) e adiciona-os ao registo do paciente.")
    try:
        df = ler_dados_da_planilha(planilha)
        if df.empty:
            st.warning("Não há pacientes na base de dados.")
            return
        lista_pacientes = sorted(df['Nome Completo'].tolist())
        st.subheader("1. Selecione o Paciente e o Ficheiro do Prontuário")
        paciente_selecionado = st.selectbox("Selecione o paciente:", lista_pacientes, index=None, placeholder="Escolha um paciente...")
        uploaded_file = st.file_uploader("Carregue o prontuário em formato PDF:", type=["pdf"])
        if paciente_selecionado and uploaded_file:
            if st.button("🔍 Iniciar Extração de Dados"):
                st.session_state.dados_clinicos_extraidos = None
                with st.spinner("A processar PDF e a analisar com IA... Este processo pode demorar um pouco."):
                    texto_prontuario = ler_texto_prontuario(uploaded_file.getvalue(), st.secrets["OCRSPACEKEY"])
                    if texto_prontuario:
                        st.success("Texto extraído do prontuário com sucesso!")
                        # --- CHAMADA ATUALIZADA PARA O GEMINI ---
                        dados_clinicos = extrair_dados_clinicos_com_google_gemini(texto_prontuario, st.secrets["GOOGLE_API_KEY"])
                        if dados_clinicos:
                            st.session_state.dados_clinicos_extraidos = dados_clinicos
                            st.session_state.paciente_para_atualizar = paciente_selecionado
                            st.rerun()
                        else: st.error("A IA não conseguiu extrair informações clínicas do texto.")
                    else: st.error("Não foi possível extrair texto do PDF.")
        if 'dados_clinicos_extraidos' in st.session_state and st.session_state.dados_clinicos_extraidos is not None:
            st.markdown("---")
            st.subheader("2. Valide os Dados e Salve na Planilha")
            st.warning("Verifique as informações extraídas pela IA. Pode adicionar ou remover itens antes de salvar.")
            dados = st.session_state.dados_clinicos_extraidos
            with st.form(key="clinical_data_form"):
                st.write(f"**Paciente:** {st.session_state.paciente_para_atualizar}")
                diagnosticos_validados = st.multiselect("Diagnósticos Encontrados:", options=dados.get('diagnosticos', []), default=dados.get('diagnosticos', []))
                medicamentos_validados = st.multiselect("Medicamentos Encontrados:", options=dados.get('medicamentos', []), default=dados.get('medicamentos', []))
                if st.form_submit_button("✅ Salvar Informações no Registo do Paciente"):
                    with st.spinner("A atualizar a planilha..."):
                        try:
                            diagnosticos_str = ", ".join(diagnosticos_validados)
                            medicamentos_str = ", ".join(medicamentos_validados)
                            cell = planilha.find(st.session_state.paciente_para_atualizar)
                            headers = planilha.row_values(1)
                            col_condicao_index = headers.index("Condição") + 1 if "Condição" in headers else None
                            col_medicamentos_index = headers.index("Medicamentos") + 1 if "Medicamentos" in headers else None
                            if col_condicao_index: planilha.update_cell(cell.row, col_condicao_index, diagnosticos_str)
                            if col_medicamentos_index: planilha.update_cell(cell.row, col_medicamentos_index, medicamentos_str)
                            st.success(f"Os dados do paciente {st.session_state.paciente_para_atualizar} foram atualizados com sucesso!")
                            st.session_state.dados_clinicos_extraidos = None
                            st.session_state.paciente_para_atualizar = None
                            st.cache_data.clear()
                        except gspread.exceptions.CellNotFound:
                            st.error(f"Não foi possível encontrar o paciente '{st.session_state.paciente_para_atualizar}' na planilha.")
                        except Exception as e:
                            st.error(f"Ocorreu um erro ao salvar na planilha: {e}")
    except Exception as e:
        st.error(f"Ocorreu um erro ao carregar a página: {e}")

def pagina_dashboard_resumo(planilha):
    st.title("📊 Resumo de Pacientes")
    st.caption(f"Dados atualizados em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    try:
        df = ler_dados_da_planilha(planilha)
        if df.empty:
            st.warning("A base de dados de pacientes está vazia."); return
        total_pacientes = len(df)
        sexo_counts = df['Sexo'].str.strip().str.upper().value_counts()
        total_homens = sexo_counts.get('M', 0) + sexo_counts.get('MASCULINO', 0)
        total_mulheres = sexo_counts.get('F', 0) + sexo_counts.get('FEMININO', 0)
        df['Idade'] = df['Data de Nascimento DT'].apply(lambda dt: calcular_idade(dt) if pd.notnull(dt) else -1)
        total_criancas = df[df['Idade'].between(0, 11)].shape[0]
        total_adolescentes = df[df['Idade'].between(12, 17)].shape[0]
        total_idosos = df[df['Idade'] >= 60].shape[0]
        st.header("Visão Geral")
        st.metric("Total de Pacientes", f"{total_pacientes}")
        st.header("Distribuição por Sexo")
        col1, col2 = st.columns(2)
        col1.metric("Homens", f"{total_homens}")
        col2.metric("Mulheres", f"{total_mulheres}")
        st.header("Distribuição por Faixa Etária")
        col1, col2, col3 = st.columns(3)
        col1.metric("Crianças", f"{total_criancas}")
        col2.metric("Adolescentes", f"{total_adolescentes}")
        col3.metric("Idosos", f"{total_idosos}")
    except Exception as e:
        st.error(f"Ocorreu um erro ao carregar as estatísticas: {e}")

def pagina_gerador_qrcode(planilha):
    st.title("Generator de QR Code para Dashboard")
    st.info("Utilize esta página para gerar o QR code que será afixado em locais físicos. Ao ser lido, ele exibirá um painel com as estatísticas atualizadas da sua base de dados.")
    st.subheader("1. Insira o URL da sua aplicação")
    base_url = st.text_input("URL Base da sua aplicação Streamlit Cloud:", placeholder="Ex: https://sua-app-id.streamlit.app")
    if base_url:
        dashboard_url = f"{base_url.strip('/')}?page=resumo"
        st.success(f"URL do Dashboard: {dashboard_url}")
        st.subheader("2. Gere e Descarregue o QR Code")
        if st.button("Gerar QR Code"):
            try:
                qr = qrcode.QRCode(version=1, box_size=10, border=4)
                qr.add_data(dashboard_url)
                qr.make(fit=True)
                img_qr = qr.make_image(fill_color="black", back_color="white")
                qr_buffer = BytesIO()
                img_qr.save(qr_buffer, format='PNG')
                qr_buffer.seek(0)
                st.image(qr_buffer, caption="QR Code Gerado", width=300)
                st.download_button(label="📥 Descarregar QR Code (PNG)", data=qr_buffer, file_name="qrcode_dashboard_pacientes.png", mime="image/png")
            except Exception as e:
                st.error(f"Ocorreu um erro ao gerar o QR Code: {e}")

def main():
    query_params = st.query_params
    if query_params.get("page") == "resumo":
        try:
            st.set_page_config(page_title="Resumo de Pacientes", layout="centered")
            st.html("<meta http-equiv='refresh' content='60'>")
            planilha_conectada = conectar_planilha()
            if planilha_conectada:
                pagina_dashboard_resumo(planilha_conectada)
            else:
                st.error("Falha na conexão com a base de dados.")
        except Exception as e:
            st.error(f"Ocorreu um erro crítico: {e}")
    else:
        st.set_page_config(page_title="Coleta Inteligente", page_icon="🤖", layout="wide")
        st.sidebar.title("Navegação")
        try:
            planilha_conectada = conectar_planilha()
        except Exception as e:
            st.error(f"Não foi possível inicializar os serviços. Verifique seus segredos. Erro: {e}")
            st.stop()
        if planilha_conectada is None:
            st.error("A conexão com a planilha falhou.")
            st.stop()
        
        # --- REMOÇÃO DO CLIENTE COHERE (Já feito no código anterior) ---
        
        paginas = {
            "🏠 Início": pagina_inicial, # Adicionando a página inicial
            "Verificação Rápida WhatsApp": lambda: pagina_ocr_e_alerta_whatsapp(planilha_conectada),
            "Análise de Vacinação": lambda: pagina_analise_vacinacao(planilha_conectada),
            "Importar Dados de Prontuário": lambda: pagina_importar_prontuario(planilha_conectada),
            "Coletar Fichas": lambda: pagina_coleta(planilha_conectada),
            "Gestão de Pacientes": lambda: pagina_pesquisa(planilha_conectada),
            "Dashboard": lambda: pagina_dashboard(planilha_conectada),
            "Gerar Etiquetas": lambda: pagina_etiquetas(planilha_conectada),
            "Gerar Capas de Prontuário": lambda: pagina_capas_prontuario(planilha_conectada),
            "Gerar Documentos": lambda: pagina_gerar_documentos(planilha_conectada),
            "Enviar WhatsApp (Manual)": lambda: pagina_whatsapp(planilha_conectada),
            "Gerador de QR Code": lambda: pagina_gerador_qrcode(planilha_conectada),
        }
        pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas.keys())
        paginas[pagina_selecionada]()

if __name__ == "__main__":
    main()
