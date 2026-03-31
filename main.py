import streamlit as st
import requests
import csv
import io
import time
from datetime import datetime

st.set_page_config(
    page_title="Edicion Masiva de Visitas",
    page_icon="🚚",
    layout="centered",
)

# --- Tema ---
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = False

dark = st.session_state.dark_mode

THEME = {
    "bg": "#0e1117" if dark else "#f5f7fb",
    "text": "#e0e0e0" if dark else "#1a1a1a",
    "label": "#7b8cff" if dark else "#2A2BA1",
    "input_border": "#3a3f4b" if dark else "#e0e3ea",
    "input_bg": "#1a1e2a" if dark else "white",
    "input_text": "#e0e0e0" if dark else "#1a1a1a",
    "uploader_border": "#3a3f4b" if dark else "#d0d5dd",
}

# --- Estilos SimpliRoute ---
st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="st-"] {{
        font-family: 'Inter', sans-serif;
    }}

    #MainMenu, header, footer {{visibility: hidden;}}

    .stApp {{
        background: {THEME["bg"]};
        color: {THEME["text"]};
    }}

    .block-container {{
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
    }}

    /* Header */
    .sr-header {{
        background: linear-gradient(135deg, #2A2BA1 0%, #1a1b6b 100%);
        padding: 1.5rem 2rem 1.2rem 2rem;
        border-radius: 0.8rem;
        text-align: center;
        margin-bottom: 1rem;
    }}
    .sr-header h1 {{
        color: white;
        font-size: 1.5rem;
        font-weight: 700;
        margin: 0;
        letter-spacing: -0.02em;
    }}
    .sr-header p {{
        color: rgba(255,255,255,0.7);
        font-size: 0.85rem;
        margin: 0.2rem 0 0 0;
    }}

    /* Cuenta badge */
    .sr-cuenta {{
        background: linear-gradient(135deg, #29AB55 0%, #1e8a42 100%);
        color: white;
        padding: 0.5rem 1rem;
        border-radius: 0.5rem;
        font-size: 0.85rem;
        font-weight: 500;
        margin-bottom: 0.5rem;
    }}

    /* Stat box */
    .sr-stat {{
        background: linear-gradient(135deg, #369CFF 0%, #2A2BA1 100%);
        color: white;
        padding: 0.8rem 1rem;
        border-radius: 0.6rem;
        text-align: center;
        margin-bottom: 0.5rem;
    }}
    .sr-stat-number {{
        font-size: 1.6rem;
        font-weight: 700;
        line-height: 1;
    }}
    .sr-stat-label {{
        font-size: 0.75rem;
        opacity: 0.85;
        margin-top: 0.15rem;
    }}

    /* Label mini */
    .sr-label {{
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: {THEME["label"]};
        margin-bottom: 0.3rem;
    }}

    /* Solo boton primario con gradiente */
    button[data-testid="stBaseButton-primary"] {{
        background: linear-gradient(135deg, #2A2BA1 0%, #1a1b6b 100%) !important;
        color: white !important;
        border: none !important;
        border-radius: 0.5rem !important;
        padding: 0.6rem 2rem !important;
        font-weight: 600 !important;
        font-size: 0.9rem !important;
        transition: all 0.2s ease !important;
        width: 100% !important;
    }}
    button[data-testid="stBaseButton-primary"]:hover {{
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 12px rgba(42, 43, 161, 0.35) !important;
    }}

    /* Boton toggle tema */
    button[data-testid="stBaseButton-secondary"] {{
        background: {"rgba(255,255,255,0.1)" if dark else "rgba(42,43,161,0.08)"} !important;
        border: none !important;
        border-radius: 50% !important;
        width: 1.8rem !important;
        height: 1.8rem !important;
        min-height: 0 !important;
        padding: 0 !important;
        font-size: 0.8rem !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
    }}
    button[data-testid="stBaseButton-secondary"]:hover {{
        background: {"rgba(255,255,255,0.2)" if dark else "rgba(42,43,161,0.15)"} !important;
        transform: none !important;
        box-shadow: none !important;
    }}

    /* Input fields */
    .stTextInput > div > div > input {{
        border-radius: 0.5rem !important;
        border: 1.5px solid {THEME["input_border"]} !important;
        background: {THEME["input_bg"]} !important;
        color: {THEME["input_text"]} !important;
        padding: 0.6rem 0.8rem !important;
        font-size: 0.9rem !important;
    }}
    .stTextInput > div > div > input:focus {{
        border-color: #2A2BA1 !important;
        box-shadow: 0 0 0 3px rgba(42, 43, 161, 0.15) !important;
    }}

    /* File uploader */
    .stFileUploader > div {{
        border-radius: 0.6rem !important;
        border: 2px dashed {THEME["uploader_border"]} !important;
    }}

    /* Progress bar */
    .stProgress > div > div > div {{
        background: linear-gradient(90deg, #2A2BA1, #369CFF) !important;
        border-radius: 1rem !important;
    }}

    /* Expander */
    .streamlit-expanderHeader {{
        font-size: 0.85rem !important;
        font-weight: 500 !important;
        color: {THEME["label"]} !important;
    }}

    .stElementContainer {{
        margin-bottom: 0.3rem !important;
    }}

    a {{ color: {THEME["label"]} !important; }}
    </style>
    """,
    unsafe_allow_html=True,
)

API_BASE = "https://api.simpliroute.com/v1"


def validar_cuenta(token):
    headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
    response = requests.get(f"{API_BASE}/accounts/me/", headers=headers)
    if response.status_code == 200:
        nombre = response.json().get("account", {}).get("name", "Sin nombre")
        return True, nombre
    return False, None


def enviar_visitas(bloque, token):
    headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
    response = requests.put(f"{API_BASE}/routes/visits/", headers=headers, json=bloque)
    time.sleep(0.5)
    return response.status_code, response.text


def convertir_fecha(fecha_str):
    try:
        return datetime.strptime(fecha_str, "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return fecha_str


def leer_csv(archivo):
    contenido = archivo.read().decode("ISO-8859-1")
    lector = csv.DictReader(io.StringIO(contenido))
    return list(lector)


def calcular_tamano_bloque(total):
    bloque = total // 5
    if bloque >= 500:
        return 500
    if bloque < 1:
        return 1
    return bloque


# --- UI ---

# Toggle tema (esquina derecha)
_, toggle_col = st.columns([20, 1])
with toggle_col:
    icon = "☀️" if dark else "🌙"
    if st.button(icon, key="theme_toggle"):
        st.session_state.dark_mode = not dark
        st.rerun()

# Header
st.markdown(
    """
    <div class="sr-header">
        <h1>Edicion Masiva de Visitas</h1>
        <p>SimpliRoute Tools</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# Autenticacion
st.markdown('<div class="sr-label">Token de API</div>', unsafe_allow_html=True)
token = st.text_input("Token", type="password", label_visibility="collapsed", placeholder="Ingresa tu token de API")

if token:
    token = token.strip()
    valido, cuenta = validar_cuenta(token)
    if valido:
        st.markdown(
            f'<div class="sr-cuenta">✓ Conectado a: <strong>{cuenta}</strong></div>',
            unsafe_allow_html=True,
        )
    else:
        st.error("Token invalido. Revisa tu token de API.")
        st.stop()
else:
    st.info("Ingresa tu token de SimpliRoute para comenzar.")
    st.stop()

# Carga de archivo
st.markdown('<div class="sr-label">Archivo CSV</div>', unsafe_allow_html=True)
archivo = st.file_uploader(
    "CSV",
    type=["csv"],
    label_visibility="collapsed",
)

if not archivo:
    st.stop()

data = leer_csv(archivo)

# Stats
st.markdown(
    f"""
    <div class="sr-stat">
        <div class="sr-stat-number">{len(data):,}</div>
        <div class="sr-stat-label">visitas cargadas</div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.expander("Vista previa"):
    st.dataframe(data[:20], use_container_width=True)

if not st.button("Procesar edicion", type="primary"):
    st.stop()

# Convertir fechas
for registro in data:
    if "planned_date" in registro:
        registro["planned_date"] = convertir_fecha(registro["planned_date"])

total = len(data)
block_size = calcular_tamano_bloque(total)
editadas = 0
errores = []

barra = st.progress(0, text="Procesando...")
estado = st.empty()

for i in range(0, total, block_size):
    bloque = data[i : i + block_size]
    codigo, respuesta = enviar_visitas(bloque, token)

    if codigo == 200:
        editadas += len(bloque)
    else:
        errores.append(
            {"bloque": i // block_size + 1, "codigo": codigo, "detalle": respuesta}
        )

    progreso = min((i + block_size) / total, 1.0)
    barra.progress(progreso, text=f"{editadas}/{total} visitas editadas")

barra.progress(1.0, text="Finalizado")

if editadas > 0:
    estado.success(f"{editadas} visitas editadas correctamente")

if errores:
    st.error(f"{len(errores)} bloque(s) con error")
    for err in errores:
        st.warning(
            f"Bloque {err['bloque']} (HTTP {err['codigo']}): {err['detalle'][:200]}"
        )
