import streamlit as st
import pandas as pd
from datetime import datetime
import re
import gspread
import json
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Coleta Rápida OCR", page_icon="📋", layout="wide")

ABA_BASE = "BASE_DE_DADOS"
ABA_LISTAGEM = "LISTAGEM"

COLUNAS = [
    "ID","FAMÍLIA","Nome Completo","Data de Nascimento","Idade","Sexo",
    "Nome da Mãe","Nome do Pai","Município de Nascimento","Município de Residência",
    "CPF","CNS","Telefone","Observações","Fonte da Imagem","Data da Extração",
    "Link da Pasta da Família","Timestamp de Envio","Condição","Data de Registo",
    "Raça/Cor","Status Vacinal","Confiança OCR","Revisado"
]

def limpar_cpf(valor: str) -> str:
    return re.sub(r"\D", "", str(valor or ""))

def validar_cpf(cpf: str) -> bool:
    cpf = limpar_cpf(cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    d1 = (soma * 10 % 11) % 10
    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    d2 = (soma * 10 % 11) % 10
    return cpf[-2:] == f"{d1}{d2}"

def calcular_idade(data_nasc):
    dt = pd.to_datetime(data_nasc, dayfirst=True, errors="coerce")
    if pd.isna(dt):
        return ""
    hoje = pd.Timestamp.today().normalize()
    return int(hoje.year - dt.year - ((hoje.month, hoje.day) < (dt.month, dt.day)))

@st.cache_resource
def conectar_google():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = dict(st.secrets["gcp_service_account"])
    credentials = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(credentials)
    spreadsheet_id = st.secrets["spreadsheet_id"]
    planilha = client.open_by_key(spreadsheet_id)

    try:
        aba = planilha.worksheet(ABA_BASE)
    except gspread.WorksheetNotFound:
        aba = planilha.add_worksheet(title=ABA_BASE, rows=5000, cols=len(COLUNAS))
        aba.append_row(COLUNAS)

    registros = aba.get_all_records()
    if not registros:
        primeira_linha = aba.row_values(1)
        if primeira_linha != COLUNAS:
            aba.clear()
            aba.append_row(COLUNAS)

    return planilha, aba

def carregar_dados():
    _, aba = conectar_google()
    registros = aba.get_all_records()
    if not registros:
        return pd.DataFrame(columns=COLUNAS)
    df = pd.DataFrame(registros)
    for col in COLUNAS:
        if col not in df.columns:
            df[col] = ""
    return df[COLUNAS]

def criar_ou_recriar_listagem(planilha):
    try:
        ws_antiga = planilha.worksheet(ABA_LISTAGEM)
        planilha.del_worksheet(ws_antiga)
    except gspread.WorksheetNotFound:
        pass
    return planilha.add_worksheet(title=ABA_LISTAGEM, rows=5000, cols=5)

def aplicar_estilo_listagem(planilha, ws, total_linhas):
    sheet_id = ws.id
    requests = [
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": 5
                },
                "cell": {
                    "userEnteredFormat": {
                        "backgroundColor": {"red": 0.12, "green": 0.31, "blue": 0.47},
                        "horizontalAlignment": "CENTER",
                        "textFormat": {
                            "foregroundColor": {"red": 1, "green": 1, "blue": 1},
                            "bold": True
                        }
                    }
                },
                "fields": "userEnteredFormat(backgroundColor,textFormat,horizontalAlignment)"
            }
        },
        {
            "setBasicFilter": {
                "filter": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": total_linhas,
                        "startColumnIndex": 0,
                        "endColumnIndex": 5
                    }
                }
            }
        },
        {
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": total_linhas,
                        "startColumnIndex": 0,
                        "endColumnIndex": 5
                    }],
                    "booleanRule": {
                        "condition": {
                            "type": "CUSTOM_FORMULA",
                            "values": [{"userEnteredValue": '=$E2="SIM"'}]
                        },
                        "format": {
                            "backgroundColor": {"red": 0.99, "green": 0.89, "blue": 0.84}
                        }
                    }
                },
                "index": 0
            }
        },
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": 5
                },
                "properties": {"pixelSize": 180},
                "fields": "pixelSize"
            }
        }
    ]
    planilha.batch_update({"requests": requests})

