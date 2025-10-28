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
import os

# --- NOVA IMPORTAÇÃO E CONFIGURAÇÃO ---
# CORREÇÃO: Usando a nova SDK (google-genai)
try:
    import google.genai as genai
    # Importação para Pydantic - Essencial para Saída Estruturada
    from pydantic import BaseModel, Field
    # Importação da SDK para tipos
    from google.genai.types import Part
except ImportError as e:
    st.error(f"Erro de importação: {e}. Verifique se 'google-genai' e 'pydantic' estão no seu requirements.txt.")
    st.stop()


# --- CONFIGURAÇÃO GLOBAL DA API GEMINI ---
MODELO_GEMINI = "gemini-2.5-flash"

# --- ESQUEMAS PYDANTIC PARA SAÍDA ESTRUTURADA GEMINI ---

# Esquema 1: Extração de Dados Cadastrais
class CadastroSchema(BaseModel):
    """Esquema de extração para dados cadastrais do paciente."""
    ID: str = Field(description="ID único gerado. Se não for claro, retorne string vazia.")
    FAMÍLIA: str = Field(description="Código de família (ex: FAM111). Se não for claro, retorne string vazia.")
    nome_completo: str = Field(alias="Nome Completo")
    data_nascimento: str = Field(alias="Data de Nascimento", description="Data no formato DD/MM/AAAA. Se ausente, retorne string vazia.")
    Telefone: str
    CPF: str
    nome_da_mae: str = Field(alias="Nome da Mãe")
    nome_do_pai: str = Field(alias="Nome do Pai")
    Sexo: str = Field(description="M, F, I (Ignorado).")
    CNS: str = Field(description="Número do Cartão Nacional de Saúde.")
    municipio_nascimento: str = Field(alias="Município de Nascimento")

    # Configuração Pydantic para aceitar a chave 'Data de Nascimento' e forçá-la no output
    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "required": ["Nome Completo", "Data de Nascimento"]
        }
    }

# Esquema 2: Extração de Vacinação
class VacinaAdministrada(BaseModel):
    """Representa uma vacina administrada com dose normalizada."""
    vacina: str = Field(description="Nome normalizado da vacina (ex: Pentavalente, Tríplice Viral).")
    dose: str = Field(description="Dose (ex: 1ª Dose, Reforço).")

class VacinacaoSchema(BaseModel):
    """Esquema de extração para dados de vacinação e doses."""
    nome_paciente: str
    data_nascimento: str = Field(description="Data no formato DD/MM/AAAA.")
    vacinas_administradas: list[VacinaAdministrada] = Field(
        description="Lista de vacinas e doses normalizadas."
    )
    model_config = {
        "json_schema_extra": {
            "required": ["nome_paciente", "data_nascimento", "vacinas_administradas"]
        }
    }

# Esquema 3: Extração de Dados Clínicos
class ClinicoSchema(BaseModel):
    """Esquema de extração para diagnósticos e medicamentos."""
    diagnosticos: list[str] = Field(description="Lista de condições médicas ou diagnósticos, priorizando crônicas.")
    medicamentos: list[str] = Field(description="Lista de medicamentos, incluindo dosagem se disponível.")
    
    model_config = {
        "json_schema_extra": {
            "required": ["diagnosticos", "medicamentos"]
        }
    }


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
    try:
        # Nota: 'convert_from_bytes' requer que o utilitário Poppler esteja instalado no sistema
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

# --- Funções de Conexão e API ---
@st.cache_resource
def conectar_planilha():
    try:
        # AQUI VOCÊ DEVE TER CONFIGURADO CORRETAMENTE SEUS SECRETS NO STREAMLIT CLOUD
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
        # Assumindo que você está usando a primeira aba ou uma folha específica.
        # Para fins de demonstração, mantendo a sheet1.
        sheet = client.open_by_key(st.secrets["SHEETSID"]).sheet1 
        return sheet
    except Exception as e:
        st.error(f"Erro ao conectar com o Google Sheets: {e}"); return None

