import streamlit as st
from datetime import datetime
import os

st.set_page_config(page_title="Coleta Rápida", layout="centered")

st.markdown("## 📋 Fichas")
st.write("Envie a imagem da ficha preenchida (foto ou escaneado)")

uploaded_file = st.file_uploader("Envie o arquivo", type=["jpg", "jpeg", "png", "pdf"])

observacoes = st.text_area("Observações adicionais (opcional)")

if uploaded_file:
    with open(f"temp_{uploaded_file.name}", "wb") as f:
        f.write(uploaded_file.getbuffer())
    st.success("✅ Arquivo carregado com sucesso!")
    st.image(uploaded_file, width=300)

    if st.button("Enviar"):
        # Aqui você pode colocar o processamento real
        st.success("📥 Dados enviados com sucesso!")
        # Opcional: limpar o arquivo temporário
        os.remove(f"temp_{uploaded_file.name}")
else:
    st.warning("⚠️ Por favor, envie uma imagem antes de confirmar.")