def atualizar_listagem():
    planilha, aba_base = conectar_google()
    registros = aba_base.get_all_records()
    ws_listagem = criar_ou_recriar_listagem(planilha)

    cabecalho = ["FAMÍLIA", "Nome Completo", "Idade", "Qtd. Família", "Idoso?"]

    if not registros:
        ws_listagem.update("A1:E1", [cabecalho])
        aplicar_estilo_listagem(planilha, ws_listagem, 1)
        return

    df = pd.DataFrame(registros)
    for col in ["FAMÍLIA", "Nome Completo", "Idade"]:
        if col not in df.columns:
            df[col] = ""

    lista = df[["FAMÍLIA", "Nome Completo", "Idade"]].copy()
    lista["FAMÍLIA"] = lista["FAMÍLIA"].fillna("").astype(str).str.strip()
    lista["Nome Completo"] = lista["Nome Completo"].fillna("").astype(str).str.strip()
    lista["Idade"] = pd.to_numeric(lista["Idade"], errors="coerce").fillna(0).astype(int)

    lista = lista[lista["Nome Completo"] != ""].copy()
    lista["Qtd. Família"] = lista.groupby("FAMÍLIA")["FAMÍLIA"].transform("count")
    lista["Idoso?"] = lista["Idade"].apply(lambda x: "SIM" if x >= 60 else "NÃO")

    lista = lista.sort_values(
        by=["FAMÍLIA", "Nome Completo"],
        key=lambda s: s.astype(str).str.upper()
    ).reset_index(drop=True)

    valores = [cabecalho] + lista[["FAMÍLIA", "Nome Completo", "Idade", "Qtd. Família", "Idoso?"]].values.tolist()
    ws_listagem.update(f"A1:E{len(valores)}", valores)
    aplicar_estilo_listagem(planilha, ws_listagem, len(valores))

def salvar_registro(novo):
    _, aba = conectar_google()
    linha = [novo.get(col, "") for col in COLUNAS]
    aba.append_row(linha, value_input_option="USER_ENTERED")
    atualizar_listagem()

def extrair_com_gemini(image_bytes: bytes, mime_type: str):
    try:
        import google.generativeai as genai
    except Exception:
        return {"erro": "Biblioteca google-generativeai não instalada."}

    api_key = st.secrets.get("gemini_api_key", "")
    if not api_key:
        return {"erro": "gemini_api_key não configurada no Secrets."}

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")

    prompt = """
Você vai ler uma ficha/cadastro em português do Brasil e extrair os campos.
Responda SOMENTE em JSON válido, sem markdown, sem comentários.
Se não souber um campo, retorne string vazia.

Use exatamente estas chaves:
ID
FAMÍLIA
Nome Completo
Data de Nascimento
Sexo
Nome da Mãe
Nome do Pai
Município de Nascimento
Município de Residência
CPF
CNS
Telefone
Observações
Condição
Data de Registo
Raça/Cor
Status Vacinal
confianca_ocr
"""
    response = model.generate_content([
        {"mime_type": mime_type, "data": image_bytes},
        prompt
    ])
    texto = response.text.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(texto)
    except Exception:
        return {"erro": "A IA não retornou JSON válido.", "resposta_bruta": texto}

st.title("📋 Coleta Rápida OCR")
st.caption("Google Sheets + LISTAGEM com filtro, contador por família e destaque para idosos.")

with st.expander("Configuração", expanded=False):
    st.markdown("""
A aba `LISTAGEM` é criada/atualizada automaticamente com:
- **FAMÍLIA**
- **Nome Completo**
- **Idade**
- **Qtd. Família**
- **Idoso?**

Recursos da aba:
- ordenação por **Família** e depois **Nome**
- **filtro**
- **contador por família**
- **destaque visual** para idosos
""")

