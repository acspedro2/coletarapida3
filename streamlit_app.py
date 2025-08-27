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
        colunas_esperadas = ["ID", "FAMÍLIA", "Nome Completo", "Data de Nascimento", "Telefone", "CPF", "Nome da Mãe", "Nome do Pai", "Sexo", "CNS", "Município de Nascimento", "Link do Prontuário", "Link da Pasta da Família", "Condição", "Data de Registo"]
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
        
        # --- CALIBRAÇÃO DOS CAMPOS ---
        can.setFont("Helvetica", 10)
        can.drawString(3.2 * cm, 23.8 * cm, str(paciente_dados.get("Nome Completo", "")))
        can.drawString(15 * cm, 23.8 * cm, str(paciente_dados.get("CPF", "")))
        can.drawString(16.5 * cm, 23 * cm, str(paciente_dados.get("Data de Nascimento", "")))
        
        # --- LÓGICA PARA MARCAR O 'X' NO SEXO ---
        sexo = str(paciente_dados.get("Sexo", "")).strip().upper()
        can.setFont("Helvetica-Bold", 12)
        if sexo.startswith('F'):
            can.drawString(11.7 * cm, 22.9 * cm, "X") # Ajuste final
        elif sexo.startswith('M'):
            can.drawString(12.6 * cm, 22.9 * cm, "X") # Ajuste final
        
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
        st.error(f"Erro: O arquivo modelo '{template_pdf_path}' não foi encontrado no repositório GitHub.")
        return None
    except Exception as e:
        st.error(f"Ocorreu um erro ao gerar o PDF: {e}")
        return None

