import toml
import streamlit as st
from PIL import Image
import google.generativeai as genai
import json
import asyncpg  # type: ignore
import asyncio
import fitz  # PyMuPDF

# Cargar configuraciones desde config.toml
config = toml.load("config.toml")

# Configuración de Gemini API
genai.configure(api_key=config["gemini"]["api_key"])

# Configurar el modelo Gemini
model = genai.GenerativeModel('gemini-1.5-flash')

# Función para obtener respuesta de Gemini
def get_gemini_response(input_prompt, image=None, text=None):
    try:
        if text:
            response = model.generate_content([input_prompt, text])
        elif image:
            response = model.generate_content([input_prompt, image[0]])
        return response.text
    except Exception as e:
        raise ValueError(f"Error al obtener respuesta de Gemini: {e}")

# Función para manejar los detalles de la imagen cargada
def input_image_details(uploaded_file):
    if uploaded_file:
        bytes_data = uploaded_file.read()
        image_parts = [{"mime_type": uploaded_file.type, "data": bytes_data}]
        return image_parts
    else:
        raise FileNotFoundError("No se ha cargado ningún archivo.")

# Función para procesar archivos PDF
def process_pdf_file(uploaded_file):
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        pdf_text = ""
        for page in doc:
            pdf_text += page.get_text("text")

        if pdf_text.strip():
            return {"type": "text", "content": pdf_text}
        else:
            images = [{"mime_type": "image/png", "data": page.get_pixmap().tobytes("png")} for page in doc]
            return {"type": "image", "content": images}
    except Exception as e:
        raise ValueError(f"Error procesando el archivo PDF: {e}")

# Función para extraer JSON de la respuesta de Gemini
def extract_json_from_response(response_text):
    try:
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}')
        if start_idx != -1 and end_idx != -1:
            json_data = response_text[start_idx:end_idx + 1]
            return json.loads(json_data)
        else:
            raise ValueError("No se encontró JSON en la respuesta.")
    except Exception as e:
        raise ValueError(f"Error al analizar JSON: {e}")

# Función para establecer conexión con la base de datos
async def get_db_connection():
    try:
        conn = await asyncpg.connect(
            user=config["database"]["user"],
            password=config["database"]["password"],
            database=config["database"]["name"],  # Ajustado para coincidir con el archivo .toml
            host=config["database"]["host"],
            port=int(config["database"]["port"])
        )
        return conn
    except Exception as e:
        raise ValueError(f"Error de conexión a la base de datos: {e}")

# Función para guardar los datos de la factura en la base de datos
async def save_invoice_data(invoice_data):
    conn = await get_db_connection()
    if not conn:
        raise Exception("No se pudo establecer una conexión con la base de datos.")
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
        raise Exception(f"Error guardando datos en la base de datos: {e}")
    finally:
        await conn.close()

# Función para manejar el procesamiento asincrónico en Streamlit
def handle_invoice_processing(invoice_data):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(save_invoice_data(invoice_data))
    loop.close()

# Inicializar la aplicación Streamlit
st.set_page_config(page_title='Modelo 1.0 Extracción de Facturas', layout='centered')

# Limitar el ancho de la página
st.markdown("""<style>.reportview-container { max-width: 1000px; margin: 0 auto; }</style>""", unsafe_allow_html=True)

# Mensaje de bienvenida y título
st.title('Modelo 1.0 Extracción de Facturas')
st.write("Extrae información de facturas usando este modelo basado en Gemini 1.5 Flash y guarda los datos en PostgreSQL.")

# Recomendación de calidad
st.markdown("""<p style="color:red; font-size:16px;"><strong>Importante:</strong> Los resultados pueden no ser 100% precisos con imágenes de baja calidad.</p>""", unsafe_allow_html=True)

# Cargador de archivos
uploaded_file = st.file_uploader("Sube una imagen o archivo PDF de factura...", type=["jpg", "jpeg", "png", "pdf"])

# Captura de imagen desde la cámara
camera_input = st.camera_input("Captura una imagen desde la cámara")

if camera_input:
    # Si la imagen es tomada con la cámara, se maneja aquí
    st.image(camera_input, caption="Imagen Capturada", use_column_width=True)
    # Puedes procesar la imagen capturada de la misma manera que un archivo cargado

# Si se ha cargado un archivo PDF
if uploaded_file:
    pdf_info = process_pdf_file(uploaded_file)
    if pdf_info["type"] == "image":
        st.sidebar.image(pdf_info["content"][0]['data'], caption="Imagen extraída del PDF.", use_container_width=True)
    else:
        st.sidebar.text_area("Texto extraído del PDF", pdf_info["content"], height=200)

# Botón para procesar la factura
submit = st.button('Procesar Factura')

if submit:
    try:
        input_prompt = """
        Eres un experto en procesamiento de facturas. Dada una imagen o texto de una factura, extrae y devuelve los datos clave en formato JSON con esta estructura:

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

        Si falta algún dato, usa `null`. Verifica los códigos de producto si es necesario.
        """

        # Procesar ya sea texto o imagen
        if pdf_info["type"] == "text":
            response = get_gemini_response(input_prompt, text=pdf_info["content"])
        else:
            response = get_gemini_response(input_prompt, image=pdf_info["content"])

        invoice_data = extract_json_from_response(response)

        st.subheader("Datos Extraídos")
        st.json(invoice_data, expanded=False)

        handle_invoice_processing(invoice_data)
        st.success("Los datos de la factura se guardaron correctamente en la base de datos.")
    except Exception as e:
        st.error(f"Error: {e}")

# Footer
st.markdown("""<p style="font-size:20px; text-align:center; color: gray;">Test model trained by Lucas Gnemmi. Commercial use is prohibited.</p>""", unsafe_allow_html=True)
