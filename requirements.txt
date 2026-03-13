import re
import time
import urllib.parse
from io import BytesIO
from datetime import datetime

import gspread
import pandas as pd
import qrcode
import requests
import streamlit as st
import matplotlib.pyplot as plt

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pdf2image import convert_from_bytes
from dateutil.relativedelta import relativedelta

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader

try:
    from google import genai
    from google.genai.types import Part
    from pydantic import BaseModel, Field
except ImportError as e:
    st.error(
        f"Erro de importação: {e}. "
        "Verifique se 'google-genai' e 'pydantic' estão no requirements.txt."
    )
    st.stop()


MODELO_GEMINI = "gemini-2.5-flash"

EXAMES_COMUNS = [
    "Hemograma Completo",
    "Glicemia em Jejum",
    "Perfil Lipídico (Colesterol Total, HDL, LDL, Triglicerídeos)",
    "Exame de Urina (EAS)",
    "Ureia e Creatinina (Função Renal)",
    "TSH e T4 Livre (Função Tireoidiana)",
    "PSA (Antígeno Prostático Específico)",
    "Papanicolau (Colpocitologia Oncótica)",
    "Eletrocardiograma (ECG)",
    "Teste Ergométrico",
    "Holter de 24 horas",
    "MAPA (Monitorização Ambulatorial da Pressão Arterial)",
    "Ultrassonografia (USG) Geral",
    "Ultrassonografia com Doppler (Vascular)",
    "Radiografia (Raio-X)",
    "Mamografia Digital",
    "Mamografia com Tomossíntese (3D)",
    "Densitometria Óssea",
    "Tomografia Computadorizada (TC)",
    "Angiotomografia (Angio-TC)",
    "Ressonância Magnética (RM)",
    "Angiorressonância (Angio-RM)",
    "Cintilografia (Medicina Nuclear)",
    "Ecocardiograma (Eco TT)",
    "Ecodoppler (de Carótidas, Venoso, etc.)",
    "Endoscopia Digestiva Alta",
    "Colonoscopia",
    "Retossigmoidoscopia",
    "Colposcopia",
    "Histerossalpingografia",
    "Biópsia (Guiada por Imagem ou PAAF)",
    "PET-CT (Tomografia por Emissão de Pósitrons)",
    "Artrografia",
    "Mielografia",
    "Urografia Excretora",
    "Eletroencefalograma (EEG)",
]

ESPECIALIDADES_MEDICAS = [
    "Clínica Médica", "Pediatria", "Ginecologia e Obstetrícia", "Cirurgia Geral",
    "Cardiologia", "Dermatologia", "Gastroenterologia", "Oftalmologia",
    "Ortopedia e Traumatologia", "Otorrinolaringologia", "Neurologia",
    "Psiquiatria", "Urologia", "Endocrinologia e Metabologia", "Nefrologia",
    "Reumatologia", "Pneumologia", "Infectologia", "Hematologia e Hemoterapia",
    "Oncologia", "Anestesiologia", "Medicina Intensiva", "Medicina da Família e Comunidade",
    "Medicina do Trabalho", "Cirurgia Plástica", "Cirurgia Vascular", "Neurocirurgia",
    "Hepatologia", "Geriatria", "Alergia e Imunologia", "Nutrologia",
    "Fisioterapia", "Nutrição", "Psicologia", "Odontologia (Geral)", "Fonoaudiologia",
    "Acupuntura", "Angiologia", "Cancerologia (Oncologia)", "Coloproctologia",
    "Genética Médica", "Homeopatia", "Medicina Física e Reabilitação",
    "Medicina Legal e Perícia Médica", "Medicina Nuclear", "Patologia",
    "Radiologia e Diagnóstico por Imagem"
]


class CadastroSchema(BaseModel):
    ID: str = Field(description="ID único gerado. Se não for claro, retornar vazio.")
    FAMÍLIA: str = Field(description="Código de família, ex: FAM111.")
    nome_completo: str = Field(alias="Nome Completo")
    data_nascimento: str = Field(alias="Data de Nascimento", description="Formato DD/MM/AAAA.")
    Telefone: str = ""
    CPF: str = ""
    nome_da_mae: str = Field(alias="Nome da Mãe", default="")
    nome_do_pai: str = Field(alias="Nome do Pai", default="")
    Sexo: str = Field(description="M, F, I (Ignorado).", default="")
    CNS: str = ""
    municipio_nascimento: str = Field(alias="Município de Nascimento", default="")

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "required": ["Nome Completo", "Data de Nascimento"]
        }
    }


class VacinaAdministrada(BaseModel):
    vacina: str
    dose: str


class VacinacaoSchema(BaseModel):
    nome_paciente: str = ""
    data_nascimento: str = ""
    vacinas_administradas: list[VacinaAdministrada] = []


class ClinicoSchema(BaseModel):
    diagnosticos: list[str] = []
    medicamentos: list[str] = []


class DicaSaude(BaseModel):
    titulo_curto: str
    texto_whatsapp: str


class DicasSaudeSchema(BaseModel):
    dicas: list[DicaSaude] = []


CALENDARIO_PNI = [
    {"vacina": "BCG", "dose": "Dose Única", "idade_meses": 0, "detalhe": "Protege contra formas graves de tuberculose."},
    {"vacina": "Hepatite B", "dose": "1ª Dose", "idade_meses": 0, "detalhe": "Primeira dose nas primeiras 12-24 horas de vida."},
    {"vacina": "Pentavalente", "dose": "1ª Dose", "idade_meses": 2, "detalhe": "Protege contra Difteria, Tétano, Coqueluche, Hepatite B e Hib."},
    {"vacina": "VIP (Poliomielite inativada)", "dose": "1ª Dose", "idade_meses": 2, "detalhe": "Protege contra poliomielite."},
    {"vacina": "Pneumocócica 10V", "dose": "1ª Dose", "idade_meses": 2, "detalhe": "Protege contra doenças pneumocócicas."},
    {"vacina": "Rotavírus", "dose": "1ª Dose", "idade_meses": 2, "detalhe": "Idade máxima para iniciar: 3 meses e 15 dias."},
    {"vacina": "Meningocócica C", "dose": "1ª Dose", "idade_meses": 3, "detalhe": "Protege contra meningite C."},
    {"vacina": "Pentavalente", "dose": "2ª Dose", "idade_meses": 4, "detalhe": "Reforço da proteção."},
    {"vacina": "VIP (Poliomielite inativada)", "dose": "2ª Dose", "idade_meses": 4, "detalhe": "Reforço da proteção."},
    {"vacina": "Pneumocócica 10V", "dose": "2ª Dose", "idade_meses": 4, "detalhe": "Reforço da proteção."},
    {"vacina": "Rotavírus", "dose": "2ª Dose", "idade_meses": 4, "detalhe": "Idade máxima para a última dose: 7 meses e 29 dias."},
    {"vacina": "Meningocócica C", "dose": "2ª Dose", "idade_meses": 5, "detalhe": "Reforço da proteção."},
    {"vacina": "Pentavalente", "dose": "3ª Dose", "idade_meses": 6, "detalhe": "Finalização do esquema primário."},
    {"vacina": "VIP (Poliomielite inativada)", "dose": "3ª Dose", "idade_meses": 6, "detalhe": "Finalização do esquema primário."},
    {"vacina": "Febre Amarela", "dose": "Dose Inicial", "idade_meses": 9, "detalhe": "Reforço aos 4 anos."},
    {"vacina": "Tríplice Viral", "dose": "1ª Dose", "idade_meses": 12, "detalhe": "Protege contra Sarampo, Caxumba e Rubéola."},
    {"vacina": "Pneumocócica 10V", "dose": "Reforço", "idade_meses": 12, "detalhe": "Dose de reforço."},
    {"vacina": "Meningocócica C", "dose": "Reforço", "idade_meses": 12, "detalhe": "Dose de reforço."},
]