@st.cache_data(ttl=300)
def ler_dados_da_planilha(_planilha):
    try:
        dados = _planilha.get_all_records()
        df = pd.DataFrame(dados)
        
        # Colunas esperadas, incluindo a nova para Automação de Documentos (Tópico 2)
        colunas_esperadas = [
            "ID", "FAMÍLIA", "Nome Completo", "Data de Nascimento", "Telefone", 
            "CPF", "Mãe", "Pai", "Sexo", "CNS", "Município de Nascimento", 
            "Link do Prontuário", "Link da Pasta da Família", "Condição", # <--- Nova coluna
            "Data de Registo", "Raça/Cor", "Medicamentos"
        ]
        
        for col in colunas_esperadas:
            if col not in df.columns: df[col] = ""
            
        df['Data de Nascimento DT'] = pd.to_datetime(df['Data de Nascimento'], format='%d/%m/%Y', errors='coerce')
        df['Idade'] = df['Data de Nascimento DT'].apply(lambda dt: calcular_idade(dt) if pd.notnull(dt) else 0)
        
        # Padroniza a coluna FAMÍLIA para string, garantindo a chave para a automação
        if 'FAMÍLIA' in df.columns:
            df['FAMÍLIA'] = df['FAMÍLIA'].astype(str).str.strip()
            
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

# --- FUNÇÕES DE AUTOMAÇÃO (TÓPICO 2: Google Drive) ---

def simular_criar_pasta_drive(folder_name: str, parent_folder_id: str = None) -> (str, str):
    """
    SIMULA a criação de uma pasta no Google Drive e retorna seu ID e Link de visualização.
    (Em um ambiente real, esta função usaria a Google Drive API)
    """
    
    # Simula um ID de pasta baseado no nome (para fins de persistência visual)
    pasta_id_simulado = f"DRIVEID-{hash(folder_name) % 10000}"
    
    # Simula um link de pasta do Google Drive
    link_pasta_simulado = f"https://drive.google.com/drive/folders/{pasta_id_simulado}"
    
    return pasta_id_simulado, link_pasta_simulado


def get_familia_folder_link(familia_id: str, planilha_sheet) -> str:
    """
    Busca o link da pasta da família na planilha.
    Se não existir ou for inválido, SIMULA a criação de uma e retorna o link,
    ATUALIZANDO todas as linhas daquela família na planilha.
    """
    familia_id_str = str(familia_id).strip()
    if not familia_id_str:
        return ""
    
    # A. Leitura rápida dos dados para otimizar
    df_temp = ler_dados_da_planilha(planilha_sheet)
    
    # 1. Tenta encontrar o link existente para esta FAMÍLIA
    try:
        df_familia = df_temp[df_temp['FAMÍLIA'] == familia_id_str]
        # Pega o primeiro link válido encontrado
        familia_link = df_familia['Link da Pasta da Família'].dropna().iloc[0]
        
        if familia_link and familia_link.startswith('http'):
            return familia_link # Link existente encontrado
            
    except (IndexError, KeyError):
        # A família é nova, o link está faltando, ou a coluna não existe.
        pass 

    # 2. Se o link não existe, SIMULA a criação da pasta
    folder_name = f"FAMÍLIA {familia_id_str}"
    
    # ⚠️ Chamada para a função de criação (simulada)
    pasta_id, link_pasta = simular_criar_pasta_drive(folder_name)
    
    # 3. Atualiza TODAS as linhas desta FAMÍLIA na planilha com o novo link
    try:
        # Encontra as células na coluna FAMÍLIA que correspondem ao ID
        cell_list = planilha_sheet.findall(familia_id_str, in_column=df_temp.columns.get_loc('FAMÍLIA') + 1)
        
        # Obtém o índice da coluna 'Link da Pasta da Família'
        headers = planilha_sheet.row_values(1)
        link_col_index = headers.index('Link da Pasta da Família') + 1
        
        # Cria uma lista de atualizações no formato [(row, col, value), ...]
        updates = []
        for cell in cell_list:
            updates.append({'range': gspread.utils.rowcol_to_a1(cell.row, link_col_index), 'values': [[link_pasta]]})

        # Executa as atualizações em lote (se houver linhas para atualizar)
        if updates:
            planilha_sheet.batch_update(updates)
            
        st.cache_data.clear() # Limpa o cache para recarregar com o link atualizado
        
    except Exception as e:
        # Erro de atualização, mas o link gerado será retornado para o novo paciente
        st.warning(f"Simulação de criação de pasta bem-sucedida, mas falha ao atualizar TODAS as linhas da família no Sheets: {e}")
    
    return link_pasta