tab1, tab2, tab3, tab4 = st.tabs(["OCR da ficha", "Novo cadastro", "Base atual", "Estatísticas"])

with tab1:
    st.subheader("Upload e leitura da ficha")
    arquivo = st.file_uploader("Envie imagem da ficha", type=["png", "jpg", "jpeg", "webp"])
    if arquivo:
        st.image(arquivo, caption="Pré-visualização da ficha", use_container_width=True)
        if st.button("Extrair dados com IA"):
            with st.spinner("Lendo a ficha..."):
                dados = extrair_com_gemini(arquivo.getvalue(), arquivo.type)
            if "erro" in dados:
                st.error(dados["erro"])
                if "resposta_bruta" in dados:
                    st.code(dados["resposta_bruta"])
            else:
                st.session_state["ocr_resultado"] = dados
                st.success("Extração concluída. Revise os campos na aba Novo cadastro.")
                st.json(dados)

ocr = st.session_state.get("ocr_resultado", {})

with tab2:
    st.subheader("Novo cadastro")
    with st.form("cadastro"):
        c1, c2, c3 = st.columns(3)
        id_reg = c1.text_input("ID", value=ocr.get("ID", ""))
        familia = c2.text_input("FAMÍLIA", value=ocr.get("FAMÍLIA", ""))
        nome = c3.text_input("Nome Completo", value=ocr.get("Nome Completo", ""))

        c4, c5, c6 = st.columns(3)
        data_nasc = c4.text_input("Data de Nascimento (dd/mm/aaaa)", value=ocr.get("Data de Nascimento", ""))
        sexo = c5.selectbox("Sexo", ["", "M", "F"], index=(["", "M", "F"].index(ocr.get("Sexo", "")) if ocr.get("Sexo", "") in ["", "M", "F"] else 0))
        telefone = c6.text_input("Telefone", value=ocr.get("Telefone", ""))

        c7, c8, c9 = st.columns(3)
        mae = c7.text_input("Nome da Mãe", value=ocr.get("Nome da Mãe", ""))
        pai = c8.text_input("Nome do Pai", value=ocr.get("Nome do Pai", ""))
        cpf = c9.text_input("CPF", value=ocr.get("CPF", ""))

        c10, c11, c12 = st.columns(3)
        cns = c10.text_input("CNS", value=ocr.get("CNS", ""))
        mun_nasc = c11.text_input("Município de Nascimento", value=ocr.get("Município de Nascimento", ""))
        mun_res = c12.text_input("Município de Residência", value=ocr.get("Município de Residência", ""))

        c13, c14, c15 = st.columns(3)
        condicao = c13.text_input("Condição", value=ocr.get("Condição", ""))
        raca_opcoes = ["", "BRANCA", "PRETA", "PARDA", "AMARELA", "INDÍGENA"]
        vac_opcoes = ["", "COMPLETO", "INCOMPLETO", "NÃO VACINADO", "IGNORADO"]
        conf_opcoes = ["", "Alta", "Média", "Baixa"]

        raca_val = ocr.get("Raça/Cor", "")
        vacina_val = ocr.get("Status Vacinal", "")
        conf_val = ocr.get("confianca_ocr", "")

        raca = c14.selectbox("Raça/Cor", raca_opcoes, index=(raca_opcoes.index(raca_val) if raca_val in raca_opcoes else 0))
        vacina = c15.selectbox("Status Vacinal", vac_opcoes, index=(vac_opcoes.index(vacina_val) if vacina_val in vac_opcoes else 0))

        c16, c17 = st.columns(2)
        confianca = c16.selectbox("Confiança OCR", conf_opcoes, index=(conf_opcoes.index(conf_val) if conf_val in conf_opcoes else 0))
        revisado = c17.selectbox("Revisado", ["", "SIM", "NÃO"], index=2 if ocr else 0)

        obs = st.text_area("Observações", value=ocr.get("Observações", ""))
        fonte = st.text_input("Fonte da Imagem", value="Upload no app" if ocr else "")
        link_pasta = st.text_input("Link da Pasta da Família")

        enviar = st.form_submit_button("Salvar cadastro no Google Sheets")

    if enviar:
        idade = calcular_idade(data_nasc)
        if cpf and not validar_cpf(cpf):
            st.warning("CPF informado parece inválido. O registro ainda pode ser salvo para revisão.")

        novo = {
            "ID": id_reg,
            "FAMÍLIA": familia,
            "Nome Completo": nome,
            "Data de Nascimento": data_nasc,
            "Idade": idade,
            "Sexo": sexo,
            "Nome da Mãe": mae,
            "Nome do Pai": pai,
            "Município de Nascimento": mun_nasc,
            "Município de Residência": mun_res,
            "CPF": cpf,
            "CNS": cns,
            "Telefone": telefone,
            "Observações": obs,
            "Fonte da Imagem": fonte,
            "Data da Extração": datetime.now().strftime("%d/%m/%Y"),
            "Link da Pasta da Família": link_pasta,
            "Timestamp de Envio": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "Condição": condicao,
            "Data de Registo": ocr.get("Data de Registo", "") or datetime.now().strftime("%d/%m/%Y"),
            "Raça/Cor": raca,
            "Status Vacinal": vacina,
            "Confiança OCR": confianca,
            "Revisado": revisado,
        }

        try:
            salvar_registro(novo)
            st.success("Cadastro salvo e LISTAGEM atualizada.")
            st.cache_resource.clear()
        except Exception as e:
            st.error(f"Erro ao salvar no Google Sheets: {e}")