# =========================
# ESTILO VISUAL
# =========================
def aplicar_estilo_visual():
    st.markdown(
        """
        <style>
        .main {
            background-color: #f7f9fc;
        }
        .block-container {
            padding-top: 1.2rem;
            padding-bottom: 2rem;
            max-width: 1250px;
        }
        h1, h2, h3 {
            color: #1f4e78;
        }
        .card {
            background: white;
            padding: 18px;
            border-radius: 16px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.06);
            border-left: 6px solid #1f4e78;
            margin-bottom: 12px;
        }
        .card-success {
            background: #eefaf2;
            padding: 18px;
            border-radius: 16px;
            border-left: 6px solid #27ae60;
            box-shadow: 0 2px 12px rgba(0,0,0,0.04);
            margin-bottom: 12px;
        }
        .card-warning {
            background: #fff8ed;
            padding: 18px;
            border-radius: 16px;
            border-left: 6px solid #e67e22;
            box-shadow: 0 2px 12px rgba(0,0,0,0.04);
            margin-bottom: 12px;
        }
        .card-danger {
            background: #fdeeee;
            padding: 18px;
            border-radius: 16px;
            border-left: 6px solid #e74c3c;
            box-shadow: 0 2px 12px rgba(0,0,0,0.04);
            margin-bottom: 12px;
        }
        .small-title {
            font-size: 14px;
            color: #7f8c8d;
            margin-bottom: 6px;
        }
        .big-number {
            font-size: 28px;
            font-weight: 700;
            color: #2c3e50;
        }
        .section-box {
            background: white;
            border-radius: 16px;
            padding: 18px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
            margin-bottom: 16px;
        }
        .stButton button {
            border-radius: 10px;
            background-color: #1f4e78;
            color: white;
            border: none;
            font-weight: 600;
        }
        .stButton button:hover {
            background-color: #163a59;
            color: white;
        }
        .hero {
            background: linear-gradient(135deg, #1f4e78 0%, #2c3e50 100%);
            color: white;
            padding: 22px;
            border-radius: 18px;
            margin-bottom: 18px;
        }
        .hero h1, .hero p {
            color: white !important;
            margin: 0;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def hero(titulo: str, subtitulo: str):
    st.markdown(
        f"""
        <div class="hero">
            <h1>{titulo}</h1>
            <p>{subtitulo}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


# =========================
# FUNÇÕES UTILITÁRIAS
# =========================
def validar_cpf(cpf: str) -> bool:
    cpf = ''.join(re.findall(r'\d', str(cpf)))
    if not cpf or len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    try:
        soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
        d1 = (soma * 10 % 11) % 10
        if d1 != int(cpf[9]):
            return False
        soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
        d2 = (soma * 10 % 11) % 10
        if d2 != int(cpf[10]):
            return False
    except Exception:
        return False
    return True


def validar_data_nascimento(data_str: str) -> tuple[bool, str]:
    try:
        data_obj = datetime.strptime(data_str, "%d/%m/%Y").date()
        if data_obj > datetime.now().date():
            return False, "A data de nascimento está no futuro."
        return True, ""
    except ValueError:
        return False, "O formato da data deve ser DD/MM/AAAA."


def calcular_idade(data_nasc):
    if pd.isna(data_nasc):
        return 0
    hoje = datetime.now()
    return hoje.year - data_nasc.year - ((hoje.month, hoje.day) < (data_nasc.month, data_nasc.day))


def padronizar_telefone(telefone):
    if pd.isna(telefone) or telefone == "":
        return None
    num_limpo = re.sub(r"\D", "", str(telefone))
    if num_limpo.startswith("55"):
        num_limpo = num_limpo[2:]
    if 10 <= len(num_limpo) <= 11:
        return num_limpo
    return None


def get_file_id(uploaded_file):
    import hashlib
    file_hash = hashlib.md5(uploaded_file.name.encode()).hexdigest()[:8]
    return f"{uploaded_file.name}_{file_hash}"


# =========================
# GEMINI
# =========================
def extrair_dados_com_google_gemini(texto_extraido: str, client: genai.Client):
    try:
        prompt = f"""
        Extraia informações de um formulário de saúde para JSON estrito.
        Procure pelo código de família (ex: FAM111) e coloque em "FAMÍLIA".
        Mantenha datas em DD/MM/AAAA.
        Se um valor não for encontrado, retorne string vazia.
        Texto:
        --- {texto_extraido} ---
        """
        response = client.models.generate_content(
            model=MODELO_GEMINI,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": CadastroSchema,
            },
        )
        return CadastroSchema.model_validate_json(response.text).model_dump(by_alias=True)
    except Exception as e:
        st.error(f"Erro ao extrair dados com Gemini: {e}")
        return None


def extrair_dados_vacinacao_com_google_gemini(texto_extraido: str, client: genai.Client):
    try:
        prompt = f"""
        Analise o texto de uma caderneta de vacinação brasileira e retorne JSON estrito.
        Normalize:
        - Penta / DTP+HB+Hib -> Pentavalente
        - Polio / VIP -> VIP (Poliomielite inativada)
        - Meningo C / MNG C -> Meningocócica C
        - SCR -> Tríplice Viral
        Texto:
        --- {texto_extraido} ---
        """
        response = client.models.generate_content(
            model=MODELO_GEMINI,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": VacinacaoSchema,
            },
        )
        return VacinacaoSchema.model_validate_json(response.text).model_dump()
    except Exception as e:
        st.error(f"Erro ao processar vacinação com Gemini: {e}")
        return None


def extrair_dados_clinicos_com_google_gemini(texto_prontuario: str, client: genai.Client):
    try:
        prompt = f"""
        Analise o texto de um prontuário médico e extraia:
        - diagnosticos
        - medicamentos
        Retorne apenas JSON estrito.
        Texto:
        ---
        {texto_prontuario}
        ---
        """
        response = client.models.generate_content(
            model=MODELO_GEMINI,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": ClinicoSchema,
            },
        )
        return ClinicoSchema.model_validate_json(response.text).model_dump()
    except Exception as e:
        st.error(f"Erro ao processar prontuário com Gemini: {e}")
        return None


def gerar_dicas_com_google_gemini(tema: str, client: genai.Client):
    try:
        prompt = f"""
        Gere 5 dicas de saúde pública e alimentação.
        Tema: "{tema}".
        Para cada dica:
        - título curto (máx 5 palavras)
        - texto curto para WhatsApp (máx 2 frases)
        Retorne JSON estrito.
        """
        response = client.models.generate_content(
            model=MODELO_GEMINI,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": DicasSaudeSchema,
            },
        )
        return DicasSaudeSchema.model_validate_json(response.text).model_dump()
    except Exception as e:
        st.error(f"Erro ao gerar dicas com Gemini: {e}")
        return None


def ler_texto_prontuario_gemini(file_bytes: bytes, client: genai.Client):
    try:
        imagens_pil = convert_from_bytes(file_bytes)
        texto_completo = ""
        progress_bar = st.progress(0, text="Processando páginas do PDF com Gemini Vision...")

        for i, imagem in enumerate(imagens_pil):
            with BytesIO() as buffer:
                imagem.save(buffer, format="JPEG")
                img_bytes = buffer.getvalue()

            image_part = Part.from_bytes(data=img_bytes, mime_type="image/jpeg")

            response = client.models.generate_content(
                model=MODELO_GEMINI,
                contents=[
                    image_part,
                    "Transcreva fielmente todo o texto presente nesta imagem. Não adicione comentários.",
                ],
            )

            if response.text:
                texto_completo += f"\n--- PÁGINA {i+1} ---\n{response.text}"

            progress_bar.progress(
                (i + 1) / len(imagens_pil),
                text=f"Página {i+1} de {len(imagens_pil)} processada.",
            )

        progress_bar.empty()
        return texto_completo.strip()
    except Exception as e:
        st.error(f"Erro ao processar PDF com Gemini Vision: {e}")
        return None


# =========================
# PLANILHA
# =========================
@st.cache_resource
def conectar_planilha():
    try:
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
        plan = client.open_by_key(st.secrets["SHEETSID"])
        try:
            return plan.worksheet("Página1")
        except Exception:
            return plan.sheet1
    except Exception as e:
        st.error(f"Erro ao conectar com o Google Sheets: {e}")
        return None


@st.cache_data(ttl=300)
def ler_dados_da_planilha(_planilha):
    try:
        dados = _planilha.get_all_records()
        df = pd.DataFrame(dados)

        colunas_esperadas = [
            "ID", "FAMÍLIA", "Nome Completo", "Data de Nascimento", "Idade", "Sexo",
            "Nome da Mãe", "Nome do Pai", "Município de Nascimento", "Município de Residência",
            "CPF", "CNS", "Telefone", "Observações", "Fonte da Imagem",
            "Data da Extração", "Link da Pasta da Família", "Timestamp de Envio",
            "Condição", "Data de Registo", "Raça/Cor", "Status_Vacinal",
            "Medicamentos", "Link do Prontuário"
        ]

        for col in colunas_esperadas:
            if col not in df.columns:
                df[col] = ""

        df["Data de Nascimento DT"] = pd.to_datetime(
            df["Data de Nascimento"], format="%d/%m/%Y", errors="coerce"
        )

        if "Idade" not in df.columns:
            df["Idade"] = ""

        df["Idade"] = df.apply(
            lambda row: row["Idade"]
            if str(row.get("Idade", "")).strip() != ""
            else (
                calcular_idade(row["Data de Nascimento DT"])
                if pd.notnull(row["Data de Nascimento DT"])
                else 0
            ),
            axis=1,
        )

        return df
    except Exception as e:
        st.error(f"Erro ao ler os dados da planilha: {e}")
        return pd.DataFrame()


