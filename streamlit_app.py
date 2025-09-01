# streamlit_app.py - VERSÃO FINAL COM OTIMIZAÇÃO DE MEMÓRIA APLICADA

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
from io import BytesIO
import urllib.parse
from dateutil.relativedelta import relativedelta
# Imports pesados foram removidos daqui e movidos para dentro das suas respetivas funções

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
    # OTIMIZAÇÃO: Importa a biblioteca pesada apenas quando a função é chamada
    from pdf2image import convert_from_bytes
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
        Sua tarefa é extrair informações de um texto de formulário de saúde e convertê-lo para um JSON...
        (Seu prompt completo vai aqui)
        """
        response = cohere_client.chat(model="command-r-plus", message=prompt, temperature=0.1)
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except Exception as e:
        st.error(f"Erro ao chamar a API do Cohere: {e}"); return None

def extrair_dados_vacinacao_com_cohere(texto_extraido: str, cohere_client):
    prompt = f"""
    Sua tarefa é atuar como um agente de saúde especializado em analisar textos de cadernetas de vacinação brasileiras...
    (Seu prompt completo vai aqui)
    """
    try:
        response = cohere_client.chat(model="command-r-plus", message=prompt, temperature=0.2)
        json_string = response.text.strip()
        if json_string.startswith("```json"): json_string = json_string[7:]
        if json_string.endswith("```"): json_string = json_string[:-3]
        dados_extraidos = json.loads(json_string.strip())
        return dados_extraidos
    except Exception as e:
        st.error(f"Erro ao processar a resposta da IA: {e}")
        return None

def extrair_dados_clinicos_com_cohere(texto_prontuario: str, cohere_client):
    prompt = f"""
    Sua tarefa é analisar o texto de um prontuário médico e extrair informações clínicas chave...
    (Seu prompt completo vai aqui)
    """
    try:
        response = cohere_client.chat(model="command-r-plus", message=prompt, temperature=0.2)
        json_string = response.text.strip()
        if json_string.startswith("```json"): json_string = json_string[7:]
        if json_string.endswith("```"): json_string = json_string[:-3]
        dados_extraidos = json.loads(json_string.strip())
        return dados_extraidos
    except Exception as e:
        st.error(f"Erro ao processar a resposta da IA para extração clínica: {e}")
        return None

def salvar_no_sheets(dados, planilha):
    try:
        cabecalhos = planilha.row_values(1)
        if 'ID' not in dados or not dados['ID']: dados['ID'] = f"ID-{int(time.time())}"
        dados['Data de Registo'] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        nova_linha = [dados.get(cabecalho, "") for cabecalho in cabecalhos]
        planilha.append_row(nova_linha)
        st.success(f"✅ Dados de '{dados.get('Nome Completo', 'Desconhecido')}' salvos com sucesso!")
        st.balloons()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao salvar na planilha: {e}")

# --- FUNÇÕES DE GERAÇÃO DE PDF (OTIMIZADAS) ---
def preencher_pdf_formulario(paciente_dados):
    # OTIMIZAÇÃO: Importa bibliotecas pesadas aqui dentro
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from pypdf import PdfReader, PdfWriter
    
    # IMPORTANTE: Garanta que este ficheiro PDF está no seu repositório GitHub!
    template_pdf_path = "Formulario_2IndiceDeVulnerabilidadeClinicoFuncional20IVCF20_ImpressoraPDFPreenchivel_202404-2.pdf"
    
    try:
        packet = BytesIO()
        can = canvas.Canvas(packet, pagesize=A4)
        can.setFont("Helvetica", 10)
        can.drawString(3.2 * cm, 23.8 * cm, str(paciente_dados.get("Nome Completo", "")))
        # ... (Sua lógica de preenchimento do canvas) ...
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
        st.error(f"Erro: O arquivo modelo '{template_pdf_path}' não foi encontrado no repositório.")
        return None
    except Exception as e:
        st.error(f"Ocorreu um erro ao gerar o PDF: {e}")
        return None

def gerar_pdf_etiquetas(familias_para_gerar):
    # OTIMIZAÇÃO: Importa bibliotecas pesadas aqui dentro
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.lib.utils import ImageReader
    import qrcode

    # ... (Sua lógica completa de gerar etiquetas aqui) ...
    pdf_buffer = BytesIO()
    can = canvas.Canvas(pdf_buffer, pagesize=A4)
    can.drawString(100, 750, "Exemplo de Etiqueta") # Código de exemplo
    can.save()
    pdf_buffer.seek(0)
    return pdf_buffer

# ... (Suas outras funções de gerar PDF aqui, com os imports dentro delas) ...

# --- PÁGINAS DO APP ---
def pagina_coleta(planilha, co_client):
    st.title("🤖 COLETA INTELIGENTE")
    # ... (seu código completo da página aqui) ...

def pagina_dashboard(planilha):
    # OTIMIZAÇÃO: Importa matplotlib aqui dentro
    import matplotlib.pyplot as plt
    st.title("📊 Dashboard de Dados")
    # ... (seu código completo da página aqui) ...

# ... (Todas as suas outras funções de página aqui) ...

# --- FUNÇÃO PRINCIPAL E ROTEADOR ---
def main():
    query_params = st.query_params
    if query_params.get("page") == "resumo":
        st.set_page_config(page_title="Resumo de Pacientes", layout="centered")
        # ... (código da página de resumo aqui) ...
    else:
        st.set_page_config(page_title="Coleta Inteligente", page_icon="🤖", layout="wide")
        st.sidebar.title("Navegação")
        
        planilha_conectada = None
        co_client = None
        
        try:
            planilha_conectada = conectar_planilha()
        except Exception as e:
            st.error(f"Falha na conexão com a Planilha. Verifique os segredos 'gcp_service_account' e 'SHEETSID'. Erro: {e}")
        
        try:
            # CORREÇÃO: Usando o nome padronizado do segredo
            co_client = cohere.Client(api_key=st.secrets["COHERE_API_KEY"])
        except Exception as e:
            st.warning(f"Não foi possível conectar ao serviço de IA. Funcionalidades limitadas. Verifique o segredo 'COHERE_API_KEY'. Erro: {e}")

        if planilha_conectada is None:
            st.error("A conexão com a planilha falhou. A aplicação não pode continuar.")
            st.stop()
            
        paginas = {
            # Preencha com suas páginas
            "Coletar Fichas": lambda: pagina_coleta(planilha_conectada, co_client),
            "Dashboard": lambda: pagina_dashboard(planilha_conectada),
        }
        pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas.keys())
        paginas[pagina_selecionada]()

if __name__ == "__main__":
    main()
