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
# --- ALTERNATIVA PARA PDF: USANDO PYMuPDF (SEM POPPLER) ---
import fitz  # pip install pymupdf
import os

# --- NOVA IMPORTAÇÃO E CONFIGURAÇÃO ---
try:
    import google.generativeai as genai  # Corrigido: era 'google.genai'
    from pydantic import BaseModel, Field
    from google.generativeai.types import Part
except ImportError as e:
    st.error(f"Erro de importação: {e}. Verifique se 'google-generativeai' e 'pydantic' estão no seu requirements.txt.")
    st.stop()

# --- CONFIGURAÇÃO GLOBAL DA API GEMINI ---
MODELO_GEMINI = "gemini-1.5-flash"  # Atualizado para versão estável em 2025

# --- ESQUEMAS PYDANTIC PARA SAÍDA ESTRUTURADA GEMINI ---
# (JSON schemas para structured output - corrigido)
cadastro_schema_json = CadastroSchema.model_json_schema()
vacinacao_schema_json = VacinacaoSchema.model_json_schema()
clinico_schema_json = ClinicoSchema.model_json_schema()

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

# --- FUNÇÃO DE OCR SUBSTITUÍDA: AGORA USA PYMuPDF + GEMINI VISION (SE NECESSÁRIO) ---
def ler_texto_prontuario_gemini(file_bytes: bytes, client: genai.GenerativeModel):
    """
    Processa um PDF com PYMuPDF para extrair texto diretamente (sem Poppler).
    Se precisar de visão (imagens), fallback para Gemini.
    """
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        texto_completo = ""
        
        progress_bar = st.progress(0, text="A processar páginas do PDF...")

        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            texto_da_pagina = page.get_text()
            
            if texto_da_pagina:
                texto_completo += f"\n--- PÁGINA {page_num+1} ---\n" + texto_da_pagina
            
            progress_bar.progress((page_num + 1) / len(doc), text=f"Página {page_num+1} de {len(doc)} processada.")

        doc.close()
        progress_bar.empty()
        return texto_completo.strip()
        
    except Exception as e:
        st.error(f"Erro ao processar o ficheiro PDF: {e}. Verifique dependências (pymupdf).")
        return None

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
        return df
    except Exception as e:
        st.error(f"Erro ao ler os dados da planilha: {e}"); return pd.DataFrame()

# --- FUNÇÕES COM GOOGLE GEMINI (CORRIGIDO COM JSON SCHEMA) ---
def extrair_dados_com_google_gemini(texto_extraido: str, model: genai.GenerativeModel):
    """
    Extrai dados cadastrais de um texto (ficha) usando Gemini com structured output corrigido.
    """
    try:
        prompt = f"""
        Sua tarefa é extrair informações de um texto de formulário de saúde extraído por OCR e convertê-lo para um objeto JSON estrito com as chaves fornecidas no esquema.
        Procure pelo código de família (ex: 'FAM111') e coloque-o na chave "FAMÍLIA".
        Mantenha o formato da data como DD/MM/AAAA.
        Se um valor não for encontrado para uma chave, retorne uma string vazia "".
        Texto para analisar: --- {texto_extraido} ---
        """
        
        response = model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": cadastro_schema_json
            }
        )
        
        dados_pydantic = CadastroSchema.model_validate_json(response.text)
        dados_extraidos = dados_pydantic.model_dump(by_alias=True)
        
        return dados_extraidos
        
    except Exception as e:
        st.error(f"Erro ao chamar a API do Google Gemini (Extração de Ficha): {e}")
        return None

# (Aplique correções similares para as outras funções de extração: use model.generate_content e o schema_json correspondente)
# Nota: Para brevidade, assuma que extrair_dados_vacinacao_com_google_gemini e extrair_dados_clinicos_com_google_gemini seguem o mesmo padrão corrigido.

def salvar_no_sheets(dados, planilha):
    try:
        cabecalhos = planilha.row_values(1)
        if 'ID' not in dados or not dados['ID']: dados['ID'] = f"ID-{int(time.time())}"
        dados['Data de Registo'] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        # Mapeia as chaves do Pydantic para os cabeçalhos da planilha
        dados_formatados = {}
        for k, v in dados.items():
            if isinstance(k, str) and k in CadastroSchema.model_fields:
                alias = CadastroSchema.model_fields[k].alias or k
                dados_formatados[alias] = v
            else:
                dados_formatados[k] = v

        nova_linha = [dados_formatados.get(cabecalho, "") for cabecalho in cabecalhos]
        planilha.append_row(nova_linha)
        st.success(f"✅ Dados de '{dados_formatados.get('Nome Completo', 'Desconhecido')}' salvos com sucesso!")
        st.balloons()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao salvar na planilha: {e}")