def salvar_no_sheets(dados, planilha):
    try:
        cabecalhos = planilha.row_values(1)

        if not cabecalhos:
            st.error("A planilha não possui cabeçalhos na primeira linha.")
            return

        if "ID" not in dados or not str(dados.get("ID", "")).strip():
            dados["ID"] = f"ID-{int(time.time())}"

        agora = datetime.now()
        dados["Timestamp de Envio"] = agora.strftime("%d/%m/%Y %H:%M:%S")
        dados["Data da Extração"] = agora.strftime("%d/%m/%Y")
        dados["Data de Registo"] = agora.strftime("%d/%m/%Y %H:%M:%S")

        idade_calculada = ""
        data_nasc_str = str(dados.get("Data de Nascimento", "")).strip()
        if data_nasc_str:
            try:
                data_nasc_dt = datetime.strptime(data_nasc_str, "%d/%m/%Y")
                hoje = datetime.now()
                idade_calculada = hoje.year - data_nasc_dt.year - (
                    (hoje.month, hoje.day) < (data_nasc_dt.month, data_nasc_dt.day)
                )
            except ValueError:
                idade_calculada = ""

        dados["Idade"] = idade_calculada

        mapa_campos = {
            "ID": dados.get("ID", ""),
            "FAMÍLIA": dados.get("FAMÍLIA", ""),
            "Nome Completo": dados.get("Nome Completo", ""),
            "Data de Nascimento": dados.get("Data de Nascimento", ""),
            "Idade": dados.get("Idade", ""),
            "Sexo": dados.get("Sexo", ""),
            "Nome da Mãe": dados.get("Nome da Mãe", dados.get("Mãe", "")),
            "Nome do Pai": dados.get("Nome do Pai", dados.get("Pai", "")),
            "Município de Nascimento": dados.get("Município de Nascimento", ""),
            "Município de Residência": dados.get("Município de Residência", ""),
            "CPF": dados.get("CPF", ""),
            "CNS": dados.get("CNS", ""),
            "Telefone": dados.get("Telefone", ""),
            "Observações": dados.get("Observações", ""),
            "Fonte da Imagem": dados.get("Fonte da Imagem", ""),
            "Data da Extração": dados.get("Data da Extração", ""),
            "Link da Pasta da Família": dados.get("Link da Pasta da Família", ""),
            "Timestamp de Envio": dados.get("Timestamp de Envio", ""),
            "Condição": dados.get("Condição", ""),
            "Data de Registo": dados.get("Data de Registo", ""),
            "Raça/Cor": dados.get("Raça/Cor", ""),
            "Status_Vacinal": dados.get("Status_Vacinal", dados.get("Status Vacinal", "")),
            "Medicamentos": dados.get("Medicamentos", ""),
            "Link do Prontuário": dados.get("Link do Prontuário", ""),
        }

        nova_linha = [mapa_campos.get(cabecalho, "") for cabecalho in cabecalhos]
        planilha.append_row(nova_linha, value_input_option="USER_ENTERED")

        st.success(f"✅ Dados de '{mapa_campos.get('Nome Completo', 'Desconhecido')}' salvos com sucesso!")
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao salvar na planilha: {e}")


# =========================
# PDF / QR
# =========================
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
        if sexo.startswith("F"):
            can.drawString(12.1 * cm, 22.9 * cm, "X")
        elif sexo.startswith("M"):
            can.drawString(12.6 * cm, 22.9 * cm, "X")
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
            img_qr.save(qr_buffer, format="PNG")
            qr_buffer.seek(0)
            can.drawImage(ImageReader(qr_buffer), x_base + 0.5 * cm, y_base + 0.5 * cm, width=2.5 * cm, height=2.5 * cm)

        x_texto = x_base + 3.5 * cm
        y_texto = y_base + altura_etiqueta - 0.8 * cm
        can.setFont("Helvetica-Bold", 12)
        can.drawString(x_texto, y_texto, f"Família: {familia_id} PB01")
        y_texto -= 0.6 * cm

        for membro in dados_familia["membros"]:
            can.setFont("Helvetica-Bold", 8)
            nome = membro.get("Nome Completo", "")
            if len(nome) > 35:
                nome = nome[:32] + "..."
            can.drawString(x_texto, y_texto, nome)
            y_texto -= 0.4 * cm
            can.setFont("Helvetica", 7)
            dn = membro.get("Data de Nascimento", "N/D")
            cns = membro.get("CNS", "N/D")
            can.drawString(x_texto, y_texto, f"DN: {dn} | CNS: {cns}")
            y_texto -= 0.5 * cm
            if y_texto < (y_base + 0.5 * cm):
                break

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

    cor_principal = HexColor("#2c3e50")
    cor_secundaria = HexColor("#7f8c8d")
    cor_fundo_cabecalho = HexColor("#ecf0f1")
    cor_alerta = HexColor("#e74c3c")
    cor_fundo_alerta = HexColor("#fde6e4")

    for _, paciente in pacientes_df.iterrows():
        can.setFont("Helvetica", 9)
        can.setFillColor(cor_secundaria)
        can.drawRightString(largura_pagina - 2 * cm, altura_pagina - 2 * cm, "Sistema de Gestão - PB01")

        can.setFont("Helvetica-Bold", 18)
        can.setFillColor(cor_principal)
        can.drawCentredString(largura_pagina / 2, altura_pagina - 4 * cm, "PRONTUÁRIO CLÍNICO INDIVIDUAL")

        margem_caixa = 2 * cm
        largura_caixa = largura_pagina - (2 * margem_caixa)
        altura_caixa = 5.5 * cm
        x_caixa, y_caixa = margem_caixa, altura_pagina - 10.5 * cm

        altura_cabecalho_interno = 1.5 * cm
        y_cabecalho_interno = y_caixa + altura_caixa - altura_cabecalho_interno
        can.setFillColor(cor_fundo_cabecalho)
        can.rect(x_caixa, y_cabecalho_interno, largura_caixa, altura_cabecalho_interno, stroke=0, fill=1)

        can.setStrokeColor(cor_principal)
        can.setLineWidth(1.5)
        can.rect(x_caixa, y_caixa, largura_caixa, altura_caixa, stroke=1, fill=0)

        nome_paciente = str(paciente.get("Nome Completo", "NOME INDISPONÍVEL")).upper()
        y_texto_nome = y_cabecalho_interno + (altura_cabecalho_interno / 2) - (0.2 * cm)
        can.setFont("Helvetica-Bold", 15)
        can.setFillColor(cor_principal)
        can.drawCentredString(largura_pagina / 2, y_texto_nome, nome_paciente)

        def draw_data_pair(y, label_esq, val_esq, label_dir, val_dir):
            x_label_esq, x_valor_esq = x_caixa + 1 * cm, x_caixa + 4.5 * cm
            x_label_dir, x_valor_dir = x_caixa + (largura_caixa / 2) + 1 * cm, x_caixa + (largura_caixa / 2) + 4 * cm
            can.setFont("Helvetica", 10)
            can.setFillColor(cor_secundaria)
            can.drawString(x_label_esq, y, f"{label_esq}:")
            can.drawString(x_label_dir, y, f"{label_dir}:")
            can.setFont("Helvetica-Bold", 11)
            can.setFillColor(cor_principal)
            can.drawString(x_valor_esq, y, str(val_esq))
            can.drawString(x_valor_dir, y, str(val_dir))

        y_inicio_dados = y_cabecalho_interno - 1.2 * cm
        draw_data_pair(y_inicio_dados, "Data de Nasc.", paciente.get("Data de Nascimento", "N/A"), "Família", paciente.get("FAMÍLIA", "N/A"))
        draw_data_pair(y_inicio_dados - 0.8 * cm, "CPF", paciente.get("CPF", "N/A"), "CNS", paciente.get("CNS", "N/A"))
        draw_data_pair(y_inicio_dados - 1.6 * cm, "Telefone", paciente.get("Telefone", "N/A"), "Sexo", paciente.get("Sexo", "N/A"))

        condicoes = str(paciente.get("Condição", "Nenhuma registrada")).strip()
        medicamentos = str(paciente.get("Medicamentos", "Nenhum registrado")).strip()

        x_alerta, y_alerta = 2 * cm, altura_pagina - 17 * cm
        largura_alerta = largura_pagina - 4 * cm
        altura_alerta = 2.5 * cm

        can.setFillColor(cor_fundo_alerta)
        can.setStrokeColor(cor_alerta)
        can.setLineWidth(0.5)
        can.rect(x_alerta, y_alerta, largura_alerta, altura_alerta, fill=1, stroke=1)

        can.setFont("Helvetica-Bold", 12)
        can.setFillColor(cor_alerta)
        can.drawString(x_alerta + 0.5 * cm, y_alerta + altura_alerta - 0.6 * cm, "ALERTA CLÍNICO RÁPIDO")

        can.setFont("Helvetica", 9)
        can.setFillColor(cor_principal)
        y_texto_alerta = y_alerta + altura_alerta - 1.5 * cm
        can.drawString(x_alerta + 0.5 * cm, y_texto_alerta, f"Condições: {condicoes}")
        can.drawString(x_alerta + 0.5 * cm, y_texto_alerta - 0.5 * cm, f"Medicamentos: {medicamentos}")

        can.setFont("Helvetica-Bold", 10)
        can.setFillColor(cor_principal)
        can.drawString(2 * cm, 5 * cm, "Observações Clínicas (uso do profissional):")

        can.setStrokeColor(cor_secundaria)
        can.setLineWidth(0.5)
        y_linha = 4.5 * cm
        for _ in range(4):
            can.line(2 * cm, y_linha, largura_pagina - 2 * cm, y_linha)
            y_linha -= 0.6 * cm

        can.showPage()

    can.save()
    pdf_buffer.seek(0)
    return pdf_buffer


