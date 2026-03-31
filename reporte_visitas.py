import streamlit as st
import requests
from datetime import datetime, timedelta
import time
from config import API_VISITS_REPORTS, API_ROUTES_REPORTS, REQUEST_TIMEOUT, REPORT_DELAY
from utils import (
    render_header, render_guide, render_stat, render_label,
    render_tip, render_error_item, validar_email,
    create_progress_tracker, update_progress, finish_progress,
)


def dividir_rango_por_dias(inicio, final, dias):
    rangos = []
    while inicio <= final:
        fin_intervalo = inicio + timedelta(days=dias - 1)
        if fin_intervalo > final:
            fin_intervalo = final
        rangos.append((inicio.strftime("%Y-%m-%d"), fin_intervalo.strftime("%Y-%m-%d")))
        inicio = fin_intervalo + timedelta(days=1)
    return rangos


def dividir_rango_por_mes(inicio, final):
    rangos = []
    while inicio <= final:
        siguiente_mes = inicio.replace(day=28) + timedelta(days=4)
        ultimo_dia_mes = siguiente_mes - timedelta(days=siguiente_mes.day)
        fin_mes = min(ultimo_dia_mes, final)
        rangos.append((inicio.strftime("%Y-%m-%d"), fin_mes.strftime("%Y-%m-%d")))
        inicio = fin_mes + timedelta(days=1)
    return rangos


def enviar_reporte(base_url, headers, inicio, final, correo):
    url = f"{base_url}/from/{inicio}/to/{final}/?email={correo}"
    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        return response.status_code, response.text
    except requests.exceptions.RequestException as e:
        return 0, f"Error de conexion: {str(e)}"


def pagina_reporte_visitas():
    render_header("Reporte de Visitas y Rutas", "Genera reportes por rango de fechas y recibelos por correo")

    render_guide(
        steps=[
            '<strong>Selecciona el tipo de reporte</strong> — Visitas o Rutas. Cada uno consulta un endpoint distinto de SimpliRoute.',
            '<strong>Ingresa token y correo</strong> — El token de la cuenta y el correo donde recibiras los reportes.',
            '<strong>Define el rango de fechas</strong> — Elige fecha de inicio, fecha final y como dividir el rango (semanal, quincenal o mensual).',
            '<strong>Genera el reporte</strong> — Se envia una solicitud por cada sub-intervalo. Los reportes llegan a tu correo.',
        ],
        tip='Para rangos largos, dividir en intervalos mas cortos evita timeouts y genera reportes mas manejables. Hay una pausa de 3 segundos entre cada solicitud.',
    )

    # --- Paso 1: Tipo de reporte ---
    render_label("Paso 1 · Tipo de reporte")
    tipo_reporte = st.radio(
        "Tipo de reporte",
        ("Visitas", "Rutas"),
        horizontal=True,
        label_visibility="collapsed",
    )

    # --- Paso 2: Token y correo ---
    render_label("Paso 2 · Token y correo")
    token = st.text_input("Token", type="password", label_visibility="collapsed", placeholder="Token de API", key="rep_token")

    if not token or not token.strip():
        render_tip(
            'Ingresa el token de API de la cuenta. Puedes obtenerlo desde '
            '<a href="https://simpliroute.tryretool.com/embedded/public/a11dd57d-c962-441f-b27a-e1ede0a85645" target="_blank"><strong>esta herramienta</strong></a>.'
        )
        st.stop()

    token = token.strip()

    correo = st.text_input("Correo", label_visibility="collapsed", placeholder="Correo para recibir los reportes", key="rep_correo")

    if not correo or not correo.strip():
        render_tip("Ingresa el correo donde recibiras los reportes.")
        st.stop()

    correo = correo.strip()

    if not validar_email(correo):
        render_tip("<strong>⚠️ Atencion:</strong> El formato del correo no es valido.", warning=True)
        st.stop()

    # --- Paso 3: Fechas e intervalo ---
    render_label("Paso 3 · Rango de fechas")

    col1, col2 = st.columns(2)
    with col1:
        fecha_inicio = st.date_input("Fecha de inicio", value=datetime.today() - timedelta(days=7), key="rep_inicio")
    with col2:
        fecha_final = st.date_input("Fecha final", value=datetime.today(), key="rep_final")

    if fecha_inicio > fecha_final:
        render_tip("<strong>⚠️ Atencion:</strong> La fecha de inicio no puede ser posterior a la fecha final.", warning=True)
        st.stop()

    render_label("Intervalo de division")
    intervalo = st.radio(
        "Intervalo",
        ("Semanal", "Quincenal", "Mensual"),
        horizontal=True,
        label_visibility="collapsed",
    )

    if intervalo == "Semanal":
        rangos = dividir_rango_por_dias(fecha_inicio, fecha_final, 7)
    elif intervalo == "Quincenal":
        rangos = dividir_rango_por_dias(fecha_inicio, fecha_final, 15)
    else:
        rangos = dividir_rango_por_mes(fecha_inicio, fecha_final)

    col_stat1, col_stat2 = st.columns(2)
    with col_stat1:
        st.markdown(
            render_stat(len(rangos), f'{"solicitud" if len(rangos) == 1 else "solicitudes"} a enviar'),
            unsafe_allow_html=True,
        )
    with col_stat2:
        st.markdown(render_stat(tipo_reporte, "tipo de reporte"), unsafe_allow_html=True)

    if not st.button("Generar reporte", type="primary", key="btn_reporte"):
        st.stop()

    # --- Procesamiento ---
    if tipo_reporte == "Visitas":
        base_url = API_VISITS_REPORTS
        headers = {
            "authorization": f"Token {token}",
            "origin": "https://app2.simpliroute.com",
            "referer": "https://app2.simpliroute.com/",
            "accept": "application/json",
            "user-agent": "Mozilla/5.0",
        }
    else:
        base_url = API_ROUTES_REPORTS
        headers = {
            "authorization": f"Token {token}",
            "origin": "https://app3.simpliroute.com",
            "referer": "https://app3.simpliroute.com/",
            "accept": "application/json",
            "user-agent": "Mozilla/5.0",
        }

    total = len(rangos)
    exitosos = 0
    fallidos = []

    barra, contador, contenedor_errores = create_progress_tracker(total, "Enviando solicitudes...")

    for i, (inicio_rango, final_rango) in enumerate(rangos):
        status, body = enviar_reporte(base_url, headers, inicio_rango, final_rango, correo)
        procesados = i + 1

        if 200 <= status < 300:
            exitosos += 1
        else:
            fallidos.append((inicio_rango, final_rango, status))
            with contenedor_errores:
                render_error_item(f"{inicio_rango} a {final_rango} — HTTP {status}")

        update_progress(barra, contador, procesados, total, "Enviando solicitudes...")

        if procesados < total:
            time.sleep(REPORT_DELAY)

    finish_progress(barra)

    if exitosos > 0:
        st.success(f"{exitosos} de {total} reportes solicitados correctamente. Revisa tu correo.")
    if fallidos:
        st.error(f"{len(fallidos)} de {total} solicitudes fallaron")