# --- PÁGINAS DO APP ---
# ... (as outras páginas permanecem inalteradas) ...
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
                        dados_para_salvar['ID'] = st.text_input("ID", value=dados_extraidos.get("ID", ""))
                        dados_para_salvar['FAMÍLIA'] = st.text_input("FAMÍLIA", value=dados_extraidos.get("FAMÍLIA", ""))
                        dados_para_salvar['Nome Completo'] = st.text_input("Nome Completo", value=dados_extraidos.get("Nome Completo", ""))
                        dados_para_salvar['Data de Nascimento'] = st.text_input("Data de Nascimento", value=dados_extraidos.get("Data de Nascimento", ""))
                        dados_para_salvar['CPF'] = st.text_input("CPF", value=dados_extraidos.get("CPF", ""))
                        dados_para_salvar['CNS'] = st.text_input("CNS", value=dados_extraidos.get("CNS", ""))
                        dados_para_salvar['Telefone'] = st.text_input("Telefone", value=dados_extraidos.get("Telefone", ""))
                        dados_para_salvar['Nome da Mãe'] = st.text_input("Nome da Mãe", value=dados_extraidos.get("Nome da Mãe", ""))
                        dados_para_salvar['Nome do Pai'] = st.text_input("Nome do Pai", value=dados_extraidos.get("Nome do Pai", ""))
                        dados_para_salvar['Sexo'] = st.text_input("Sexo", value=dados_extraidos.get("Sexo", ""))
                        dados_para_salvar['Município de Nascimento'] = st.text_input("Município de Nascimento", value=dados_extraidos.get("Município de Nascimento", ""))

                        if st.form_submit_button("✅ Salvar Dados Desta Ficha"):
                            cpf_a_verificar = ''.join(re.findall(r'\d', dados_para_salvar['CPF']))
                            cns_a_verificar = ''.join(re.findall(r'\d', dados_para_salvar['CNS']))
                            
                            duplicado_cpf = False
                            if cpf_a_verificar and not df_existente.empty:
                                duplicado_cpf = df_existente['CPF'].astype(str).str.replace(r'\D', '', regex=True).str.contains(cpf_a_verificar).any()

                            duplicado_cns = False
                            if cns_a_verificar and not df_existente.empty:
                                duplicado_cns = df_existente['CNS'].astype(str).str.replace(r'\D', '', regex=True).str.contains(cns_a_verificar).any()

                            if duplicado_cpf or duplicado_cns:
                                st.error("⚠️ Alerta de Duplicado: Já existe um paciente registado com este CPF ou CNS. O registo não foi salvo.")
                            else:
                                salvar_no_sheets(dados_para_salvar, planilha)
                                st.session_state.processados.append(proximo_arquivo.file_id)
                                st.rerun()
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

    st.sidebar.header("Filtros do Dashboard")
    
    municipios = sorted(df_original['Município de Nascimento'].unique())
    municipios_selecionados = st.sidebar.multiselect("Filtrar por Município:", options=municipios, default=municipios)

    idade_max = int(df_original['Idade'].max()) if not df_original.empty else 100
    faixa_etaria = st.sidebar.slider("Filtrar por Faixa Etária:", min_value=0, max_value=idade_max, value=(0, idade_max))

    if not municipios_selecionados:
        municipios_selecionados = municipios

    df_filtrado = df_original[
        (df_original['Município de Nascimento'].isin(municipios_selecionados)) &
        (df_original['Idade'] >= faixa_etaria[0]) &
        (df_original['Idade'] <= faixa_etaria[1])
    ]
    
    if df_filtrado.empty:
        st.warning("Nenhum dado encontrado com os filtros selecionados.")
        return

    st.markdown("### Métricas Gerais (com filtros aplicados)")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total de Fichas", len(df_filtrado))
    
    idades_validas = df_filtrado.loc[df_filtrado['Idade'] > 0, 'Idade']
    idade_media = idades_validas.mean() if not idades_validas.empty else 0
    col2.metric("Idade Média", f"{idade_media:.1f} anos" if idade_media > 0 else "N/A")

    sexo_counts = df_filtrado['Sexo'].str.strip().str.capitalize().value_counts()
    col3.metric("Sexo (Moda)", sexo_counts.index[0] if not sexo_counts.empty else "N/A")
    
    st.markdown("---")
    
    gcol1, gcol2 = st.columns(2)
    
    with gcol1:
        st.markdown("### Pacientes por Município")
        municipio_counts = df_filtrado['Município de Nascimento'].value_counts()
        if not municipio_counts.empty:
            st.bar_chart(municipio_counts)
        else:
            st.info("Não há dados de município para exibir.")

    with gcol2:
        st.markdown("### Distribuição por Sexo")
        if not sexo_counts.empty:
            fig, ax = plt.subplots(figsize=(5, 3))
            ax.pie(sexo_counts, labels=sexo_counts.index, autopct='%1.1f%%', startangle=90, colors=['#66b3ff','#ff9999', '#99ff99'])
            ax.axis('equal')
            st.pyplot(fig)
        else:
            st.info("Não há dados de sexo para exibir.")
            
    st.markdown("---")
    st.markdown("### Evolução de Novos Registos por Mês")
    if 'Data de Registo' in df_filtrado.columns and df_filtrado['Data de Registo'].notna().any():
        df_filtrado['Data de Registo DT'] = pd.to_datetime(df_filtrado['Data de Registo'], format='%d/%m/%Y %H:%M:%S', errors='coerce')
        df_filtrado.dropna(subset=['Data de Registo DT'], inplace=True)
        
        if not df_filtrado.empty:
            registos_por_mes = df_filtrado.set_index('Data de Registo DT').resample('M').size().rename('Novos Pacientes')
            st.line_chart(registos_por_mes)
        else:
            st.info("Não há dados de registo válidos para exibir a evolução.")
    else:
        st.info("Adicione a coluna 'Data de Registo' e salve novos pacientes para ver a evolução histórica.")
            
    st.markdown("---")
    st.markdown("### Tabela de Dados (com filtros aplicados)")
    st.dataframe(df_filtrado)
    
    @st.cache_data
    def convert_df_to_csv(df):
        return df.to_csv(index=False).encode('utf-8')

    csv = convert_df_to_csv(df_filtrado)
    st.download_button(
        label="📥 Descarregar Dados Filtrados (CSV)",
        data=csv,
        file_name='dados_filtrados.csv',
        mime='text/csv',
    )
    