# --- FIM DAS FUNÇÕES DE AUTOMAÇÃO ---


# --- FUNÇÕES COM GOOGLE GEMINI (MODELO ATUALIZADO E SAÍDA ESTRUTURADA) ---
# A definição dessas funções estava faltando e causou o NameError.

def extrair_dados_com_google_gemini(texto_prontuario: str, client: genai.Client) -> dict:
    """
    Extrai dados cadastrais de um texto de prontuário usando o Gemini com saída estruturada.
    """
    st.info("🤖 A IA está extraindo os dados cadastrais da ficha...")
    try:
        # Instrução detalhada para a IA
        prompt = (
            "Você é um extrator de dados de fichas médicas. Extraia APENAS as informações "
            "solicitadas do texto abaixo. Normalizar os campos Sexo (M, F, I) e Data de Nascimento (DD/MM/AAAA)."
            "Se um campo estiver ausente, use string vazia ('').\n\n"
            f"TEXTO DA FICHA:\n---\n{texto_prontuario}"
        )

        response = client.models.generate_content(
            model=MODELO_GEMINI,
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CadastroSchema,
            ),
        )
        
        dados_extraidos = CadastroSchema.model_validate_json(response.text).model_dump(by_alias=True)
        
        return dados_extraidos

    except Exception as e:
        st.error(f"Erro na extração de dados cadastrais pelo Gemini: {e}")
        return None 
        
def extrair_dados_vacinacao_com_google_gemini(texto_prontuario: str, client: genai.Client) -> dict:
    """
    Extrai dados de vacinação de um texto de prontuário usando o Gemini com saída estruturada.
    """
    st.info("🤖 A IA está extraindo os dados de vacinação...")
    try:
        prompt = (
            "Você é um extrator de dados de cadernetas de vacinação. Extraia o nome do paciente, "
            "data de nascimento e uma lista de todas as vacinas administradas com suas doses (ex: 1ª Dose, Reforço). "
            "Normalizar os nomes das vacinas para os padrões brasileiros (ex: 'Triplice Viral', 'Pentavalente'). "
            "Se um campo estiver ausente, use string vazia ('') ou lista vazia ([]).\n\n"
            f"TEXTO DA CADERNETA:\n---\n{texto_prontuario}"
        )

        response = client.models.generate_content(
            model=MODELO_GEMINI,
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=VacinacaoSchema,
            ),
        )
        
        dados_extraidos = VacinacaoSchema.model_validate_json(response.text).model_dump()
        return dados_extraidos

    except Exception as e:
        st.error(f"Erro na extração de dados de vacinação pelo Gemini: {e}")
        return None 

def extrair_dados_clinicos_com_google_gemini(texto_prontuario: str, client: genai.Client) -> dict:
    """
    Extrai diagnósticos e medicamentos de um texto de prontuário usando o Gemini com saída estruturada.
    """
    st.info("🤖 A IA está extraindo diagnósticos e medicamentos...")
    try:
        prompt = (
            "Você é um analista de prontuários. Extraia APENAS uma lista de diagnósticos (priorizando doenças crônicas) "
            "e uma lista de medicamentos, incluindo a dosagem, se disponível. Se ausente, use lista vazia (\[\]).\n\n"
            f"TEXTO DO PRONTUÁRIO:\n---\n{texto_prontuario}"
        )

        response = client.models.generate_content(
            model=MODELO_GEMINI,
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ClinicoSchema,
            ),
        )
        
        dados_extraidos = ClinicoSchema.model_validate_json(response.text).model_dump()
        return dados_extraidos

    except Exception as e:
        st.error(f"Erro na extração de dados clínicos pelo Gemini: {e}")
        return None 
