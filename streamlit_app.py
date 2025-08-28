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
        colunas_esperadas = ["ID", "FAMÍLIA", "Nome Completo", "Data de Nascimento", "Telefone", "CPF", "Nome da Mãe", "Nome do Pai", "Sexo", "CNS", "Município de Nascimento", "Link do Prontuário", "Link da Pasta da Família", "Condição", "Data de Registo", "Raça/Cor"]
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
        Sua tarefa é extrair informações de um texto de formulário de saúde e convertê-lo para um JSON.
        Procure por uma anotação à mão que pareça um código de família (ex: 'FAM111'). Este código deve ir para a chave "FAMÍLIA".
        Retorne APENAS um objeto JSON com as chaves: 'ID', 'FAMÍLIA', 'Nome Completo', 'Data de Nascimento', 'Telefone', 'CPF', 'Nome da Mãe', 'Nome do Pai', 'Sexo', 'CNS', 'Município de Nascimento'.
        Se um valor não for encontrado, retorne uma string vazia "".
        Texto para analisar: --- {texto_extraido} ---
        """
        response = cohere_client.chat(model="command-r-plus", message=prompt, temperature=0.1)
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except Exception as e:
        st.error(f"Erro ao chamar a API do Cohere: {e}"); return None
        
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
    except Exception as e:
        st.error(f"Erro ao processar a resposta da IA: {e}")
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

# ... (Funções de PDF: preencher_pdf_formulario, gerar_pdf_etiquetas, gerar_pdf_capas_prontuario, gerar_pdf_relatorio_vacinacao)
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
# ... (páginas existentes)
def pagina_analise_vacinacao(planilha, co_client):
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
                    dados = extrair_dados_vacinacao_com_cohere(texto_extraido, co_client)
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
                # ... (código de exibição)
                st.warning("⚠️ Vacinas em Atraso")
                # ... (código de exibição)
                st.info("🗓️ Próximas Doses")
                # ... (código de exibição)
                pdf_bytes = gerar_pdf_relatorio_vacinacao(st.session_state.nome_paciente_final, st.session_state.data_nasc_final, st.session_state.relatorio_final)
                file_name = f"relatorio_vacinacao_{st.session_state.nome_paciente_final.replace(' ', '_')}.pdf"
                st.download_button(label="📥 Descarregar Relatório (PDF)", data=pdf_bytes, file_name=file_name, mime="application/pdf")

    if st.button("Analisar Nova Caderneta"):
        st.session_state.clear()
        st.rerun()

def main():
    st.sidebar.title("Navegação")
    planilha_conectada = conectar_planilha()
    if planilha_conectada is None:
        st.error("A conexão com a planilha falhou.")
        st.stop()
    co_client = None
    try:
        co_client = cohere.Client(api_key=st.secrets["COHEREKEY"])
    except Exception as e:
        st.warning(f"Não foi possível conectar ao serviço de IA. Funcionalidades limitadas. Erro: {e}")

    paginas = {
        "Análise de Vacinação": lambda: pagina_analise_vacinacao(planilha_conectada, co_client),
        "Coletar Fichas": lambda: pagina_coleta(planilha_conectada, co_client),
        "Gestão de Pacientes": lambda: pagina_pesquisa(planilha_conectada),
        "Dashboard": lambda: pagina_dashboard(planilha_conectada),
        "Gerar Etiquetas": lambda: pagina_etiquetas(planilha_conectada),
        "Gerar Capas de Prontuário": lambda: pagina_capas_prontuario(planilha_conectada),
        "Gerar Documentos": lambda: pagina_gerar_documentos(planilha_conectada),
        "Enviar WhatsApp": lambda: pagina_whatsapp(planilha_conectada),
    }
    
    pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas.keys())
    paginas[pagina_selecionada]()

if __name__ == "__main__":
    # Suprimindo o código completo das funções já definidas para brevidade
    # O código completo das funções (preencher_pdf_formulario, etc.) está omitido aqui
    # mas deve estar presente no seu ficheiro.
    main()