def pagina_pesquisa(planilha):
    st.title("🔎 Gestão de Pacientes")
    st.info("Use a pesquisa para encontrar um paciente e depois expandir para ver detalhes, editar ou apagar o registo.", icon="ℹ️")

    df = ler_dados_da_planilha(planilha)
    if df.empty:
        st.warning("Ainda não há dados na planilha para pesquisar.")
        return

    colunas_pesquisaveis = ["Nome Completo", "CPF", "CNS", "Nome da Mãe", "ID"]
    coluna_selecionada = st.selectbox("Pesquisar por:", colunas_pesquisaveis)
    termo_pesquisa = st.text_input("Digite o termo de pesquisa:")

    if termo_pesquisa:
        resultados = df[df[coluna_selecionada].astype(str).str.contains(termo_pesquisa, case=False, na=False)]
        
        st.markdown(f"**{len(resultados)}** resultado(s) encontrado(s):")
        
        for index, row in resultados.iterrows():
            id_paciente = row['ID']
            with st.expander(f"**{row['Nome Completo']}** (ID: {id_paciente})"):
                st.dataframe(row.to_frame().T, hide_index=True)
                
                col1, col2 = st.columns(2)
                
                with col1:
                    if st.button("✏️ Editar Dados", key=f"edit_{id_paciente}"):
                        st.session_state['patient_to_edit'] = row.to_dict()
                
                with col2:
                    if st.button("🗑️ Apagar Registo", key=f"delete_{id_paciente}"):
                        try:
                            cell = planilha.find(str(id_paciente))
                            planilha.delete_rows(cell.row)
                            st.success(f"Registo de {row['Nome Completo']} apagado com sucesso!")
                            st.cache_data.clear()
                            time.sleep(1)
                            st.rerun()
                        except gspread.exceptions.CellNotFound:
                            st.error(f"Erro: Não foi possível encontrar o paciente com ID {id_paciente} para apagar.")
                        except Exception as e:
                            st.error(f"Ocorreu um erro ao apagar: {e}")
                            
    if 'patient_to_edit' in st.session_state:
        st.markdown("---")
        st.subheader("Editando Paciente")
        
        patient_data = st.session_state['patient_to_edit']
        
        with st.form(key="edit_form"):
            edited_data = {}
            for key, value in patient_data.items():
                if key not in ['Data de Nascimento DT', 'Idade']:
                    edited_data[key] = st.text_input(f"{key}", value=value, key=f"edit_{key}")

            submitted = st.form_submit_button("Salvar Alterações")
            
            if submitted:
                try:
                    cell = planilha.find(str(patient_data['ID']))
                    row_to_update = cell.row
                    
                    cabecalhos = planilha.row_values(1)
                    update_values = [edited_data.get(h, '') for h in cabecalhos]
                    
                    planilha.update(f'A{row_to_update}', [update_values])
                    
                    st.success("Dados do paciente atualizados com sucesso!")
                    del st.session_state['patient_to_edit']
                    st.cache_data.clear()
                    time.sleep(1)
                    st.rerun()
                except gspread.exceptions.CellNotFound:
                    st.error(f"Erro: Não foi possível encontrar o paciente com ID {patient_data['ID']} para atualizar.")
                except Exception as e:
                    st.error(f"Ocorreu um erro ao salvar: {e}")
                    
