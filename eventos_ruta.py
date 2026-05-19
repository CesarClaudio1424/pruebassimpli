import streamlit as st
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import API_BASE, API_EVENTS_REGISTER, REQUEST_TIMEOUT
from utils import (
    render_header, render_guide, render_label, render_stat,
    render_tip, render_error_item, render_cuenta_badge,
    create_progress_tracker, update_progress, finish_progress,
)

ROUTE_WORKERS = 10

EVENT_CONFIG = {
    "Iniciar": {"type": "ROUTE_STARTED", "hora": "00:00:00", "verbo": "iniciar"},
    "Finalizar": {"type": "ROUTE_FINISHED", "hora": "23:59:59", "verbo": "finalizar"},
}


def _headers(token):
    return {"Authorization": f"Token {token}", "Content-Type": "application/json"}


def _validar_cuenta(token):
    try:
        r = requests.get(f"{API_BASE}/accounts/me/", headers=_headers(token), timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return True, r.json().get("account", {}).get("name", "Sin nombre")
    except requests.exceptions.RequestException:
        pass
    return False, None


def _obtener_planned_date(token, route_id):
    url = f"{API_BASE}/routes/routes/{route_id}/"
    try:
        r = requests.get(url, headers=_headers(token), timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            planned_date = r.json().get("planned_date")
            if not planned_date:
                return None, "Respuesta sin campo planned_date"
            return planned_date, None
        return None, f"HTTP {r.status_code}: {r.text[:300]}"
    except requests.exceptions.RequestException as e:
        return None, f"Error de conexion: {e}"


def _registrar_evento(token, route_id, planned_date, event_type, hora):
    date_time = f"{planned_date}T{hora}.000Z"
    payload = {
        "date_time": date_time,
        "route_id": route_id,
        "type": event_type,
    }
    try:
        r = requests.post(API_EVENTS_REGISTER, headers=_headers(token), json=payload, timeout=REQUEST_TIMEOUT)
        if 200 <= r.status_code < 300:
            return True, planned_date, None
        return False, planned_date, f"HTTP {r.status_code}: {r.text[:300]}"
    except requests.exceptions.RequestException as e:
        return False, planned_date, f"Error de conexion: {e}"


def _procesar_ruta(token, route_id, event_type, hora):
    planned_date, err = _obtener_planned_date(token, route_id)
    if err:
        return route_id, False, None, f"GET ruta: {err}"
    ok, fecha, err = _registrar_evento(token, route_id, planned_date, event_type, hora)
    if not ok:
        return route_id, False, fecha, f"POST evento: {err}"
    return route_id, True, fecha, None


def pagina_eventos_ruta():
    render_header("Eventos de Ruta", "Registra eventos ROUTE_STARTED o ROUTE_FINISHED para una lista de rutas")

    render_guide(
        steps=[
            "<strong>Elige la accion</strong> — Iniciar (<code>ROUTE_STARTED</code>) o Finalizar (<code>ROUTE_FINISHED</code>).",
            "<strong>Ingresa el token</strong> — Token de API SimpliRoute de la cuenta donde estan las rutas.",
            "<strong>Pega los UUIDs</strong> — Uno por linea. Por cada UUID se consulta su <code>planned_date</code> via GET y luego se registra el evento.",
            "<strong>Procesa</strong> — Para cada ruta se envia <code>POST /v1/events/register/</code> con el <code>type</code> elegido y <code>date_time</code> al inicio (00:00:00) o fin (23:59:59) del dia de la ruta.",
        ],
        tip="El endpoint vive en <code>api-mobile.simpliroute.com</code> (no en el API normal). Iniciar usa <code>{planned_date}T00:00:00.000Z</code>; Finalizar usa <code>{planned_date}T23:59:59.000Z</code>.",
    )

    # --- Paso 1: Accion ---
    render_label("Paso 1 · Accion")
    accion = st.radio(
        "Accion",
        list(EVENT_CONFIG.keys()),
        horizontal=True,
        label_visibility="collapsed",
        key="ev_accion",
    )
    cfg = EVENT_CONFIG[accion]

    # --- Paso 2: Token ---
    render_label("Paso 2 · Token")
    token = st.text_input(
        "Token",
        type="password",
        label_visibility="collapsed",
        placeholder="Token de API",
        key="ev_token",
    )

    if not token:
        render_tip("Ingresa el token de la cuenta para continuar.")
        st.stop()

    ok_cuenta, nombre_cuenta = _validar_cuenta(token)
    if not ok_cuenta:
        st.error("Token invalido o sin acceso a la cuenta.")
        st.stop()
    render_cuenta_badge(f"Cuenta: {nombre_cuenta}")

    # --- Paso 3: UUIDs ---
    render_label("Paso 3 · UUIDs de rutas (uno por linea)")
    uuids_input = st.text_area(
        "UUIDs",
        placeholder="4b086533-9ca3-4a5a-baf4-342dec5cc0c6\n18e2e0b8-4db5-4a17-bb39-d5b3a9c5e393",
        label_visibility="collapsed",
        height=200,
        key="ev_uuids",
    )

    if not uuids_input or not uuids_input.strip():
        render_tip(f"Pega los UUIDs de las rutas a {cfg['verbo']}.")
        st.stop()

    uuids = []
    vistos = set()
    duplicados = 0
    for linea in uuids_input.strip().split("\n"):
        uid = linea.strip()
        if not uid:
            continue
        if uid in vistos:
            duplicados += 1
            continue
        vistos.add(uid)
        uuids.append(uid)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(render_stat(len(uuids), "rutas a procesar"), unsafe_allow_html=True)
    with col2:
        st.markdown(render_stat(duplicados, "duplicados ignorados"), unsafe_allow_html=True)

    if not st.button(f"{accion} {len(uuids)} ruta(s)", type="primary", key="btn_ev"):
        st.stop()

    # --- Procesamiento paralelo ---
    total = len(uuids)
    exitosos = 0
    fallidos = []
    detalle_ok = []

    barra, contador, contenedor_errores = create_progress_tracker(total, "Procesando rutas...")

    procesados = 0
    with ThreadPoolExecutor(max_workers=ROUTE_WORKERS) as executor:
        futures = {
            executor.submit(_procesar_ruta, token, uid, cfg["type"], cfg["hora"]): uid
            for uid in uuids
        }
        for future in as_completed(futures):
            route_id, ok, fecha, err = future.result()
            procesados += 1
            if ok:
                exitosos += 1
                detalle_ok.append((route_id, fecha))
            else:
                fallidos.append((route_id, err))
                with contenedor_errores:
                    render_error_item(f"{route_id} — {err}")
            update_progress(barra, contador, procesados, total, "Procesando rutas...")

    finish_progress(barra)

    if exitosos > 0:
        st.success(f"{exitosos} de {total} rutas procesadas correctamente ({cfg['type']})")
        with st.expander(f"Ver {exitosos} ruta(s) procesada(s)", expanded=False):
            for rid, fecha in detalle_ok:
                st.markdown(f"- `{rid}` — `{fecha}`")
    if fallidos:
        st.error(f"{len(fallidos)} de {total} fallaron")
