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
        Instrução Crítica: Procure por uma anotação à mão que pareça um código de família (ex: 'FAM111'). Este código deve ir para a chave "FAMÍLIA".
        Retorne APENAS um objeto JSON com as chaves: 'ID', 'FAMÍLIA', 'Nome Completo', 'Data de Nascimento', 'Telefone', 'CPF', 'Nome da Mãe', 'Nome do Pai', 'Sexo', 'CNS', 'Município de Nascimento'.
        Se um valor não for encontrado, retorne uma string vazia "".
        Texto para analisar: --- {texto_extraido} ---
        """
        response = cohere_client.chat(model="command-r-plus", message=prompt, temperature=0.1)
        json_string = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_string)
    except Exception as e:
        st.error(f"Erro ao chamar a API do Cohere: {e}"); return None

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

# --- FUNÇÕES DE GERAÇÃO DE PDF ---
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
    COR_PRINCIPAL = HexColor('#2c3e50')
    COR_SECUNDARIA = HexColor('#7f8c8d')
    COR_FUNDO_CABECALHO = HexColor('#ecf0f1')
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
        x_caixa = margem_caixa
        y_caixa = altura_pagina - 10 * cm
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
        x_label_esq = x_caixa + 1 * cm
        x_valor_esq = x_caixa + 4.5 * cm
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
        x_label_dir = x_caixa + (largura_caixa / 2) + 1 * cm
        x_valor_dir = x_caixa + (largura_caixa / 2) + 3.5 * cm
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
# ... (As funções de página existentes: pagina_gerar_documentos, pagina_coleta, etc. permanecem aqui)
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

def pagina_coleta(planilha, co_client):
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
                dados_extraidos = extrair_dados_com_cohere(texto_extraido, co_client)
                if dados_extraidos:
                    with st.form(key=f"form_{proximo_arquivo.file_id}"):
                        st.subheader("2. Confirme e salve os dados")
                        dados_para_salvar = {}
                        # ... (inputs do formulário)
                        if st.form_submit_button("✅ Salvar Dados Desta Ficha"):
                            # ... (lógica de verificação e salvamento)
                            pass
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
    # ... (restante do código do dashboard)
    pass

def pagina_pesquisa(planilha):
    st.title("🔎 Gestão de Pacientes")
    # ... (código da página de pesquisa)
    pass

def pagina_etiquetas(planilha):
    st.title("🏷️ Gerador de Etiquetas por Família")
    # ... (código da página de etiquetas)
    pass

def pagina_capas_prontuario(planilha):
    st.title("📇 Gerador de Capas de Prontuário")
    # ... (código da página de capas)
    pass
    
def pagina_whatsapp(planilha):
    st.title("📱 Enviar Mensagens de WhatsApp")
    # ... (código da página de whatsapp)
    pass

def pagina_analise_vacinacao(planilha):
    st.title("💉 Análise da Caderneta de Vacinação (Protótipo)")
    st.info("Esta página utiliza dados de teste para validar a lógica de análise do calendário vacinal.")
    st.subheader("Dados do Paciente (Simulação)")
    nome_paciente_teste = st.text_input("Nome do Paciente:", "José da Silva (Teste)")
    data_hoje = datetime.now()
    data_exemplo = (data_hoje - relativedelta(months=4)).strftime("%d/%m/%Y")
    data_nasc_teste = st.text_input("Data de Nascimento do Paciente:", data_exemplo)
    vacinas_teste = [
        {"vacina": "BCG", "dose": "Dose Única"},
        {"vacina": "Hepatite B", "dose": "1ª Dose"},
        {"vacina": "Pentavalente", "dose": "1ª Dose"},
        {"vacina": "VIP (Poliomielite inativada)", "dose": "1ª Dose"},
        {"vacina": "Pneumocócica 10V", "dose": "1ª Dose"},
        {"vacina": "Rotavírus", "dose": "1ª Dose"},
    ]
    st.write("Vacinas administradas (simulação):")
    st.json(vacinas_teste)
    if st.button("Analisar Situação Vacinal"):
        with st.spinner("Analisando..."):
            relatorio = analisar_carteira_vacinacao(data_nasc_teste, vacinas_teste)
            if "erro" in relatorio:
                st.error(relatorio["erro"])
            else:
                st.session_state['relatorio_vacinacao'] = relatorio
                st.session_state['nome_paciente_relatorio'] = nome_paciente_teste
                st.session_state['data_nasc_relatorio'] = data_nasc_teste
                st.subheader("Resultado da Análise")
                st.success("✅ Vacinas em Dia")
                if relatorio["em_dia"]:
                    for vac in relatorio["em_dia"]: st.write(f"- **{vac['vacina']} ({vac['dose']})** - Recomendada aos {vac['idade_meses']} meses.")
                else: st.write("Nenhuma vacina registrada como em dia.")
                st.warning("⚠️ Vacinas em Atraso")
                if relatorio["em_atraso"]:
                    for vac in relatorio["em_atraso"]: st.write(f"- **{vac['vacina']} ({vac['dose']})** - Deveria ter sido administrada aos {vac['idade_meses']} meses.")
                else: st.write("Nenhuma vacina em atraso identificada.")
                st.info("🗓️ Próximas Doses")
                if relatorio["proximas_doses"]:
                    proximas_ordenadas = sorted(relatorio["proximas_doses"], key=lambda x: x['idade_meses'])
                    for vac in proximas_ordenadas: st.write(f"- **{vac['vacina']} ({vac['dose']})** - Recomendada aos **{vac['idade_meses']} meses**.")
                else: st.write("Nenhuma próxima dose identificada no calendário do primeiro ano.")
    if 'relatorio_vacinacao' in st.session_state and st.session_state['relatorio_vacinacao']:
        st.markdown("---")
        st.subheader("Exportar Relatório")
        pdf_bytes = gerar_pdf_relatorio_vacinacao(
            st.session_state['nome_paciente_relatorio'],
            st.session_state['data_nasc_relatorio'],
            st.session_state['relatorio_vacinacao']
        )
        file_name = f"relatorio_vacinacao_{st.session_state['nome_paciente_relatorio'].replace(' ', '_')}.pdf"
        st.download_button(
            label="📥 Descarregar Relatório (PDF)",
            data=pdf_bytes,
            file_name=file_name,
            mime="application/pdf"
        )

def main():
    st.sidebar.title("Navegação")
    
    try:
        planilha_conectada = conectar_planilha()
    except Exception as e:
        st.error(f"Não foi possível inicializar os serviços. Verifique seus segredos. Erro: {e}")
        st.stop()
    if planilha_conectada is None:
        st.error("A conexão com a planilha falhou. Não é possível carregar a aplicação.")
        st.stop()
    co_client = None
    try:
        co_client = cohere.Client(api_key=st.secrets["COHEREKEY"])
    except Exception as e:
        st.warning(f"Não foi possível conectar ao serviço de IA. A página de coleta pode não funcionar. Erro: {e}")

    paginas = {
        "Coletar Fichas": lambda: pagina_coleta(planilha_conectada, co_client),
        "Gestão de Pacientes": lambda: pagina_pesquisa(planilha_conectada),
        "Dashboard": lambda: pagina_dashboard(planilha_conectada),
        "Gerar Etiquetas": lambda: pagina_etiquetas(planilha_conectada),
        "Gerar Capas de Prontuário": lambda: pagina_capas_prontuario(planilha_conectada),
        "Gerar Documentos": lambda: pagina_gerar_documentos(planilha_conectada),
        "Enviar WhatsApp": lambda: pagina_whatsapp(planilha_conectada),
        "Análise de Vacinação (Teste)": lambda: pagina_analise_vacinacao(planilha_conectada),
    }
    
    pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas.keys())
    paginas[pagina_selecionada]()

if __name__ == "__main__":
    main()