def pagina_etiquetas(planilha):
    st.title("🏷️ Gerador de Etiquetas por Família")
    df = ler_dados_da_planilha(planilha)
    if df.empty: st.warning("Ainda não há dados na planilha para gerar etiquetas."); return
        
    def agregador(x):
        return {
            "membros": x[['Nome Completo', 'Data de Nascimento', 'CNS']].to_dict('records'),
            "link_pasta": x['Link da Pasta da Família'].iloc[0] if 'Link da Pasta da Família' in x.columns and not x['Link da Pasta da Família'].empty else ""
        }
    
    df_familias = df[df['FAMÍLIA'].astype(str).str.strip() != '']
    if df_familias.empty:
        st.warning("Não há famílias para exibir. Verifique se os IDs das famílias estão preenchidos na planilha.")
        return
        
    familias_dict = df_familias.groupby('FAMÍLIA').apply(agregador).to_dict()
    
    lista_familias = sorted([f for f in familias_dict.keys() if f])
    st.subheader("1. Selecione as famílias")
    familias_selecionadas = st.multiselect("Deixe em branco para selecionar todas as famílias:", lista_familias)
    if not familias_selecionadas: familias_para_gerar = familias_dict
    else: familias_para_gerar = {fid: familias_dict[fid] for fid in familias_selecionadas}
    st.subheader("2. Pré-visualização e Geração do PDF")
    if not familias_para_gerar: st.warning("Nenhuma família para exibir."); return
    for familia_id, dados_familia in familias_para_gerar.items():
        if familia_id:
            with st.expander(f"**Família: {familia_id}** ({len(dados_familia['membros'])} membro(s))"):
                for membro in dados_familia['membros']:
                    st.write(f"**{membro['Nome Completo']}**"); st.caption(f"DN: {membro['Data de Nascimento']} | CNS: {membro['CNS']}")
    if st.button("📥 Gerar PDF das Etiquetas com QR Code"):
        pdf_bytes = gerar_pdf_etiquetas(familias_para_gerar)
        st.download_button(label="Descarregar PDF", data=pdf_bytes, file_name=f"etiquetas_qrcode_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf")

def pagina_capas_prontuario(planilha):
    st.title("📇 Gerador de Capas de Prontuário")
    df = ler_dados_da_planilha(planilha)
    if df.empty: st.warning("Ainda não há dados na planilha para gerar capas."); return
    if "Link do Prontuário" not in df.columns:
        st.error("A sua planilha precisa de uma coluna chamada 'Link do Prontuário' para esta funcionalidade.")
        return
    st.subheader("1. Selecione os pacientes")
    lista_pacientes = df['Nome Completo'].tolist()
    pacientes_selecionados_nomes = st.multiselect("Escolha um ou mais pacientes para gerar as capas:", sorted(lista_pacientes))
    if pacientes_selecionados_nomes:
        pacientes_df = df[df['Nome Completo'].isin(pacientes_selecionados_nomes)]
        st.subheader("2. Pré-visualização")
        st.dataframe(pacientes_df[["Nome Completo", "Data de Nascimento", "FAMÍLIA", "CPF", "CNS", "Link do Prontuário"]])
        if st.button("📥 Gerar PDF das Capas com QR Code"):
            pdf_bytes = gerar_pdf_capas_prontuario(pacientes_df)
            st.download_button(label="Descarregar PDF das Capas", data=pdf_bytes, file_name=f"capas_prontuario_qrcode_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf")
    else: st.info("Selecione pelo menos um paciente para gerar as capas.")

def pagina_whatsapp(planilha):
    st.title("📱 Enviar Mensagens de WhatsApp")
    df = ler_dados_da_planilha(planilha)
    if df.empty: st.warning("Ainda não há dados na planilha para enviar mensagens."); return
    st.subheader("1. Escreva a sua mensagem")
    mensagem_padrao = st.text_area("Mensagem:", "Olá, [NOME]! A sua autorização de exame para [ESCREVA AQUI O NOME DO EXAME] foi liberada. Por favor, entre em contato para mais detalhes.", height=150)
    st.subheader("2. Escolha o paciente e envie")
    df_com_telefone = df[df['Telefone'].astype(str).str.strip() != ''].copy()
    for index, row in df_com_telefone.iterrows():
        nome = row['Nome Completo']
        telefone = re.sub(r'\D', '', str(row['Telefone']))
        if len(telefone) < 10: continue
        mensagem_personalizada = mensagem_padrao.replace("[NOME]", nome.split()[0])
        whatsapp_url = f"https://wa.me/55{telefone}?text={urllib.parse.quote(mensagem_personalizada)}"
        col1, col2 = st.columns([3, 1])
        col1.text(f"{nome} - ({row['Telefone']})")
        col2.link_button("Enviar Mensagem ↗️", whatsapp_url, use_container_width=True)

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
    }
    
    pagina_selecionada = st.sidebar.radio("Escolha uma página:", paginas.keys())
    
    paginas[pagina_selecionada]()

if __name__ == "__main__":
    main()
