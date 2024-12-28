import toml
import google.generativeai as genai
import psycopg2
from sqlalchemy import create_engine
import asyncio
import fitz  # PyMuPDF
import streamlit as st
import json
import requests  # Asegúrate de importar requests

# Cargar la configuración desde el archivo TOML
def load_config():
    config = toml.load("config.toml")
    return config

# Cargar configuración
config = load_config()

# Configurar la API de Gemini
genai.configure(api_key=config["gemini"]["api_key"])

# Función para obtener la respuesta de Gemini
def get_gemini_response(prompt, text=None, image=None):
    try:
        if text:
            response = genai.generate_text(prompt=prompt, input_text=text)
        elif image:
            response = genai.generate_text(prompt=prompt, input_image=image)
        else:
            raise ValueError("Debe proporcionar texto o imagen para procesar.")
        return response.text
    except Exception as e:
        raise ValueError(f"Error al obtener la respuesta de Gemini: {e}")

# Función para obtener la conexión a PostgreSQL usando psycopg2
def get_postgresql_connection():
    try:
        connection = psycopg2.connect(
            host=config["database"]["host"],
            port=config["database"]["port"],
            user=config["database"]["user"],
            password=config["database"]["password"],
            database=config["database"]["name"]
        )
        return connection
    except Exception as e:
        st.error(f"Error de conexión a la base de datos PostgreSQL: {e}")
        return None

# Función para establecer la conexión con MySQL usando SQLAlchemy
def get_mysql_connection():
    try:
        engine = create_engine(
            f"mysql+pymysql://{config['database']['user']}:{config['database']['password']}@{config['database']['host']}:{config['database']['port']}/{config['database']['name']}"
        )
        return engine.connect()
    except Exception as e:
        st.error(f"Error de conexión a MySQL: {e}")
        return None

# Función para procesar el archivo PDF
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
        raise ValueError(f"Error al procesar el archivo PDF: {e}")

# Función para extraer JSON de la respuesta de Gemini
def extract_json_from_response(response_text):
    try:
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            json_data = response_text[start_idx:end_idx + 1]
            return json.loads(json_data)
        else:
            raise ValueError("JSON no encontrado en la respuesta.")
    except Exception as e:
        raise ValueError(f"Error al analizar JSON: {e}")

# Función para guardar los datos de la factura en la base de datos
async def save_invoice_data(invoice_data):
    connection = await get_postgresql_connection()
    if connection is None:
        raise Exception("No se pudo establecer la conexión a la base de datos.")
    try:
        cursor = connection.cursor()
        for product in invoice_data['Detalles de Productos']:
            # Verificar si la factura ya está registrada
            cursor.execute(
                """SELECT 1 FROM facturas WHERE invoice_number = %s AND product_code = %s LIMIT 1;""",
                (invoice_data['Número de Factura'], product['Codigo Producto'])
            )
            if cursor.fetchone():
                continue  # No insertar si ya existe
            cursor.execute(
                """INSERT INTO facturas (invoice_number, date, client_name, provider_name, total, product_code, product_description, product_quantity)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);""",
                (invoice_data['Número de Factura'], invoice_data['Fecha'], invoice_data['Nombre del Cliente'],
                 invoice_data['Nombre del Proveedor'], str(invoice_data['Total']),
                 product['Codigo Producto'], product['Descripcion producto'], product['Cantidad'])
            )
        connection.commit()
    except Exception as e:
        raise Exception(f"Error al guardar los datos en la base de datos: {e}")
    finally:
        connection.close()

# Función para manejar el procesamiento de la factura de forma asíncrona
def handle_invoice_processing(invoice_data):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(save_invoice_data(invoice_data))
    loop.close()

# Configuración de la interfaz de Streamlit
st.set_page_config(page_title='Modelo 1.0 Extracción de Facturas', layout='centered')

# Limitar el ancho de la página
st.markdown("""<style>.reportview-container {max-width: 1000px; margin: 0 auto;}</style>""", unsafe_allow_html=True)

# Mensaje de bienvenida y título
st.title('Modelo 1.0 Extracción de Facturas')
st.write("Extrae la información de la factura utilizando este modelo basado en Gemini 1.5 Flash y guarda los datos en PostgreSQL.")

# Recomendación de calidad
st.markdown("""<p style="color:red; font-size:16px;"><strong>Importante:</strong> Los resultados pueden no ser 100% precisos con imágenes de baja calidad. Siempre usa imágenes de alta resolución o PDFs con texto seleccionable para obtener los mejores resultados.</p>""", unsafe_allow_html=True)

# Cargar archivo
uploaded_file = st.file_uploader("Sube una imagen o PDF de factura...", type=["jpg", "jpeg", "png", "pdf"])

if uploaded_file is not None:
    pdf_info = process_pdf_file(uploaded_file)
    if pdf_info["type"] == "image":
        st.sidebar.image(pdf_info["content"][0]['data'], caption="Imagen extraída del PDF.", use_container_width=True)
    else:
        st.sidebar.text_area("Texto extraído del PDF", pdf_info["content"], height=200)

# Procesar la factura
submit = st.button('Procesar Factura')

if submit:
    try:
        input_prompt = """
        Eres un experto en procesamiento de facturas. Dado una imagen o texto de una factura, extrae y devuelve los datos clave en formato JSON con esta estructura:

        {
          "Número de Factura": "Valor",
          "Fecha": "Valor",
          "Nombre del Cliente": "Valor",
          "Nombre del Proveedor": "Valor",
          "Total": "Valor",
          "Detalles de Productos": [
            {
              "Codigo Producto": "Valor",
              "Descripcion producto": "Valor",
              "Cantidad": "Valor"
            }
          ]
        }

        Si falta algún dato, usa `null`. Revisa los códigos de producto si es necesario.
        """

        if pdf_info["type"] == "text":
            response = get_gemini_response(input_prompt, text=pdf_info["content"])
        else:
            response = get_gemini_response(input_prompt, image=pdf_info["content"])

        invoice_data = extract_json_from_response(response)

        st.subheader("Datos Extraídos")
        st.json(invoice_data, expanded=False)

        handle_invoice_processing(invoice_data)
        st.success("Datos de la factura guardados con éxito en la base de datos.")
    except Exception as e:
        st.error(f"Error: {e}")

# Pie de página
st.markdown("""<p style="font-size:20px; text-align:center; color: gray;">Modelo entrenado por Lucas Gnemmi. El uso comercial está prohibido.</p>""", unsafe_allow_html=True)
