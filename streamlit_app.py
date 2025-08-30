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
from pdf2image import convert_from_bytes

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
# O st.set_page_config é chamado dentro da função main para permitir o roteamento de página

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
        colunas_esperadas = ["ID", "FAMÍLIA", "Nome Completo", "Data de Nascimento", "Telefone", "CPF", "Nome da Mãe", "Nome do Pai", "Sexo", "CNS", "Município de Nascimento", "Link do Prontuário", "Link da Pasta da Família", "Condição", "Data de Registo", "Raça/Cor", "Medicamentos"]
        for col in colunas_esperadas:
            if col not in df.columns: df[col] = ""
        df['Data de Nascimento DT'] = pd.to_datetime(df['Data de Nascimento'], format='%d/%m/%Y', errors='coerce')
        df['Idade'] = df['Data de Nascimento DT'].apply(lambda dt: calcular_idade(dt) if pd.notnull(dt) else 0)
        return df
    except Exception as e:
        st.error(f"Erro ao ler os dados da planilha: {e}"); return pd.DataFrame()

@st.cache_data(ttl=300)
def ler_agendamentos(planilha_key):
    try:
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
        sheet = client.open_by_key(planilha_key).worksheet("Agendamentos")
        dados = sheet.get_all_records()
        df = pd.DataFrame(dados)
        if not df.empty:
            df['Data_Hora_Agendamento'] = pd.to_datetime(df['Data_Agendamento'] + ' ' + df['Hora_Agendamento'], format='%d/%m/%Y %H:%M', errors='coerce')
        return df
    except gspread.exceptions.WorksheetNotFound:
        st.error("A folha 'Agendamentos' não foi encontrada na sua Planilha Google. Por favor, crie-a com os cabeçalhos corretos.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao ler os agendamentos: {e}")
        return pd.DataFrame()

def salvar_agendamento(planilha_key, agendamento_dados):
    try:
        creds = st.secrets["gcp_service_account"]
        client = gspread.service_account_from_dict(creds)
        sheet = client.open_by_key(planilha_key).worksheet("Agendamentos")
        agendamento_dados['ID_Agendamento'] = f"AG-{int(time.time())}"
        cabecalhos = sheet.row_values(1)
        nova_linha = [agendamento_dados.get(cabecalho, "") for cabecalho in cabecalhos]
        sheet.append_row(nova_linha)
        st.success("Agendamento salvo com sucesso!")
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Ocorreu um erro ao salvar o agendamento: {e}")
        return False
        
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

def extrair_dados_clinicos_com_cohere(texto_prontuario: str, cohere_client):
    prompt = f"""
    Sua tarefa é analisar o texto de um prontuário médico e extrair informações clínicas chave.
    O seu foco deve ser em duas categorias: Diagnósticos (especialmente condições crónicas) e Medicamentos.
    Instruções:
    1.  Analise o texto completo para compreender o contexto clínico do paciente.
    2.  Extraia Diagnósticos: Identifique todas as condições médicas e diagnósticos mencionados. Dê prioridade a doenças crónicas como 'Diabetes' (Tipo 1 ou 2), 'Hipertensão Arterial Sistêmica (HAS)', 'Asma', 'DPOC'.
    3.  Extraia Medicamentos: Identifique todos os medicamentos de uso contínuo ou relevante mencionados, incluindo a dosagem, se disponível (ex: 'Metformina 500mg', 'Losartana 50mg').
    4.  Formato de Saída: Retorne APENAS um objeto JSON com as seguintes chaves:
        -   "diagnosticos": (uma lista de strings com os diagnósticos encontrados)
        -   "medicamentos": (uma lista de strings com os medicamentos encontrados)
    Se nenhuma informação de uma categoria for encontrada, retorne uma lista vazia para essa chave.
    Texto do Prontuário para analisar:
    ---
    {texto_prontuario}
    ---
    """
    try:
        response = cohere_client.chat(model="command-r-plus", message=prompt, temperature=0.2)
        json_string = response.text.strip()
        if json_string.startswith("```json"): json_string = json_string[7:]
        if json_string.endswith("```"): json_string = json_string[:-3]
        dados_extraidos = json.loads(json_string.strip())
        if "diagnosticos" in dados_extraidos and "medicamentos" in dados_extraidos:
            return dados_extraidos
        else: return None
    except Exception as e:
        st.error(f"Erro ao processar a resposta da IA para extração clínica: {e}")
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

# --- FUNÇÕES DE GERAÇÃO DE PDF ---
def preencher_pdf_formulario(paciente_dados):
    # (Corpo da função preencher_pdf_formulario)
    pass
def gerar_pdf_etiquetas(familias_para_gerar):
    # (Corpo da função gerar_pdf_etiquetas)
    pass
def gerar_pdf_capas_prontuario(pacientes_df):
    # (Corpo da função gerar_pdf_capas_prontuario)
    pass
