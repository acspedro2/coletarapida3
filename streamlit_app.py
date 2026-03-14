import json
import re
import time
import urllib.parse
import uuid
from datetime import date, datetime
from io import BytesIO

import gspread
import matplotlib.pyplot as plt
import pandas as pd
import qrcode
import streamlit as st
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

GENAI_OK = True
PDF2IMAGE_OK = True

try:
    import google.genai as genai
    from google.genai.types import Part
    from pydantic import BaseModel, Field
except Exception:
    GENAI_OK = False

try:
    from pdf2image import convert_from_bytes
except Exception:
    PDF2IMAGE_OK = False


MODELO_GEMINI = "gemini-2.5-flash"

STATUS_OPCOES = ["Backlog", "Para Fazer", "Em Andamento", "Aguardando", "Concluído"]
PRIORIDADE_OPCOES = ["Baixa", "Média", "Alta", "Urgente"]

CORES_STATUS = {
    "Backlog": "#dfe6e9",
    "Para Fazer": "#74b9ff",
    "Em Andamento": "#ffeaa7",
    "Aguardando": "#fab1a0",
    "Concluído": "#55efc4",
}

COLUNAS_PACIENTES = [
    "ID",
    "FAMÍLIA",
    "Nome Completo",
    "Data de Nascimento",
    "Idade",
    "Sexo",
    "Nome da Mãe",
    "Nome do Pai",
    "Município de Nascimento",
    "Município de Residência",
    "CPF",
    "CNS",
    "Telefone",
    "Observações",
    "Fonte da Imagem",
    "Data da Extração",
    "Link da Pasta da Família",
    "Timestamp de Envio",
    "Condição",
    "Data de Registo",
    "Raça/Cor",
    "Status_Vacinal",
    "Medicamentos",
    "Link do Prontuário",
]

COLUNAS_KANBAN = [
    "ID",
    "Título",
    "Descrição",
    "Status",
    "Prioridade",
    "Responsável",
    "Prazo",
    "Checklist",
    "Comentários",
    "Criado em",
    "Atualizado em",
]

EXAMES_COMUNS = [
    "Hemograma Completo",
    "Glicemia em Jejum",
    "Perfil Lipídico",
    "Exame de Urina (EAS)",
    "Ureia e Creatinina",
    "TSH e T4 Livre",
    "PSA",
    "Papanicolau",
    "Eletrocardiograma (ECG)",
    "Teste Ergométrico",
    "Holter de 24 horas",
    "MAPA",
    "Ultrassonografia",
    "Radiografia (Raio-X)",
    "Mamografia",
    "Densitometria Óssea",
    "Tomografia",
    "Ressonância Magnética",
    "Ecocardiograma",
    "Endoscopia",
    "Colonoscopia",
]

ESPECIALIDADES_MEDICAS = [
    "Clínica Médica",
    "Pediatria",
    "Ginecologia e Obstetrícia",
    "Cirurgia Geral",
    "Cardiologia",
    "Dermatologia",
    "Gastroenterologia",
    "Oftalmologia",
    "Ortopedia",
    "Otorrinolaringologia",
    "Neurologia",
    "Psiquiatria",
    "Urologia",
    "Endocrinologia",
    "Nefrologia",
    "Reumatologia",
    "Pneumologia",
    "Infectologia",
    "Oncologia",
    "Geriatria",
    "Nutrição",
    "Psicologia",
    "Fisioterapia",
]