# --- FIM DAS FUNÇÕES COM GOOGLE GEMINI ---


def salvar_no_sheets(dados, planilha):
    try:
        cabecalhos = planilha.row_values(1)
        
        # --- GATILHO DE AUTOMAÇÃO DE DOCUMENTOS (TÓPICO 2) ---
        familia_id = dados.get('FAMÍLIA', '').strip()
        link_pasta_familia = ""
        
        if familia_id:
            # 1. Obter ou Criar Link da Pasta da Família
            # Esta função fará a busca e, se necessário, a simulação de criação/atualização.
            link_pasta_familia = get_familia_folder_link(familia_id, planilha)
            # 2. Insere o link no dicionário que será salvo
            dados['Link da Pasta da Família'] = link_pasta_familia
        # --- FIM DO GATILHO ---
            
        if 'ID' not in dados or not dados['ID']: dados['ID'] = f"ID-{int(time.time())}"
        dados['Data de Registo'] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        # Mapeia as chaves do Pydantic (com underscore) para os cabeçalhos da planilha (com espaço/alias)
        dados_formatados = {}
        for k, v in dados.items():
            # Mapeamento do Pydantic (para chaves como 'nome_completo' -> 'Nome Completo')
            if isinstance(k, str) and k in CadastroSchema.model_fields:
                alias = CadastroSchema.model_fields[k].alias or k
                dados_formatados[alias] = v
            # Inclui as chaves automáticas e de automação (e.g., 'ID', 'FAMÍLIA', 'Link da Pasta da Família')
            else:
                dados_formatados[k] = v

        # Padroniza as chaves do dicionário para casar com os cabeçalhos da planilha
        nova_linha = [dados_formatados.get(cabecalho, "") for cabecalho in cabecalhos]
        planilha.append_row(nova_linha)
        
        st.success(f"✅ Dados de '{dados_formatados.get('Nome Completo', 'Desconhecido')}' salvos com sucesso!")
        if link_pasta_familia:
             st.info(f"📁 Pasta da Família Vinculada Automaticamente: [Acessar Pasta]({link_pasta_familia})")
             
        st.balloons()
        st.cache_data.clear() # Limpa o cache após a gravação
    except Exception as e:
        st.error(f"Erro ao salvar na planilha: {e}")

# --- FUNÇÕES DE GERAÇÃO DE PDF (Sem Alterações) ---
# Aqui, você deve incluir suas funções: preencher_pdf_formulario, gerar_pdf_etiquetas, 
# gerar_pdf_capas_prontuario, gerar_pdf_relatorio_vacinacao, etc.
# Mantenho o comentário para brevidade, mas o seu código real deve tê-las.

# Exemplo de função de PDF para evitar NameError (a função real é mais complexa)
def preencher_pdf_formulario(dados):
    st.info("Simulando geração de PDF...")
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    c.drawString(72, 800, f"Formulário de Vulnerabilidade para: {dados.get('Nome Completo', 'N/A')}")
    c.drawString(72, 780, f"CPF: {dados.get('CPF', 'N/A')}")
    c.save()
    return buffer.getvalue()
    
# Exemplo de função de PDF para evitar NameError
def gerar_pdf_etiquetas(familias_para_gerar):
    st.info("Simulando geração de etiquetas...")
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.drawString(72, 800, f"Etiquetas Geradas em {datetime.now().strftime('%d/%m/%Y')}")
    c.save()
    return buffer.getvalue()
    
# Exemplo de função de PDF para evitar NameError
def gerar_pdf_capas_prontuario(pacientes):
    st.info("Simulando geração de capas...")
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.drawString(72, 800, f"Capas de Prontuário Geradas em {datetime.now().strftime('%d/%m/%Y')}")
    c.save()
    return buffer.getvalue()
    
