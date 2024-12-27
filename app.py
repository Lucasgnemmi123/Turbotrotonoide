from dotenv import load_dotenv
import streamlit as st
import os
from PIL import Image
import google.generativeai as genai
import json
import asyncpg  # type: ignore
import asyncio
import fitz  # PyMuPDF
from io import BytesIO

# Load environment variables
load_dotenv()

# Configure Google API
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

# Configure Gemini Model
model = genai.GenerativeModel('gemini-1.5-flash')

# Function to get response from Gemini
def get_gemini_response(input_prompt, content):
    try:
        response = model.generate_content([input_prompt, content])
        return response.text
    except Exception as e:
        raise ValueError(f"Error with Gemini API: {e}")

# Function to handle uploaded image details
def process_image(uploaded_file):
    try:
        bytes_data = uploaded_file.read()
        return [{"mime_type": uploaded_file.type, "data": bytes_data}]
    except Exception as e:
        raise ValueError(f"Error processing image: {e}")

# Function to process PDF files
def process_pdf(uploaded_file):
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        pdf_text = "".join(page.get_text("text") for page in doc)

        if pdf_text.strip():
            return {"type": "text", "content": pdf_text}
        else:
            images = [
                {"mime_type": "image/png", "data": page.get_pixmap().tobytes("png")}
                for page in doc
            ]
            return {"type": "image", "content": images}
    except Exception as e:
        raise ValueError(f"Error processing PDF: {e}")

# Function to extract JSON from Gemini's response
def extract_json(response_text):
    try:
        start_idx, end_idx = response_text.find('{'), response_text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            return json.loads(response_text[start_idx:end_idx + 1])
        raise ValueError("JSON not found in the response.")
    except Exception as e:
        raise ValueError(f"Error extracting JSON: {e}")

# Function to establish a database connection
async def get_db_connection():
    try:
        return await asyncpg.connect(
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT")
        )
    except Exception as e:
        raise ConnectionError(f"Database connection error: {e}")

# Function to save invoice data in the database
async def save_invoice_data(invoice_data):
    conn = await get_db_connection()
    try:
        for product in invoice_data['Detalles de Productos']:
            existing_entry = await conn.fetchval(
                """SELECT 1 FROM facturas WHERE invoice_number = $1 AND product_code = $2 LIMIT 1;""",
                invoice_data['Número de Factura'], product['Codigo Producto']
            )
            if not existing_entry:
                await conn.execute(
                    """INSERT INTO facturas (invoice_number, date, client_name, provider_name, total, product_code, product_description, product_quantity)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8);""",
                    invoice_data['Número de Factura'], invoice_data['Fecha'], invoice_data['Nombre del Cliente'],
                    invoice_data['Nombre del Proveedor'], str(invoice_data['Total']),
                    product['Codigo Producto'], product['Descripcion producto'], product['Cantidad']
                )
    except Exception as e:
        raise Exception(f"Error saving data: {e}")
    finally:
        await conn.close()

# Function to handle asynchronous database operations
def handle_database_operations(invoice_data):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(save_invoice_data(invoice_data))
    loop.close()

# Function to process the uploaded file and get Gemini's response
def process_uploaded_file(uploaded_file, is_pdf=False):
    try:
        input_prompt = (
            """
            Extract the following data from the invoice in JSON format:
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
            Use `null` for missing data.
            """
        )

        if uploaded_file.type.startswith("image/"):
            image_parts = process_image(uploaded_file)
            response = get_gemini_response(input_prompt, image_parts[0])
        elif is_pdf:
            pdf_data = process_pdf(uploaded_file)
            if pdf_data['type'] == "text":
                response = get_gemini_response(input_prompt, pdf_data['content'])
            else:
                response = get_gemini_response(input_prompt, pdf_data['content'][0])

        return extract_json(response)
    except Exception as e:
        st.error(f"Error: {e}")
        return None

# Streamlit app
st.set_page_config(page_title='Modelo 1.0 - Extracción de Facturas', layout='centered')

st.title('Modelo 1.0 - Extracción de Facturas')
st.write("Extrae información de facturas y guárdala en PostgreSQL utilizando Gemini 1.5 Flash.")

# Layout with camera and file upload
col1, col2 = st.columns(2)

with col1:
    camera_capture = st.camera_input("Captura una imagen")
    if camera_capture:
        try:
            image = Image.open(camera_capture)
            st.image(image, caption="Imagen capturada", use_column_width=True)

            buffered = BytesIO()
            image.save(buffered, format="PNG")
            image_bytes = buffered.getvalue()

            invoice_data = process_uploaded_file(camera_capture)
            if invoice_data:
                st.subheader("Datos Extraídos")
                st.json(invoice_data)
                handle_database_operations(invoice_data)
                st.success("Datos guardados en la base de datos.")
        except Exception as e:
            st.error(f"Error: {e}")

with col2:
    uploaded_file = st.file_uploader("Sube un archivo de factura", type=["pdf", "png", "jpg", "jpeg"])
    if uploaded_file:
        try:
            invoice_data = process_uploaded_file(uploaded_file, is_pdf=(uploaded_file.type == "application/pdf"))
            if invoice_data:
                st.subheader("Datos Extraídos")
                st.json(invoice_data)
                handle_database_operations(invoice_data)
                st.success("Datos guardados en la base de datos.")
        except Exception as e:
            st.error(f"Error: {e}")
