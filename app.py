
import streamlit as st
from PIL import Image
import datetime

st.set_page_config(page_title="Coleta Rápida", layout="centered")

st.title("📄 Upload de Fichas")
st.markdown("Envie a imagem da ficha preenchida (foto ou escaneado)")

uploaded_file = st.file_uploader("Arraste e solte ou clique para selecionar", type=["jpg", "jpeg", "png", "pdf"])

if uploaded_file:
    st.success("Arquivo recebido com sucesso!")
    file_details = {
        "nome": uploaded_file.name,
        "tipo": uploaded_file.type,
        "tamanho": f"{uploaded_file.size / 1024:.2f} KB"
    }
    st.write(file_details)
    if uploaded_file.type.startswith("image/"):
        image = Image.open(uploaded_file)
        st.image(image, caption="Pré-visualização", use_column_width=True)

    # Observações opcionais
    obs = st.text_area("Observações adicionais (opcional)", "")

    if st.button("Enviar"):
        st.success("📤 Dados enviados (simulação).")
else:
    st.warning("⚠️ Por favor, envie uma imagem antes de confirmar.")
    