# Exemplo de função de Página para evitar NameError
def pagina_ocr_e_alerta_whatsapp(planilha): st.subheader("Verificação Rápida WhatsApp (Função Omitida)")
def pagina_analise_vacinacao(planilha, gemini_client): st.subheader("Análise de Vacinação (Função Omitida)")
def pagina_importar_prontuario(planilha, gemini_client): st.subheader("Importar Dados de Prontuário (Função Omitida)")
def pagina_capas_prontuario(planilha): st.subheader("Gerar Capas de Prontuário (Função Omitida)")
def pagina_whatsapp(planilha): st.subheader("Enviar WhatsApp (Manual) (Função Omitida)")
def pagina_gerador_qrcode(planilha): st.subheader("Gerador de QR Code (Função Omitida)")
def pagina_dashboard_resumo(planilha): st.subheader("Dashboard de Resumo (Omitida)")

# As funções de geração de PDF, Dashboard, Pesquisa, etc., permanecem inalteradas,
# exceto pelos pontos de integração do Link da Pasta da Família.

def desenhar_dashboard_familia(familia_id, df_completo):
    st.header(f"Dashboard da Família: {familia_id}")
    df_familia = df_completo[df_completo['FAMÍLIA'] == familia_id].copy()
    
    # Novo: Botão de acesso à pasta
    if not df_familia.empty:
        link_pasta = df_familia['Link da Pasta da Família'].dropna().iloc[0] if 'Link da Pasta da Família' in df_familia.columns and not df_familia['Link da Pasta da Família'].empty else ""
        if link_pasta and link_pasta.startswith('http'):
            st.link_button("📂 Acessar Pasta de Documentos da Família", link_pasta, type="primary")
        else:
            st.info("Link da Pasta de Documentos não gerado ou não disponível.")
    
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
            
            # --- Tópico 1: Simulação de Alerta de Lembretes (Base para futura automação) ---
            if membro['Idade'] >= 0 and membro['Idade'] <= 6:
                telefone = padronizar_telefone(membro.get('Telefone', ''))
                if telefone:
                    mensagem_lembrete = f"Olá, {membro['Nome Completo'].split()[0]}! O paciente {membro['Nome Completo']} é uma criança de {membro['Idade']} anos e pode estar com a vacinação atrasada. Por favor, traga a caderneta na UBS."
                    whatsapp_url = f"https://wa.me/55{telefone}?text={urllib.parse.quote(mensagem_lembrete)}"
                    st.error(f"🚨 **ALERTA (0-6 anos)!** [Enviar Lembrete Vacinal]({whatsapp_url})")
                else:
                    st.error("🚨 **ALERTA (0-6 anos)!** Telefone inválido.")


def pagina_etiquetas(planilha):
    st.title("🏷️ Gerador de Etiquetas por Família")
    df = ler_dados_da_planilha(planilha)
    if df.empty: st.warning("Ainda não há dados na planilha para gerar etiquetas."); return
    
    # Inclui 'Link da Pasta da Família' no agregador
    def agregador(x):
        return {
            "membros": x[['Nome Completo', 'Data de Nascimento', 'CNS']].to_dict('records'), 
            "link_pasta": x['Link da Pasta da Família'].iloc[0] if 'Link da Pasta da Família' in x.columns and not x['Link da Pasta da Família'].empty else ""
        }
        
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
    
    # Mostra o link da pasta na pré-visualização (se houver)
    for familia_id, dados_familia in familias_para_gerar.items():
        if familia_id:
            with st.expander(f"**Família: {familia_id}** ({len(dados_familia['membros'])} membro(s))"):
                if dados_familia['link_pasta']:
                    st.caption(f"📁 Pasta Vinculada: [Acessar]({dados_familia['link_pasta']})")
                else:
                    st.caption("🚨 Nenhuma pasta vinculada (o QR Code não funcionará).")
                for membro in dados_familia['membros']:
                    st.write(f"**{membro['Nome Completo']}**"); st.caption(f"DN: {membro['Data de Nascimento']} | CNS: {membro['CNS']}")
                    
    if st.button("📥 Gerar PDF das Etiquetas com QR Code"):
        pdf_bytes = gerar_pdf_etiquetas(familias_para_gerar)
        st.download_button(label="Descarregar PDF", data=pdf_bytes, file_name=f"etiquetas_qrcode_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf")

