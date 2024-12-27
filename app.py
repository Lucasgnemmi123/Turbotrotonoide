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
genai.configure(api_key=os.getenv("google_api_key"))

# Configure Gemini Model
model = genai.GenerativeModel('gemini-1.5-flash')

# Function to get response from Gemini
def get_gemini_response(input_prompt, image=None, text=None):
    if text:
        response = model.generate_content([input_prompt, text])
    elif image:
        response = model.generate_content([input_prompt, image[0]])
    return response.text

# Function to handle uploaded image details
def input_image_details(uploaded_file):
    if uploaded_file is not None:
        bytes_data = uploaded_file.read()
        image_parts = [{"mime_type": uploaded_file.type, "data": bytes_data}]
        return image_parts
    else:
        raise FileNotFoundError("No file uploaded.")

# Function to process PDF files
def process_pdf_file(uploaded_file):
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        pdf_text = ""
        for page_number in range(len(doc)):
            page = doc[page_number]
            pdf_text += page.get_text("text")

        if pdf_text.strip():
            return {"type": "text", "content": pdf_text}
        else:
            images = []
            for page_number in range(len(doc)):
                page = doc[page_number]
                pix = page.get_pixmap()
                image_data = pix.tobytes("png")
                images.append({"mime_type": "image/png", "data": image_data})
            return {"type": "image", "content": images}
    except Exception as e:
        raise ValueError(f"Error processing the PDF file: {e}")

# Function to extract JSON from Gemini's response
def extract_json_from_response(response_text):
    try:
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            json_data = response_text[start_idx:end_idx + 1]
            return json.loads(json_data)
        else:
            raise ValueError("JSON not found in the response.")
    except Exception as e:
        raise ValueError(f"Error parsing JSON: {e}")

# Function to establish a database connection
async def get_db_connection():
    try:
        conn = await asyncpg.connect(
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
            host=os.getenv("DB_HOST"),
            port=os.getenv("DB_PORT")
        )
        return conn
    except Exception as e:
        st.error(f"Database connection error: {e}")
        return None

# Function to save invoice data in the database
async def save_invoice_data(invoice_data):
    conn = await get_db_connection()
    if conn is None:
        raise Exception("Could not establish a database connection.")
    try:
        for product in invoice_data['Detalles de Productos']:
            existing_entry = await conn.fetchval(
                """SELECT 1 FROM facturas WHERE invoice_number = $1 AND product_code = $2 LIMIT 1;""",
                invoice_data['Número de Factura'], product['Codigo Producto']
            )
            if existing_entry:
                continue
            await conn.execute(
                """INSERT INTO facturas (invoice_number, date, client_name, provider_name, total, product_code, product_description, product_quantity)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8);""",
                invoice_data['Número de Factura'], invoice_data['Fecha'], invoice_data['Nombre del Cliente'],
                invoice_data['Nombre del Proveedor'], str(invoice_data['Total']),
                product['Codigo Producto'], product['Descripcion producto'], product['Cantidad']
            )
    except Exception as e:
        raise Exception(f"Error saving data to the database: {e}")
    finally:
        await conn.close()

# Function to handle asynchronous processing in Streamlit
def handle_invoice_processing(invoice_data):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(save_invoice_data(invoice_data))
    loop.close()

# Helper function to process the file and get Gemini's response
def process_and_get_invoice_data(uploaded_file=None, image_data=None, is_pdf=False):
    try:
        if uploaded_file:
            if uploaded_file.type.startswith("image/"):
                image_parts = input_image_details(uploaded_file)
                response = get_gemini_response(input_prompt, image=image_parts)
            elif is_pdf:
                pdf_data = process_pdf_file(uploaded_file)
                if pdf_data['type'] == "text":
                    response = get_gemini_response(input_prompt, text=pdf_data['content'])
                else:
                    response = get_gemini_response(input_prompt, image=pdf_data['content'])
        elif image_data:
            # If image data is provided (e.g., from the camera capture)
            response = get_gemini_response(input_prompt, image=image_data)

        # Extract JSON from the response
        invoice_data = extract_json_from_response(response)
        return invoice_data
    except Exception as e:
        st.error(f"Error: {e}")
        return None

# Initialize Streamlit app
st.set_page_config(page_title='Modelo 1.0 Extraccion de Facturas', layout='centered')

# Limit page width
st.markdown("""
    <style>
        .reportview-container {
            max-width: 1000px;
            margin: 0 auto;
        }
        .camera-image {
            max-width: 600px;
            margin: 0 auto;
            display: block;
        }
    </style>
""", unsafe_allow_html=True)

# Welcome message and title
st.title('Modelo 1.0 Extraccion de Facturas')
st.write("Extract invoice information using this model based on Gemini 1.5 Flash and save the data in PostgreSQL.")

# Quality recommendation
st.markdown("""
    <p style="color:red; font-size:16px;">
        <strong>Important:</strong> Results may not be 100% accurate with low-quality images. 
        Always use high-resolution images or PDFs with selectable text for best results.
    </p>
""", unsafe_allow_html=True)

# Layout with two options: Camera and File Upload
col1, col2 = st.columns(2)

with col1:
    # Camera capture
    camera_capture = st.camera_input("Capture an image")
    if camera_capture:
        # Display captured image with custom class for styling
        image = Image.open(camera_capture)
        st.image(image, caption="Captured Image", use_column_width=True, class_="camera-image")

        # Process the image with Gemini
        try:
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

            # Convert captured image to bytes for Gemini API
            buffered = BytesIO()
            image.save(buffered, format="PNG")
            image_bytes = buffered.getvalue()

            invoice_data = process_and_get_invoice_data(image_data=[{"mime_type": "image/png", "data": image_bytes}])

            if invoice_data:
                st.subheader("Extracted Data")
                st.json(invoice_data, expanded=False)
                handle_invoice_processing(invoice_data)
                st.success("Invoice data successfully saved to the database.")
        except Exception as e:  
            st.error(f"Error: {e}")

with col2:
    # File upload
    uploaded_file = st.file_uploader("Upload an invoice file", type=["pdf", "png", "jpg", "jpeg"])
    if uploaded_file:
        if uploaded_file.type.startswith("image/"):
            invoice_data = process_and_get_invoice_data(uploaded_file=uploaded_file)
        elif uploaded_file.type == "application/pdf":
            invoice_data = process_and_get_invoice_data(uploaded_file=uploaded_file, is_pdf=True)

        if invoice_data:
            st.subheader("Extracted Data")
            st.json(invoice_data, expanded=False)
            handle_invoice_processing(invoice_data)
            st.success("Invoice data successfully saved to the database.")
