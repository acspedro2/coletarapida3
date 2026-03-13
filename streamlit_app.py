import streamlit as st
import pandas as pd
import gspread
import uuid
import json
from datetime import datetime, date

# =========================
# CONFIGURAÇÕES
# =========================
STATUS_OPCOES = ["Backlog", "Para Fazer", "Em Andamento", "Aguardando", "Concluído"]
PRIORIDADE_OPCOES = ["Baixa", "Média", "Alta", "Urgente"]

CORES_STATUS = {
    "Backlog": "#dfe6e9",
    "Para Fazer": "#74b9ff",
    "Em Andamento": "#ffeaa7",
    "Aguardando": "#fab1a0",
    "Concluído": "#55efc4"
}

USUARIOS_FIXOS = {
    "admin": "1234",
    "agente1": "1234",
    "agente2": "1234"
}

COLUNAS_PLANILHA = [
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
    "Criado por"
]

# =========================
# ESTILO
# =========================
def aplicar_estilo():
    st.markdown("""
    <style>
    .main {
        background-color: #f7f9fc;
    }

    .block-container {
        padding-top: 1rem;
        padding-bottom: 2rem;
        max-width: 1450px;
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

    .section-box {
        background: white;
        padding: 18px;
        border-radius: 16px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.06);
        margin-bottom: 16px;
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

    .login-box {
        background: white;
        padding: 24px;
        border-radius: 18px;
        box-shadow: 0 2px 12px rgba(0,0,0,0.08);
        max-width: 500px;
        margin: 30px auto;
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
    </style>
    """, unsafe_allow_html=True)


def hero(titulo="Sistema com Kanban", subtitulo="Gestão visual de tarefas com Google Sheets."):
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

# =========================
# LOGIN
# =========================
def inicializar_login():
    if "logado" not in st.session_state:
        st.session_state.logado = False
    if "usuario" not in st.session_state:
        st.session_state.usuario = ""


def tela_login():
    st.markdown('<div class="login-box">', unsafe_allow_html=True)
    st.title("Acesso ao sistema")
    usuario = st.text_input("Usuário")
    senha = st.text_input("Senha", type="password")

    if st.button("Entrar"):
        if usuario in USUARIOS_FIXOS and USUARIOS_FIXOS[usuario] == senha:
            st.session_state.logado = True
            st.session_state.usuario = usuario
            st.success("Login realizado com sucesso.")
            st.rerun()
        else:
            st.error("Usuário ou senha inválidos.")
    st.markdown('</div>', unsafe_allow_html=True)


def logout():
    st.session_state.logado = False
    st.session_state.usuario = ""
    st.rerun()

# =========================
# GOOGLE SHEETS
# =========================
@st.cache_resource
def conectar_planilha():
    try:
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
        planilha = client.open_by_key(st.secrets["KANBAN_SHEET_ID"])
        try:
            aba = planilha.worksheet("KANBAN")
        except:
            aba = planilha.add_worksheet(title="KANBAN", rows=3000, cols=20)
            aba.append_row(COLUNAS_PLANILHA)
        return aba
    except Exception as e:
        st.error(f"Erro ao conectar ao Google Sheets: {e}")
        return None


@st.cache_data(ttl=60)
def carregar_tarefas(_aba):
    try:
        dados = _aba.get_all_records()
        df = pd.DataFrame(dados)

        for col in COLUNAS_PLANILHA:
            if col not in df.columns:
                df[col] = ""

        return df
    except Exception as e:
        st.error(f"Erro ao carregar tarefas: {e}")
        return pd.DataFrame(columns=COLUNAS_PLANILHA)


def salvar_nova_tarefa(aba, tarefa):
    try:
        aba.append_row([tarefa.get(col, "") for col in COLUNAS_PLANILHA])
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao salvar tarefa: {e}")


def atualizar_tarefa_por_id(aba, task_id, novos_dados):
    try:
        dados = aba.get_all_values()
        if len(dados) < 2:
            st.error("Nenhuma tarefa encontrada.")
            return

        linhas = dados[1:]
        for i, linha in enumerate(linhas, start=2):
            if str(linha[0]) == str(task_id):
                nova_linha = [novos_dados.get(col, "") for col in COLUNAS_PLANILHA]
                aba.update(f"A{i}:L{i}", [nova_linha])
                st.cache_data.clear()
                return

        st.error("Tarefa não encontrada.")
    except Exception as e:
        st.error(f"Erro ao atualizar tarefa: {e}")


def excluir_tarefa_por_id(aba, task_id):
    try:
        dados = aba.get_all_values()
        if len(dados) < 2:
            st.error("Nenhuma tarefa encontrada.")
            return

        linhas = dados[1:]
        for i, linha in enumerate(linhas, start=2):
            if str(linha[0]) == str(task_id):
                aba.delete_rows(i)
                st.cache_data.clear()
                return

        st.error("Tarefa não encontrada.")
    except Exception as e:
        st.error(f"Erro ao excluir tarefa: {e}")

