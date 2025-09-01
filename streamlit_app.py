# streamlit_app.py - VERSÃO FINAL COM OTIMIZAÇÃO DE MEMÓRIA

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
# Imports pesados foram removidos daqui e movidos para dentro das funções

# --- MOTOR DE REGRAS: CALENDÁRIO NACIONAL DE IMUNIZAÇÕES (PNI) ---
CALENDARIO_PNI = [
    {"vacina": "BCG", "dose": "Dose Única", "idade_meses": 0, "detalhe": "Protege contra formas graves de tuberculose."},
    # ... cole o resto do seu calendário aqui ...
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
# ... (cole suas outras funções utilitárias como validar_data_nascimento, etc. aqui) ...

def ler_texto_prontuario(file_bytes, ocr_api_key):
    # OTIMIZAÇÃO: Importa a biblioteca pesada apenas quando a função é chamada
    from pdf2image import convert_from_bytes
    # ... (seu código da função aqui) ...
    pass

# --- Funções de Conexão e API ---
@st.cache_resource
def conectar_planilha():
    # ... (seu código da função aqui) ...
    pass

@st.cache_data(ttl=300)
def ler_dados_da_planilha(_planilha):
    # ... (seu código da função aqui) ...
    pass

# ... (suas outras funções de API como ocr_space_api, extrair_dados_com_cohere, etc. aqui) ...

def salvar_no_sheets(dados, planilha):
    # ... (seu código da função aqui) ...
    pass

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
        # ... (seu código completo de preencher o PDF aqui) ...
        pass
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
    
    # ... (seu código completo de gerar etiquetas aqui) ...
    pass

# ... (suas outras funções de gerar PDF aqui, com os imports dentro delas) ...


# --- PÁGINAS DO APP ---
def pagina_dashboard(planilha):
    # OTIMIZAÇÃO: Importa matplotlib aqui dentro
    import matplotlib.pyplot as plt
    st.title("📊 Dashboard de Dados")
    # ... (seu código completo da página do dashboard aqui) ...

# ... (todas as suas outras funções de página como pagina_coleta, pagina_pesquisa, etc. aqui) ...

def main():
    # ... (seu código completo da função main, com o roteador de páginas, aqui) ...
    pass

if __name__ == "__main__":
    main()
