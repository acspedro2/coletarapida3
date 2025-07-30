import streamlit as st
from datetime import datetime
import os
import uuid
import time # Para simular atrasos com st.spinner e st.progress

st.set_page_config(page_title="Coleta Rápida", layout="centered", initial_sidebar_state="collapsed")

# Inicialização do session_state para resetar o formulário
if 'file_uploader_key' not in st.session_state:
    st.session_state.file_uploader_key = 0
if 'form_submitted' not in st.session_state:
    st.session_state.form_submitted = False

st.header("📋 Coleta Rápida de Fichas")
st.subheader("Envie imagens de fichas preenchidas de forma ágil.")

st.write("---") # Linha divisória para organização

# Campo para o nome/ID da ficha
nome_ficha = st.text_input(
    "Nome ou ID da Ficha:",
    placeholder="Ex: Ficha Cliente 001, Pedido 12345"
)

# Seleção de tipo de ficha
tipos_ficha = ["Selecione um tipo", "Ficha de Cliente", "Ficha de Produto", "Ficha de Serviço", "Outro"]
tipo_ficha_selecionado = st.selectbox("Tipo de Ficha:", tipos_ficha)

# Data da ficha
data_ficha = st.date_input("Data da Ficha:", datetime.now().date())

st.write("---") # Outra linha divisória

st.markdown("### 🖼️ Anexar Imagem da Ficha")
st.write("Envie a imagem da ficha preenchida (foto ou escaneado):")

uploaded_file = st.file_uploader(
    "Selecione o arquivo",
    type=["jpg", "jpeg", "png", "pdf"],
    key=f"file_uploader_{st.session_state.file_uploader_key}" # Usa key para permitir reset
)

observacoes = st.text_area("Observações adicionais (opcional):", placeholder="Qualquer informação extra sobre a ficha...")

temp_file_path = None

if uploaded_file:
    # Gera um nome de arquivo único
    file_extension = os.path.splitext(uploaded_file.name)[1]
    unique_filename = f"temp_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex}{file_extension}"
    temp_file_path = os.path.join("uploaded_files", unique_filename) # Salva em uma subpasta

    # Cria a pasta 'uploaded_files' se não existir
    os.makedirs("uploaded_files", exist_ok=True)

    try:
        with open(temp_file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        st.success("✅ Arquivo carregado com sucesso!")
        st.image(uploaded_file, width=300, caption=f"Pré-visualização de: {uploaded_file.name}")
    except Exception as e:
        st.error(f"❌ Erro ao salvar o arquivo: {e}")
        temp_file_path = None # Reseta se o salvamento falhou

st.write("---")

col1, col2 = st.columns(2) # Usando colunas para organizar os botões

with col1:
    if st.button("Enviar Ficha", type="primary"):
        if not nome_ficha:
            st.warning("⚠️ Por favor, preencha o **Nome ou ID da Ficha**.")
        elif tipo_ficha_selecionado == "Selecione um tipo":
            st.warning("⚠️ Por favor, selecione um **Tipo de Ficha**.")
        elif not uploaded_file:
            st.warning("⚠️ Por favor, envie uma **imagem** da ficha antes de confirmar.")
        elif temp_file_path:
            # Barra de progresso e spinner
            progress_bar = st.progress(0)
            status_text = st.empty()

            with st.spinner("🚀 Enviando dados e processando..."):
                for percent_complete in range(100):
                    time.sleep(0.02) # Pequeno atraso para visualização da barra
                    progress_bar.progress(percent_complete + 1)
                    status_text.text(f"Progresso: {percent_complete + 1}%")

                try:
                    # --- Aqui é onde seu processamento de backend real entraria ---
                    # Você usaria os dados coletados: nome_ficha, tipo_ficha_selecionado, data_ficha, observacoes, temp_file_path
                    # Ex: Salvar em um banco de dados, enviar para um serviço de OCR, mover para armazenamento em nuvem

                    st.success("🎉 Ficha e dados enviados com sucesso!")
                    st.balloons() # Efeito visual de celebração
                    st.session_state.form_submitted = True # Marca que o formulário foi enviado

                    # Opcional: limpar o arquivo temporário após o processamento bem-sucedido
                    if os.path.exists(temp_file_path):
                        os.remove(temp_file_path)
                        # print(f"Arquivo temporário limpo: {temp_file_path}")

                except Exception as e:
                    st.error(f"❌ Erro ao enviar os dados: {e}")
                finally:
                    progress_bar.empty() # Limpa a barra de progresso
                    status_text.empty() # Limpa o texto de status
        else:
            st.warning("⚠️ Erro: O arquivo não pôde ser processado para envio.")

with col2:
    # Botão para limpar o formulário
    if st.button("Limpar Formulário"):
        st.session_state.file_uploader_key += 1 # Incrementa a key para resetar o uploader
        st.session_state.form_submitted = False # Reseta o estado de submissão
        # Para resetar text_input, selectbox e date_input, o ideal é recarregar a página
        # ou usar lógica mais complexa com st.session_state para cada campo
        st.rerun() # Recarrega o app para limpar os campos

if st.session_state.form_submitted:
    st.info("Para enviar uma nova ficha, clique em 'Limpar Formulário' acima.")

st.write("---")
st.markdown("_Desenvolvido com Streamlit_")

