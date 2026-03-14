import streamlit as st
import pandas as pd
import gspread
import urllib.parse
import uuid
import json
import time
import re
from datetime import datetime, date

# =========================================================
# CONFIGURAÇÕES GERAIS
# =========================================================
STATUS_OPCOES = ["Backlog", "Para Fazer", "Em Andamento", "Aguardando", "Concluído"]
PRIORIDADE_OPCOES = ["Baixa", "Média", "Alta", "Urgente"]

CORES_STATUS = {
    "Backlog": "#dfe6e9",
    "Para Fazer": "#74b9ff",
    "Em Andamento": "#ffeaa7",
    "Aguardando": "#fab1a0",
    "Concluído": "#55efc4"
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
    "Link do Prontuário"
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
    "Atualizado em"
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
    "Cardiologia",
    "Dermatologia",
    "Neurologia",
    "Psiquiatria",
    "Ortopedia",
    "Oftalmologia",
    "Endocrinologia",
    "Geriatria",
    "Nutrição",
    "Psicologia",
    "Fisioterapia",
]

# =========================================================
# ESTILO
# =========================================================
def aplicar_estilo():
    st.markdown("""
    <style>
    .main {
        background-color: #f7f9fc;
    }

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
        unsafe_allow_html=True
    )


def metric_card(titulo, valor):
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-title">{titulo}</div>
            <div class="metric-number">{valor}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

# =========================================================
# GOOGLE SHEETS
# =========================================================
@st.cache_resource
def conectar_planilha():
    creds = st.secrets["gcp_service_account"]
    client = gspread.service_account_from_dict(creds)
    planilha = client.open_by_key(st.secrets["APP_SHEET_ID"])
    return planilha


def obter_ou_criar_aba(planilha, nome_aba, colunas):
    try:
        aba = planilha.worksheet(nome_aba)
    except:
        aba = planilha.add_worksheet(title=nome_aba, rows=3000, cols=max(len(colunas) + 5, 20))
        aba.append_row(colunas)
    return aba


@st.cache_data(ttl=60)
def carregar_dados_aba(_aba):
    dados = _aba.get_all_records()
    return pd.DataFrame(dados)

# =========================================================
# HELPERS PACIENTES
# =========================================================
def calcular_idade_por_data(data_str):
    if not str(data_str).strip():
        return ""
    try:
        dt = datetime.strptime(str(data_str), "%d/%m/%Y")
        hoje = datetime.now()
        idade = hoje.year - dt.year - ((hoje.month, hoje.day) < (dt.month, dt.day))
        return idade
    except:
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
        "[MUNICIPIO_NASC]": dados_paciente.get("Município de Nascimento", "N/A")
    }
    for placeholder, valor in substituicoes.items():
        mensagem = mensagem.replace(placeholder, str(valor))
    return mensagem

# =========================================================
# HELPERS KANBAN
# =========================================================
def parse_checklist(raw):
    if not str(raw).strip():
        return []
    try:
        valor = json.loads(raw)
        return valor if isinstance(valor, list) else []
    except:
        return []


def checklist_para_json(items):
    try:
        return json.dumps(items, ensure_ascii=False)
    except:
        return "[]"


def parse_comentarios(raw):
    if not str(raw).strip():
        return []
    try:
        valor = json.loads(raw)
        return valor if isinstance(valor, list) else []
    except:
        return []


def comentarios_para_json(items):
    try:
        return json.dumps(items, ensure_ascii=False)
    except:
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
    except:
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

# =========================================================
# CRUD PACIENTES
# =========================================================
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

# =========================================================
# CRUD KANBAN
# =========================================================
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

# =========================================================
# PÁGINAS
# =========================================================
def pagina_inicial():
    hero("Sistema Unificado", "Pacientes + WhatsApp + Dashboard + Kanban no mesmo app.")
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
            <h3>📱 WhatsApp Manual</h3>
            <p>Gere mensagens personalizadas para consultas, exames e orientações.</p>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown("""
        <div class="section-box">
            <h3>📊 Dashboard</h3>
            <p>Visualize métricas de pacientes e distribuição por faixa etária.</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="section-box">
            <h3>📋 Kanban</h3>
            <p>Controle tarefas com checklist, comentários, prioridade e prazos.</p>
        </div>
        """, unsafe_allow_html=True)


def pagina_cadastro_pacientes(aba_pacientes):
    hero("Cadastro de Pacientes", "Cadastro manual direto na planilha do Google Sheets.")

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
    df = carregar_dados_aba(aba_pacientes)

    if df.empty:
        st.warning("Ainda não há pacientes cadastrados.")
        return

    for col in COLUNAS_PACIENTES:
        if col not in df.columns:
            df[col] = ""

    coluna = st.selectbox("Pesquisar por:", ["Nome Completo", "CPF", "CNS", "FAMÍLIA", "Nome da Mãe"])
    termo = st.text_input("Digite o termo de pesquisa")

    if termo:
        resultados = df[df[coluna].astype(str).str.contains(termo, case=False, na=False)]
    else:
        resultados = df.copy()

    st.markdown(f"**{len(resultados)}** resultado(s) encontrado(s).")

    for _, row in resultados.iterrows():
        patient_id = row["ID"]
        with st.expander(f"**{row['Nome Completo']}** (ID: {patient_id})"):
            st.dataframe(row.to_frame().T, use_container_width=True, hide_index=True)

            with st.form(f"edit_patient_{patient_id}"):
                c1, c2 = st.columns(2)
                novos_dados = row.to_dict()

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
                novos_dados["Raça/Cor"] = row.get("Raça/Cor", "")
                novos_dados["Status_Vacinal"] = row.get("Status_Vacinal", "")
                novos_dados["Medicamentos"] = row.get("Medicamentos", "")

                b1, b2 = st.columns(2)
                with b1:
                    salvar = st.form_submit_button("Salvar alterações")
                with b2:
                    excluir = st.form_submit_button("Excluir paciente")

                if salvar:
                    atualizar_paciente_por_id(aba_pacientes, patient_id, novos_dados)
                    st.success("Paciente atualizado.")
                    st.rerun()

                if excluir:
                    excluir_paciente_por_id(aba_pacientes, patient_id)
                    st.success("Paciente excluído.")
                    st.rerun()


def pagina_dashboard_pacientes(aba_pacientes):
    hero("Dashboard de Pacientes", "Visão geral da base cadastrada.")
    df = carregar_dados_aba(aba_pacientes)

    if df.empty:
        st.warning("Ainda não há pacientes cadastrados.")
        return

    for col in COLUNAS_PACIENTES:
        if col not in df.columns:
            df[col] = ""

    if "Idade" not in df.columns:
        df["Idade"] = ""

    df["Idade"] = df.apply(
        lambda row: row["Idade"] if str(row.get("Idade", "")).strip() != "" else calcular_idade_por_data(row.get("Data de Nascimento", "")),
        axis=1
    )
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
    st.subheader("Tabela geral")
    st.dataframe(df, use_container_width=True)


def pagina_whatsapp(aba_pacientes):
    hero("WhatsApp Manual", "Gere mensagens personalizadas para pacientes.")
    df = carregar_dados_aba(aba_pacientes)

    if df.empty:
        st.warning("Ainda não há pacientes cadastrados.")
        return

    if "Telefone" not in df.columns:
        df["Telefone"] = ""

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
        "Personalizada": "Olá, [NOME]! [SUA_MENSAGEM_AQUI]"
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


def pagina_kanban(aba_kanban):
    hero("Kanban", "Controle visual de tarefas com checklist, comentários e prazo.")
    df = carregar_dados_aba(aba_kanban)

    if df.empty:
        df = pd.DataFrame(columns=COLUNAS_KANBAN)

    for col in COLUNAS_KANBAN:
        if col not in df.columns:
            df[col] = ""

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

    with st.expander("➕ Nova tarefa", expanded=False):
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

            checklist_inicial = st.text_area(
                "Checklist inicial (uma linha por item)",
                placeholder="Ex:\nLigar para cliente\nAtualizar cadastro\nSeparar documentos"
            )

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
                        "Atualizado em": agora
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
        df_filtrado = df_filtrado[
            df_filtrado["Responsável"].astype(str).str.contains(filtro_responsavel, case=False, na=False)
        ]

    if filtro_prioridade != "Todas":
        df_filtrado = df_filtrado[df_filtrado["Prioridade"] == filtro_prioridade]

    if filtro_status != "Todos":
        df_filtrado = df_filtrado[df_filtrado["Status"] == filtro_status]

    if filtro_texto.strip():
        df_filtrado = df_filtrado[
            df_filtrado["Título"].astype(str).str.contains(filtro_texto, case=False, na=False)
        ]

    st.markdown("---")
    colunas = st.columns(len(STATUS_OPCOES))

    for i, status in enumerate(STATUS_OPCOES):
        with colunas[i]:
            cor = CORES_STATUS[status]
            st.markdown(
                f'<div class="kanban-header" style="background:{cor};">{status}</div>',
                unsafe_allow_html=True
            )

            tarefas_coluna = df_filtrado[df_filtrado["Status"] == status]

            if tarefas_coluna.empty:
                st.markdown(
                    '<div class="kanban-col"><p style="text-align:center;color:#999;">Sem tarefas</p></div>',
                    unsafe_allow_html=True
                )
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
                                    key=f"status_{row['ID']}"
                                )
                            with a2:
                                nova_prioridade = st.selectbox(
                                    "Prioridade",
                                    PRIORIDADE_OPCOES,
                                    index=PRIORIDADE_OPCOES.index(row["Prioridade"]) if row["Prioridade"] in PRIORIDADE_OPCOES else 0,
                                    key=f"prio_{row['ID']}"
                                )

                            prazo_valor = None
                            try:
                                if str(row["Prazo"]).strip():
                                    prazo_valor = datetime.strptime(str(row["Prazo"]), "%d/%m/%Y").date()
                            except:
                                prazo_valor = None

                            novo_prazo = st.date_input(
                                "Prazo",
                                value=prazo_valor,
                                key=f"prazo_{row['ID']}"
                            )

                            st.markdown("**Checklist**")
                            checklist_editado = []
                            if checklist_itens:
                                for idx, item in enumerate(checklist_itens):
                                    feito = st.checkbox(
                                        item.get("texto", ""),
                                        value=item.get("feito", False),
                                        key=f"check_{row['ID']}_{idx}"
                                    )
                                    checklist_editado.append({
                                        "texto": item.get("texto", ""),
                                        "feito": feito
                                    })

                            novo_item_checklist = st.text_input(
                                "Adicionar item ao checklist",
                                key=f"novo_item_{row['ID']}"
                            )

                            st.markdown("**Comentários anteriores**")
                            if comentarios:
                                for c in comentarios:
                                    st.markdown(f"- **{c.get('data','')}**: {c.get('texto','')}")
                            else:
                                st.caption("Sem comentários.")

                            novo_comentario = st.text_area(
                                "Novo comentário",
                                key=f"comentario_{row['ID']}"
                            )

                            b1, b2 = st.columns(2)
                            with b1:
                                salvar = st.form_submit_button("Salvar alterações")
                            with b2:
                                excluir = st.form_submit_button("Excluir tarefa")

                            if salvar:
                                agora = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                                prazo_str = novo_prazo.strftime("%d/%m/%Y") if novo_prazo else ""

                                if novo_item_checklist.strip():
                                    checklist_editado.append({
                                        "texto": novo_item_checklist.strip(),
                                        "feito": False
                                    })

                                if novo_comentario.strip():
                                    comentarios.append({
                                        "data": agora,
                                        "texto": novo_comentario.strip()
                                    })

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
                                    "Atualizado em": agora
                                }

                                atualizar_tarefa_por_id(aba_kanban, row["ID"], novos_dados)
                                st.success("Tarefa atualizada.")
                                st.rerun()

                            if excluir:
                                excluir_tarefa_por_id(aba_kanban, row["ID"])
                                st.success("Tarefa excluída.")
                                st.rerun()

                st.markdown('</div>', unsafe_allow_html=True)


# =========================================================
# MAIN
# =========================================================
def main():
    st.set_page_config(page_title="Sistema Unificado", page_icon="📋", layout="wide")
    aplicar_estilo()

    planilha = conectar_planilha()
    aba_pacientes = obter_ou_criar_aba(planilha, "PACIENTES", COLUNAS_PACIENTES)
    aba_kanban = obter_ou_criar_aba(planilha, "KANBAN", COLUNAS_KANBAN)

    st.sidebar.title("Menu")
    pagina = st.sidebar.radio(
        "Escolha uma página:",
        [
            "🏠 Início",
            "👥 Cadastro de Pacientes",
            "🔎 Gestão de Pacientes",
            "📊 Dashboard de Pacientes",
            "📱 WhatsApp Manual",
            "📋 Kanban"
        ]
    )

    if pagina == "🏠 Início":
        pagina_inicial()
    elif pagina == "👥 Cadastro de Pacientes":
        pagina_cadastro_pacientes(aba_pacientes)
    elif pagina == "🔎 Gestão de Pacientes":
        pagina_gestao_pacientes(aba_pacientes)
    elif pagina == "📊 Dashboard de Pacientes":
        pagina_dashboard_pacientes(aba_pacientes)
    elif pagina == "📱 WhatsApp Manual":
        pagina_whatsapp(aba_pacientes)
    elif pagina == "📋 Kanban":
        pagina_kanban(aba_kanban)


if __name__ == "__main__":
    main()