def gerar_pdf_relatorio_vacinacao(nome_paciente, data_nascimento, relatorio):
    pdf_buffer = BytesIO()
    can = canvas.Canvas(pdf_buffer, pagesize=A4)
    largura_pagina, altura_pagina = A4
    cor_principal = HexColor("#2c3e50")
    cor_secundaria = HexColor("#7f8c8d")
    cor_sucesso = HexColor("#27ae60")
    cor_alerta = HexColor("#e67e22")
    cor_info = HexColor("#3498db")

    can.setFont("Helvetica-Bold", 16)
    can.setFillColor(cor_principal)
    can.drawCentredString(largura_pagina / 2, altura_pagina - 3 * cm, "Relatório de Situação Vacinal")
    can.setFont("Helvetica", 10)
    can.setFillColor(cor_secundaria)
    can.drawString(2 * cm, altura_pagina - 4.5 * cm, f"Paciente: {nome_paciente}")
    can.drawString(2 * cm, altura_pagina - 5 * cm, f"Data de Nascimento: {data_nascimento}")
    data_emissao = datetime.now().strftime("%d/%m/%Y às %H:%M")
    can.drawRightString(largura_pagina - 2 * cm, altura_pagina - 4.5 * cm, f"Emitido em: {data_emissao}")
    can.line(2 * cm, altura_pagina - 5.5 * cm, largura_pagina - 2 * cm, altura_pagina - 5.5 * cm)

    def desenhar_secao(titulo, cor_titulo, lista_vacinas, y_inicial):
        can.setFont("Helvetica-Bold", 12)
        can.setFillColor(cor_titulo)
        y_atual = y_inicial
        can.drawString(2 * cm, y_atual, titulo)
        y_atual -= 0.7 * cm

        if not lista_vacinas:
            can.setFont("Helvetica-Oblique", 10)
            can.setFillColor(cor_secundaria)
            can.drawString(2.5 * cm, y_atual, "Nenhuma vacina nesta categoria.")
            y_atual -= 0.7 * cm
            return y_atual

        can.setFont("Helvetica", 10)
        can.setFillColor(cor_principal)
        for vac in lista_vacinas:
            texto = f"• {vac['vacina']} ({vac['dose']}) - Idade recomendada: {vac['idade_meses']} meses."
            can.drawString(2.5 * cm, y_atual, texto)
            y_atual -= 0.6 * cm

        y_atual -= 0.5 * cm
        return y_atual

    y_corpo = altura_pagina - 6.5 * cm
    y_corpo = desenhar_secao("Vacinas com Pendência (Atraso)", cor_alerta, relatorio["em_atraso"], y_corpo)
    proximas_ordenadas = sorted(relatorio["proximas_doses"], key=lambda x: x["idade_meses"])
    y_corpo = desenhar_secao("Próximas Doses Recomendadas", cor_info, proximas_ordenadas, y_corpo)
    y_corpo = desenhar_secao("Vacinas em Dia", cor_sucesso, relatorio["em_dia"], y_corpo)

    can.save()
    pdf_buffer.seek(0)
    return pdf_buffer


# =========================
# WHATSAPP / PLACEHOLDERS
# =========================
def mascarar_cpf_cns(valor: str, tipo: str = "cpf") -> str:
    if pd.isna(valor) or not valor:
        return "Não Informado"
    digits = re.sub(r"\D", "", str(valor))
    if tipo == "cpf" and len(digits) == 11:
        return f"{digits[:3]}.***.***-{digits[-2:]}"
    elif len(digits) >= 6:
        return f"{digits[:3]}********{digits[-3:]}"
    return valor


def buscar_dados_completos_paciente(nome_paciente, df):
    paciente_row = df[df["Nome Completo"] == nome_paciente]
    if paciente_row.empty:
        return None
    dados = paciente_row.iloc[0].to_dict()
    dados["CPF_Mascarado"] = mascarar_cpf_cns(dados.get("CPF", ""), "cpf")
    dados["CNS_Mascarado"] = mascarar_cpf_cns(dados.get("CNS", ""), "cns")
    return dados


def aplicar_substituicoes_completas(mensagem, dados_paciente):
    substituicoes = {
        "[NOME]": dados_paciente.get("Nome Completo", "").split()[0] if dados_paciente.get("Nome Completo") else "",
        "[NOME_COMPLETO]": dados_paciente.get("Nome Completo", "Não Informado"),
        "[IDADE]": f"{dados_paciente.get('Idade', 'N/A')} anos",
        "[CPF]": dados_paciente.get("CPF", "Não Informado"),
        "[CNS]": dados_paciente.get("CNS", "Não Informado"),
        "[DATA_NASCIMENTO]": dados_paciente.get("Data de Nascimento", "Não Informado"),
        "[TELEFONE]": dados_paciente.get("Telefone", "Não Informado"),
        "[CONDICOES]": dados_paciente.get("Condição", "Nenhuma registrada"),
        "[MEDICAMENTOS]": dados_paciente.get("Medicamentos", "Nenhum registrado"),
        "[FAMILIA]": dados_paciente.get("FAMÍLIA", "N/A"),
        "[MUNICIPIO_NASC]": dados_paciente.get("Município de Nascimento", "N/A"),
    }
    for placeholder, valor in substituicoes.items():
        mensagem = mensagem.replace(placeholder, str(valor))
    return mensagem


# =========================
# REGRAS VACINAÇÃO
# =========================
def analisar_carteira_vacinacao(data_nascimento_str, vacinas_administradas):
    try:
        data_nascimento = datetime.strptime(data_nascimento_str, "%d/%m/%Y")
    except ValueError:
        return {"erro": "Formato da data de nascimento inválido. Utilize DD/MM/AAAA."}

    hoje = datetime.now()
    idade = relativedelta(hoje, data_nascimento)
    idade_total_meses = idade.years * 12 + idade.months
    vacinas_tomadas_set = {(v["vacina"], v["dose"]) for v in vacinas_administradas}
    relatorio = {"em_dia": [], "em_atraso": [], "proximas_doses": []}

    for regra in CALENDARIO_PNI:
        vacina_requerida = (regra["vacina"], regra["dose"])
        idade_recomendada_meses = regra["idade_meses"]
        if idade_total_meses >= idade_recomendada_meses:
            if vacina_requerida in vacinas_tomadas_set:
                relatorio["em_dia"].append(regra)
            else:
                relatorio["em_atraso"].append(regra)
        else:
            relatorio["proximas_doses"].append(regra)

    return relatorio


# =========================
# PÁGINAS
# =========================
def pagina_inicial():
    hero("Coleta Rápida", "Sistema inteligente para coleta, gestão e comunicação com pacientes.")
    c1, c2 = st.columns(2)

    with c1:
        st.markdown(
            """
            <div class="section-box">
                <h3>🤖 Coleta Inteligente</h3>
                <p>Extraia automaticamente dados de fichas e registre na base.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class="section-box">
                <h3>💉 Análise de Vacinação</h3>
                <p>Leia cadernetas e gere relatórios com doses em dia e pendentes.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with c2:
        st.markdown(
            """
            <div class="section-box">
                <h3>🔎 Gestão de Pacientes</h3>
                <p>Pesquise, edite, apague registros e visualize famílias.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class="section-box">
                <h3>📱 WhatsApp</h3>
                <p>Gere mensagens personalizadas para alertas, consultas e exames.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )


def pagina_gerador_cards(gemini_client):
    hero("Gerador de Cards de Saúde", "Crie 5 dicas curtas para cards e WhatsApp.")
    temas = [
        "Alimentação Saudável e Guia Alimentar",
        "Redução de Sal e Prevenção de Hipertensão",
        "Combate ao Sedentarismo e Atividade Física",
        "Saúde Mental e Bem-Estar Emocional",
        "Higiene e Prevenção de Doenças Infecciosas",
        "Diabetes e Controle Glicêmico",
        "Saúde da Gestante e Pré-Natal",
        "Saúde da Criança e Imunização",
        "Cuidado com a Saúde do Idoso",
    ]

    tema_selecionado = st.selectbox("Selecione o tema:", options=temas, index=0)
    if st.button("✨ Gerar 5 Dicas com a IA"):
        with st.spinner("Gerando dicas..."):
            dicas_geradas = gerar_dicas_com_google_gemini(tema_selecionado, gemini_client)
            if dicas_geradas and "dicas" in dicas_geradas:
                st.session_state.dicas_para_exibir = dicas_geradas["dicas"]
                st.session_state.tema_atual = tema_selecionado
                st.success("Dicas geradas com sucesso.")
            else:
                st.error("Falha ao gerar as dicas.")

    if st.session_state.get("dicas_para_exibir"):
        st.markdown("---")
        st.subheader(f"Conteúdo Gerado para {st.session_state.tema_atual}")
        dicas_whatsapp = ""
        for i, dica in enumerate(st.session_state.dicas_para_exibir):
            st.markdown(f"### 💡 Dica {i+1}")
            st.markdown(f"**Título curto:** `{dica['titulo_curto']}`")
            st.code(dica["texto_whatsapp"], language="text")
            dicas_whatsapp += f"💡 {dica['titulo_curto']}\n{dica['texto_whatsapp']}\n\n"

        mensagem_final = (
            "Olá! Aqui estão as dicas de saúde desta semana da equipe ESF AMPARO:\n\n"
            f"{dicas_whatsapp}"
            "Cuide-se! Em caso de dúvidas, ligue para 2641-1499.\n"
            "Atenciosamente, ESF AMPARO."
        )
        st.text_area("Mensagem completa:", value=mensagem_final, height=300)


