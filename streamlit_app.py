import streamlit as st
import datetime

st.set_page_config(page_title="Coleta Rápida", layout="centered")

st.title("📋 Fichas")

st.markdown("Envie a imagem da ficha preenchida (foto ou escaneado)")

uploaded_file = st.file_uploader("Envie o arquivo", type=["jpg", "jpeg", "png", "pdf"])

obs = st.text_area("Observações adicionais (opcional)")

if uploaded_file is not None:
    st.success(f"Arquivo recebido: {uploaded_file.name}")
    if st.button("Enviar"):
        st.info("✅ Dados enviados com sucesso (simulação)")
else:
    st.warning("⚠️ Por favor, envie uma imagem antes de confirmar.")