import streamlit as st
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from config import API_BASE, REQUEST_TIMEOUT
from utils import (
    render_header, render_guide, render_label, render_stat,
    render_tip, render_error_item,
)

ROUTE_WORKERS = 10


def _headers(token):
    return {"Authorization": f"Token {token}", "Content-Type": "application/json"}


def listar_planes(token, inicio, fin):
    url = f"{API_BASE}/routes/plans/?start_date={inicio}&end_date={fin}"
    try:
        r = requests.get(url, headers=_headers(token), timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and "results" in data:
                return data["results"], r.status_code, None, url
            if isinstance(data, list):
                return data, r.status_code, None, url
            return [], r.status_code, "Respuesta inesperada", url
        return [], r.status_code, r.text[:500], url
    except requests.exceptions.RequestException as e:
        return [], 0, str(e), url


def actualizar_plan(token, plan, nueva_inicio, nueva_fin):
    plan_id = plan.get("id")
    url = f"{API_BASE}/routes/plans/{plan_id}/"
    payload = dict(plan)
    payload["start_date"] = nueva_inicio
    payload["end_date"] = nueva_fin
    try:
        r = requests.put(url, headers=_headers(token), json=payload, timeout=REQUEST_TIMEOUT)
        return r.status_code, r.text, url, payload
    except requests.exceptions.RequestException as e:
        return 0, str(e), url, payload


def actualizar_ruta_fecha(token, route_id, nueva_fecha):
    url = f"{API_BASE}/routes/{route_id}/"
    try:
        r = requests.put(url, headers=_headers(token), json={"planned_date": nueva_fecha}, timeout=REQUEST_TIMEOUT)
        return r.status_code, r.text, url
    except requests.exceptions.RequestException as e:
        return 0, str(e), url


def pagina_cambiar_fecha_plan():
    render_header(
        "Cambiar Fecha de Plan",
        "Mueve un plan existente a una nueva fecha de inicio y fin",
    )

    render_guide(
        steps=[
            "<strong>Ingresa el token</strong> — Token de API de la cuenta donde esta el plan.",
            "<strong>Define el rango de busqueda</strong> — Fechas de inicio y fin donde buscar los planes existentes.",
            "<strong>Buscar planes</strong> — Se consultan los planes en ese rango y se listan en pantalla.",
            "<strong>Selecciona y actualiza</strong> — Elige el plan, define las nuevas fechas y confirma para enviar el PUT.",
        ],
        tip="La API de SimpliRoute exige que start_date y end_date del plan coincidan (1 dia). Si ingresas fechas distintas, la API puede rechazar el cambio.",
    )

    # --- Token ---
    render_label("Paso 1 · Token")
    token = st.text_input(
        "Token",
        type="password",
        label_visibility="collapsed",
        placeholder="Token de API",
        key="cfp_token",
    )
    if not token or not token.strip():
        render_tip("Ingresa el token de API de la cuenta.")
        st.stop()
    token = token.strip()

    # --- Rango de busqueda ---
    render_label("Paso 2 · Rango de busqueda")
    col1, col2 = st.columns(2)
    with col1:
        inicio = st.date_input(
            "Fecha inicio",
            value=date.today() - timedelta(days=7),
            format="DD/MM/YYYY",
            key="cfp_inicio",
        )
    with col2:
        fin = st.date_input(
            "Fecha fin",
            value=date.today(),
            format="DD/MM/YYYY",
            key="cfp_fin",
        )

    if inicio > fin:
        render_tip(
            "<strong>⚠️ Atencion:</strong> La fecha de inicio no puede ser posterior a la fecha fin.",
            warning=True,
        )
        st.stop()

    if st.button("Buscar planes", key="cfp_buscar"):
        st.session_state.pop("cfp_planes", None)
        st.session_state.pop("cfp_resultado_put", None)
        with st.spinner("Consultando planes..."):
            planes, status, err, url = listar_planes(
                token,
                inicio.strftime("%Y-%m-%d"),
                fin.strftime("%Y-%m-%d"),
            )
        if status != 200:
            render_error_item(f"HTTP {status} al consultar planes: {err or ''}")
            st.code(f"GET {url}", language="bash")
            st.stop()
        st.session_state.cfp_planes = planes
        st.session_state.cfp_url_busqueda = url

    if "cfp_planes" not in st.session_state:
        st.stop()

    planes = st.session_state.cfp_planes
    st.markdown(
        render_stat(len(planes), "plan(es) encontrado(s)"),
        unsafe_allow_html=True,
    )

    if not planes:
        render_tip("No se encontraron planes en el rango seleccionado.")
        st.stop()

    # --- Seleccion de plan ---
    render_label("Paso 3 · Selecciona el plan a editar")

    opciones = {
        f"{p.get('name', '(sin nombre)')} · {p.get('start_date', '?')} → {p.get('end_date', '?')} · {p.get('id')}": p
        for p in planes
    }
    etiqueta = st.selectbox(
        "Plan",
        list(opciones.keys()),
        label_visibility="collapsed",
        key="cfp_plan_sel",
    )
    plan_sel = opciones[etiqueta]

    with st.expander("Ver JSON del plan seleccionado", expanded=False):
        st.json(plan_sel)

    # --- Nuevas fechas ---
    render_label("Paso 4 · Nuevas fechas del plan")

    try:
        fecha_default = date.fromisoformat(plan_sel.get("start_date"))
    except (TypeError, ValueError):
        fecha_default = date.today()

    col_n1, col_n2 = st.columns(2)
    with col_n1:
        nueva_inicio = st.date_input(
            "Nueva fecha inicio",
            value=fecha_default,
            format="DD/MM/YYYY",
            key="cfp_nueva_inicio",
        )
    with col_n2:
        nueva_fin = st.date_input(
            "Nueva fecha fin",
            value=fecha_default,
            format="DD/MM/YYYY",
            key="cfp_nueva_fin",
        )

    if nueva_inicio > nueva_fin:
        render_tip(
            "<strong>⚠️ Atencion:</strong> La nueva fecha de inicio no puede ser posterior a la nueva fecha fin.",
            warning=True,
        )
        st.stop()

    if not st.button("Actualizar plan", type="primary", key="cfp_actualizar"):
        st.stop()

    status, body, url, payload = actualizar_plan(
        token,
        plan_sel,
        nueva_inicio.strftime("%Y-%m-%d"),
        nueva_fin.strftime("%Y-%m-%d"),
    )

    st.session_state.cfp_resultado_put = {
        "status": status,
        "body": body,
        "url": url,
        "payload": payload,
    }

    if 200 <= status < 300:
        st.success(f"Plan actualizado correctamente (HTTP {status}).")
    else:
        st.error(f"Error al actualizar el plan (HTTP {status}).")

    with st.expander("Detalle del request/response del plan", expanded=(status < 200 or status >= 300)):
        st.code(f"PUT {url}", language="bash")
        st.markdown("**Payload enviado:**")
        st.json(payload)
        st.markdown(f"**Status:** `{status}`")
        st.markdown("**Response:**")
        try:
            import json
            st.json(json.loads(body))
        except Exception:
            st.code(body or "(vacio)")

    if not (200 <= status < 300):
        st.stop()

    # --- Actualizar planned_date de cada ruta (cascadea a visitas) ---
    route_ids = plan_sel.get("routes", [])
    if not route_ids:
        render_tip("El plan no tiene rutas asociadas.")
        st.stop()

    nueva_fecha_str = nueva_inicio.strftime("%Y-%m-%d")
    total = len(route_ids)
    st.markdown(render_stat(total, "ruta(s) a actualizar"), unsafe_allow_html=True)

    barra = st.progress(0, text=f"Actualizando rutas... (0/{total})")
    errores_rutas = []
    completados = 0

    with ThreadPoolExecutor(max_workers=ROUTE_WORKERS) as executor:
        futures = {executor.submit(actualizar_ruta_fecha, token, rid, nueva_fecha_str): rid for rid in route_ids}
        for future in as_completed(futures):
            rid = futures[future]
            s, b, u = future.result()
            completados += 1
            if not (200 <= s < 300):
                errores_rutas.append({"route_id": rid, "status": s, "body": b, "url": u})
            barra.progress(completados / total, text=f"Actualizando rutas... ({completados}/{total})")

    barra.empty()
    ok = total - len(errores_rutas)
    st.success(f"{ok}/{total} rutas actualizadas. Las visitas de cada ruta quedan en {nueva_fecha_str}.")

    if errores_rutas:
        st.warning(f"{len(errores_rutas)} ruta(s) con error:")
        for e in errores_rutas:
            with st.expander(f"Error · {e['route_id']} (HTTP {e['status']})", expanded=True):
                st.code(f"PUT {e['url']}", language="bash")
                st.code(e["body"] or "(vacio)")