def pagina_coleta(planilha, gemini_client):
    hero("Coleta Inteligente", "Envie imagens de fichas para extração e cadastro automático.")
    df_existente = ler_dados_da_planilha(planilha)

    uploaded_files = st.file_uploader(
        "Selecione uma ou mais imagens",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
    )

    if "processados" not in st.session_state:
        st.session_state.processados = []

    if uploaded_files:
        proximo_arquivo = next(
            (f for f in uploaded_files if get_file_id(f) not in st.session_state.processados),
            None,
        )

        if proximo_arquivo:
            st.subheader(f"Processando ficha: `{proximo_arquivo.name}`")
            st.image(Image.open(proximo_arquivo), width=420)

            file_bytes = proximo_arquivo.getvalue()
            texto_extraido = None

            with st.spinner("Extraindo texto da imagem com Gemini Vision..."):
                try:
                    image_part = Part.from_bytes(data=file_bytes, mime_type=proximo_arquivo.type)
                    response = gemini_client.models.generate_content(
                        model=MODELO_GEMINI,
                        contents=[image_part, "Transcreva fielmente todo o texto do formulário contido nesta imagem."],
                    )
                    texto_extraido = response.text
                except Exception as e:
                    st.error(f"Falha no OCR com Gemini Vision: {e}")

            if texto_extraido:
                dados_extraidos = extrair_dados_com_google_gemini(texto_extraido, gemini_client)

                if dados_extraidos:
                    with st.form(key=f"form_{get_file_id(proximo_arquivo)}"):
                        st.subheader("Confirmar e salvar dados")
                        dados_para_salvar = {}

                        col1, col2 = st.columns(2)
                        with col1:
                            dados_para_salvar["ID"] = st.text_input("ID", value=dados_extraidos.get("ID", ""))
                            dados_para_salvar["FAMÍLIA"] = st.text_input("FAMÍLIA", value=dados_extraidos.get("FAMÍLIA", ""))
                            dados_para_salvar["Nome Completo"] = st.text_input("Nome Completo", value=dados_extraidos.get("Nome Completo", ""))
                            dados_para_salvar["Data de Nascimento"] = st.text_input("Data de Nascimento", value=dados_extraidos.get("Data de Nascimento", ""))
                            dados_para_salvar["CPF"] = st.text_input("CPF", value=dados_extraidos.get("CPF", ""))
                            dados_para_salvar["CNS"] = st.text_input("CNS", value=dados_extraidos.get("CNS", ""))

                        with col2:
                            dados_para_salvar["Telefone"] = st.text_input("Telefone", value=dados_extraidos.get("Telefone", ""))
                            dados_para_salvar["Nome da Mãe"] = st.text_input("Nome da Mãe", value=dados_extraidos.get("Nome da Mãe", ""))
                            dados_para_salvar["Nome do Pai"] = st.text_input("Nome do Pai", value=dados_extraidos.get("Nome do Pai", ""))
                            sexo_extraido = dados_extraidos.get("Sexo", "").strip().upper()[:1]
                            sexo_selecionado = sexo_extraido if sexo_extraido in ["M", "F", "I"] else ""
                            dados_para_salvar["Sexo"] = st.selectbox(
                                "Sexo",
                                options=["", "M", "F", "I"],
                                index=["", "M", "F", "I"].index(sexo_selecionado) if sexo_selecionado else 0,
                            )
                            dados_para_salvar["Município de Nascimento"] = st.text_input(
                                "Município de Nascimento",
                                value=dados_extraidos.get("Município de Nascimento", ""),
                            )
                            dados_para_salvar["Município de Residência"] = st.text_input("Município de Residência", value="")

                        dados_para_salvar["Observações"] = st.text_area("Observações", value="")
                        c3, c4, c5 = st.columns(3)
                        with c3:
                            dados_para_salvar["Condição"] = st.text_input("Condição", value="")
                        with c4:
                            dados_para_salvar["Raça/Cor"] = st.text_input("Raça/Cor", value="")
                        with c5:
                            dados_para_salvar["Status_Vacinal"] = st.text_input("Status Vacinal", value="")

                        dados_para_salvar["Fonte da Imagem"] = proximo_arquivo.name
                        dados_para_salvar["Link da Pasta da Família"] = st.text_input("Link da Pasta da Família", value="")
                        dados_para_salvar["Medicamentos"] = st.text_input("Medicamentos", value="")
                        dados_para_salvar["Link do Prontuário"] = st.text_input("Link do Prontuário", value="")

                        if st.form_submit_button("✅ Salvar Dados Desta Ficha"):
                            cpf_a_verificar = "".join(re.findall(r"\d", dados_para_salvar["CPF"]))
                            cns_a_verificar = "".join(re.findall(r"\d", dados_para_salvar["CNS"]))

                            duplicado_cpf = False
                            if cpf_a_verificar and not df_existente.empty:
                                duplicado_cpf = any(
                                    df_existente["CPF"].astype(str).str.replace(r"\D", "", regex=True) == cpf_a_verificar
                                )

                            duplicado_cns = False
                            if cns_a_verificar and not df_existente.empty:
                                duplicado_cns = any(
                                    df_existente["CNS"].astype(str).str.replace(r"\D", "", regex=True) == cns_a_verificar
                                )

                            if duplicado_cpf or duplicado_cns:
                                st.error("⚠️ Já existe um paciente registrado com este CPF ou CNS.")
                            else:
                                salvar_no_sheets(dados_para_salvar, planilha)
                                st.session_state.processados.append(get_file_id(proximo_arquivo))
                                st.rerun()
                else:
                    st.error("A IA não conseguiu extrair dados deste texto.")
            else:
                st.error("Não foi possível extrair texto desta imagem.")

        elif len(uploaded_files) > 0:
            st.success("🎉 Todas as fichas enviadas foram processadas e salvas.")
            if st.button("Limpar lista para enviar novas imagens"):
                st.session_state.processados = []
                st.rerun()


def pagina_dashboard(planilha):
    hero("Dashboard de Dados", "Visualize métricas, filtros e distribuição da sua base.")
    df_original = ler_dados_da_planilha(planilha)
    if df_original.empty:
        st.warning("Ainda não há dados na planilha para exibir.")
        return

    st.sidebar.header("Filtros do Dashboard")
    municipios = sorted(df_original["Município de Nascimento"].astype(str).unique())
    municipios_selecionados = st.sidebar.multiselect("Filtrar por Município:", options=municipios, default=municipios)

    df_original["Idade"] = pd.to_numeric(df_original["Idade"], errors="coerce").fillna(0)
    idade_max = int(df_original["Idade"].max()) if not df_original["Idade"].empty else 100
    faixa_etaria = st.sidebar.slider("Filtrar por Faixa Etária:", min_value=0, max_value=max(idade_max, 1), value=(0, max(idade_max, 1)))

    df_filtrado = df_original[
        (df_original["Município de Nascimento"].isin(municipios_selecionados))
        & (df_original["Idade"] >= faixa_etaria[0])
        & (df_original["Idade"] <= faixa_etaria[1])
    ]

    if df_filtrado.empty:
        st.warning("Nenhum dado encontrado com os filtros selecionados.")
        return

    total = len(df_filtrado)
    idade_media = df_filtrado.loc[df_filtrado["Idade"] > 0, "Idade"].mean()
    idosos = df_filtrado[df_filtrado["Idade"] >= 60].shape[0]
    criancas = df_filtrado[df_filtrado["Idade"].between(0, 11)].shape[0]

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            f'<div class="card"><div class="small-title">Total de Fichas</div><div class="big-number">{total}</div></div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f'<div class="card-warning"><div class="small-title">Idosos</div><div class="big-number">{idosos}</div></div>',
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f'<div class="card-success"><div class="small-title">Crianças</div><div class="big-number">{criancas}</div></div>',
            unsafe_allow_html=True,
        )
    with c4:
        st.markdown(
            f'<div class="card"><div class="small-title">Idade Média</div><div class="big-number">{idade_media:.1f if pd.notna(idade_media) else 0}</div></div>'.replace("nan", "0"),
            unsafe_allow_html=True,
        )

    gcol1, gcol2 = st.columns(2)
    with gcol1:
        st.markdown("### Pacientes por Município")
        municipio_counts = df_filtrado["Município de Nascimento"].value_counts()
        st.bar_chart(municipio_counts)

    with gcol2:
        st.markdown("### Distribuição por Sexo")
        sexo_counts = df_filtrado["Sexo"].astype(str).str.strip().str.capitalize().value_counts()
        fig, ax = plt.subplots(figsize=(5, 3))
        if not sexo_counts.empty:
            sexo_counts.plot.pie(ax=ax, autopct="%1.1f%%", startangle=90)
            ax.axis("equal")
            st.pyplot(fig)

    st.markdown("### Tabela de Dados")
    st.dataframe(df_filtrado, use_container_width=True)


def desenhar_dashboard_familia(familia_id, df_completo):
    st.header(f"Dashboard da Família: {familia_id}")
    df_familia = df_completo[df_completo["FAMÍLIA"] == familia_id].copy()
    st.subheader("Membros da Família")
    st.dataframe(df_familia[["Nome Completo", "Data de Nascimento", "Idade", "Sexo", "CPF", "CNS"]], use_container_width=True)

    st.markdown("---")
    st.subheader("Acompanhamento Individual")
    cols = st.columns(max(len(df_familia), 1))

    for i, (_, membro) in enumerate(df_familia.iterrows()):
        with cols[i]:
            st.info(f"**{membro['Nome Completo'].split()[0]}** ({membro['Idade']} anos)")
            condicoes = membro.get("Condição", "")
            medicamentos = membro.get("Medicamentos", "")
            st.write(f"**Condições:** {condicoes if condicoes else 'Nenhuma registrada.'}")
            st.write(f"**Medicamentos:** {medicamentos if medicamentos else 'Nenhum registrado.'}")


