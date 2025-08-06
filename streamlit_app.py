import streamlit as st
import gspread
import pandas as pd
import json
import os
import datetime

# --- Configuração da Página e Título ---
st.set_page_config(
    page_title="Aplicativo de Coleta Rápida",
    page_icon=":camera:",
    layout="centered"
)

# --- Conexão com o Google Sheets ---
try:
    credenciais_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_CREDENTIALS")
    planilha_id = os.environ.get("GOOGLE_SHEETS_ID")

    if not credenciais_json or not planilha_id:
        st.error("Erro de configuração: As variáveis de ambiente GOOGLE_SERVICE_ACCOUNT_CREDENTIALS ou GOOGLE_SHEETS_ID não foram encontradas.")
        st.stop()

    credenciais = json.loads(credenciais_json)
    gc = gspread.service_account_from_dict(credenciais)
    planilha = gc.open_by_key(planilha_id).sheet1 
except Exception as e:
    st.error(f"Erro ao conectar com o Google Sheets. Por favor, verifique as credenciais e as permissões da planilha. Erro: {e}")
    st.stop()

# --- Estrutura da Página ---
st.title("Aplicativo de Coleta Rápida")
st.markdown("---")

with st.form("formulario_coleta", clear_on_submit=True):
    st.header("Insira os dados da família")

    # Layout com colunas
    col1, col2 = st.columns(2)
    with col1:
        id_familia = st.text_input("ID Família (Ex: FAM001)", key="id_familia")
    with col2:
        nome_completo = st.text_input("Nome Completo", key="nome_completo")
    
    data_nascimento = st.date_input("Data de Nascimento", key="data_nascimento")

    st.markdown("---")
    st.subheader("Envie a Foto")
    uploaded_file = st.file_uploader("Escolha uma imagem", type=['png', 'jpg', 'jpeg'], key="uploaded_file")

    # Pré-visualização da imagem
    if uploaded_file is not None:
        # AQUI ESTÁ A ALTERAÇÃO: use_container_width no lugar de use_column_width
        st.image(uploaded_file, caption="Pré-visualização", use_container_width=True)
    
    st.markdown("---")
    submitted = st.form_submit_button("Salvar Dados na Planilha")
    
    if submitted:
        if id_familia and nome_completo and uploaded_file is not None:
            # Salvar a imagem localmente (adaptação para Render)
            try:
                caminho_imagens = "imagens_salvas"
                if not os.path.exists(caminho_imagens):
                    os.makedirs(caminho_imagens)
                
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                nome_unico_arquivo = f"{id_familia}_{timestamp}_{uploaded_file.name}"
                caminho_completo = os.path.join(caminho_imagens, nome_unico_arquivo)
                
                with open(caminho_completo, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                st.success(f"Imagem salva como '{nome_unico_arquivo}'!")
                
            except Exception as e:
                st.error(f"Ocorreu um erro ao salvar a imagem. Por favor, tente novamente. Erro: {e}")
                st.stop()
            
            # Adicionar os dados à planilha
            try:
                nova_linha = [
                    id_familia,
                    nome_completo,
                    data_nascimento.strftime("%d/%m/%Y"),
                    nome_unico_arquivo
                ]
                
                planilha.append_row(nova_linha)
                
                st.success("Dados enviados para a planilha com sucesso!")
                
            except Exception as e:
                st.error(f"Ocorreu um erro ao adicionar os dados na planilha. Verifique as permissões. Erro: {e}")
                
        else:
            st.warning("Por favor, preencha todos os campos obrigatórios e envie uma imagem.")