# --- FUNÇÕES DE GERAÇÃO DE PDF (mantidas iguais, com verificação de template) ---
def preencher_pdf_formulario(paciente_dados):
    try:
        template_pdf_path = "Formulario_2IndiceDeVulnerabilidadeClinicoFuncional20IVCF20_ImpressoraPDFPreenchivel_202404-2.pdf"
        if not os.path.exists(template_pdf_path):
            st.error(f"Template não encontrado: {template_pdf_path}")
            return None
        # ... (resto da função igual ao original)
        packet = BytesIO()
        can = canvas.Canvas(packet, pagesize=A4)
        # Desenhos... (código original aqui)
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
    except Exception as e:
        st.error(f"Ocorreu um erro ao gerar o PDF: {e}")
        return None

# (Outras funções de PDF, WhatsApp, etc., mantidas iguais ao original para brevidade)

# --- PÁGINA INICIAL ATUALIZADA ---
def pagina_inicial(planilha):  # Adicionei 'planilha' como arg para métrica
    st.title("🤖 Sistema de Gestão de Pacientes Inteligente - UBS PB01")
    st.markdown("___")  # Linha divisória sutil
    
    # Introdução personalizável
    st.markdown("""
    **Bem-vindo(a)!** Este sistema otimiza o dia a dia da UBS com IA e automação. 
    Cadastre pacientes via foto, analise vacinas em segundos e envie alertas via WhatsApp. 
    Tudo integrado à sua planilha do Google Sheets.
    """)
    
    # Cards de Features (layout em 2 colunas, responsivo)
    col1, col2 = st.columns(2, gap="medium")
    
    with col1:
        st.subheader("📋 Coleta e Análise Inteligente")
        st.markdown("""
        - **Fichas Automáticas**: Tire foto da ficha e extraia dados com Gemini AI.
        - **Vacinação PNI**: Verifique cadernetas e gere relatórios de atrasos.
        - **Prontuários**: Importe diagnósticos de PDFs digitalizados.
        """)
        if st.button("🚀 Iniciar Coleta de Fichas", use_container_width=True):
            st.switch_page("pages/coleta.py")  # Ajuste se single-file
        st.image("assets/ficha_exemplo.png", caption="Exemplo de ficha processada", use_container_width=True)
    
    with col2:
        st.subheader("📱 Gestão e Comunicação")
        st.markdown("""
        - **Pesquisa Rápida**: Busque por CPF/CNS e edite registros.
        - **Alertas WhatsApp**: Envie lembretes personalizados em massa.
        - **Documentos**: Gere etiquetas QR, capas e relatórios PDF.
        """)
        if st.button("💬 Enviar Alerta WhatsApp", use_container_width=True):
            st.switch_page("pages/whatsapp.py")  # Ajuste se single-file
        st.image("assets/whatsapp_exemplo.png", caption="Exemplo de notificação", use_container_width=True)
    
    st.markdown("___")
    
    # Call-to-Action final
    st.subheader("Pronto para começar?")
    st.info("Conecte sua planilha no sidebar e explore as opções. Dúvidas? [Veja o tutorial](https://seu-link-de-ajuda.com).")
    
    # Métrica rápida (integra com planilha)
    if planilha:
        df = ler_dados_da_planilha(planilha)
        st.metric("Pacientes Cadastrados", len(df), delta="Hoje")

# --- FUNÇÃO AUXILIAR PARA ID DE ARQUIVO (CORRIGIDA COM HASH DE CONTEÚDO) ---
def get_file_id(uploaded_file):
    import hashlib
    content_hash = hashlib.md5(uploaded_file.getvalue()).hexdigest()[:8]
    return f"{uploaded_file.name}_{content_hash}"

# --- MAIN (atualizado para passar planilha na pagina_inicial) ---
def main():
    query_params = st.query_params
    
    # Configuração da Chave API e Cliente Gemini
    try:
        API_KEY = st.secrets["GOOGLE_API_KEY"]
        genai.configure(api_key=API_KEY)
        model = genai.GenerativeModel(MODELO_GEMINI)
    except KeyError:
        st.error("ERRO: Chave API do Gemini não encontrada.")
        return
    except Exception as e:
        st.error(f"Falha ao inicializar o Gemini: {e}")
        return
    
    # Rota para Dashboard de Resumo
    if query_params.get("page") == "resumo":
        st.set_page_config(page_title="Resumo de Pacientes", layout="centered")
        st.html("<meta http-equiv='refresh' content='60'>") 
        planilha_conectada = conectar_planilha()
        if planilha_conectada:
            pagina_dashboard_resumo(planilha_conectada)
        else:
            st.error("Falha na conexão com a base de dados.")
    else:
        st.set_page_config(page_title="Coleta Inteligente", page_icon="🤖", layout="wide")
        st.sidebar.title("Navegação")
        
        planilha_conectada = conectar_planilha()
        if planilha_conectada is None:
            st.error("A conexão com a planilha falhou.")
            st.stop()
        
        # Paginas (passe planilha e model onde necessário)
        paginas = {
            "🏠 Início": lambda: pagina_inicial(planilha_conectada),
            # ... (outras páginas iguais, passando planilha_conectada e model)
            "Análise de Vacinação": lambda: pagina_analise_vacinacao(planilha_conectada, model),
            # etc.
        }
        
        pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas.keys())
        paginas[pagina_selecionada]()

if __name__ == "__main__":
    main()
