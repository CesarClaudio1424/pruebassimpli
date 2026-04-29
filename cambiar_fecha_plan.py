import json
import time
import streamlit as st
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from config import API_BASE, REQUEST_TIMEOUT, EDIT_TIMEOUT, MAX_BLOCK_SIZE, MAX_RETRIES, RETRY_BASE_DELAY
from utils import (
    render_header, render_guide, render_label, render_stat,
    render_tip, render_error_item, render_cuenta_badge,
)

ROUTE_WORKERS = 10
PAGINATED_PAGE_SIZE = 500


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


# ── Plan API ──────────────────────────────────────────────────────────────────

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


# ── Rutas API ─────────────────────────────────────────────────────────────────

def listar_rutas(token, planned_date):
    rutas = []
    url = f"{API_BASE}/routes/?planned_date={planned_date}"
    try:
        while url:
            r = requests.get(url, headers=_headers(token), timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                return [], r.status_code, r.text[:500]
            data = r.json()
            if isinstance(data, list):
                rutas.extend(data)
                break
            rutas.extend(data.get("results", []))
            url = data.get("next")
        return rutas, 200, None
    except requests.exceptions.RequestException as e:
        return [], 0, str(e)


# ── Visitas API ───────────────────────────────────────────────────────────────

def buscar_visitas_paginadas(token, planned_date, barra=None):
    url = f"{API_BASE}/routes/visits/paginated/"
    visitas = []
    page = 1
    count_total = None
    while True:
        data = None
        last_status = 0
        last_err = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                r = requests.get(
                    url,
                    headers=_headers(token),
                    params={"planned_date": planned_date, "page": page, "page_size": PAGINATED_PAGE_SIZE},
                    timeout=EDIT_TIMEOUT,
                )
                last_status = r.status_code
                if r.status_code == 200:
                    data = r.json()
                    break
                last_err = r.text[:500]
                if r.status_code < 500:
                    return visitas, r.status_code, last_err
            except requests.exceptions.RequestException as e:
                last_status = 0
                last_err = str(e)
            if attempt >= MAX_RETRIES:
                return visitas, last_status, last_err
            time.sleep(RETRY_BASE_DELAY * (2 ** attempt))

        if data is None:
            return visitas, last_status, last_err

        results = data.get("results", [])
        count_total = data.get("count", 0)
        visitas.extend(results)

        if barra and count_total:
            barra.progress(min(len(visitas) / count_total, 1.0), text=f"Descargando visitas... ({len(visitas)}/{count_total})")

        if len(visitas) >= count_total or not results:
            break
        page += 1

    return visitas, 200, None


def put_visitas_bulk(token, payload_block):
    url = f"{API_BASE}/routes/visits/"
    try:
        r = requests.put(url, headers=_headers(token), json=payload_block, timeout=EDIT_TIMEOUT)
        return r.status_code, r.text, url
    except requests.exceptions.RequestException as e:
        return 0, str(e), url


# ── Sub-secciones ─────────────────────────────────────────────────────────────

def _seccion_plan():
    render_guide(
        steps=[
            "<strong>Ingresa el token</strong> — Token de la cuenta donde esta el plan.",
            "<strong>Define el rango de busqueda</strong> — Inicio y fin del rango donde buscar planes.",
            "<strong>Buscar planes</strong> — Se listan los planes en ese rango.",
            "<strong>Selecciona y actualiza</strong> — Elige el plan, define las nuevas fechas y confirma.",
        ],
        tip="SimpliRoute exige que start_date y end_date del plan coincidan (1 dia). Si ingresas fechas distintas, la API puede rechazar el cambio.",
    )

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
        return
    token = token.strip()

    valido, cuenta = _validar_cuenta(token)
    if not valido:
        st.error("Token invalido. Revisa tu token de API.")
        return
    render_cuenta_badge(f"✓ Conectado a: <strong>{cuenta}</strong>")

    render_label("Paso 2 · Rango de busqueda")
    col1, col2 = st.columns(2)
    with col1:
        inicio = st.date_input("Fecha inicio", value=date.today() - timedelta(days=7), format="DD/MM/YYYY", key="cfp_inicio")
    with col2:
        fin = st.date_input("Fecha fin", value=date.today(), format="DD/MM/YYYY", key="cfp_fin")

    if inicio > fin:
        render_tip("<strong>⚠️ Atencion:</strong> La fecha de inicio no puede ser posterior a la fecha fin.", warning=True)
        return

    if st.button("Buscar planes", key="cfp_buscar"):
        st.session_state.pop("cfp_planes", None)
        st.session_state.pop("cfp_resultado_put", None)
        with st.spinner("Consultando planes..."):
            planes, status, err, url = listar_planes(token, inicio.strftime("%Y-%m-%d"), fin.strftime("%Y-%m-%d"))
        if status != 200:
            render_error_item(f"HTTP {status} al consultar planes: {err or ''}")
            st.code(f"GET {url}", language="bash")
            return
        st.session_state.cfp_planes = planes

    if "cfp_planes" not in st.session_state:
        return

    planes = st.session_state.cfp_planes
    st.markdown(render_stat(len(planes), "plan(es) encontrado(s)"), unsafe_allow_html=True)

    if not planes:
        render_tip("No se encontraron planes en el rango seleccionado.")
        return

    render_label("Paso 3 · Selecciona el plan a editar")
    opciones = {
        f"{p.get('name', '(sin nombre)')} · {p.get('start_date', '?')} → {p.get('end_date', '?')} · {p.get('id')}": p
        for p in planes
    }
    etiqueta = st.selectbox("Plan", list(opciones.keys()), label_visibility="collapsed", key="cfp_plan_sel")
    plan_sel = opciones[etiqueta]

    with st.expander("Ver JSON del plan seleccionado", expanded=False):
        st.json(plan_sel)

    render_label("Paso 4 · Nuevas fechas del plan")
    try:
        fecha_default = date.fromisoformat(plan_sel.get("start_date"))
    except (TypeError, ValueError):
        fecha_default = date.today()

    col_n1, col_n2 = st.columns(2)
    with col_n1:
        nueva_inicio = st.date_input("Nueva fecha inicio", value=fecha_default, format="DD/MM/YYYY", key="cfp_nueva_inicio")
    with col_n2:
        nueva_fin = st.date_input("Nueva fecha fin", value=fecha_default, format="DD/MM/YYYY", key="cfp_nueva_fin")

    if nueva_inicio > nueva_fin:
        render_tip("<strong>⚠️ Atencion:</strong> La nueva fecha de inicio no puede ser posterior a la nueva fecha fin.", warning=True)
        return

    if not st.button("Actualizar plan", type="primary", key="cfp_actualizar"):
        return

    status, body, url, payload = actualizar_plan(
        token, plan_sel, nueva_inicio.strftime("%Y-%m-%d"), nueva_fin.strftime("%Y-%m-%d")
    )

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
            st.json(json.loads(body))
        except Exception:
            st.code(body or "(vacio)")

    if not (200 <= status < 300):
        return

    route_ids = plan_sel.get("routes", [])
    if not route_ids:
        render_tip("El plan no tiene rutas asociadas.")
        return

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


def _seccion_rutas():
    render_guide(
        steps=[
            "<strong>Ingresa el token</strong> — Token de la cuenta donde estan las rutas.",
            "<strong>Fecha origen</strong> — Fecha en la que estan las rutas actualmente.",
            "<strong>Buscar rutas</strong> — Se listan todas las rutas de esa fecha.",
            "<strong>Selecciona y actualiza</strong> — Elige las rutas a mover y define la nueva fecha.",
        ],
        tip="Al cambiar la fecha de una ruta via PUT, SimpliRoute mueve automaticamente las visitas asociadas. El plan NO se modifica.",
    )

    render_label("Paso 1 · Token")
    token = st.text_input(
        "Token",
        type="password",
        label_visibility="collapsed",
        placeholder="Token de API",
        key="cfr_token",
    )
    if not token or not token.strip():
        render_tip("Ingresa el token de API de la cuenta.")
        return
    token = token.strip()

    valido, cuenta = _validar_cuenta(token)
    if not valido:
        st.error("Token invalido. Revisa tu token de API.")
        return
    render_cuenta_badge(f"✓ Conectado a: <strong>{cuenta}</strong>")

    render_label("Paso 2 · Fecha origen")
    fecha_origen = st.date_input("Fecha origen", value=date.today(), format="DD/MM/YYYY", key="cfr_fecha_origen")

    if st.button("Buscar rutas", key="cfr_buscar"):
        st.session_state.pop("cfr_rutas", None)
        with st.spinner("Consultando rutas..."):
            rutas, status, err = listar_rutas(token, fecha_origen.strftime("%Y-%m-%d"))
        if status != 200:
            render_error_item(f"HTTP {status} al consultar rutas: {err or ''}")
            return
        st.session_state.cfr_rutas = rutas

    if "cfr_rutas" not in st.session_state:
        return

    rutas = st.session_state.cfr_rutas
    st.markdown(render_stat(len(rutas), "ruta(s) encontrada(s)"), unsafe_allow_html=True)

    if not rutas:
        render_tip("No se encontraron rutas para esa fecha.")
        return

    render_label("Paso 3 · Selecciona las rutas a actualizar")
    opciones_rutas = {
        f"{r.get('name', r.get('title', '?'))} (id: {r.get('id')})": r.get("id")
        for r in rutas
    }
    seleccionadas = st.multiselect(
        "Rutas",
        list(opciones_rutas.keys()),
        default=list(opciones_rutas.keys()),
        label_visibility="collapsed",
        key="cfr_seleccion",
    )

    if not seleccionadas:
        render_tip("Selecciona al menos una ruta.")
        return

    render_label("Paso 4 · Nueva fecha")
    nueva_fecha = st.date_input("Nueva fecha", value=fecha_origen, format="DD/MM/YYYY", key="cfr_nueva_fecha")

    render_tip(
        "<strong>⚠️ Advertencia:</strong> Al cambiar el planned_date de las rutas, SimpliRoute tambien "
        "movera automaticamente la fecha de todas las visitas asociadas a esas rutas. "
        "El plan general <strong>no</strong> se modifica.",
        warning=True,
    )

    if not st.button("Actualizar rutas", type="primary", key="cfr_actualizar"):
        return

    route_ids = [opciones_rutas[s] for s in seleccionadas]
    nueva_fecha_str = nueva_fecha.strftime("%Y-%m-%d")
    total = len(route_ids)

    barra = st.progress(0, text=f"Actualizando rutas... (0/{total})")
    errores = []
    completados = 0

    with ThreadPoolExecutor(max_workers=ROUTE_WORKERS) as executor:
        futures = {executor.submit(actualizar_ruta_fecha, token, rid, nueva_fecha_str): rid for rid in route_ids}
        for future in as_completed(futures):
            rid = futures[future]
            s, b, u = future.result()
            completados += 1
            if not (200 <= s < 300):
                errores.append({"route_id": rid, "status": s, "body": b, "url": u})
            barra.progress(completados / total, text=f"Actualizando rutas... ({completados}/{total})")

    barra.empty()
    ok = total - len(errores)
    st.success(f"{ok}/{total} rutas actualizadas a {nueva_fecha_str}. Las visitas asociadas quedan en la misma fecha.")

    if errores:
        st.warning(f"{len(errores)} ruta(s) con error:")
        for e in errores:
            with st.expander(f"Error · ruta {e['route_id']} (HTTP {e['status']})", expanded=True):
                st.code(f"PUT {e['url']}", language="bash")
                st.code(e["body"] or "(vacio)")


def _seccion_visitas():
    render_guide(
        steps=[
            "<strong>Ingresa el token</strong> — Token de la cuenta donde estan las visitas.",
            "<strong>Fecha origen</strong> — Fecha en la que estan las visitas actualmente.",
            "<strong>Buscar visitas</strong> — Se recuperan todas las visitas de esa fecha via endpoint paginado.",
            "<strong>Define la nueva fecha y actualiza</strong> — Se envia un PUT bulk con la nueva fecha.",
        ],
        tip="Solo se actualiza el planned_date de las visitas. Las rutas y el plan NO se modifican.",
    )

    render_label("Paso 1 · Token")
    token = st.text_input(
        "Token",
        type="password",
        label_visibility="collapsed",
        placeholder="Token de API",
        key="cfv_token",
    )
    if not token or not token.strip():
        render_tip("Ingresa el token de API de la cuenta.")
        return
    token = token.strip()

    valido, cuenta = _validar_cuenta(token)
    if not valido:
        st.error("Token invalido. Revisa tu token de API.")
        return
    render_cuenta_badge(f"✓ Conectado a: <strong>{cuenta}</strong>")

    render_label("Paso 2 · Fecha origen")
    fecha_origen = st.date_input("Fecha origen", value=date.today(), format="DD/MM/YYYY", key="cfv_fecha_origen")

    if st.button("Buscar visitas", key="cfv_buscar"):
        st.session_state.pop("cfv_visitas", None)
        barra = st.progress(0, text="Descargando visitas...")
        visitas, status, err = buscar_visitas_paginadas(token, fecha_origen.strftime("%Y-%m-%d"), barra=barra)
        barra.empty()
        if status != 200:
            render_error_item(f"HTTP {status} al consultar visitas: {err or ''}")
            return
        st.session_state.cfv_visitas = visitas

    if "cfv_visitas" not in st.session_state:
        return

    visitas = st.session_state.cfv_visitas
    st.markdown(render_stat(len(visitas), "visita(s) encontrada(s)"), unsafe_allow_html=True)

    if not visitas:
        render_tip("No se encontraron visitas para esa fecha.")
        return

    render_label("Paso 3 · Nueva fecha")
    nueva_fecha = st.date_input("Nueva fecha", value=fecha_origen, format="DD/MM/YYYY", key="cfv_nueva_fecha")

    render_tip(
        "<strong>Nota:</strong> Solo se actualizara el planned_date de las visitas. "
        "Las rutas y el plan general <strong>no</strong> se modifican.",
    )

    if not st.button("Actualizar visitas", type="primary", key="cfv_actualizar"):
        return

    nueva_fecha_str = nueva_fecha.strftime("%Y-%m-%d")
    payload_total = [
        {
            "id": v["id"],
            "reference": v.get("reference", ""),
            "title": v.get("title", ""),
            "address": v.get("address", ""),
            "planned_date": nueva_fecha_str,
        }
        for v in visitas
    ]

    bloques = [payload_total[i:i + MAX_BLOCK_SIZE] for i in range(0, len(payload_total), MAX_BLOCK_SIZE)]
    total_visitas = len(payload_total)
    errores = []
    procesadas = 0

    barra = st.progress(0, text=f"Actualizando visitas... (0/{total_visitas})")
    for i, bloque in enumerate(bloques):
        s, b, u = put_visitas_bulk(token, bloque)
        procesadas += len(bloque)
        barra.progress(procesadas / total_visitas, text=f"Actualizando visitas... ({procesadas}/{total_visitas})")
        if not (200 <= s < 300):
            errores.append({"bloque": i + 1, "status": s, "body": b, "url": u, "size": len(bloque)})

    barra.empty()
    ok_visitas = total_visitas - sum(e["size"] for e in errores)
    st.success(f"{ok_visitas}/{total_visitas} visitas actualizadas a {nueva_fecha_str}.")

    if errores:
        st.warning(f"{len(errores)} bloque(s) con error:")
        for e in errores:
            with st.expander(f"Error · Bloque {e['bloque']} ({e['size']} visitas, HTTP {e['status']})", expanded=True):
                st.code(f"PUT {e['url']}", language="bash")
                st.code(e["body"] or "(vacio)")


# ── Entry point ───────────────────────────────────────────────────────────────

def pagina_cambiar_fecha_plan():
    render_header(
        "Cambio de Fechas",
        "Actualiza fechas de planes, rutas o visitas via API SimpliRoute",
    )

    tab1, tab2, tab3 = st.tabs(["Cambiar Fecha de Plan", "Cambiar Fecha de Rutas", "Cambiar Fecha de Visitas"])
    with tab1:
        _seccion_plan()
    with tab2:
        _seccion_rutas()
    with tab3:
        _seccion_visitas()