def pagina_pesquisa(planilha):
    hero("Gestão de Pacientes", "Pesquise, edite, apague e visualize famílias.")
    if "familia_selecionada_id" in st.session_state and st.session_state.familia_selecionada_id:
        if st.button("⬅️ Voltar para a Pesquisa"):
            del st.session_state.familia_selecionada_id
            st.rerun()

    df = ler_dados_da_planilha(planilha)
    if df.empty:
        st.warning("Ainda não há dados na planilha para pesquisar.")
        return

    if "familia_selecionada_id" in st.session_state and st.session_state.familia_selecionada_id:
        desenhar_dashboard_familia(st.session_state.familia_selecionada_id, df)
        return

    colunas_pesquisaveis = ["Nome Completo", "CPF", "CNS", "Nome da Mãe", "ID", "FAMÍLIA"]
    coluna_selecionada = st.selectbox("Pesquisar por:", colunas_pesquisaveis)
    termo_pesquisa = st.text_input("Digite o termo de pesquisa:")

    if termo_pesquisa:
        resultados = df[df[coluna_selecionada].astype(str).str.contains(termo_pesquisa, case=False, na=False)]
        st.markdown(f"**{len(resultados)}** resultado(s) encontrado(s):")

        for _, row in resultados.iterrows():
            id_paciente = row["ID"]
            with st.expander(f"**{row['Nome Completo']}** (ID: {id_paciente})"):
                st.dataframe(row.to_frame().T, hide_index=True, use_container_width=True)
                botoes = st.columns(3)

                with botoes[0]:
                    if st.button("✏️ Editar Dados", key=f"edit_{id_paciente}"):
                        st.session_state["patient_to_edit"] = row.to_dict()
                        st.rerun()

                with botoes[1]:
                    if st.button("🗑️ Apagar Registo", key=f"delete_{id_paciente}"):
                        try:
                            cell = planilha.find(str(id_paciente))
                            planilha.delete_rows(cell.row)
                            st.success(f"Registo de {row['Nome Completo']} apagado com sucesso!")
                            st.cache_data.clear()
                            time.sleep(1)
                            st.rerun()
                        except gspread.exceptions.CellNotFound:
                            st.error(f"Não foi possível encontrar o paciente com ID {id_paciente}.")
                        except Exception as e:
                            st.error(f"Ocorreu um erro ao apagar: {e}")

                with botoes[2]:
                    familia_id = row.get("FAMÍLIA")
                    if familia_id:
                        if st.button("👨‍👩‍👧 Ver Dashboard da Família", key=f"fam_{id_paciente}"):
                            st.session_state.familia_selecionada_id = familia_id
                            st.rerun()

    if "patient_to_edit" in st.session_state:
        st.markdown("---")
        st.subheader("Editando Paciente")
        patient_data = st.session_state["patient_to_edit"]

        with st.form(key="edit_form"):
            edited_data = {}
            for key, value in patient_data.items():
                if key not in ["Data de Nascimento DT"]:
                    edited_data[key] = st.text_input(f"{key}", value=value, key=f"edit_{key}")

            if st.form_submit_button("Salvar Alterações"):
                try:
                    cell = planilha.find(str(patient_data["ID"]))
                    cabecalhos = planilha.row_values(1)
                    update_values = [edited_data.get(h, "") for h in cabecalhos]
                    planilha.update(f"A{cell.row}", [update_values])
                    st.success("Dados do paciente atualizados com sucesso!")
                    del st.session_state["patient_to_edit"]
                    st.cache_data.clear()
                    time.sleep(1)
                    st.rerun()
                except gspread.exceptions.CellNotFound:
                    st.error(f"Não foi possível encontrar o paciente com ID {patient_data['ID']}.")
                except Exception as e:
                    st.error(f"Ocorreu um erro ao salvar: {e}")


def pagina_etiquetas(planilha):
    hero("Gerador de Etiquetas", "Crie etiquetas por família com QR Code da pasta.")
    df = ler_dados_da_planilha(planilha)
    if df.empty:
        st.warning("Ainda não há dados na planilha para gerar etiquetas.")
        return

    def agregador(x):
        return {
            "membros": x[["Nome Completo", "Data de Nascimento", "CNS"]].to_dict("records"),
            "link_pasta": x["Link da Pasta da Família"].iloc[0] if "Link da Pasta da Família" in x.columns and not x["Link da Pasta da Família"].empty else "",
        }

    df_familias = df[df["FAMÍLIA"].astype(str).str.strip() != ""]
    if df_familias.empty:
        st.warning("Não há famílias para exibir.")
        return

    familias_dict = df_familias.groupby("FAMÍLIA").apply(agregador).to_dict()
    lista_familias = sorted([f for f in familias_dict.keys() if f])
    familias_selecionadas = st.multiselect("Famílias:", lista_familias)

    familias_para_gerar = familias_dict if not familias_selecionadas else {
        fid: familias_dict[fid] for fid in familias_selecionadas
    }

    if not familias_para_gerar:
        st.warning("Nenhuma família para exibir.")
        return

    for familia_id, dados_familia in familias_para_gerar.items():
        with st.expander(f"**Família: {familia_id}** ({len(dados_familia['membros'])} membro(s))"):
            for membro in dados_familia["membros"]:
                st.write(f"**{membro['Nome Completo']}**")
                st.caption(f"DN: {membro['Data de Nascimento']} | CNS: {membro['CNS']}")

    if st.button("📥 Gerar PDF das Etiquetas com QR Code"):
        pdf_bytes = gerar_pdf_etiquetas(familias_para_gerar)
        st.download_button(
            label="Descarregar PDF",
            data=pdf_bytes,
            file_name=f"etiquetas_qrcode_{datetime.now().strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
        )


def pagina_capas_prontuario(planilha):
    hero("Capas de Prontuário", "Gere capas profissionais para os pacientes selecionados.")
    df = ler_dados_da_planilha(planilha)
    if df.empty:
        st.warning("Ainda não há dados para gerar capas.")
        return

    lista_pacientes = df["Nome Completo"].tolist()
    pacientes_selecionados_nomes = st.multiselect("Escolha um ou mais pacientes:", sorted(lista_pacientes))

    if pacientes_selecionados_nomes:
        pacientes_df = df[df["Nome Completo"].isin(pacientes_selecionados_nomes)]
        st.dataframe(
            pacientes_df[["Nome Completo", "Data de Nascimento", "FAMÍLIA", "CPF", "CNS"]],
            use_container_width=True,
        )

        if st.button("📥 Gerar PDF das Capas"):
            pdf_bytes = gerar_pdf_capas_prontuario(pacientes_df)
            st.download_button(
                label="Descarregar PDF das Capas",
                data=pdf_bytes,
                file_name=f"capas_prontuario_{datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
            )


def pagina_gerar_documentos(planilha):
    hero("Gerador de Documentos", "Preencha formulários PDF com dados do paciente.")
    df = ler_dados_da_planilha(planilha)
    if df.empty:
        st.warning("Não há pacientes para gerar documentos.")
        return

    lista_pacientes = sorted(df["Nome Completo"].tolist())
    paciente_selecionado_nome = st.selectbox("Escolha um paciente:", lista_pacientes, index=None)

    if paciente_selecionado_nome:
        paciente_dados = df[df["Nome Completo"] == paciente_selecionado_nome].iloc[0]
        if st.button("📄 Gerar Formulário de Vulnerabilidade"):
            pdf_buffer = preencher_pdf_formulario(paciente_dados.to_dict())
            if pdf_buffer:
                st.download_button(
                    label="Descarregar Formulário Preenchido (PDF)",
                    data=pdf_buffer,
                    file_name=f"formulario_{paciente_selecionado_nome.replace(' ', '_')}.pdf",
                    mime="application/pdf",
                )


def pagina_whatsapp(planilha):
    hero("WhatsApp Manual", "Gere mensagens personalizadas por paciente ou em massa.")
    df = ler_dados_da_planilha(planilha)

    df_com_telefone = df[df["Telefone"].astype(str).str.strip() != ""].copy()
    df_com_telefone["Telefone Limpo"] = df_com_telefone["Telefone"].apply(padronizar_telefone)
    df_com_telefone.dropna(subset=["Telefone Limpo"], inplace=True)

    if df_com_telefone.empty:
        st.warning("Não há pacientes com telefones válidos.")
        return

    lista_pacientes = sorted(df_com_telefone["Nome Completo"].tolist())

    col1, col2 = st.columns(2)
    with col1:
        tipo_mensagem = st.selectbox(
            "Tipo de Notificação:",
            options=["Exames", "Marcação Médica", "Orientações Gerais", "Personalizada"],
        )
    with col2:
        enviar_para = st.selectbox(
            "Enviar para:",
            options=["Um paciente", "Múltiplos pacientes (em massa)"],
        )

    templates = {
        "Exames": """Olá, [NOME]! Seu exame [TIPO_EXAME] está agendado para [DATA_HORA]. Leve jejum de 8h e seu CNS: [CNS]. Histórico: [IDADE], condições: [CONDICOES]. Dúvidas? Ligue [TELEFONE_UBS]. [SAÚDE MUNICIPAL]""",
        "Marcação Médica": """Olá, [NOME]! Consulta com [MEDICO_ESPECIALIDADE] marcada para [DATA_HORA]. Traga medicamentos: [MEDICAMENTOS]. Família: [FAMILIA]. Confirme presença! [SAÚDE MUNICIPAL]""",
        "Orientações Gerais": """Olá, [NOME]! Orientação: Mantenha hidratação e monitore [CONDICOES]. Próxima dose vacinal em [DATA_PROXIMA]. Idade: [IDADE] | Nasc.: [DATA_NASCIMENTO]. Suporte: [TELEFONE_UBS]. [SAÚDE MUNICIPAL]""",
        "Personalizada": """Olá, [NOME]! [SUA_MENSAGEM_AQUI]. Histórico: [CONDICOES] | Medicamentos: [MEDICAMENTOS]. [SAÚDE MUNICIPAL]""",
    }
    mensagem_base = templates.get(tipo_mensagem, templates["Personalizada"])

    custom_fields = {}
    if tipo_mensagem == "Exames":
        custom_fields["TIPO_EXAME"] = st.selectbox("Tipo de Exame:", options=EXAMES_COMUNS, index=None)
        custom_fields["DATA_HORA"] = st.text_input("Data/Hora:", placeholder="DD/MM/YYYY HH:MM")
    elif tipo_mensagem == "Marcação Médica":
        especialidade = st.selectbox("Especialidade:", options=ESPECIALIDADES_MEDICAS, index=None)
        medico_input = st.text_input("Nome do Médico (Opcional):", placeholder="ex: Dr. Silva")
        custom_fields["DATA_HORA"] = st.text_input("Data/Hora:", placeholder="DD/MM/YYYY HH:MM")

        final_medico_especialidade = ""
        if medico_input and especialidade:
            final_medico_especialidade = f"{medico_input} ({especialidade})"
        elif especialidade:
            final_medico_especialidade = especialidade
        elif medico_input:
            final_medico_especialidade = medico_input

        custom_fields["MEDICO_ESPECIALIDADE"] = final_medico_especialidade
    elif tipo_mensagem == "Orientações Gerais":
        custom_fields["DATA_PROXIMA"] = st.text_input("Próxima Ação/Data:", placeholder="ex: 15/12/2025")

    for key, value in custom_fields.items():
        if value:
            mensagem_base = mensagem_base.replace(f"[{key}]", value)

    mensagem_padrao = st.text_area("Edite a mensagem:", mensagem_base, height=160)

    telefone_contato = st.text_input("Telefone de contato:", value="2641-1499")
    if telefone_contato:
        mensagem_padrao = mensagem_padrao.replace("[TELEFONE_UBS]", telefone_contato)

    assinatura_fechamento = st.text_input("Assinatura:", value="Atenciosamente, ESF AMPARO.")
    if assinatura_fechamento:
        mensagem_padrao = mensagem_padrao.replace("[SAÚDE MUNICIPAL]", assinatura_fechamento)

    if enviar_para == "Um paciente":
        paciente_selecionado_nome = st.selectbox("Paciente:", lista_pacientes)
        pacientes_selecionados = [paciente_selecionado_nome] if paciente_selecionado_nome else []
    else:
        pacientes_selecionados = st.multiselect("Pacientes:", lista_pacientes)

    if pacientes_selecionados:
        st.markdown("---")
        for nome_paciente in pacientes_selecionados:
            with st.expander(f"Preview para {nome_paciente}"):
                dados_paciente = buscar_dados_completos_paciente(nome_paciente, df_com_telefone)
                if dados_paciente:
                    mensagem_final = aplicar_substituicoes_completas(mensagem_padrao, dados_paciente)
                    st.code(mensagem_final, language="text")
                    telefone_limpo = dados_paciente["Telefone Limpo"]
                    whatsapp_url = f"https://wa.me/55{telefone_limpo}?text={urllib.parse.quote(mensagem_final)}"
                    st.link_button("Abrir WhatsApp", whatsapp_url)