with tab3:
    st.subheader("Base atual")
    try:
        df = carregar_dados()
        if df.empty:
            st.info("Nenhum registro encontrado.")
        else:
            busca = st.text_input("Pesquisar por nome, família, CPF ou CNS")
            if busca:
                mask = df.astype(str).apply(lambda col: col.str.contains(busca, case=False, na=False)).any(axis=1)
                df = df[mask]
            st.dataframe(df, use_container_width=True, hide_index=True)
            csv = df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("Baixar CSV", data=csv, file_name="coleta_rapida_base.csv", mime="text/csv")

            if st.button("Atualizar LISTAGEM agora"):
                atualizar_listagem()
                st.success("LISTAGEM atualizada com sucesso.")
    except Exception as e:
        st.error(f"Erro ao carregar dados da planilha: {e}")

with tab4:
    st.subheader("Estatísticas")
    try:
        df = carregar_dados()
        if df.empty:
            st.info("Sem dados para análise.")
        else:
            col1, col2, col3 = st.columns(3)
            col1.metric("Total de registros", len(df))
            col2.metric("Famílias únicas", df["FAMÍLIA"].astype(str).nunique())
            idosos = pd.to_numeric(df["Idade"], errors="coerce").fillna(0)
            col3.metric("Pessoas com 60+", int((idosos >= 60).sum()))

            st.markdown("**Distribuição por sexo**")
            sexo_df = df["Sexo"].fillna("").replace("", "Não informado").value_counts().rename_axis("Sexo").reset_index(name="Quantidade")
            st.bar_chart(sexo_df.set_index("Sexo"))

            st.markdown("**Status vacinal**")
            vac_df = df["Status Vacinal"].fillna("").replace("", "Não informado").value_counts().rename_axis("Status").reset_index(name="Quantidade")
            st.bar_chart(vac_df.set_index("Status"))
    except Exception as e:
        st.error(f"Erro ao gerar estatísticas: {e}")

st.sidebar.header("LISTAGEM")
st.sidebar.write("Ordenação por Família + Nome, filtro automático, contador por família e destaque de idosos.")
