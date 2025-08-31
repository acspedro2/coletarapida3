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
from io import BytesIO
from dateutil.relativedelta import relativedelta
from pdf2image import convert_from_bytes

# --- CONFIGURAÇÕES E CLIENTES (INICIALIZAÇÃO) ---
try:
    # Inicializa o cliente da API Cohere usando a chave dos segredos
    cohere_client = cohere.Client(st.secrets["COHERE_API_KEY"])
except Exception as e:
    st.error(f"Erro ao inicializar o cliente Cohere. Verifique os segredos: {e}")
    cohere_client = None

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

# --- FUNÇÕES DE VALIDAÇÃO E UTILITÁRIAS ---
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

# --- FUNÇÕES DE GERAÇÃO DE DOCUMENTOS (OTIMIZADAS) ---

def gerar_capa_prontuario_pdf(dados_paciente):
    """Gera PDF da capa do prontuário, importando a biblioteca sob demanda."""
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import cm

        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        largura, altura = A4

        c.setFont("Helvetica-Bold", 18)
        c.drawCentredString(largura / 2, altura - 2 * cm, "Capa de Prontuário")
        c.line(2 * cm, altura - 2.5 * cm, largura - 2 * cm, altura - 2.5 * cm)

        c.setFont("Helvetica", 12)
        y = altura - 4 * cm
        c.drawString(3 * cm, y, f"Nome Completo: {dados_paciente.get('nome', '')}")
        y -= 1 * cm
        c.drawString(3 * cm, y, f"Data de Nascimento: {dados_paciente.get('data_nasc', '')}")
        y -= 1 * cm
        c.drawString(3 * cm, y, f"CPF: {dados_paciente.get('cpf', '')}")
        y -= 1 * cm
        c.drawString(3 * cm, y, f"Nome da Mãe: {dados_paciente.get('mae', '')}")
        y -= 1 * cm
        c.drawString(3 * cm, y, f"CNS: {dados_paciente.get('cns', '')}")

        c.showPage()
        c.save()
        buffer.seek(0)
        return buffer
    except Exception as e:
        st.error(f"Erro ao gerar o PDF: {e}")
        return None

def gerar_qrcode_imagem(dados_para_qr):
    """Gera uma imagem PNG de um QR Code, importando a biblioteca sob demanda."""
    try:
        import qrcode
        
        qr_img = qrcode.make(dados_para_qr)
        qr_buffer = BytesIO()
        qr_img.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)
        return qr_buffer
    except Exception as e:
        st.error(f"Erro ao gerar QR Code: {e}")
        return None

# --- INTERFACE PRINCIPAL ---
def main():
    st.set_page_config(page_title="Coleta Inteligente", page_icon="🤖", layout="wide")
    st.title("Coleta Inteligente e Geração de Documentos")

    with st.form("coleta_form"):
        st.header("Coleta de Dados do Paciente")
        nome = st.text_input("Nome Completo")
        data_nasc = st.text_input("Data de Nascimento (DD/MM/AAAA)")
        cpf = st.text_input("CPF")
        nome_mae = st.text_input("Nome da Mãe")
        cns = st.text_input("Cartão Nacional de Saúde (CNS)")
        
        submitted = st.form_submit_button("Salvar Paciente")
        if submitted:
            # A lógica para salvar os dados na sua planilha Google entraria aqui
            st.success(f"Paciente {nome} salvo com sucesso! (Simulação)")

    st.divider()
    st.header("Gerar Documentos")
    
    # Geração da Capa do Prontuário
    if st.button("Gerar Capa de Prontuário em PDF"):
        if nome:
            with st.spinner("A gerar PDF..."):
                dados_paciente = {"nome": nome, "data_nasc": data_nasc, "cpf": cpf, "mae": nome_mae, "cns": cns}
                pdf_buffer = gerar_capa_prontuario_pdf(dados_paciente)
                if pdf_buffer:
                    st.success("PDF da capa gerado!")
                    st.download_button(
                        label="Baixar Capa do Prontuário", data=pdf_buffer,
                        file_name=f"capa_prontuario_{nome.replace(' ', '_').lower()}.pdf", mime="application/pdf"
                    )
        else:
            st.warning("Preencha o nome do paciente no formulário acima.")

    st.divider()
    
    # Gerador de Etiqueta QR Code
    st.header("Gerador de Etiqueta QR Code")
    
    sugestao_dados = f"Nome: {nome}\nCPF: {cpf}\nNasc: {data_nasc}"
    dados_qr = st.text_area("Dados para incluir no QR Code:", value=sugestao_dados, height=100)

    if st.button("Gerar Imagem do QR Code"):
        if dados_qr:
            with st.spinner("A gerar QR Code..."):
                qr_buffer = gerar_qrcode_imagem(dados_qr)
                if qr_buffer:
                    st.success("QR Code gerado!")
                    st.image(qr_buffer)
                    st.download_button(
                        label="Baixar Imagem QR Code", data=qr_buffer,
                        file_name=f"qrcode_{nome.replace(' ', '_').lower()}.png", mime="image/png"
                    )
        else:
            st.warning("Insira os dados que você quer incluir no QR Code.")

# --- Ponto de Entrada da Aplicação ---
if __name__ == "__main__":
    main()