# O restante do código, incluindo as páginas do Streamlit, permanece o mesmo.

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
        st.image("https://images.unsplash.com/photo-1587351021759-4001a145873d?q=80&w=2070&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D", caption="Coleta automatizada de dados", use_container_width=True)
        
        st.subheader("💉 Análise de Vacinação")
        st.markdown("""
            Envie uma foto da caderneta de vacinação e receba um relatório detalhado sobre as vacinas 
            em dia, em atraso e as próximas doses recomendadas, tudo de forma automática.
            """)
        st.image("https://images.unsplash.com/photo-1629891392650-db7e8340d1df?q=80&w=2070&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D", caption="Análise de caderneta de vacinação", use_container_width=True)

    with col2:
        st.subheader("🔎 Gestão Completa de Pacientes")
        st.markdown("""
            Pesquise, visualize, edite e apague registos de pacientes. 
            Acesse dashboards familiares para uma visão integrada da saúde de cada núcleo.
            """)
        st.image("https://images.unsplash.com/photo-1579684385133-722a0df8d0b2?q=80&w=2070&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D", caption="Gestão e visão familiar", use_container_width=True)
        
        st.subheader("📱 Alertas e Comunicação via WhatsApp")
        st.markdown("""
            Envie mensagens personalizadas de WhatsApp para pacientes individualmente 
            ou use a verificação rápida para localizar um paciente e enviar alertas.
            """)
        st.image("https://images.unsplash.com/photo-1596701072971-fec1256b7c52?q=80&w=2070&auto=format&fit=crop&ixlib=rb-4.0.3&ixid=M3wxMjA3fDB8MHxwaG90by1wYWdlfHx8fGVufDB8fHx8fA%3D%3D", caption="Comunicação eficiente", use_container_width=True)

    st.write("---")
    st.markdown("""
        Explore as opções no menu lateral para começar a utilizar as funcionalidades do sistema.
    """)

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

def pagina_coleta(planilha, gemini_client):
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
            
            # Etapa 1: OCR - Mantido o OCRSpace conforme o código original, mas o Gemini poderia fazer isso.
            texto_extraido = ocr_space_api(file_bytes, st.secrets["OCRSPACEKEY"])
            
            if texto_extraido:
                # Etapa 2: Extração com Gemini (Structured Output) - Passa o cliente
                # A CORREÇÃO ESTÁ AQUI: AGORA A FUNÇÃO FOI DEFINIDA
                dados_extraidos = extrair_dados_com_google_gemini(texto_extraido, gemini_client)
                
                if dados_extraidos:
                    with st.form(key=f"form_{proximo_arquivo.file_id}"):
                        st.subheader("2. Confirme e salve os dados")
                        # Mapeia as chaves do Pydantic (snake_case) para as chaves de input (camelCase/Alias)
                        dados_para_salvar = {}
                        
                        # Preenchimento dos inputs com os dados extraídos pelo Gemini
                        # Usando get() para lidar com possíveis retornos vazios
                        dados_para_salvar['ID'] = st.text_input("ID", value=dados_extraidos.get("ID", ""))
                        dados_para_salvar['FAMÍLIA'] = st.text_input("FAMÍLIA", value=dados_extraidos.get("FAMÍLIA", ""))
                        dados_para_salvar['Nome Completo'] = st.text_input("Nome Completo", value=dados_extraidos.get("Nome Completo", ""))
                        dados_para_salvar['Data de Nascimento'] = st.text_input("Data de Nascimento", value=dados_extraidos.get("Data de Nascimento", ""))
                        dados_para_salvar['CPF'] = st.text_input("CPF", value=dados_extraidos.get("CPF", ""))
                        dados_para_salvar['CNS'] = st.text_input("CNS", value=dados_extraidos.get("CNS", ""))
                        dados_para_salvar['Telefone'] = st.text_input("Telefone", value=dados_extraidos.get("Telefone", ""))
                        dados_para_salvar['Nome da Mãe'] = st.text_input("Nome da Mãe", value=dados_extraidos.get("Nome da Mãe", ""))
                        dados_para_salvar['Nome do Pai'] = st.text_input("Nome do Pai", value=dados_extraidos.get("Nome do Pai", ""))
                        
                        sexo_extraido = dados_extraidos.get("Sexo", "").strip().upper()[:1]
                        sexo_selecionado = ""
                        if sexo_extraido in ["M", "F", "I"]:
                            sexo_selecionado = sexo_extraido
                        
                        dados_para_salvar['Sexo'] = st.selectbox("Sexo", options=["", "M", "F", "I (Ignorado)"], index=["", "M", "F", "I (Ignorado)"].index(sexo_selecionado) if sexo_selecionado else 0)
                        dados_para_salvar['Município de Nascimento'] = st.text_input("Município de Nascimento", value=dados_extraidos.get("Município de Nascimento", ""))
                        
                        if st.form_submit_button("✅ Salvar Dados Desta Ficha"):
                            # Validação de Duplicidade
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
    # Incluindo a coluna de Link da Pasta na visualização do Dashboard
    colunas_tabela = [col for col in df_filtrado.columns if col not in ['Data de Nascimento DT']]
    st.dataframe(df_filtrado[colunas_tabela])
    @st.cache_data
    def convert_df_to_csv(df):
        return df.to_csv(index=False).encode('utf-8')
    csv = convert_df_to_csv(df_filtrado)
    st.download_button(label="📥 Descarregar Dados Filtrados (CSV)", data=csv, file_name='dados_filtrados.csv', mime='text/csv')

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

