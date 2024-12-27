from dotenv import load_dotenv
import streamlit as st
import os
from PIL import Image
import google.generativeai as genai
import json
import fitz  # PyMuPDF
from io import BytesIO

# Load environment variables
load_dotenv()

# Configure Google API
genai.configure(api_key=os.getenv("google_api_key"))

# Initialize Streamlit app
st.set_page_config(page_title='Modelo 1.0 Extracción de Facturas', layout='centered')

# Define input prompt for Gemini
input_prompt = """
You are an expert in invoice processing. Given an image or text of an invoice, extract and return key data in JSON format with this structure:

{
  "Número de Factura": "Value",
  "Fecha": "Value",
  "Nombre del Cliente": "Value",
  "Nombre del Proveedor": "Value",
  "Total": "Value",
  "Detalles de Productos": [
    {
      "Codigo Producto": "Value",
      "Descripcion producto": "Value",
      "Cantidad": "Value"
    }
  ]
}

If any data is missing, use `null`. Double-check product codes if necessary.
"""

# Function to get response from Gemini
def get_gemini_response(input_prompt, content):
    try:
        response = genai.generate_text(input_prompt, content=content)
        return response.text
    except Exception as e:
        st.error(f"Error communicating with Gemini: {e}")
        return None

# Function to process uploaded images
def process_image(image_data):
    try:
        image_bytes = image_data.getvalue()
        image_parts = [{"mime_type": "image/png", "data": image_bytes}]
        return image_parts
    except Exception as e:
        st.error(f"Error processing image: {e}")
        return None

# Function to process PDF files
def process_pdf(uploaded_file):
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        text_content = ""
        for page in doc:
            text_content += page.get_text("text")
        if text_content.strip():
            return {"type": "text", "content": text_content}
        else:
            images = []
            for page in doc:
                pix = page.get_pixmap()
                images.append({"mime_type": "image/png", "data": pix.tobytes("png")})
            return {"type": "image", "content": images}
    except Exception as e:
        st.error(f"Error processing PDF: {e}")
        return None

# Helper to extract JSON from Gemini's response
def extract_json(response_text):
    try:
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}")
        if start_idx != -1 and end_idx != -1:
            return json.loads(response_text[start_idx:end_idx + 1])
        else:
            raise ValueError("No valid JSON found in response.")
    except Exception as e:
        st.error(f"Error extracting JSON: {e}")
        return None

# Main application
st.title('Modelo 1.0 Extracción de Facturas')
st.write("Procesa facturas en imágenes o PDFs y extrae información clave.")

# File upload
uploaded_file = st.file_uploader("Sube una factura (imagen o PDF)", type=["pdf", "png", "jpg", "jpeg"])
if uploaded_file:
    try:
        if uploaded_file.type.startswith("image/"):
            image_data = process_image(uploaded_file)
            if image_data:
                response = get_gemini_response(input_prompt, content=image_data)
                if response:
                    invoice_data = extract_json(response)
                    if invoice_data:
                        st.subheader("Datos extraídos")
                        st.json(invoice_data, expanded=False)
        elif uploaded_file.type == "application/pdf":
            pdf_content = process_pdf(uploaded_file)
            if pdf_content:
                if pdf_content["type"] == "text":
                    response = get_gemini_response(input_prompt, content=pdf_content["content"])
                else:
                    response = get_gemini_response(input_prompt, content=pdf_content["content"])
                if response:
                    invoice_data = extract_json(response)
                    if invoice_data:
                        st.subheader("Datos extraídos")
                        st.json(invoice_data, expanded=False)
    except Exception as e:
        st.error(f"Error: {e}")