TEMAS_CARDS = [
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

CALENDARIO_PNI = [
    {"vacina": "BCG", "dose": "Dose Única", "idade_meses": 0},
    {"vacina": "Hepatite B", "dose": "1ª Dose", "idade_meses": 0},
    {"vacina": "Pentavalente", "dose": "1ª Dose", "idade_meses": 2},
    {"vacina": "VIP (Poliomielite inativada)", "dose": "1ª Dose", "idade_meses": 2},
    {"vacina": "Pneumocócica 10V", "dose": "1ª Dose", "idade_meses": 2},
    {"vacina": "Rotavírus", "dose": "1ª Dose", "idade_meses": 2},
    {"vacina": "Meningocócica C", "dose": "1ª Dose", "idade_meses": 3},
    {"vacina": "Pentavalente", "dose": "2ª Dose", "idade_meses": 4},
    {"vacina": "VIP (Poliomielite inativada)", "dose": "2ª Dose", "idade_meses": 4},
    {"vacina": "Pneumocócica 10V", "dose": "2ª Dose", "idade_meses": 4},
    {"vacina": "Rotavírus", "dose": "2ª Dose", "idade_meses": 4},
    {"vacina": "Meningocócica C", "dose": "2ª Dose", "idade_meses": 5},
    {"vacina": "Pentavalente", "dose": "3ª Dose", "idade_meses": 6},
    {"vacina": "VIP (Poliomielite inativada)", "dose": "3ª Dose", "idade_meses": 6},
    {"vacina": "Febre Amarela", "dose": "Dose Inicial", "idade_meses": 9},
    {"vacina": "Tríplice Viral", "dose": "1ª Dose", "idade_meses": 12},
    {"vacina": "Pneumocócica 10V", "dose": "Reforço", "idade_meses": 12},
    {"vacina": "Meningocócica C", "dose": "Reforço", "idade_meses": 12},
]

if GENAI_OK:
    class CadastroSchema(BaseModel):
        ID: str = Field(description="ID único gerado. Se não for claro, retorne string vazia.")
        FAMÍLIA: str = Field(description="Código de família, ex: FAM111.")
        nome_completo: str = Field(alias="Nome Completo")
        data_nascimento: str = Field(alias="Data de Nascimento")
        Telefone: str
        CPF: str
        nome_da_mae: str = Field(alias="Nome da Mãe")
        nome_do_pai: str = Field(alias="Nome do Pai")
        Sexo: str
        CNS: str
        municipio_nascimento: str = Field(alias="Município de Nascimento")

        model_config = {"populate_by_name": True}

    class VacinaAdministrada(BaseModel):
        vacina: str
        dose: str

    class VacinacaoSchema(BaseModel):
        nome_paciente: str
        data_nascimento: str
        vacinas_administradas: list[VacinaAdministrada]

    class ClinicoSchema(BaseModel):
        diagnosticos: list[str]
        medicamentos: list[str]

    class DicaSaude(BaseModel):
        titulo_curto: str
        texto_whatsapp: str

    class DicasSaudeSchema(BaseModel):
        dicas: list[DicaSaude]


def aplicar_estilo():
    st.markdown("""
    <style>
    .main { background-color: #f7f9fc; }
    .block-container {
        max-width: 1450px;
        padding-top: 1rem;
        padding-bottom: 2rem;
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
    .section-box {
        background: white;
        padding: 18px;
        border-radius: 16px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.06);
        margin-bottom: 16px;
    }
    .metric-card {
        background: white;
        padding: 16px;
        border-radius: 16px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.06);
        text-align: center;
        margin-bottom: 10px;
    }
    .metric-title {
        font-size: 13px;
        color: #7f8c8d;
    }
    .metric-number {
        font-size: 28px;
        font-weight: 700;
        color: #1f4e78;
    }
    .kanban-header {
        font-weight: 700;
        font-size: 17px;
        margin-bottom: 12px;
        text-align: center;
        padding: 10px;
        border-radius: 12px;
        color: #2d3436;
    }
    .kanban-col {
        background: #ffffff;
        border-radius: 16px;
        padding: 12px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.06);
        min-height: 500px;
    }
    .task-card {
        background: white;
        border-radius: 14px;
        padding: 12px;
        margin-bottom: 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        border-left: 6px solid #1f4e78;
    }
    .task-card-late {
        background: #fff1f1;
        border-left: 6px solid #e74c3c;
    }
    .task-title {
        font-size: 16px;
        font-weight: 700;
        color: #2c3e50;
        margin-bottom: 6px;
    }
    .task-text {
        font-size: 13px;
        color: #636e72;
        margin-bottom: 6px;
    }
    .badge {
        display: inline-block;
        padding: 4px 8px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
        margin-right: 6px;
        margin-top: 4px;
    }
    .b-baixa { background: #dfe6e9; color: #2d3436; }
    .b-media { background: #ffeaa7; color: #2d3436; }
    .b-alta { background: #fab1a0; color: #2d3436; }
    .b-urgente { background: #ff7675; color: white; }
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
    </style>
    """, unsafe_allow_html=True)


def hero(titulo, subtitulo):
    st.markdown(
        f"""
        <div class="hero">
            <h1>{titulo}</h1>
            <p>{subtitulo}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_card(titulo, valor):
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-title">{titulo}</div>
            <div class="metric-number">{valor}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


@st.cache_resource
def conectar_planilha():
    if "APP_SHEET_ID" not in st.secrets:
        st.error("Falta APP_SHEET_ID nos Secrets do Streamlit.")
        st.stop()

    if "gcp_service_account" not in st.secrets:
        st.error("Falta gcp_service_account nos Secrets do Streamlit.")
        st.stop()

    creds = st.secrets["gcp_service_account"]
    client = gspread.service_account_from_dict(creds)
    return client.open_by_key(st.secrets["APP_SHEET_ID"])


def obter_ou_criar_aba(planilha, nome_aba, colunas):
    try:
        aba = planilha.worksheet(nome_aba)
    except Exception:
        aba = planilha.add_worksheet(title=nome_aba, rows=4000, cols=max(30, len(colunas) + 5))
        aba.append_row(colunas)
    return aba


@st.cache_data(ttl=60)
def carregar_dados_aba(_aba):
    dados = _aba.get_all_records()
    return pd.DataFrame(dados)


@st.cache_resource
def cliente_gemini():
    if not GENAI_OK:
        return None
    if "GOOGLE_API_KEY" not in st.secrets:
        return None
    try:
        return genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])
    except Exception:
        return None


def calcular_idade_por_data(data_str):
    if not str(data_str).strip():
        return ""
    try:
        dt = datetime.strptime(str(data_str), "%d/%m/%Y")
        hoje = datetime.now()
        return hoje.year - dt.year - ((hoje.month, hoje.day) < (dt.month, dt.day))
    except Exception:
        return ""


def padronizar_telefone(telefone):
    if pd.isna(telefone) or telefone == "":
        return None
    num_limpo = re.sub(r"\D", "", str(telefone))
    if num_limpo.startswith("55"):
        num_limpo = num_limpo[2:]
    if 10 <= len(num_limpo) <= 11:
        return num_limpo
    return None


def validar_cpf(cpf: str) -> bool:
    cpf = "".join(re.findall(r"\d", str(cpf)))
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


def buscar_dados_paciente(df, nome_paciente):
    paciente_row = df[df["Nome Completo"] == nome_paciente]
    if paciente_row.empty:
        return None
    return paciente_row.iloc[0].to_dict()


def aplicar_substituicoes(mensagem, dados_paciente):
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


def parse_checklist(raw):
    if not str(raw).strip():
        return []
    try:
        valor = json.loads(raw)
        return valor if isinstance(valor, list) else []
    except Exception:
        return []


def checklist_para_json(items):
    try:
        return json.dumps(items, ensure_ascii=False)
    except Exception:
        return "[]"


def parse_comentarios(raw):
    if not str(raw).strip():
        return []
    try:
        valor = json.loads(raw)
        return valor if isinstance(valor, list) else []
    except Exception:
        return []


def comentarios_para_json(items):
    try:
        return json.dumps(items, ensure_ascii=False)
    except Exception:
        return "[]"


def tarefa_atrasada(row):
    if str(row.get("Status", "")).strip() == "Concluído":
        return False
    prazo = str(row.get("Prazo", "")).strip()
    if not prazo:
        return False
    try:
        data_prazo = datetime.strptime(prazo, "%d/%m/%Y").date()
        return data_prazo < date.today()
    except Exception:
        return False


def progresso_checklist(raw):
    items = parse_checklist(raw)
    if not items:
        return "0/0"
    total = len(items)
    feitos = sum(1 for i in items if i.get("feito"))
    return f"{feitos}/{total}"


def prioridade_badge(prioridade):
    p = str(prioridade).strip().lower()
    if p == "baixa":
        return '<span class="badge b-baixa">Baixa</span>'
    if p in ["média", "media"]:
        return '<span class="badge b-media">Média</span>'
    if p == "alta":
        return '<span class="badge b-alta">Alta</span>'
    if p == "urgente":
        return '<span class="badge b-urgente">Urgente</span>'
    return ""


def card_tarefa_html(row):
    classe = "task-card task-card-late" if tarefa_atrasada(row) else "task-card"
    titulo = row.get("Título", "")
    descricao = row.get("Descrição", "")
    responsavel = row.get("Responsável", "")
    prazo = row.get("Prazo", "")
    progresso = progresso_checklist(row.get("Checklist", ""))
    return f"""
    <div class="{classe}">
        <div class="task-title">{titulo}</div>
        <div class="task-text">{descricao if descricao else "Sem descrição."}</div>
        <div class="task-text"><b>Responsável:</b> {responsavel if responsavel else "Não definido"}</div>
        <div class="task-text"><b>Prazo:</b> {prazo if prazo else "Sem prazo"}</div>
        <div class="task-text"><b>Checklist:</b> {progresso}</div>
        {prioridade_badge(row.get("Prioridade", ""))}
    </div>
    """


def garantir_colunas_pacientes(df):
    for col in COLUNAS_PACIENTES:
        if col not in df.columns:
            df[col] = ""
    df["Idade"] = df.apply(
        lambda row: row["Idade"] if str(row.get("Idade", "")).strip() != "" else calcular_idade_por_data(row.get("Data de Nascimento", "")),
        axis=1,
    )
    return df


def salvar_paciente(aba_pacientes, dados):
    agora = datetime.now()
    if not dados.get("ID"):
        dados["ID"] = f"ID-{int(time.time())}"
    dados["Timestamp de Envio"] = agora.strftime("%d/%m/%Y %H:%M:%S")
    dados["Data da Extração"] = agora.strftime("%d/%m/%Y")
    dados["Data de Registo"] = agora.strftime("%d/%m/%Y %H:%M:%S")
    dados["Idade"] = calcular_idade_por_data(dados.get("Data de Nascimento", ""))
    linha = [dados.get(col, "") for col in COLUNAS_PACIENTES]
    aba_pacientes.append_row(linha, value_input_option="USER_ENTERED")
    st.cache_data.clear()


def atualizar_paciente_por_id(aba_pacientes, patient_id, novos_dados):
    dados = aba_pacientes.get_all_values()
    linhas = dados[1:]
    for i, linha in enumerate(linhas, start=2):
        if str(linha[0]) == str(patient_id):
            novos_dados["Idade"] = calcular_idade_por_data(novos_dados.get("Data de Nascimento", ""))
            nova_linha = [novos_dados.get(col, "") for col in COLUNAS_PACIENTES]
            aba_pacientes.update(f"A{i}:X{i}", [nova_linha])
            st.cache_data.clear()
            return


def excluir_paciente_por_id(aba_pacientes, patient_id):
    dados = aba_pacientes.get_all_values()
    linhas = dados[1:]
    for i, linha in enumerate(linhas, start=2):
        if str(linha[0]) == str(patient_id):
            aba_pacientes.delete_rows(i)
            st.cache_data.clear()
            return


def garantir_colunas_kanban(df):
    for col in COLUNAS_KANBAN:
        if col not in df.columns:
            df[col] = ""
    return df


def salvar_tarefa(aba_kanban, tarefa):
    linha = [tarefa.get(col, "") for col in COLUNAS_KANBAN]
    aba_kanban.append_row(linha)
    st.cache_data.clear()


def atualizar_tarefa_por_id(aba_kanban, task_id, novos_dados):
    dados = aba_kanban.get_all_values()
    linhas = dados[1:]
    for i, linha in enumerate(linhas, start=2):
        if str(linha[0]) == str(task_id):
            nova_linha = [novos_dados.get(col, "") for col in COLUNAS_KANBAN]
            aba_kanban.update(f"A{i}:K{i}", [nova_linha])
            st.cache_data.clear()
            return


def excluir_tarefa_por_id(aba_kanban, task_id):
    dados = aba_kanban.get_all_values()
    linhas = dados[1:]
    for i, linha in enumerate(linhas, start=2):
        if str(linha[0]) == str(task_id):
            aba_kanban.delete_rows(i)
            st.cache_data.clear()
            return


def ocr_imagem_com_gemini(file_bytes, mime_type, client):
    if not client or not GENAI_OK:
        return None
    try:
        image_part = Part.from_bytes(data=file_bytes, mime_type=mime_type)
        response = client.models.generate_content(
            model=MODELO_GEMINI,
            contents=[image_part, "Transcreva fielmente todo o texto contido nesta imagem."],
        )
        return response.text
    except Exception as e:
        st.error(f"Erro no OCR com Gemini: {e}")
        return None


def extrair_dados_com_google_gemini(texto_extraido, client):
    if not client or not GENAI_OK:
        return None
    try:
        prompt = f"""
        Extraia os dados cadastrais do texto abaixo e responda em JSON estrito.
        Procure por FAMÍLIA, Nome Completo, Data de Nascimento, Telefone, CPF, Nome da Mãe, Nome do Pai, Sexo, CNS e Município de Nascimento.
        Se não encontrar um campo, use string vazia.

        TEXTO:
        {texto_extraido}
        """
        response = client.models.generate_content(
            model=MODELO_GEMINI,
            contents=[prompt],
            config={"response_mime_type": "application/json", "response_schema": CadastroSchema},
        )
        dados_pydantic = CadastroSchema.model_validate_json(response.text)
        return dados_pydantic.model_dump(by_alias=True)
    except Exception as e:
        st.error(f"Erro ao extrair dados com Gemini: {e}")
        return None


def extrair_dados_vacinacao_com_google_gemini(texto_extraido, client):
    if not client or not GENAI_OK:
        return None
    try:
        prompt = f"""
        Analise este texto de caderneta de vacinação e retorne JSON estrito com:
        nome_paciente, data_nascimento e vacinas_administradas.
        Normalize nomes de vacinas como Pentavalente, VIP (Poliomielite inativada), Meningocócica C, Tríplice Viral.
        Se não encontrar algo, use vazio.

        TEXTO:
        {texto_extraido}
        """
        response = client.models.generate_content(
            model=MODELO_GEMINI,
            contents=[prompt],
            config={"response_mime_type": "application/json", "response_schema": VacinacaoSchema},
        )
        dados_pydantic = VacinacaoSchema.model_validate_json(response.text)
        return dados_pydantic.model_dump()
    except Exception as e:
        st.error(f"Erro ao extrair vacinação com Gemini: {e}")
        return None


def extrair_dados_clinicos_com_google_gemini(texto_prontuario, client):
    if not client or not GENAI_OK:
        return None
    try:
        prompt = f"""
        Analise o texto de prontuário abaixo e retorne JSON estrito com:
        diagnosticos e medicamentos.

        TEXTO:
        {texto_prontuario}
        """
        response = client.models.generate_content(
            model=MODELO_GEMINI,
            contents=[prompt],
            config={"response_mime_type": "application/json", "response_schema": ClinicoSchema},
        )
        dados_pydantic = ClinicoSchema.model_validate_json(response.text)
        return dados_pydantic.model_dump()
    except Exception as e:
        st.error(f"Erro ao extrair dados clínicos com Gemini: {e}")
        return None


def gerar_dicas_com_google_gemini(tema, client):
    if not client or not GENAI_OK:
        return None
    try:
        prompt = f"""
        Crie 5 dicas curtas de saúde sobre o tema "{tema}".
        Cada dica deve ter:
        - titulo_curto (máx 5 palavras)
        - texto_whatsapp (máx 2 frases)
        """
        response = client.models.generate_content(
            model=MODELO_GEMINI,
            contents=[prompt],
            config={"response_mime_type": "application/json", "response_schema": DicasSaudeSchema},
        )
        dados_pydantic = DicasSaudeSchema.model_validate_json(response.text)
        return dados_pydantic.model_dump()
    except Exception as e:
        st.error(f"Erro ao gerar dicas com Gemini: {e}")
        return None


def ler_texto_prontuario_gemini(file_bytes, client):
    if not client or not GENAI_OK:
        return None
    if not PDF2IMAGE_OK:
        st.error("pdf2image não está disponível no ambiente.")
        return None

    try:
        imagens_pil = convert_from_bytes(file_bytes)
        texto_completo = ""
        progress_bar = st.progress(0, text="Processando páginas do PDF...")
        for i, imagem in enumerate(imagens_pil):
            with BytesIO() as buffer:
                imagem.save(buffer, format="JPEG")
                img_bytes = buffer.getvalue()
                image_part = Part.from_bytes(data=img_bytes, mime_type="image/jpeg")

            response = client.models.generate_content(
                model=MODELO_GEMINI,
                contents=[image_part, "Transcreva fielmente todo o texto presente nesta imagem."],
            )
            texto_da_pagina = response.text
            if texto_da_pagina:
                texto_completo += f"\n--- PÁGINA {i+1} ---\n{texto_da_pagina}"
            progress_bar.progress((i + 1) / len(imagens_pil), text=f"Página {i+1} de {len(imagens_pil)}")
        progress_bar.empty()
        return texto_completo.strip()
    except Exception as e:
        st.error(f"Erro ao processar PDF com Gemini: {e}")
        return None


def analisar_carteira_vacinacao(data_nascimento_str, vacinas_administradas):
    try:
        data_nascimento = datetime.strptime(data_nascimento_str, "%d/%m/%Y")
    except ValueError:
        return {"erro": "Formato da data de nascimento inválido. Utilize DD/MM/AAAA."}

    hoje = datetime.now()
    idade_total_meses = (hoje.year - data_nascimento.year) * 12 + (hoje.month - data_nascimento.month)
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


def preencher_pdf_formulario(paciente_dados):
    template_pdf_path = "Formulario_2IndiceDeVulnerabilidadeClinicoFuncional20IVCF20_ImpressoraPDFPreenchivel_202404-2.pdf"
    try:
        packet = BytesIO()
        can = canvas.Canvas(packet, pagesize=A4)
        can.setFont("Helvetica", 10)
        can.drawString(3.2 * cm, 23.8 * cm, str(paciente_dados.get("Nome Completo", "")))
        can.drawString(15 * cm, 23.8 * cm, str(paciente_dados.get("CPF", "")))
        can.drawString(16.5 * cm, 23 * cm, str(paciente_dados.get("Data de Nascimento", "")))
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
        st.warning("Arquivo modelo do formulário não encontrado no repositório.")
        return None
    except Exception as e:
        st.error(f"Erro ao gerar PDF do formulário: {e}")
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
        can.drawString(x_texto, y_texto, f"Família: {familia_id}")

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
            info_str = f"DN: {dn} | CNS: {cns}"
            can.drawString(x_texto, y_texto, info_str)
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

    COR_PRINCIPAL = HexColor("#2c3e50")
    COR_SECUNDARIA = HexColor("#7f8c8d")
    COR_FUNDO_CABECALHO = HexColor("#ecf0f1")
    COR_ALERTA = HexColor("#e74c3c")
    COR_FUNDO_ALERTA = HexColor("#fde6e4")

    for _, paciente in pacientes_df.iterrows():
        can.setFont("Helvetica", 9)
        can.setFillColor(COR_SECUNDARIA)
        can.drawRightString(largura_pagina - 2 * cm, altura_pagina - 2 * cm, "Sistema de Gestão")

        can.setFont("Helvetica-Bold", 18)
        can.setFillColor(COR_PRINCIPAL)
        can.drawCentredString(largura_pagina / 2, altura_pagina - 4 * cm, "PRONTUÁRIO CLÍNICO INDIVIDUAL")

        margem_caixa = 2 * cm
        largura_caixa = largura_pagina - (2 * margem_caixa)
        altura_caixa = 5.5 * cm
        x_caixa, y_caixa = margem_caixa, altura_pagina - 10.5 * cm

        altura_cabecalho_interno = 1.5 * cm
        y_cabecalho_interno = y_caixa + altura_caixa - altura_cabecalho_interno
        can.setFillColor(COR_FUNDO_CABECALHO)
        can.rect(x_caixa, y_cabecalho_interno, largura_caixa, altura_cabecalho_interno, stroke=0, fill=1)

        can.setStrokeColor(COR_PRINCIPAL)
        can.setLineWidth(1.5)
        can.rect(x_caixa, y_caixa, largura_caixa, altura_caixa, stroke=1, fill=0)

        nome_paciente = str(paciente.get("Nome Completo", "NOME INDISPONÍVEL")).upper()
        y_texto_nome = y_cabecalho_interno + (altura_cabecalho_interno / 2) - (0.2 * cm)
        can.setFont("Helvetica-Bold", 15)
        can.setFillColor(COR_PRINCIPAL)
        can.drawCentredString(largura_pagina / 2, y_texto_nome, nome_paciente)

        def draw_data_pair(y, label_esq, val_esq, label_dir, val_dir):
            x_label_esq, x_valor_esq = x_caixa + 1 * cm, x_caixa + 4.5 * cm
            x_label_dir, x_valor_dir = x_caixa + (largura_caixa / 2) + 1 * cm, x_caixa + (largura_caixa / 2) + 4 * cm
            can.setFont("Helvetica", 10)
            can.setFillColor(COR_SECUNDARIA)
            can.drawString(x_label_esq, y, f"{label_esq}:")
            can.drawString(x_label_dir, y, f"{label_dir}:")
            can.setFont("Helvetica-Bold", 11)
            can.setFillColor(COR_PRINCIPAL)
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

        can.setFillColor(COR_FUNDO_ALERTA)
        can.setStrokeColor(COR_ALERTA)
        can.setLineWidth(0.5)
        can.rect(x_alerta, y_alerta, largura_alerta, altura_alerta, fill=1, stroke=1)

        can.setFont("Helvetica-Bold", 12)
        can.setFillColor(COR_ALERTA)
        can.drawString(x_alerta + 0.5 * cm, y_alerta + altura_alerta - 0.6 * cm, "ALERTA CLÍNICO RÁPIDO")

        can.setFont("Helvetica", 9)
        can.setFillColor(COR_PRINCIPAL)
        y_texto_alerta = y_alerta + altura_alerta - 1.5 * cm
        can.drawString(x_alerta + 0.5 * cm, y_texto_alerta, f"Condições: {condicoes}")
        can.drawString(x_alerta + 0.5 * cm, y_texto_alerta - 0.5 * cm, f"Medicamentos: {medicamentos}")

        can.setFont("Helvetica-Bold", 10)
        can.drawString(2 * cm, 5 * cm, "Observações Clínicas:")
        can.setStrokeColor(COR_SECUNDARIA)
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
    COR_PRINCIPAL = HexColor("#2c3e50")
    COR_SECUNDARIA = HexColor("#7f8c8d")
    COR_SUCESSO = HexColor("#27ae60")
    COR_ALERTA = HexColor("#e67e22")
    COR_INFO = HexColor("#3498db")

    can.setFont("Helvetica-Bold", 16)
    can.setFillColor(COR_PRINCIPAL)
    can.drawCentredString(largura_pagina / 2, altura_pagina - 3 * cm, "Relatório de Situação Vacinal")

    can.setFont("Helvetica", 10)
    can.setFillColor(COR_SECUNDARIA)
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
    y_corpo = desenhar_secao("Vacinas com Pendência", COR_ALERTA, relatorio["em_atraso"], y_corpo)
    y_corpo = desenhar_secao("Próximas Doses Recomendadas", COR_INFO, sorted(relatorio["proximas_doses"], key=lambda x: x["idade_meses"]), y_corpo)
    y_corpo = desenhar_secao("Vacinas em Dia", COR_SUCESSO, relatorio["em_dia"], y_corpo)

    can.save()
    pdf_buffer.seek(0)
    return pdf_buffer


def pagina_inicial():
    hero("Sistema Unificado", "Pacientes, WhatsApp, PDFs, vacinação, prontuário, QR Code, cards IA e Kanban.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""
        <div class="section-box">
            <h3>👥 Gestão de Pacientes</h3>
            <p>Cadastre, pesquise, edite e acompanhe pacientes em uma base única.</p>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("""
        <div class="section-box">
            <h3>📱 WhatsApp</h3>
            <p>Gere mensagens personalizadas para consultas, exames e orientações.</p>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("""
        <div class="section-box">
            <h3>🧾 PDFs</h3>
            <p>Etiquetas, capas de prontuário, formulários e relatórios em PDF.</p>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown("""
        <div class="section-box">
            <h3>🤖 IA</h3>
            <p>Coleta de fichas, vacinação, prontuário e cards de saúde com Gemini.</p>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("""
        <div class="section-box">
            <h3>📊 Dashboard</h3>
            <p>Indicadores gerais da base de pacientes e do quadro de tarefas.</p>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("""
        <div class="section-box">
            <h3>📋 Kanban</h3>
            <p>Controle visual de tarefas com checklist, comentários e prazo.</p>
        </div>
        """, unsafe_allow_html=True)


def pagina_coletar_fichas(aba_pacientes, gemini_client):
    hero("Coletar Fichas", "Envie imagens de fichas para extração assistida por IA.")
    st.info("Envie uma imagem. A IA tentará preencher os campos; você revisa e salva.")

    uploaded_file = st.file_uploader("Envie imagem da ficha", type=["jpg", "jpeg", "png"])
    if not uploaded_file:
        return

    st.image(Image.open(uploaded_file), width=380)

    texto_extraido = None
    if st.button("Extrair texto da imagem"):
        with st.spinner("Lendo imagem com IA..."):
            texto_extraido = ocr_imagem_com_gemini(uploaded_file.getvalue(), uploaded_file.type, gemini_client)
            st.session_state["texto_ficha"] = texto_extraido

    texto_extraido = st.session_state.get("texto_ficha")
    if not texto_extraido:
        return

    st.text_area("Texto extraído", value=texto_extraido, height=200)

    dados_extraidos = extrair_dados_com_google_gemini(texto_extraido, gemini_client) if gemini_client else None
    if not dados_extraidos:
        st.warning("Não foi possível estruturar os dados automaticamente. Você ainda pode preencher manualmente.")
        dados_extraidos = {}

    with st.form("form_ficha_extraida"):
        c1, c2 = st.columns(2)
        with c1:
            familia = st.text_input("FAMÍLIA", value=dados_extraidos.get("FAMÍLIA", ""))
            nome = st.text_input("Nome Completo", value=dados_extraidos.get("Nome Completo", ""))
            data_nasc = st.text_input("Data de Nascimento", value=dados_extraidos.get("Data de Nascimento", ""))
            sexo = st.text_input("Sexo", value=dados_extraidos.get("Sexo", ""))
            nome_mae = st.text_input("Nome da Mãe", value=dados_extraidos.get("Nome da Mãe", ""))
            nome_pai = st.text_input("Nome do Pai", value=dados_extraidos.get("Nome do Pai", ""))
        with c2:
            municipio_nasc = st.text_input("Município de Nascimento", value=dados_extraidos.get("Município de Nascimento", ""))
            cpf = st.text_input("CPF", value=dados_extraidos.get("CPF", ""))
            cns = st.text_input("CNS", value=dados_extraidos.get("CNS", ""))
            telefone = st.text_input("Telefone", value=dados_extraidos.get("Telefone", ""))
            observacoes = st.text_area("Observações", value="")
            condicao = st.text_input("Condição", value="")
        salvar = st.form_submit_button("Salvar paciente")

        if salvar:
            dados = {col: "" for col in COLUNAS_PACIENTES}
            dados["FAMÍLIA"] = familia
            dados["Nome Completo"] = nome
            dados["Data de Nascimento"] = data_nasc
            dados["Sexo"] = sexo
            dados["Nome da Mãe"] = nome_mae
            dados["Nome do Pai"] = nome_pai
            dados["Município de Nascimento"] = municipio_nasc
            dados["CPF"] = cpf
            dados["CNS"] = cns
            dados["Telefone"] = telefone
            dados["Observações"] = observacoes
            dados["Condição"] = condicao
            dados["Fonte da Imagem"] = uploaded_file.name
            salvar_paciente(aba_pacientes, dados)
            st.success("Paciente salvo com sucesso.")
            st.session_state.pop("texto_ficha", None)
            st.rerun()


def pagina_cadastro_pacientes(aba_pacientes):
    hero("Cadastro de Pacientes", "Cadastro manual direto na planilha.")
    with st.form("cadastro_paciente"):
        c1, c2 = st.columns(2)
        with c1:
            familia = st.text_input("FAMÍLIA")
            nome = st.text_input("Nome Completo")
            nascimento = st.text_input("Data de Nascimento (DD/MM/AAAA)")
            sexo = st.selectbox("Sexo", ["", "M", "F", "I"])
            nome_mae = st.text_input("Nome da Mãe")
            nome_pai = st.text_input("Nome do Pai")
            mun_nasc = st.text_input("Município de Nascimento")
            mun_res = st.text_input("Município de Residência")
        with c2:
            cpf = st.text_input("CPF")
            cns = st.text_input("CNS")
            telefone = st.text_input("Telefone")
            condicao = st.text_input("Condição")
            raca = st.text_input("Raça/Cor")
            status_vacinal = st.text_input("Status Vacinal")
            medicamentos = st.text_input("Medicamentos")
            obs = st.text_area("Observações")

        enviar = st.form_submit_button("Salvar paciente")

        if enviar:
            if not nome.strip():
                st.error("Informe o nome completo.")
            else:
                dados = {col: "" for col in COLUNAS_PACIENTES}
                dados["FAMÍLIA"] = familia.strip()
                dados["Nome Completo"] = nome.strip()
                dados["Data de Nascimento"] = nascimento.strip()
                dados["Sexo"] = sexo
                dados["Nome da Mãe"] = nome_mae.strip()
                dados["Nome do Pai"] = nome_pai.strip()
                dados["Município de Nascimento"] = mun_nasc.strip()
                dados["Município de Residência"] = mun_res.strip()
                dados["CPF"] = cpf.strip()
                dados["CNS"] = cns.strip()
                dados["Telefone"] = telefone.strip()
                dados["Condição"] = condicao.strip()
                dados["Raça/Cor"] = raca.strip()
                dados["Status_Vacinal"] = status_vacinal.strip()
                dados["Medicamentos"] = medicamentos.strip()
                dados["Observações"] = obs.strip()
                salvar_paciente(aba_pacientes, dados)
                st.success("Paciente salvo com sucesso.")
                st.rerun()


def pagina_gestao_pacientes(aba_pacientes):
    hero("Gestão de Pacientes", "Pesquise, edite e exclua registros.")
    df = garantir_colunas_pacientes(carregar_dados_aba(aba_pacientes))
    if df.empty:
        st.warning("Ainda não há pacientes cadastrados.")
        return

    coluna = st.selectbox("Pesquisar por:", ["Nome Completo", "CPF", "CNS", "FAMÍLIA", "Nome da Mãe"])
    termo = st.text_input("Digite o termo de pesquisa")
    resultados = df[df[coluna].astype(str).str.contains(termo, case=False, na=False)] if termo else df.copy()

    st.markdown(f"**{len(resultados)}** resultado(s) encontrado(s).")

    for _, row in resultados.iterrows():
        patient_id = row["ID"]
        with st.expander(f"**{row['Nome Completo']}** (ID: {patient_id})"):
            st.dataframe(row.to_frame().T, use_container_width=True, hide_index=True)

            with st.form(f"edit_patient_{patient_id}"):
                novos_dados = row.to_dict()
                c1, c2 = st.columns(2)
                with c1:
                    novos_dados["FAMÍLIA"] = st.text_input("FAMÍLIA", value=row.get("FAMÍLIA", ""))
                    novos_dados["Nome Completo"] = st.text_input("Nome Completo", value=row.get("Nome Completo", ""))
                    novos_dados["Data de Nascimento"] = st.text_input("Data de Nascimento", value=row.get("Data de Nascimento", ""))
                    novos_dados["Sexo"] = st.text_input("Sexo", value=row.get("Sexo", ""))
                    novos_dados["Nome da Mãe"] = st.text_input("Nome da Mãe", value=row.get("Nome da Mãe", ""))
                    novos_dados["Nome do Pai"] = st.text_input("Nome do Pai", value=row.get("Nome do Pai", ""))
                with c2:
                    novos_dados["Município de Nascimento"] = st.text_input("Município de Nascimento", value=row.get("Município de Nascimento", ""))
                    novos_dados["Município de Residência"] = st.text_input("Município de Residência", value=row.get("Município de Residência", ""))
                    novos_dados["CPF"] = st.text_input("CPF", value=row.get("CPF", ""))
                    novos_dados["CNS"] = st.text_input("CNS", value=row.get("CNS", ""))
                    novos_dados["Telefone"] = st.text_input("Telefone", value=row.get("Telefone", ""))
                    novos_dados["Condição"] = st.text_input("Condição", value=row.get("Condição", ""))
                novos_dados["Observações"] = st.text_area("Observações", value=row.get("Observações", ""))

                b1, b2 = st.columns(2)
                salvar = b1.form_submit_button("Salvar alterações")
                excluir = b2.form_submit_button("Excluir paciente")

                if salvar:
                    atualizar_paciente_por_id(aba_pacientes, patient_id, novos_dados)
                    st.success("Paciente atualizado.")
                    st.rerun()

                if excluir:
                    excluir_paciente_por_id(aba_pacientes, patient_id)
                    st.success("Paciente excluído.")
                    st.rerun()


def pagina_dashboard_pacientes(aba_pacientes):
    hero("Dashboard de Pacientes", "Indicadores gerais da base cadastrada.")
    df = garantir_colunas_pacientes(carregar_dados_aba(aba_pacientes))
    if df.empty:
        st.warning("Ainda não há pacientes cadastrados.")
        return

    df["Idade"] = pd.to_numeric(df["Idade"], errors="coerce").fillna(0)
    total = len(df)
    idosos = len(df[df["Idade"] >= 60])
    criancas = len(df[df["Idade"].between(0, 11)])
    adolescentes = len(df[df["Idade"].between(12, 17)])

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        metric_card("Total", total)
    with m2:
        metric_card("Idosos", idosos)
    with m3:
        metric_card("Crianças", criancas)
    with m4:
        metric_card("Adolescentes", adolescentes)

    st.markdown("---")
    c1, c2 = st.columns(2)

    with c1:
        st.subheader("Pacientes por Município")
        if "Município de Nascimento" in df.columns:
            st.bar_chart(df["Município de Nascimento"].astype(str).value_counts())

    with c2:
        st.subheader("Distribuição por Sexo")
        sexo_counts = df["Sexo"].astype(str).str.upper().value_counts()
        if not sexo_counts.empty:
            fig, ax = plt.subplots(figsize=(5, 3))
            sexo_counts.plot.pie(ax=ax, autopct="%1.1f%%", startangle=90)
            ax.axis("equal")
            st.pyplot(fig)

    st.markdown("---")
    st.dataframe(df, use_container_width=True)


def pagina_whatsapp(aba_pacientes):
    hero("WhatsApp Manual", "Gere mensagens personalizadas para pacientes.")
    df = garantir_colunas_pacientes(carregar_dados_aba(aba_pacientes))
    if df.empty:
        st.warning("Ainda não há pacientes cadastrados.")
        return

    df_com_telefone = df[df["Telefone"].astype(str).str.strip() != ""].copy()
    df_com_telefone["Telefone Limpo"] = df_com_telefone["Telefone"].apply(padronizar_telefone)
    df_com_telefone = df_com_telefone.dropna(subset=["Telefone Limpo"])

    if df_com_telefone.empty:
        st.warning("Não há pacientes com telefone válido.")
        return

    lista_pacientes = sorted(df_com_telefone["Nome Completo"].tolist())

    c1, c2 = st.columns(2)
    with c1:
        tipo = st.selectbox("Tipo de mensagem", ["Exames", "Marcação Médica", "Orientações Gerais", "Personalizada"])
    with c2:
        paciente_nome = st.selectbox("Paciente", lista_pacientes)

    templates = {
        "Exames": "Olá, [NOME]! Seu exame [TIPO_EXAME] está agendado para [DATA_HORA]. Dúvidas? Ligue 2641-1499.",
        "Marcação Médica": "Olá, [NOME]! Consulta com [MEDICO_ESPECIALIDADE] marcada para [DATA_HORA].",
        "Orientações Gerais": "Olá, [NOME]! Orientação: mantenha atenção à sua condição [CONDICOES].",
        "Personalizada": "Olá, [NOME]! [SUA_MENSAGEM_AQUI]",
    }

    mensagem_base = templates[tipo]

    if tipo == "Exames":
        exame = st.selectbox("Tipo de exame", EXAMES_COMUNS)
        data_hora = st.text_input("Data/Hora")
        mensagem_base = mensagem_base.replace("[TIPO_EXAME]", exame).replace("[DATA_HORA]", data_hora)
    elif tipo == "Marcação Médica":
        especialidade = st.selectbox("Especialidade", ESPECIALIDADES_MEDICAS)
        data_hora = st.text_input("Data/Hora")
        medico = st.text_input("Nome do médico (opcional)")
        final_medico = f"{medico} ({especialidade})" if medico else especialidade
        mensagem_base = mensagem_base.replace("[MEDICO_ESPECIALIDADE]", final_medico).replace("[DATA_HORA]", data_hora)
    elif tipo == "Personalizada":
        mensagem_livre = st.text_area("Mensagem personalizada")
        mensagem_base = mensagem_base.replace("[SUA_MENSAGEM_AQUI]", mensagem_livre)

    mensagem_editada = st.text_area("Mensagem final", mensagem_base, height=150)

    if paciente_nome:
        dados_paciente = buscar_dados_paciente(df_com_telefone, paciente_nome)
        if dados_paciente:
            mensagem_final = aplicar_substituicoes(mensagem_editada, dados_paciente)
            telefone_limpo = dados_paciente["Telefone Limpo"]
            whatsapp_url = f"https://wa.me/55{telefone_limpo}?text={urllib.parse.quote(mensagem_final)}"
            st.code(mensagem_final, language="text")
            st.link_button("Abrir WhatsApp", whatsapp_url)


def pagina_etiquetas_qrcode(aba_pacientes):
    hero("Etiquetas com QR Code", "Gere etiquetas por família em PDF.")
    df = garantir_colunas_pacientes(carregar_dados_aba(aba_pacientes))
    if df.empty:
        st.warning("Ainda não há dados.")
        return

    df_familias = df[df["FAMÍLIA"].astype(str).str.strip() != ""].copy()
    if df_familias.empty:
        st.warning("Não há famílias para exibir.")
        return

    def agregador(x):
        return {
            "membros": x[["Nome Completo", "Data de Nascimento", "CNS"]].to_dict("records"),
            "link_pasta": x["Link da Pasta da Família"].iloc[0] if "Link da Pasta da Família" in x.columns else "",
        }

    familias_dict = df_familias.groupby("FAMÍLIA").apply(agregador).to_dict()
    lista_familias = sorted([f for f in familias_dict.keys() if f])

    selecionadas = st.multiselect("Selecione as famílias", lista_familias)
    familias_para_gerar = familias_dict if not selecionadas else {fid: familias_dict[fid] for fid in selecionadas}

    for familia_id, dados_familia in familias_para_gerar.items():
        with st.expander(f"Família: {familia_id} ({len(dados_familia['membros'])} membro(s))"):
            for membro in dados_familia["membros"]:
                st.write(f"**{membro['Nome Completo']}**")
                st.caption(f"DN: {membro['Data de Nascimento']} | CNS: {membro['CNS']}")

    if st.button("Gerar PDF das Etiquetas"):
        pdf_bytes = gerar_pdf_etiquetas(familias_para_gerar)
        st.download_button(
            label="Baixar PDF",
            data=pdf_bytes,
            file_name=f"etiquetas_qrcode_{datetime.now().strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
        )


def pagina_capas_prontuario(aba_pacientes):
    hero("Capas de Prontuário", "Gere capas em PDF para pacientes.")
    df = garantir_colunas_pacientes(carregar_dados_aba(aba_pacientes))
    if df.empty:
        st.warning("Ainda não há dados.")
        return

    lista_pacientes = sorted(df["Nome Completo"].tolist())
    selecionados = st.multiselect("Escolha um ou mais pacientes", lista_pacientes)
    if not selecionados:
        return

    pacientes_df = df[df["Nome Completo"].isin(selecionados)]
    st.dataframe(pacientes_df[["Nome Completo", "Data de Nascimento", "FAMÍLIA", "CPF", "CNS"]], use_container_width=True)

    if st.button("Gerar PDF das Capas"):
        pdf_bytes = gerar_pdf_capas_prontuario(pacientes_df)
        st.download_button(
            label="Baixar PDF das Capas",
            data=pdf_bytes,
            file_name=f"capas_prontuario_{datetime.now().strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
        )


def pagina_gerar_documentos(aba_pacientes):
    hero("Gerar Documentos", "Preencha formulário PDF a partir do paciente.")
    df = garantir_colunas_pacientes(carregar_dados_aba(aba_pacientes))
    if df.empty:
        st.warning("Não há pacientes cadastrados.")
        return

    paciente_nome = st.selectbox("Escolha um paciente", sorted(df["Nome Completo"].tolist()), index=None)
    if not paciente_nome:
        return

    paciente_dados = df[df["Nome Completo"] == paciente_nome].iloc[0].to_dict()
    if st.button("Gerar Formulário de Vulnerabilidade"):
        pdf_buffer = preencher_pdf_formulario(paciente_dados)
        if pdf_buffer:
            st.download_button(
                label="Baixar Formulário (PDF)",
                data=pdf_buffer,
                file_name=f"formulario_{paciente_nome.replace(' ', '_')}.pdf",
                mime="application/pdf",
            )


def pagina_analise_vacinacao(gemini_client):
    hero("Análise de Vacinação", "Envie foto da caderneta para extrair e analisar.")
    if not gemini_client:
        st.warning("GOOGLE_API_KEY ausente ou Gemini indisponível.")
        return

    uploaded_file = st.file_uploader("Envie foto da caderneta", type=["jpg", "jpeg", "png"])
    if not uploaded_file:
        return

    if st.button("Extrair dados da caderneta"):
        with st.spinner("Lendo caderneta..."):
            texto_extraido = ocr_imagem_com_gemini(uploaded_file.getvalue(), uploaded_file.type, gemini_client)
            st.session_state["texto_vacina"] = texto_extraido

    texto_extraido = st.session_state.get("texto_vacina")
    if not texto_extraido:
        return

    st.text_area("Texto extraído", value=texto_extraido, height=220)

    dados = extrair_dados_vacinacao_com_google_gemini(texto_extraido, gemini_client)
    if not dados:
        return

    with st.form("validation_form_vac"):
        nome_validado = st.text_input("Nome do Paciente", value=dados.get("nome_paciente", ""))
        dn_validada = st.text_input("Data de Nascimento", value=dados.get("data_nascimento", ""))
        vacinas_df = pd.DataFrame(dados.get("vacinas_administradas", []))
        vacinas_editadas = st.data_editor(vacinas_df, num_rows="dynamic")
        analisar = st.form_submit_button("Analisar carteira")

        if analisar:
            relatorio = analisar_carteira_vacinacao(dn_validada, vacinas_editadas.to_dict("records"))
            if "erro" in relatorio:
                st.error(relatorio["erro"])
            else:
                st.success("Vacinas em Dia")
                for vac in relatorio["em_dia"]:
                    st.write(f"- {vac['vacina']} ({vac['dose']})")
                st.warning("Vacinas em Atraso")
                for vac in relatorio["em_atraso"]:
                    st.write(f"- {vac['vacina']} ({vac['dose']})")
                st.info("Próximas Doses")
                for vac in sorted(relatorio["proximas_doses"], key=lambda x: x["idade_meses"]):
                    st.write(f"- {vac['vacina']} ({vac['dose']})")
                pdf_bytes = gerar_pdf_relatorio_vacinacao(nome_validado, dn_validada, relatorio)
                st.download_button(
                    label="Baixar Relatório (PDF)",
                    data=pdf_bytes,
                    file_name=f"relatorio_vacinacao_{nome_validado.replace(' ', '_')}.pdf",
                    mime="application/pdf",
                )


def pagina_importar_prontuario(aba_pacientes, gemini_client):
    hero("Importar Prontuário", "Envie um PDF e atualize condições e medicamentos.")
    if not gemini_client:
        st.warning("GOOGLE_API_KEY ausente ou Gemini indisponível.")
        return

    df = garantir_colunas_pacientes(carregar_dados_aba(aba_pacientes))
    if df.empty:
        st.warning("Não há pacientes na base.")
        return

    paciente_nome = st.selectbox("Selecione o paciente", sorted(df["Nome Completo"].tolist()), index=None)
    uploaded_file = st.file_uploader("Carregue o prontuário em PDF", type=["pdf"])

    if not paciente_nome or not uploaded_file:
        return

    if st.button("Iniciar extração do prontuário"):
        with st.spinner("Processando PDF..."):
            texto_prontuario = ler_texto_prontuario_gemini(uploaded_file.getvalue(), gemini_client)
            st.session_state["texto_prontuario"] = texto_prontuario

    texto_prontuario = st.session_state.get("texto_prontuario")
    if not texto_prontuario:
        return

    st.text_area("Texto extraído do prontuário", value=texto_prontuario, height=220)

    dados_clinicos = extrair_dados_clinicos_com_google_gemini(texto_prontuario, gemini_client)
    if not dados_clinicos:
        return

    with st.form("clinical_data_form"):
        diagnosticos_validados = st.multiselect(
            "Diagnósticos Encontrados",
            options=dados_clinicos.get("diagnosticos", []),
            default=dados_clinicos.get("diagnosticos", []),
        )
        medicamentos_validados = st.multiselect(
            "Medicamentos Encontrados",
            options=dados_clinicos.get("medicamentos", []),
            default=dados_clinicos.get("medicamentos", []),
        )
        salvar = st.form_submit_button("Salvar no paciente")

        if salvar:
            paciente_row = df[df["Nome Completo"] == paciente_nome].iloc[0].to_dict()
            paciente_row["Condição"] = ", ".join(diagnosticos_validados)
            paciente_row["Medicamentos"] = ", ".join(medicamentos_validados)
            atualizar_paciente_por_id(aba_pacientes, paciente_row["ID"], paciente_row)
            st.success("Paciente atualizado com dados clínicos.")
            st.rerun()


def pagina_gerador_qrcode():
    hero("Gerador de QR Code", "Crie QR Code para o dashboard público do app.")
    base_url = st.text_input("URL base da sua aplicação Streamlit Cloud", placeholder="https://seu-app.streamlit.app")
    if not base_url:
        return

    dashboard_url = f"{base_url.strip('/')}"
    st.success(f"URL: {dashboard_url}")

    if st.button("Gerar QR Code"):
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(dashboard_url)
        qr.make(fit=True)
        img_qr = qr.make_image(fill_color="black", back_color="white")
        qr_buffer = BytesIO()
        img_qr.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)
        st.image(qr_buffer, caption="QR Code Gerado", width=300)
        st.download_button(
            label="Baixar QR Code (PNG)",
            data=qr_buffer,
            file_name="qrcode_dashboard.png",
            mime="image/png",
        )


def pagina_gerador_cards(gemini_client):
    hero("Cards de Saúde com IA", "Gere 5 dicas prontas para card e WhatsApp.")
    if not gemini_client:
        st.warning("GOOGLE_API_KEY ausente ou Gemini indisponível.")
        return

    tema = st.selectbox("Selecione o tema", TEMAS_CARDS)
    if st.button("Gerar 5 dicas com IA"):
        with st.spinner("Gerando dicas..."):
            dicas_geradas = gerar_dicas_com_google_gemini(tema, gemini_client)
            if dicas_geradas and "dicas" in dicas_geradas:
                st.session_state["dicas_cards"] = dicas_geradas["dicas"]
                st.session_state["tema_cards"] = tema

    if st.session_state.get("dicas_cards"):
        st.subheader(f"Conteúdo gerado para {st.session_state.get('tema_cards')}")
        dicas_whatsapp = ""
        for i, dica in enumerate(st.session_state["dicas_cards"], start=1):
            st.markdown(f"#### Dica {i}")
            st.markdown(f"**Título:** `{dica['titulo_curto']}`")
            st.code(dica["texto_whatsapp"], language="text")
            dicas_whatsapp += f"💡 *{dica['titulo_curto']}*\n{dica['texto_whatsapp']}\n\n"

        mensagem_final = (
            "Olá! Aqui estão as dicas de saúde desta semana:\n\n"
            f"{dicas_whatsapp}"
            "Cuide-se!\nAtenciosamente."
        )
        st.text_area("Mensagem completa", value=mensagem_final, height=280)


def pagina_kanban(aba_kanban):
    hero("Kanban", "Controle visual de tarefas com checklist, comentários e prazo.")
    df = garantir_colunas_kanban(carregar_dados_aba(aba_kanban))
    if df.empty:
        df = pd.DataFrame(columns=COLUNAS_KANBAN)

    total = len(df)
    backlog = len(df[df["Status"] == "Backlog"])
    andamento = len(df[df["Status"] == "Em Andamento"])
    concluidas = len(df[df["Status"] == "Concluído"])
    atrasadas = sum(1 for _, row in df.iterrows() if tarefa_atrasada(row))

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        metric_card("Total", total)
    with m2:
        metric_card("Backlog", backlog)
    with m3:
        metric_card("Em Andamento", andamento)
    with m4:
        metric_card("Atrasadas", atrasadas)

    st.markdown("---")

    with st.expander("Nova tarefa", expanded=False):
        with st.form("nova_tarefa_form"):
            c1, c2 = st.columns(2)
            with c1:
                titulo = st.text_input("Título")
                descricao = st.text_area("Descrição")
                responsavel = st.text_input("Responsável")
            with c2:
                status = st.selectbox("Status", STATUS_OPCOES, index=0)
                prioridade = st.selectbox("Prioridade", PRIORIDADE_OPCOES, index=1)
                prazo = st.date_input("Prazo", value=None)

            checklist_inicial = st.text_area("Checklist inicial (uma linha por item)")
            enviar = st.form_submit_button("Salvar tarefa")

            if enviar:
                if not titulo.strip():
                    st.error("Informe o título da tarefa.")
                else:
                    agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                    prazo_str = prazo.strftime("%d/%m/%Y") if prazo else ""
                    checklist_lista = []
                    if checklist_inicial.strip():
                        for linha in checklist_inicial.splitlines():
                            item = linha.strip()
                            if item:
                                checklist_lista.append({"texto": item, "feito": False})

                    tarefa = {
                        "ID": str(uuid.uuid4()),
                        "Título": titulo.strip(),
                        "Descrição": descricao.strip(),
                        "Status": status,
                        "Prioridade": prioridade,
                        "Responsável": responsavel.strip(),
                        "Prazo": prazo_str,
                        "Checklist": checklist_para_json(checklist_lista),
                        "Comentários": comentarios_para_json([]),
                        "Criado em": agora,
                        "Atualizado em": agora,
                    }
                    salvar_tarefa(aba_kanban, tarefa)
                    st.success("Tarefa salva com sucesso.")
                    st.rerun()

    st.markdown("---")

    f1, f2, f3, f4 = st.columns(4)
    with f1:
        filtro_responsavel = st.text_input("Filtrar por responsável")
    with f2:
        filtro_prioridade = st.selectbox("Filtrar por prioridade", ["Todas"] + PRIORIDADE_OPCOES)
    with f3:
        filtro_status = st.selectbox("Filtrar por status", ["Todos"] + STATUS_OPCOES)
    with f4:
        filtro_texto = st.text_input("Buscar por título")

    df_filtrado = df.copy()

    if filtro_responsavel.strip():
        df_filtrado = df_filtrado[df_filtrado["Responsável"].astype(str).str.contains(filtro_responsavel, case=False, na=False)]
    if filtro_prioridade != "Todas":
        df_filtrado = df_filtrado[df_filtrado["Prioridade"] == filtro_prioridade]
    if filtro_status != "Todos":
        df_filtrado = df_filtrado[df_filtrado["Status"] == filtro_status]
    if filtro_texto.strip():
        df_filtrado = df_filtrado[df_filtrado["Título"].astype(str).str.contains(filtro_texto, case=False, na=False)]

    st.markdown("---")
    colunas = st.columns(len(STATUS_OPCOES))

    for i, status in enumerate(STATUS_OPCOES):
        with colunas[i]:
            cor = CORES_STATUS[status]
            st.markdown(f'<div class="kanban-header" style="background:{cor};">{status}</div>', unsafe_allow_html=True)
            tarefas_coluna = df_filtrado[df_filtrado["Status"] == status]

            if tarefas_coluna.empty:
                st.markdown('<div class="kanban-col"><p style="text-align:center;color:#999;">Sem tarefas</p></div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="kanban-col">', unsafe_allow_html=True)
                for _, row in tarefas_coluna.iterrows():
                    st.markdown(card_tarefa_html(row), unsafe_allow_html=True)
                    with st.expander(f"Editar: {row['Título']}"):
                        checklist_itens = parse_checklist(row.get("Checklist", ""))
                        comentarios = parse_comentarios(row.get("Comentários", ""))

                        with st.form(f"edit_{row['ID']}"):
                            novo_titulo = st.text_input("Título", value=row["Título"])
                            nova_descricao = st.text_area("Descrição", value=row["Descrição"])
                            novo_responsavel = st.text_input("Responsável", value=row["Responsável"])

                            a1, a2 = st.columns(2)
                            with a1:
                                novo_status = st.selectbox(
                                    "Status",
                                    STATUS_OPCOES,
                                    index=STATUS_OPCOES.index(row["Status"]) if row["Status"] in STATUS_OPCOES else 0,
                                    key=f"status_{row['ID']}",
                                )
                            with a2:
                                nova_prioridade = st.selectbox(
                                    "Prioridade",
                                    PRIORIDADE_OPCOES,
                                    index=PRIORIDADE_OPCOES.index(row["Prioridade"]) if row["Prioridade"] in PRIORIDADE_OPCOES else 0,
                                    key=f"prio_{row['ID']}",
                                )

                            prazo_valor = None
                            try:
                                if str(row["Prazo"]).strip():
                                    prazo_valor = datetime.strptime(str(row["Prazo"]), "%d/%m/%Y").date()
                            except Exception:
                                prazo_valor = None

                            novo_prazo = st.date_input("Prazo", value=prazo_valor, key=f"prazo_{row['ID']}")

                            st.markdown("**Checklist**")
                            checklist_editado = []
                            if checklist_itens:
                                for idx, item in enumerate(checklist_itens):
                                    feito = st.checkbox(item.get("texto", ""), value=item.get("feito", False), key=f"check_{row['ID']}_{idx}")
                                    checklist_editado.append({"texto": item.get("texto", ""), "feito": feito})

                            novo_item_checklist = st.text_input("Adicionar item ao checklist", key=f"novo_item_{row['ID']}")

                            st.markdown("**Comentários anteriores**")
                            if comentarios:
                                for c in comentarios:
                                    st.markdown(f"- **{c.get('data','')}**: {c.get('texto','')}")
                            else:
                                st.caption("Sem comentários.")

                            novo_comentario = st.text_area("Novo comentário", key=f"comentario_{row['ID']}")

                            b1, b2 = st.columns(2)
                            salvar = b1.form_submit_button("Salvar alterações")
                            excluir = b2.form_submit_button("Excluir tarefa")

                            if salvar:
                                agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                                prazo_str = novo_prazo.strftime("%d/%m/%Y") if novo_prazo else ""
                                if novo_item_checklist.strip():
                                    checklist_editado.append({"texto": novo_item_checklist.strip(), "feito": False})
                                if novo_comentario.strip():
                                    comentarios.append({"data": agora, "texto": novo_comentario.strip()})

                                novos_dados = {
                                    "ID": row["ID"],
                                    "Título": novo_titulo.strip(),
                                    "Descrição": nova_descricao.strip(),
                                    "Status": novo_status,
                                    "Prioridade": nova_prioridade,
                                    "Responsável": novo_responsavel.strip(),
                                    "Prazo": prazo_str,
                                    "Checklist": checklist_para_json(checklist_editado),
                                    "Comentários": comentarios_para_json(comentarios),
                                    "Criado em": row["Criado em"],
                                    "Atualizado em": agora,
                                }
                                atualizar_tarefa_por_id(aba_kanban, row["ID"], novos_dados)
                                st.success("Tarefa atualizada.")
                                st.rerun()

                            if excluir:
                                excluir_tarefa_por_id(aba_kanban, row["ID"])
                                st.success("Tarefa excluída.")
                                st.rerun()

                st.markdown("</div>", unsafe_allow_html=True)


def main():
    st.set_page_config(page_title="Sistema Unificado", page_icon="📋", layout="wide")
    aplicar_estilo()

    planilha = conectar_planilha()
    aba_pacientes = obter_ou_criar_aba(planilha, "PACIENTES", COLUNAS_PACIENTES)
    aba_kanban = obter_ou_criar_aba(planilha, "KANBAN", COLUNAS_KANBAN)
    gemini_client = cliente_gemini()

    st.sidebar.title("Menu")
    pagina = st.sidebar.radio(
        "Escolha uma página:",
        [
            "🏠 Início",
            "🤖 Coletar Fichas",
            "👥 Cadastro de Pacientes",
            "🔎 Gestão de Pacientes",
            "📊 Dashboard de Pacientes",
            "📱 WhatsApp Manual",
            "🏷️ Etiquetas QR Code",
            "📇 Capas de Prontuário",
            "📄 Gerar Documentos",
            "💉 Análise de Vacinação",
            "📄 Importar Prontuário",
            "🧠 Cards de Saúde com IA",
            "🔳 Gerador de QR Code",
            "📋 Kanban",
        ],
    )

    if pagina == "🏠 Início":
        pagina_inicial()
    elif pagina == "🤖 Coletar Fichas":
        pagina_coletar_fichas(aba_pacientes, gemini_client)
    elif pagina == "👥 Cadastro de Pacientes":
        pagina_cadastro_pacientes(aba_pacientes)
    elif pagina == "🔎 Gestão de Pacientes":
        pagina_gestao_pacientes(aba_pacientes)
    elif pagina == "📊 Dashboard de Pacientes":
        pagina_dashboard_pacientes(aba_pacientes)
    elif pagina == "📱 WhatsApp Manual":
        pagina_whatsapp(aba_pacientes)
    elif pagina == "🏷️ Etiquetas QR Code":
        pagina_etiquetas_qrcode(aba_pacientes)
    elif pagina == "📇 Capas de Prontuário":
        pagina_capas_prontuario(aba_pacientes)
    elif pagina == "📄 Gerar Documentos":
        pagina_gerar_documentos(aba_pacientes)
    elif pagina == "💉 Análise de Vacinação":
        pagina_analise_vacinacao(gemini_client)
    elif pagina == "📄 Importar Prontuário":
        pagina_importar_prontuario(aba_pacientes, gemini_client)
    elif pagina == "🧠 Cards de Saúde com IA":
        pagina_gerador_cards(gemini_client)
    elif pagina == "🔳 Gerador de QR Code":
        pagina_gerador_qrcode()
    elif pagina == "📋 Kanban":
        pagina_kanban(aba_kanban)


if __name__ == "__main__":
    main()
