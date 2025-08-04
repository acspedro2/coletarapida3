import streamlit as st
import gspread
import pandas as pd
import json
import os

# 1. Obter as credenciais e a ID da planilha das variáveis de ambiente do Render
try:
    # O conteúdo do JSON da conta de serviço é lido como uma string
    credenciais_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_CREDENTIALS")
    credenciais = json.loads(credenciais_json)

    # A ID da planilha também é uma variável de ambiente
    planilha_id = os.environ.get("GOOGLE_SHEETS_ID")

except (json.JSONDecodeError, KeyError) as e:
    st.error("Erro ao carregar as credenciais ou a ID da planilha. Verifique as variáveis de ambiente no Render.")
    st.stop()

# 2. Autenticar e conectar à planilha
try:
    gc = gspread.service_account_from_dict(credenciais)
    planilha = gc.open_by_key(planilha_id).sheet1
except gspread.exceptions.APIError as e:
    st.error(f"Erro de autenticação com a API do Google Sheets. Verifique as permissões da conta de serviço. Detalhes do erro: {e}")
    st.stop()
except Exception as e:
    st.error(f"Não foi possível conectar à planilha. Verifique se a ID está correta e se a planilha existe. Detalhes do erro: {e}")
    st.stop()


st.title("Aplicativo de Coleta")

with st.form("meu_formulario"):
    nome = st.text_input("Nome")
    uploaded_file = st.file_uploader("Envie uma imagem", type=['png', 'jpg', 'jpeg'])
    
    submitted = st.form_submit_button("Salvar")
    
    if submitted:
        if nome and uploaded_file is not None:
            # 3. Salvar a imagem localmente (adaptação para Render/Glitch/Replit)
            try:
                # O caminho da pasta para salvar as imagens
                caminho_imagens = "imagens_salvas"
                if not os.path.exists(caminho_imagens):
                    os.makedirs(caminho_imagens)
                
                # Caminho completo do arquivo
                caminho_completo = os.path.join(caminho_imagens, uploaded_file.name)
                
                # Salva o arquivo
                with open(caminho_completo, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                st.success(f"Imagem '{uploaded_file.name}' salva com sucesso!")
                
                # 4. Adicionar os dados à planilha
                nova_linha = [nome, uploaded_file.name]
                planilha.append_row(nova_linha)
                
                st.success("Dados enviados para a planilha!")
            
            except Exception as e:
                st.error(f"Ocorreu um erro ao salvar a imagem ou adicionar os dados na planilha. Erro: {e}")
        else:
            st.warning("Por favor, preencha o nome e envie uma imagem.")