def gerar_pdf_relatorio_vacinacao(nome_paciente, data_nascimento, relatorio):
    # (Corpo da função gerar_pdf_relatorio_vacinacao)
    pass

# --- PÁGINAS DO APP ---
def pagina_agendamentos(planilha, co_client):
    st.title("🗓️ Gestão de Agendamentos")
    df_pacientes = ler_dados_da_planilha(planilha)
    df_agendamentos = ler_agendamentos(st.secrets["SHEETSID"])

    with st.expander("➕ Adicionar Novo Agendamento"):
        with st.form("form_novo_agendamento", clear_on_submit=True):
            lista_pacientes = df_pacientes.sort_values('Nome Completo')['Nome Completo'].tolist()
            paciente_selecionado = st.selectbox("Paciente:", lista_pacientes, index=None, placeholder="Selecione um paciente...")
            col1, col2 = st.columns(2)
            data_agendamento = col1.date_input("Data:")
            hora_agendamento = col2.time_input("Hora:")
            tipo_agendamento = st.selectbox("Tipo de Agendamento:", ["Consulta", "Vacinação", "Exame", "Retorno", "Visita Domiciliar"])
            descricao = st.text_area("Descrição (Opcional):")
            submit_button = st.form_submit_button("Salvar Agendamento")
            if submit_button and paciente_selecionado:
                paciente_info = df_pacientes[df_pacientes['Nome Completo'] == paciente_selecionado].iloc[0]
                novo_agendamento = {
                    "ID_Paciente": paciente_info.get("ID", ""), "Nome_Paciente": paciente_selecionado,
                    "Telefone_Paciente": paciente_info.get("Telefone", ""), "Data_Agendamento": data_agendamento.strftime("%d/%m/%Y"),
                    "Hora_Agendamento": hora_agendamento.strftime("%H:%M"), "Tipo_Agendamento": tipo_agendamento,
                    "Descricao": descricao, "Status": "Agendado", "Lembrete_Enviado": "Não"
                }
                salvar_agendamento(st.secrets["SHEETSID"], novo_agendamento)
                st.rerun()

    st.markdown("---")
    st.subheader("📅 Próximos Agendamentos")
    if not df_agendamentos.empty:
        hoje = pd.to_datetime(datetime.now().date())
        proximos_agendamentos = df_agendamentos[df_agendamentos['Data_Hora_Agendamento'] >= hoje].sort_values("Data_Hora_Agendamento")
        st.dataframe(proximos_agendamentos[['Nome_Paciente', 'Data_Agendamento', 'Hora_Agendamento', 'Tipo_Agendamento', 'Status']], use_container_width=True)
    else:
        st.info("Nenhum agendamento futuro encontrado.")
    st.markdown("---")
    st.subheader("📱 Lembretes para Enviar (Próximas 48 horas)")
    if not df_agendamentos.empty:
        amanha = pd.to_datetime((datetime.now() + pd.Timedelta(days=2)).date())
        proximos_agendamentos = df_agendamentos[df_agendamentos['Data_Hora_Agendamento'] >= pd.to_datetime(datetime.now().date())].sort_values("Data_Hora_Agendamento")
        agendamentos_para_lembrete = proximos_agendamentos[
            (proximos_agendamentos['Data_Hora_Agendamento'] < amanha) & 
            (proximos_agendamentos['Lembrete_Enviado'] == 'Não')
        ]
        if not agendamentos_para_lembrete.empty:
            for index, row in agendamentos_para_lembrete.iterrows():
                nome_paciente = row['Nome_Paciente']
                telefone = re.sub(r'\D', '', str(row['Telefone_Paciente']))
                if len(telefone) >= 10:
                    mensagem = f"Olá, {nome_paciente.split()[0]}. Gostaríamos de lembrar do seu agendamento de '{row['Tipo_Agendamento']}' no dia {row['Data_Agendamento']} às {row['Hora_Agendamento']}. Por favor, confirme a sua presença respondendo a esta mensagem. Obrigado!"
                    whatsapp_url = f"https://wa.me/55{telefone}?text={urllib.parse.quote(mensagem)}"
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.write(f"**{nome_paciente}** - {row['Tipo_Agendamento']} em {row['Data_Agendamento']} às {row['Hora_Agendamento']}")
                    with col2:
                        st.link_button("Enviar Lembrete ↗️", whatsapp_url, use_container_width=True)
        else:
            st.info("Nenhum lembrete a ser enviado nas próximas 48 horas.")
    else:
        st.info("Nenhum agendamento futuro encontrado.")

def desenhar_dashboard_familia(familia_id, df_completo):
    # (Corpo da função desenhar_dashboard_familia)
    pass
def pagina_pesquisa(planilha):
    # (Corpo da função pagina_pesquisa)
    pass
# ... (outras funções de página: coleta, dashboard, etc.)

def main():
    # (Corpo da função main com o roteador e a adição da nova página de agendamentos)
    pass

if __name__ == "__main__":
    main()