# =========================
# HELPERS
# =========================
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


def parse_checklist(raw):
    if not str(raw).strip():
        return []
    try:
        valor = json.loads(raw)
        if isinstance(valor, list):
            return valor
        return []
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
        if isinstance(valor, list):
            return valor
        return []
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

# =========================
# PÁGINAS
# =========================
def pagina_inicial():
    hero("Sistema com Kanban", "App completo com login, tarefas, dashboard e Google Sheets.")
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("""
        <div class="section-box">
            <h3>📋 Kanban V2</h3>
            <p>Organize tarefas em colunas, acompanhe status e produtividade.</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="section-box">
            <h3>✅ Checklist</h3>
            <p>Adicione subtarefas e acompanhe o progresso dentro de cada cartão.</p>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown("""
        <div class="section-box">
            <h3>💬 Comentários</h3>
            <p>Registre histórico das tarefas com data e usuário responsável.</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("""
        <div class="section-box">
            <h3>📊 Dashboard</h3>
            <p>Veja tarefas totais, andamento, concluídas e atrasadas.</p>
        </div>
        """, unsafe_allow_html=True)


def pagina_dashboard(aba):
    hero("Dashboard do Kanban", "Métricas gerais do quadro.")
    df = carregar_tarefas(aba)

    total = len(df)
    backlog = len(df[df["Status"] == "Backlog"])
    fazer = len(df[df["Status"] == "Para Fazer"])
    andamento = len(df[df["Status"] == "Em Andamento"])
    aguardando = len(df[df["Status"] == "Aguardando"])
    concluidas = len(df[df["Status"] == "Concluído"])
    atrasadas = sum(1 for _, row in df.iterrows() if tarefa_atrasada(row))

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    with m1:
        metric_card("Total", total)
    with m2:
        metric_card("Backlog", backlog)
    with m3:
        metric_card("Para Fazer", fazer)
    with m4:
        metric_card("Em Andamento", andamento)
    with m5:
        metric_card("Concluídas", concluidas)
    with m6:
        metric_card("Atrasadas", atrasadas)

    st.markdown("---")
    st.subheader("Tabela geral")
    st.dataframe(df, use_container_width=True)


def pagina_kanban(aba):
    hero("Kanban V2", "Controle visual de tarefas com filtros, checklist e comentários.")
    df = carregar_tarefas(aba)

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
                responsavel = st.text_input("Responsável", value=st.session_state.usuario)
            with c2:
                status = st.selectbox("Status", STATUS_OPCOES, index=0)
                prioridade = st.selectbox("Prioridade", PRIORIDADE_OPCOES, index=1)
                prazo = st.date_input("Prazo", value=None)

            checklist_inicial = st.text_area(
                "Checklist inicial (uma linha por item)",
                placeholder="Ex:\nLigar para cliente\nSeparar documentos\nAtualizar cadastro"
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
                        "Atualizado em": agora,
                        "Criado por": st.session_state.usuario
                    }
                    salvar_nova_tarefa(aba, tarefa)
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
                                    st.markdown(
                                        f"- **{c.get('data','')} | {c.get('usuario','')}**: {c.get('texto','')}"
                                    )
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
                                        "usuario": st.session_state.usuario,
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
                                    "Atualizado em": agora,
                                    "Criado por": row.get("Criado por", "")
                                }

                                atualizar_tarefa_por_id(aba, row["ID"], novos_dados)
                                st.success("Tarefa atualizada.")
                                st.rerun()

                            if excluir:
                                excluir_tarefa_por_id(aba, row["ID"])
                                st.success("Tarefa excluída.")
                                st.rerun()

                st.markdown('</div>', unsafe_allow_html=True)

# =========================
# MAIN
# =========================
def main():
    st.set_page_config(page_title="Sistema com Kanban", page_icon="📋", layout="wide")
    aplicar_estilo()
    inicializar_login()

    if not st.session_state.logado:
        tela_login()
        return

    aba = conectar_planilha()
    if aba is None:
        st.stop()

    st.sidebar.title("Menu")
    st.sidebar.success(f"Usuário: {st.session_state.usuario}")

    pagina = st.sidebar.radio(
        "Escolha uma página:",
        ["🏠 Início", "📋 Kanban", "📊 Dashboard"]
    )

    if st.sidebar.button("Sair"):
        logout()

    if pagina == "🏠 Início":
        pagina_inicial()
    elif pagina == "📋 Kanban":
        pagina_kanban(aba)
    elif pagina == "📊 Dashboard":
        pagina_dashboard(aba)


if __name__ == "__main__":
    main()