def main():
    query_params = st.query_params
    
    # 1. Configuração da Chave API e Cliente Gemini (FEITA AQUI PARA REUTILIZAÇÃO)
    try:
        API_KEY = st.secrets["GOOGLE_API_KEY"]
        # CRÍTICO: Cria o objeto Client.
        gemini_client = genai.Client(api_key=API_KEY)
    except KeyError:
        st.error("ERRO: Chave API do Gemini não encontrada. Verifique se 'GOOGLE_API_KEY' está no seu secrets.toml.")
        return
    except Exception as e:
        st.error(f"Falha ao inicializar o cliente Gemini: {e}")
        return
    
    # Rota para o Dashboard de Resumo (uso em TV/Totem)
    if query_params.get("page") == "resumo":
        try:
            st.set_page_config(page_title="Resumo de Pacientes", layout="centered")
            # Atualiza a página a cada 60 segundos
            st.html("<meta http-equiv='refresh' content='60'>") 
            planilha_conectada = conectar_planilha()
            if planilha_conectada:
                pagina_dashboard_resumo(planilha_conectada)
            else:
                st.error("Falha na conexão com a base de dados.")
        except Exception as e:
            st.error(f"Ocorreu um erro crítico: {e}")
    else:
        # Rota Principal da Aplicação
        st.set_page_config(page_title="Coleta Inteligente", page_icon="🤖", layout="wide")
        st.sidebar.title("Navegação")
        
        try:
            planilha_conectada = conectar_planilha()
        except Exception as e:
            st.error(f"Não foi possível inicializar os serviços de Sheets. Erro: {e}")
            st.stop()
            
        if planilha_conectada is None:
            st.error("A conexão com a planilha falhou.")
            st.stop()
        
        # Paginas que precisam do cliente Gemini recebem o objeto 'gemini_client'
        paginas = {
            "🏠 Início": pagina_inicial,
            "Verificação Rápida WhatsApp": lambda: pagina_ocr_e_alerta_whatsapp(planilha_conectada),
            "Análise de Vacinação": lambda: pagina_analise_vacinacao(planilha_conectada, gemini_client),
            "Importar Dados de Prontuário": lambda: pagina_importar_prontuario(planilha_conectada, gemini_client),
            "Coletar Fichas": lambda: pagina_coleta(planilha_conectada, gemini_client),
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
    # Para o código funcionar, você deve incluir no seu secrets.toml:
    # 1. GOOGLE_API_KEY (sua chave Gemini)
    # 2. OCRSPACEKEY (sua chave OCRSpace)
    # 3. SHEETSID (ID da sua planilha)
    # 4. As credenciais completas de Service Account para gspread.
    main()