def pagina_ocr_e_alerta_whatsapp(planilha):
    hero("Verificação Rápida + WhatsApp", "Localize um paciente e gere a notificação com dados completos.")
    df = ler_dados_da_planilha(planilha)
    if df.empty:
        st.error("A planilha não possui dados para busca.")
        return

    df_com_telefone = df[df["Telefone"].astype(str).str.strip() != ""].copy()
    df_com_telefone["Telefone Limpo"] = df_com_telefone["Telefone"].apply(padronizar_telefone)
    df_com_telefone.dropna(subset=["Telefone Limpo"], inplace=True)

    if df_com_telefone.empty:
        st.error("Nenhum paciente na planilha tem telefone válido.")
        return

    foto_paciente = st.camera_input("Tire uma foto do documento do paciente:")
    nome_para_buscar = None

    if foto_paciente is not None:
        lista_pacientes_validos = df_com_telefone["Nome Completo"].tolist()
        nome_para_buscar = st.selectbox(
            "Simule o nome que a IA extraiu:",
            options=sorted(lista_pacientes_validos),
            index=None,
        )

    if nome_para_buscar:
        dados_paciente = buscar_dados_completos_paciente(nome_para_buscar, df_com_telefone)
        if dados_paciente is None:
            st.error(f"O nome '{nome_para_buscar}' não consta na planilha.")
            return

        telefone_limpo = dados_paciente["Telefone Limpo"]

        mensagem_default = (
            "Olá, [NOME]! Seu procedimento foi LIBERADO. Resumo do seu histórico:\n\n"
            "- Idade: [IDADE] | Nasc.: [DATA_NASCIMENTO]\n"
            "- CPF: [CPF_Mascarado] | CNS: [CNS_Mascarado]\n"
            "- Condições: [CONDICOES]\n"
            "- Medicamentos: [MEDICAMENTOS]\n\n"
            "Entre em contato com sua UBS. [SAÚDE MUNICIPAL]"
        )

        mensagem_padrao = st.text_area(
            f"Mensagem para {nome_para_buscar.split()[0]}:",
            mensagem_default,
            height=150,
        )

        mensagem_personalizada = aplicar_substituicoes_completas(mensagem_padrao, dados_paciente)
        mensagem_personalizada = mensagem_personalizada.replace("[TELEFONE_UBS]", "2641-1499")
        mensagem_personalizada = mensagem_personalizada.replace("[SAÚDE MUNICIPAL]", "Atenciosamente, ESF AMPARO.")
        mensagem_personalizada = mensagem_personalizada.replace("[CPF_Mascarado]", dados_paciente["CPF"])
        mensagem_personalizada = mensagem_personalizada.replace("[CNS_Mascarado]", dados_paciente["CNS"])

        whatsapp_url = f"https://wa.me/55{telefone_limpo}?text={urllib.parse.quote(mensagem_personalizada)}"
        st.link_button("Abrir WhatsApp e Enviar", whatsapp_url)


def pagina_analise_vacinacao(planilha, gemini_client):
    hero("Análise de Vacinação", "Leia cadernetas e gere relatórios automáticos.")
    if "uploaded_file_id" not in st.session_state:
        st.session_state.dados_extraidos = None
        st.session_state.relatorio_final = None

    uploaded_file = st.file_uploader("Envie a foto da caderneta de vacinação:", type=["jpg", "jpeg", "png"])

    if uploaded_file is not None:
        file_id = get_file_id(uploaded_file)
        if st.session_state.get("uploaded_file_id") != file_id:
            st.session_state.dados_extraidos = None
            st.session_state.relatorio_final = None
            st.session_state.uploaded_file_id = file_id
            st.rerun()

        if st.session_state.get("dados_extraidos") is None:
            texto_extraido = None
            with st.spinner("Extraindo texto da caderneta com Gemini Vision..."):
                try:
                    image_part = Part.from_bytes(data=uploaded_file.getvalue(), mime_type=uploaded_file.type)
                    response = gemini_client.models.generate_content(
                        model=MODELO_GEMINI,
                        contents=[image_part, "Transcreva fielmente todos os dados de vacinação e as datas desta caderneta."],
                    )
                    texto_extraido = response.text
                except Exception as e:
                    st.error(f"Falha no OCR com Gemini Vision: {e}")

            if texto_extraido:
                dados = extrair_dados_vacinacao_com_google_gemini(texto_extraido, gemini_client)
                if dados:
                    st.session_state.dados_extraidos = dados
                    st.rerun()
                else:
                    st.error("A IA não conseguiu estruturar os dados.")
            else:
                st.error("O OCR não conseguiu extrair texto da imagem.")

        if st.session_state.get("dados_extraidos") is not None and st.session_state.get("relatorio_final") is None:
            st.subheader("Validação dos Dados Extraídos")
            with st.form(key="validation_form"):
                dados = st.session_state.dados_extraidos
                nome_validado = st.text_input("Nome do Paciente:", value=dados.get("nome_paciente", ""))
                dn_validada = st.text_input("Data de Nascimento:", value=dados.get("data_nascimento", ""))
                vacinas_validadas_df = pd.DataFrame(dados.get("vacinas_administradas", []))
                vacinas_editadas = st.data_editor(vacinas_validadas_df, num_rows="dynamic")

                if st.form_submit_button("✅ Confirmar Dados e Analisar"):
                    relatorio = analisar_carteira_vacinacao(dn_validada, vacinas_editadas.to_dict("records"))
                    st.session_state.relatorio_final = relatorio
                    st.session_state.nome_paciente_final = nome_validado
                    st.session_state.data_nasc_final = dn_validada
                    st.rerun()

        if st.session_state.get("relatorio_final") is not None:
            relatorio = st.session_state.relatorio_final
            st.subheader(f"Relatório para: {st.session_state.nome_paciente_final}")

            if "erro" in relatorio:
                st.error(relatorio["erro"])
            else:
                st.success("✅ Vacinas em Dia")
                if relatorio["em_dia"]:
                    for vac in relatorio["em_dia"]:
                        st.write(f"- **{vac['vacina']} ({vac['dose']})**")
                else:
                    st.write("Nenhuma vacina registrada como em dia.")

                st.warning("⚠️ Vacinas em Atraso")
                if relatorio["em_atraso"]:
                    for vac in relatorio["em_atraso"]:
                        st.write(f"- **{vac['vacina']} ({vac['dose']})** - Recomendada aos {vac['idade_meses']} meses.")
                else:
                    st.write("Nenhuma vacina em atraso identificada.")

                st.info("🗓️ Próximas Doses")
                if relatorio["proximas_doses"]:
                    proximas_ordenadas = sorted(relatorio["proximas_doses"], key=lambda x: x["idade_meses"])
                    for vac in proximas_ordenadas:
                        st.write(f"- **{vac['vacina']} ({vac['dose']})** - Recomendada aos **{vac['idade_meses']} meses**.")
                else:
                    st.write("Nenhuma próxima dose identificada.")

                pdf_bytes = gerar_pdf_relatorio_vacinacao(
                    st.session_state.nome_paciente_final,
                    st.session_state.data_nasc_final,
                    st.session_state.relatorio_final,
                )
                file_name = f"relatorio_vacinacao_{st.session_state.nome_paciente_final.replace(' ', '_')}.pdf"
                st.download_button(
                    label="📥 Descarregar Relatório (PDF)",
                    data=pdf_bytes,
                    file_name=file_name,
                    mime="application/pdf",
                )

    if st.button("Analisar Nova Caderneta"):
        st.session_state.clear()
        st.rerun()


