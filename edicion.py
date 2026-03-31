import streamlit as st
import requests
import csv
import io
import time
from datetime import datetime
import pandas as pd

API_BASE = "https://api.simpliroute.com/v1"

PLANTILLA_CAMPOS = [
    {"columna": "id", "tipo": "integer", "req": True, "desc": "ID de la visita en SimpliRoute", "ejemplo": "200189436"},
    {"columna": "title", "tipo": "string", "req": False, "desc": "Nombre / identificador de la entrega", "ejemplo": "Pedido #1234"},
    {"columna": "address", "tipo": "string", "req": False, "desc": "Direccion (formato Google Maps)", "ejemplo": "Av. Providencia 1234, Santiago"},
    {"columna": "planned_date", "tipo": "date", "req": False, "desc": "Fecha planificada (dd/mm/yyyy)", "ejemplo": "15/04/2026"},
    {"columna": "contact_name", "tipo": "string", "req": False, "desc": "Nombre del receptor", "ejemplo": "Juan Perez"},
    {"columna": "contact_phone", "tipo": "string", "req": False, "desc": "Telefono del receptor", "ejemplo": "+56912345678"},
    {"columna": "contact_email", "tipo": "string", "req": False, "desc": "Email del receptor", "ejemplo": "[email protected]"},
    {"columna": "reference", "tipo": "string", "req": False, "desc": "ID interno / numero de orden", "ejemplo": "ORD-5678"},
    {"columna": "notes", "tipo": "string", "req": False, "desc": "Notas para el conductor", "ejemplo": "Dejar en conserjeria"},
    {"columna": "load", "tipo": "number", "req": False, "desc": "Carga principal", "ejemplo": "10"},
    {"columna": "load_2", "tipo": "number", "req": False, "desc": "Carga secundaria", "ejemplo": "5"},
    {"columna": "load_3", "tipo": "number", "req": False, "desc": "Carga terciaria", "ejemplo": "2"},
    {"columna": "window_start", "tipo": "time", "req": False, "desc": "Inicio ventana horaria (HH:mm:ss)", "ejemplo": "09:00:00"},
    {"columna": "window_end", "tipo": "time", "req": False, "desc": "Fin ventana horaria (HH:mm:ss)", "ejemplo": "18:00:00"},
    {"columna": "duration", "tipo": "time", "req": False, "desc": "Tiempo de servicio (HH:mm:ss)", "ejemplo": "00:15:00"},
    {"columna": "latitude", "tipo": "float", "req": False, "desc": "Latitud del destino", "ejemplo": "-33.413433"},
    {"columna": "longitude", "tipo": "float", "req": False, "desc": "Longitud del destino", "ejemplo": "-70.585503"},
    {"columna": "priority_level", "tipo": "integer", "req": False, "desc": "Nivel de prioridad (1-5)", "ejemplo": "3"},
]


def generar_csv_plantilla():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([c["columna"] for c in PLANTILLA_CAMPOS])
    writer.writerow([c["ejemplo"] for c in PLANTILLA_CAMPOS])
    writer.writerow(["200189437", "Pedido #5678", "Los Leones 2345, Providencia", "16/04/2026",
                      "Maria Lopez", "+56987654321", "[email protected]", "ORD-9012",
                      "Llamar antes", "5", "", "", "10:00:00", "14:00:00", "00:10:00",
                      "-33.421958", "-70.607270", "1"])
    return output.getvalue()


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