def pagina_importar_prontuario(planilha, gemini_client):
    hero("Importar Prontuário Clínico", "Extraia diagnósticos e medicamentos de PDFs.")
    try:
        df = ler_dados_da_planilha(planilha)
        if df.empty:
            st.warning("Não há pacientes na base de dados.")
            return

        lista_pacientes = sorted(df["Nome Completo"].tolist())
        paciente_selecionado = st.selectbox("Selecione o paciente:", lista_pacientes, index=None)
        uploaded_file = st.file_uploader("Carregue o prontuário em PDF:", type=["pdf"])

        if paciente_selecionado and uploaded_file:
            if st.button("🔍 Iniciar Extração de Dados"):
                st.session_state.dados_clinicos_extraidos = None
                with st.spinner("Processando PDF e analisando com IA..."):
                    texto_prontuario = ler_texto_prontuario_gemini(uploaded_file.getvalue(), gemini_client)

                if texto_prontuario:
                    dados_clinicos = extrair_dados_clinicos_com_google_gemini(texto_prontuario, gemini_client)
                    if dados_clinicos:
                        st.session_state.dados_clinicos_extraidos = dados_clinicos
                        st.session_state.paciente_para_atualizar = paciente_selecionado
                        st.rerun()
                    else:
                        st.error("A IA não conseguiu extrair informações clínicas.")
                else:
                    st.error("Não foi possível extrair texto do PDF.")

        if "dados_clinicos_extraidos" in st.session_state and st.session_state.dados_clinicos_extraidos is not None:
            st.subheader("Valide os Dados e Salve na Planilha")
            dados = st.session_state.dados_clinicos_extraidos

            with st.form(key="clinical_data_form"):
                st.write(f"**Paciente:** {st.session_state.paciente_para_atualizar}")
                diagnosticos_validados = st.multiselect(
                    "Diagnósticos Encontrados:",
                    options=dados.get("diagnosticos", []),
                    default=dados.get("diagnosticos", []),
                )
                medicamentos_validados = st.multiselect(
                    "Medicamentos Encontrados:",
                    options=dados.get("medicamentos", []),
                    default=dados.get("medicamentos", []),
                )

                if st.form_submit_button("✅ Salvar Informações no Registo do Paciente"):
                    try:
                        diagnosticos_str = ", ".join(diagnosticos_validados)
                        medicamentos_str = ", ".join(medicamentos_validados)

                        cell = planilha.find(st.session_state.paciente_para_atualizar)
                        headers = planilha.row_values(1)

                        col_condicao_index = headers.index("Condição") + 1 if "Condição" in headers else None
                        col_medicamentos_index = headers.index("Medicamentos") + 1 if "Medicamentos" in headers else None

                        if col_condicao_index:
                            planilha.update_cell(cell.row, col_condicao_index, diagnosticos_str)
                        if col_medicamentos_index:
                            planilha.update_cell(cell.row, col_medicamentos_index, medicamentos_str)

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
    hero("Resumo de Pacientes", "Visão rápida para monitoramento e exibição em TV ou painel.")
    st.caption(f"Dados atualizados em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

    try:
        df = ler_dados_da_planilha(planilha)
        if df.empty:
            st.warning("A base de dados de pacientes está vazia.")
            return

        total_pacientes = len(df)
        sexo_counts = df["Sexo"].astype(str).str.strip().str.upper().value_counts()
        total_homens = sexo_counts.get("M", 0) + sexo_counts.get("MASCULINO", 0)
        total_mulheres = sexo_counts.get("F", 0) + sexo_counts.get("FEMININO", 0)

        df["Idade"] = pd.to_numeric(df["Idade"], errors="coerce").fillna(0)
        total_criancas = df[df["Idade"].between(0, 11)].shape[0]
        total_adolescentes = df[df["Idade"].between(12, 17)].shape[0]
        total_idosos = df[df["Idade"] >= 60].shape[0]

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.markdown(
                f'<div class="card"><div class="small-title">Total de Pacientes</div><div class="big-number">{total_pacientes}</div></div>',
                unsafe_allow_html=True,
            )
        with col2:
            st.markdown(
                f'<div class="card-warning"><div class="small-title">Idosos</div><div class="big-number">{total_idosos}</div></div>',
                unsafe_allow_html=True,
            )
        with col3:
            st.markdown(
                f'<div class="card-success"><div class="small-title">Crianças</div><div class="big-number">{total_criancas}</div></div>',
                unsafe_allow_html=True,
            )
        with col4:
            st.markdown(
                f'<div class="card"><div class="small-title">Adolescentes</div><div class="big-number">{total_adolescentes}</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown("### Distribuição por Sexo")
        c1, c2 = st.columns(2)
        c1.metric("Homens", total_homens)
        c2.metric("Mulheres", total_mulheres)

    except Exception as e:
        st.error(f"Ocorreu um erro ao carregar as estatísticas: {e}")


def pagina_gerador_qrcode(planilha):
    hero("Gerador de QR Code", "Crie um QR Code para abrir o resumo em TV, totem ou celular.")
    base_url = st.text_input("URL Base da sua aplicação Streamlit Cloud:", placeholder="Ex: https://sua-app.streamlit.app")
    if base_url:
        dashboard_url = f"{base_url.strip('/')}?page=resumo"
        st.success(f"URL do Dashboard: {dashboard_url}")

        if st.button("Gerar QR Code"):
            try:
                qr = qrcode.QRCode(version=1, box_size=10, border=4)
                qr.add_data(dashboard_url)
                qr.make(fit=True)
                img_qr = qr.make_image(fill_color="black", back_color="white")
                qr_buffer = BytesIO()
                img_qr.save(qr_buffer, format="PNG")
                qr_buffer.seek(0)
                st.image(qr_buffer, caption="QR Code Gerado", width=300)
                st.download_button(
                    label="📥 Descarregar QR Code (PNG)",
                    data=qr_buffer,
                    file_name="qrcode_dashboard_pacientes.png",
                    mime="image/png",
                )
            except Exception as e:
                st.error(f"Ocorreu um erro ao gerar o QR Code: {e}")


# =========================
# MAIN
# =========================
def main():
    query_params = st.query_params

    try:
        api_key = st.secrets["GOOGLE_API_KEY"]
        gemini_client = genai.Client(api_key=api_key)
    except KeyError:
        st.error("ERRO: Chave API do Gemini não encontrada. Verifique 'GOOGLE_API_KEY' no secrets.")
        return
    except Exception as e:
        st.error(f"Falha ao inicializar o cliente Gemini: {e}")
        return

    if query_params.get("page") == "resumo":
        st.set_page_config(page_title="Resumo de Pacientes", layout="centered")
        aplicar_estilo_visual()
        try:
            planilha_conectada = conectar_planilha()
            if planilha_conectada:
                pagina_dashboard_resumo(planilha_conectada)
            else:
                st.error("Falha na conexão com a base de dados.")
        except Exception as e:
            st.error(f"Ocorreu um erro crítico: {e}")
        return

    st.set_page_config(page_title="Coleta Rápida", page_icon="🤖", layout="wide")
    aplicar_estilo_visual()
    st.sidebar.title("Navegação")

    try:
        planilha_conectada = conectar_planilha()
    except Exception as e:
        st.error(f"Não foi possível inicializar os serviços de Sheets. Erro: {e}")
        st.stop()

    if planilha_conectada is None:
        st.error("A conexão com a planilha falhou.")
        st.stop()

    paginas = {
        "🏠 Início": pagina_inicial,
        "🤖 Gerar Cards de Saúde (IA)": lambda: pagina_gerador_cards(gemini_client),
        "📸 Verificação Rápida WhatsApp": lambda: pagina_ocr_e_alerta_whatsapp(planilha_conectada),
        "💉 Análise de Vacinação": lambda: pagina_analise_vacinacao(planilha_conectada, gemini_client),
        "📄 Importar Dados de Prontuário": lambda: pagina_importar_prontuario(planilha_conectada, gemini_client),
        "🧾 Coletar Fichas": lambda: pagina_coleta(planilha_conectada, gemini_client),
        "🔎 Gestão de Pacientes": lambda: pagina_pesquisa(planilha_conectada),
        "📊 Dashboard": lambda: pagina_dashboard(planilha_conectada),
        "🏷️ Gerar Etiquetas": lambda: pagina_etiquetas(planilha_conectada),
        "📇 Gerar Capas de Prontuário": lambda: pagina_capas_prontuario(planilha_conectada),
        "📄 Gerar Documentos": lambda: pagina_gerar_documentos(planilha_conectada),
        "📱 Enviar WhatsApp (Manual)": lambda: pagina_whatsapp(planilha_conectada),
        "🔳 Gerador de QR Code": lambda: pagina_gerador_qrcode(planilha_conectada),
    }

    pagina_selecionada = st.sidebar.radio("Escolha uma página:", list(paginas.keys()))
    paginas[pagina_selecionada]()


if __name__ == "__main__":
    main()