def pagina_edicion(THEME):
    # Header
    st.markdown(
        """
        <div class="sr-header">
            <h1>Edicion Masiva de Visitas</h1>
            <p>Edita visitas en bloque via API</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # --- Guia de uso ---
    with st.expander("📖 ¿Como funciona? — Guia rapida", expanded=False):
        st.markdown(
            """
            <div class="sr-guide">
                <div class="sr-step">
                    <div class="sr-step-num">1</div>
                    <div class="sr-step-text"><strong>Ingresa el token de API</strong> — El token de la cuenta donde estan las visitas. Puedes obtenerlo desde <a href="https://simpliroute.tryretool.com/embedded/public/a11dd57d-c962-441f-b27a-e1ede0a85645" target="_blank">esta herramienta</a>.</div>
                </div>
                <div class="sr-step">
                    <div class="sr-step-num">2</div>
                    <div class="sr-step-text"><strong>Prepara tu archivo CSV</strong> — Debe tener una columna <code>id</code> (obligatoria) con el ID de cada visita, mas las columnas de los campos que quieras editar. Descarga la plantilla de ejemplo mas abajo.</div>
                </div>
                <div class="sr-step">
                    <div class="sr-step-num">3</div>
                    <div class="sr-step-text"><strong>Sube el CSV</strong> — La app mostrara una vista previa de los datos cargados para que verifiques antes de procesar.</div>
                </div>
                <div class="sr-step">
                    <div class="sr-step-num">4</div>
                    <div class="sr-step-text"><strong>Procesa la edicion</strong> — Los datos se envian a SimpliRoute en bloques. Veras el progreso en tiempo real y un resumen al finalizar.</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class="sr-tip">
                <strong>💡 Tip:</strong> Solo incluye en el CSV las columnas que necesitas modificar. No es necesario enviar todos los campos — basta con <code>id</code> + los campos a editar.
            </div>
            """,
            unsafe_allow_html=True,
        )

    # --- Paso 1: Autenticacion ---
    st.markdown('<div class="sr-label">Paso 1 · Token de API</div>', unsafe_allow_html=True)
    token = st.text_input("Token", type="password", label_visibility="collapsed", placeholder="Ingresa el token de API")

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
        st.markdown(
            """
            <div class="sr-tip">
                Ingresa el token de API de la cuenta a la que pertenecen las visitas. Puedes obtenerlo desde
                <a href="https://simpliroute.tryretool.com/embedded/public/a11dd57d-c962-441f-b27a-e1ede0a85645" target="_blank"><strong>esta herramienta</strong></a>.
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.stop()

    # --- Paso 2: Archivo CSV ---
    st.markdown('<div class="sr-label">Paso 2 · Archivo CSV</div>', unsafe_allow_html=True)

    with st.expander("📋 Formato del CSV y campos disponibles"):
        st.markdown(
            """
            <div class="sr-tip">
                <strong>Importante:</strong> La columna <code>id</code> es <strong>obligatoria</strong> — identifica que visita se va a editar.
                Ademas necesitas al menos una columna mas con el campo que quieras modificar. Las fechas deben ir en formato <code>dd/mm/yyyy</code>.
            </div>
            """,
            unsafe_allow_html=True,
        )
        filas_html = ""
        for campo in PLANTILLA_CAMPOS:
            tag = '<span class="sr-tag sr-tag-req">obligatorio</span>' if campo["req"] else '<span class="sr-tag sr-tag-opt">opcional</span>'
            filas_html += f'<tr><td><code>{campo["columna"]}</code></td><td>{campo["tipo"]}</td><td>{tag}</td><td>{campo["desc"]}</td><td><code>{campo["ejemplo"]}</code></td></tr>'

        st.markdown(
            f"""
            <table class="sr-fields-table">
                <thead><tr><th>Columna</th><th>Tipo</th><th></th><th>Descripcion</th><th>Ejemplo</th></tr></thead>
                <tbody>{filas_html}</tbody>
            </table>
            """,
            unsafe_allow_html=True,
        )

    # Descarga de plantilla
    st.download_button(
        label="⬇ Descargar plantilla CSV de ejemplo",
        data=generar_csv_plantilla(),
        file_name="plantilla_edicion_visitas.csv",
        mime="text/csv",
    )

    archivo = st.file_uploader(
        "CSV",
        type=["csv"],
        label_visibility="collapsed",
        help="Sube un archivo CSV con columna 'id' y los campos a editar",
    )

    if not archivo:
        st.markdown(
            """
            <div class="sr-tip">
                Sube un archivo <strong>.csv</strong> con los datos de las visitas a editar. Puedes descargar la plantilla de ejemplo como referencia.
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.stop()

    data = leer_csv(archivo)

    if not data:
        st.error("El archivo CSV esta vacio o no se pudo leer.")
        st.stop()

    # Validar que exista columna id + al menos un campo a editar
    columnas = list(data[0].keys()) if data else []
    if "id" not in columnas:
        st.error("El CSV debe tener una columna **id** para identificar las visitas a editar.")
        st.stop()
    if len(columnas) < 2:
        st.error("El CSV debe tener al menos una columna ademas de **id** con los datos a editar.")
        st.stop()

    # --- Paso 3: Preview y procesamiento ---
    st.markdown('<div class="sr-label">Paso 3 · Revisar y procesar</div>', unsafe_allow_html=True)

    # Stats
    col_stat, col_cols = st.columns(2)
    with col_stat:
        st.markdown(
            f"""
            <div class="sr-stat">
                <div class="sr-stat-number">{len(data):,}</div>
                <div class="sr-stat-label">visitas cargadas</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_cols:
        st.markdown(
            f"""
            <div class="sr-stat">
                <div class="sr-stat-number">{len(columnas)}</div>
                <div class="sr-stat-label">campos a editar</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        f'<div style="font-size:0.78rem; color:{THEME["label"]}; margin-bottom:0.3rem;">Columnas detectadas: <code>{", ".join(columnas)}</code></div>',
        unsafe_allow_html=True,
    )

    with st.expander("Vista previa (primeras 20 filas)"):
        st.dataframe(pd.DataFrame(data[:20]), use_container_width=True)

    if not st.button("Procesar edicion", type="primary", key="btn_edicion"):
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
