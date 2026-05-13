import re
import time
from datetime import date
import pandas as pd
import streamlit as st
import requests
from config import (
    API_BASE,
    API_SEND_PLAN_WEBHOOKS,
    API_SEND_ROUTE_WEBHOOKS,
    API_SEND_ON_ITS_WAY_WEBHOOKS,
    REQUEST_TIMEOUT,
    EDIT_TIMEOUT,
    MAX_RETRIES,
    RETRY_BASE_DELAY,
)
from utils import (
    render_header, render_guide, render_stat, render_label,
    render_tip, render_error_item, render_cuenta_badge, load_secret,
    create_progress_tracker, update_progress, finish_progress,
)


UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


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


def _enviar_webhook(token, endpoint, id_key, id_value, action):
    headers = _headers(token)
    payload = {id_key: id_value, "action": action}
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(endpoint, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                return True, ""
            if response.status_code >= 500 and attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                continue
            return False, f"HTTP {response.status_code}: {response.text}"
        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                continue
            return False, f"Error de conexion: {str(e)}"
    return False, "Reintentos agotados"


def _listar_planes(token, inicio, fin):
    url = f"{API_BASE}/routes/plans/?start_date={inicio}&end_date={fin}"
    try:
        r = requests.get(url, headers=_headers(token), timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and "results" in data:
                return data["results"], r.status_code, None
            if isinstance(data, list):
                return data, r.status_code, None
            return [], r.status_code, "Respuesta inesperada"
        return [], r.status_code, r.text[:500]
    except requests.exceptions.RequestException as e:
        return [], 0, str(e)


def _listar_visitas_paginated(token, planned_date, progress_bar=None):
    visitas = []
    page = 1
    page_size = 500
    while True:
        url = f"{API_BASE}/routes/visits/paginated/"
        try:
            r = requests.get(
                url,
                headers=_headers(token),
                params={"planned_date": planned_date, "page": page, "page_size": page_size},
                timeout=EDIT_TIMEOUT,
            )
            if r.status_code != 200:
                return [], r.status_code, r.text[:500]
            data = r.json()
            results = data.get("results", [])
            count_total = data.get("count", 0)
            visitas.extend(results)
            if progress_bar and count_total:
                progress_bar.progress(
                    min(len(visitas) / count_total, 1.0),
                    text=f"Descargando visitas... ({len(visitas)}/{count_total})",
                )
            if len(visitas) >= count_total or not results:
                break
            page += 1
        except requests.exceptions.RequestException as e:
            return [], 0, str(e)
    return visitas, 200, None


def _enviar_on_its_way_bloque(token, visit_ids):
    headers = _headers(token)
    payload = {"visit_ids": visit_ids}
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.post(
                API_SEND_ON_ITS_WAY_WEBHOOKS,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            if r.status_code == 200:
                data = r.json()
                return True, data.get("visits found", []), data.get("not found visits", []), ""
            if r.status_code >= 500 and attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                continue
            return False, [], [], f"HTTP {r.status_code}: {r.text}"
        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                continue
            return False, [], [], f"Error de conexion: {str(e)}"
    return False, [], [], "Reintentos agotados"


def _listar_rutas(token, planned_date):
    rutas = []
    url = f"{API_BASE}/routes/routes/?planned_date={planned_date}"
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


def _parse_ids_textarea(text):
    lineas = [line.strip() for line in text.strip().split("\n") if line.strip()]
    validos = []
    errores = []
    for i, linea in enumerate(lineas):
        if UUID_RE.match(linea):
            validos.append(linea)
        else:
            errores.append(f"Linea {i + 1}: '{linea[:50]}' no tiene formato UUID")
    return validos, errores


def _parse_visit_ids_textarea(text):
    lineas = [line.strip() for line in text.strip().split("\n") if line.strip()]
    validos = []
    errores = []
    for i, linea in enumerate(lineas):
        try:
            validos.append(int(linea))
        except ValueError:
            errores.append(f"Linea {i + 1}: '{linea[:50]}' no es un entero")
    return validos, errores


def _procesar_envio(token, ids, endpoint, id_key, action, label_singular):
    total = len(ids)
    exitosos = 0
    fallidos = []
    barra, contador, contenedor_errores = create_progress_tracker(total, "Enviando webhooks...")

    for i, _id in enumerate(ids):
        if i > 0:
            time.sleep(1)
        ok, detalle = _enviar_webhook(token, endpoint, id_key, _id, action)
        procesados = i + 1
        if ok:
            exitosos += 1
        else:
            fallidos.append((_id, detalle))
            with contenedor_errores:
                render_error_item(f"{label_singular} {_id} — {detalle}")
        update_progress(barra, contador, procesados, total, "Enviando webhooks...")

    finish_progress(barra)
    if exitosos > 0:
        st.success(f"{exitosos} de {total} procesados correctamente")
    if fallidos:
        st.error(f"{len(fallidos)} de {total} fallaron")


# ── Tab Planes ────────────────────────────────────────────────────────────────

PLAN_EVENTOS = {
    "Creacion (plan_created)": "plan_created",
    "Edicion (plan_edited)": "plan_edited",
}

ROUTE_EVENTOS = {
    "Creacion (route_created)": "route_created",
    "Inicio (route_started)": "route_started",
    "Edicion (route_edited)": "route_edited",
    "Finalizacion (route_finished)": "route_finished",
}


def _seccion_planes(token_post):
    render_label("Evento")
    evento = st.radio(
        "Evento plan",
        list(PLAN_EVENTOS.keys()),
        label_visibility="collapsed",
        key="rwp_evento",
        horizontal=True,
    )
    action = PLAN_EVENTOS[evento]

    render_label("Origen de los plan_ids")
    origen = st.radio(
        "Origen",
        ["Pegar plan_ids", "Cargar por fecha"],
        label_visibility="collapsed",
        key="rwp_origen",
        horizontal=True,
    )

    ids_finales = []

    if origen == "Pegar plan_ids":
        datos_input = st.text_area(
            "Plan IDs",
            placeholder="07e69fb2-7175-44af-9a18-2388a16c091f\nb1c2d3e4-5678-90ab-cdef-1234567890ab",
            label_visibility="collapsed",
            height=200,
            key="rwp_textarea",
        )
        if not datos_input or not datos_input.strip():
            render_tip("Pega los plan_id a procesar. Cada linea debe ser un UUID.")
            return
        validos, errores = _parse_ids_textarea(datos_input)
        for err in errores:
            render_error_item(err)
        if not validos:
            render_tip("<strong>⚠️ Atencion:</strong> No se encontraron plan_ids validos.", warning=True)
            return
        ids_finales = validos
    else:
        render_label("Token de la cuenta (solo para la busqueda)")
        token_get = st.text_input(
            "Token GET planes",
            type="password",
            label_visibility="collapsed",
            placeholder="Token de API de la cuenta donde estan los planes",
            key="rwp_token_get",
        )
        if not token_get or not token_get.strip():
            render_tip("Ingresa el token de la cuenta para listar sus planes. El envio del webhook seguira usando <code>checkout_token</code>.")
            return
        token_get = token_get.strip()

        valido, cuenta = _validar_cuenta(token_get)
        if not valido:
            st.error("Token invalido. Revisa el token de la cuenta.")
            return
        render_cuenta_badge(f"✓ Listando planes de: <strong>{cuenta}</strong>")

        col1, col2 = st.columns(2)
        with col1:
            inicio = st.date_input("Desde", value=date.today(), format="DD/MM/YYYY", key="rwp_desde")
        with col2:
            fin = st.date_input("Hasta", value=date.today(), format="DD/MM/YYYY", key="rwp_hasta")
        if inicio > fin:
            render_tip("<strong>⚠️ Atencion:</strong> 'Desde' no puede ser posterior a 'Hasta'.", warning=True)
            return

        if st.button("Buscar planes", key="rwp_buscar"):
            st.session_state.pop("rwp_planes", None)
            st.session_state.pop("rwp_editor", None)
            st.session_state.pop("rwp_sel", None)
            with st.spinner("Consultando planes..."):
                planes, status, err = _listar_planes(
                    token_get, inicio.strftime("%Y-%m-%d"), fin.strftime("%Y-%m-%d")
                )
            if status != 200:
                render_error_item(f"HTTP {status} al consultar planes: {err or ''}")
                return
            st.session_state.rwp_planes = planes

        if "rwp_planes" not in st.session_state:
            return

        planes = st.session_state.rwp_planes
        st.markdown(render_stat(len(planes), "plan(es) encontrado(s)"), unsafe_allow_html=True)
        if not planes:
            render_tip("No se encontraron planes en el rango.")
            return

        if "rwp_sel" not in st.session_state:
            st.session_state.rwp_sel = {p["id"]: False for p in planes}

        editor_state = st.session_state.get("rwp_editor", {})
        for row_idx_str, changes in editor_state.get("edited_rows", {}).items():
            if "☑" in changes:
                pid = planes[int(row_idx_str)]["id"]
                st.session_state.rwp_sel[pid] = changes["☑"]

        all_selected = all(st.session_state.rwp_sel.get(p["id"], False) for p in planes)
        btn_label = "Deseleccionar todas" if all_selected else "Seleccionar todas"
        if st.button(btn_label, key="rwp_toggle_all"):
            new_val = not all_selected
            st.session_state.rwp_sel = {p["id"]: new_val for p in planes}
            st.session_state.pop("rwp_editor", None)
            st.rerun()

        df = pd.DataFrame([
            {
                "☑": st.session_state.rwp_sel.get(p["id"], False),
                "Nombre": p.get("name", "(sin nombre)"),
                "Fechas": f"{p.get('start_date','?')} → {p.get('end_date','?')}",
                "Rutas": len(p.get("routes", [])),
                "Plan ID": p.get("id", ""),
            }
            for p in planes
        ])
        edited_df = st.data_editor(
            df,
            column_config={
                "☑": st.column_config.CheckboxColumn(width="small"),
                "Nombre": st.column_config.TextColumn(width="medium"),
                "Fechas": st.column_config.TextColumn(width="medium"),
                "Rutas": st.column_config.NumberColumn("Rutas", width="small"),
                "Plan ID": st.column_config.TextColumn(width="large"),
            },
            use_container_width=True,
            hide_index=True,
            disabled=["Nombre", "Fechas", "Rutas", "Plan ID"],
            key="rwp_editor",
        )
        ids_finales = [planes[i]["id"] for i, sel in enumerate(edited_df["☑"]) if sel]
        if not ids_finales:
            render_tip("Selecciona al menos un plan en la tabla.")
            return

    st.markdown(render_stat(len(ids_finales), "plan(es) a procesar"), unsafe_allow_html=True)

    if not st.button(f"Enviar webhooks {action}", type="primary", key="rwp_enviar"):
        return

    _procesar_envio(token_post, ids_finales, API_SEND_PLAN_WEBHOOKS, "plan_id", action, "Plan")


# ── Tab Rutas ─────────────────────────────────────────────────────────────────

def _seccion_rutas(token_post):
    render_label("Evento")
    evento = st.radio(
        "Evento ruta",
        list(ROUTE_EVENTOS.keys()),
        label_visibility="collapsed",
        key="rwr_evento",
        horizontal=True,
    )
    action = ROUTE_EVENTOS[evento]

    render_label("Origen de los route_ids")
    origen = st.radio(
        "Origen",
        ["Pegar route_ids", "Cargar por fecha"],
        label_visibility="collapsed",
        key="rwr_origen",
        horizontal=True,
    )

    ids_finales = []

    if origen == "Pegar route_ids":
        datos_input = st.text_area(
            "Route IDs",
            placeholder="00167387-03d5-468e-ad00-43af1add4645\n18e2e0b8-4db5-4a17-bb39-d5b3a9c5e393",
            label_visibility="collapsed",
            height=200,
            key="rwr_textarea",
        )
        if not datos_input or not datos_input.strip():
            render_tip("Pega los route_id a procesar. Cada linea debe ser un UUID.")
            return
        validos, errores = _parse_ids_textarea(datos_input)
        for err in errores:
            render_error_item(err)
        if not validos:
            render_tip("<strong>⚠️ Atencion:</strong> No se encontraron route_ids validos.", warning=True)
            return
        ids_finales = validos
    else:
        render_label("Token de la cuenta (solo para la busqueda)")
        token_get = st.text_input(
            "Token GET rutas",
            type="password",
            label_visibility="collapsed",
            placeholder="Token de API de la cuenta donde estan las rutas",
            key="rwr_token_get",
        )
        if not token_get or not token_get.strip():
            render_tip("Ingresa el token de la cuenta para listar sus rutas. El envio del webhook seguira usando <code>checkout_token</code>.")
            return
        token_get = token_get.strip()

        valido, cuenta = _validar_cuenta(token_get)
        if not valido:
            st.error("Token invalido. Revisa el token de la cuenta.")
            return
        render_cuenta_badge(f"✓ Listando rutas de: <strong>{cuenta}</strong>")

        fecha_origen = st.date_input(
            "Fecha de las rutas",
            value=date.today(),
            format="DD/MM/YYYY",
            key="rwr_fecha",
        )

        if st.button("Buscar rutas", key="rwr_buscar"):
            st.session_state.pop("rwr_rutas", None)
            st.session_state.pop("rwr_editor", None)
            st.session_state.pop("rwr_sel", None)
            with st.spinner("Consultando rutas..."):
                rutas, status, err = _listar_rutas(token_get, fecha_origen.strftime("%Y-%m-%d"))
            if status != 200:
                render_error_item(f"HTTP {status} al consultar rutas: {err or ''}")
                return
            st.session_state.rwr_rutas = rutas

        if "rwr_rutas" not in st.session_state:
            return

        rutas = st.session_state.rwr_rutas
        st.markdown(render_stat(len(rutas), "ruta(s) encontrada(s)"), unsafe_allow_html=True)
        if not rutas:
            render_tip("No se encontraron rutas para esa fecha.")
            return

        if "rwr_sel" not in st.session_state:
            st.session_state.rwr_sel = {r["id"]: False for r in rutas}

        editor_state = st.session_state.get("rwr_editor", {})
        for row_idx_str, changes in editor_state.get("edited_rows", {}).items():
            if "☑" in changes:
                rid = rutas[int(row_idx_str)]["id"]
                st.session_state.rwr_sel[rid] = changes["☑"]

        all_selected = all(st.session_state.rwr_sel.get(r["id"], False) for r in rutas)
        btn_label = "Deseleccionar todas" if all_selected else "Seleccionar todas"
        if st.button(btn_label, key="rwr_toggle_all"):
            new_val = not all_selected
            st.session_state.rwr_sel = {r["id"]: new_val for r in rutas}
            st.session_state.pop("rwr_editor", None)
            st.rerun()

        df = pd.DataFrame([
            {
                "☑": st.session_state.rwr_sel.get(r["id"], False),
                "Fecha": r.get("planned_date", "?"),
                "Visitas": r.get("total_visits", 0),
                "Route ID": r.get("id", ""),
            }
            for r in rutas
        ])
        edited_df = st.data_editor(
            df,
            column_config={
                "☑": st.column_config.CheckboxColumn(width="small"),
                "Fecha": st.column_config.TextColumn(width="medium"),
                "Visitas": st.column_config.NumberColumn("Visitas", width="small"),
                "Route ID": st.column_config.TextColumn(width="large"),
            },
            use_container_width=True,
            hide_index=True,
            disabled=["Fecha", "Visitas", "Route ID"],
            key="rwr_editor",
        )
        ids_finales = [rutas[i]["id"] for i, sel in enumerate(edited_df["☑"]) if sel]
        if not ids_finales:
            render_tip("Selecciona al menos una ruta en la tabla.")
            return

    st.markdown(render_stat(len(ids_finales), "ruta(s) a procesar"), unsafe_allow_html=True)

    if not st.button(f"Enviar webhooks {action}", type="primary", key="rwr_enviar"):
        return

    _procesar_envio(token_post, ids_finales, API_SEND_ROUTE_WEBHOOKS, "route_id", action, "Ruta")


# ── Tab Visitas ───────────────────────────────────────────────────────────────

VISIT_BATCH_SIZE = 500


def _procesar_envio_on_its_way(token, visit_ids):
    bloques = [visit_ids[i:i + VISIT_BATCH_SIZE] for i in range(0, len(visit_ids), VISIT_BATCH_SIZE)]
    total_bloques = len(bloques)
    total_ids = len(visit_ids)
    found_total = []
    not_found_total = []
    errores_bloque = []

    barra = st.progress(0, text=f"Enviando bloques... (0/{total_bloques})")
    contenedor_errores = st.container()

    for i, bloque in enumerate(bloques):
        if i > 0:
            time.sleep(1)
        ok, found, not_found, detalle = _enviar_on_its_way_bloque(token, bloque)
        if ok:
            found_total.extend(found)
            not_found_total.extend(not_found)
        else:
            errores_bloque.append((i + 1, len(bloque), detalle))
            with contenedor_errores:
                render_error_item(f"Bloque {i + 1} ({len(bloque)} visitas) — {detalle}")
        barra.progress((i + 1) / total_bloques, text=f"Enviando bloques... ({i + 1}/{total_bloques})")

    barra.progress(1.0, text="Finalizado")

    if found_total:
        st.success(f"{len(found_total)} de {total_ids} visitas procesadas (visits found)")
    if not_found_total:
        st.warning(f"{len(not_found_total)} visit_id(s) no encontradas:")
        with st.expander("Ver visit_ids no encontradas", expanded=False):
            st.code("\n".join(str(v) for v in not_found_total))
    if errores_bloque:
        st.error(f"{len(errores_bloque)} bloque(s) con error")


def _seccion_visitas(token_post):
    render_label("Evento: En camino (on_its_way)")

    render_label("Origen de los visit_ids")
    origen = st.radio(
        "Origen",
        ["Pegar visit_ids", "Cargar por fecha"],
        label_visibility="collapsed",
        key="rwv_origen",
        horizontal=True,
    )

    ids_finales = []

    if origen == "Pegar visit_ids":
        datos_input = st.text_area(
            "Visit IDs",
            placeholder="688102532\n688102530",
            label_visibility="collapsed",
            height=200,
            key="rwv_textarea",
        )
        if not datos_input or not datos_input.strip():
            render_tip("Pega los visit_id a procesar. Cada linea debe ser un entero.")
            return
        validos, errores = _parse_visit_ids_textarea(datos_input)
        for err in errores:
            render_error_item(err)
        if not validos:
            render_tip("<strong>⚠️ Atencion:</strong> No se encontraron visit_ids validos.", warning=True)
            return
        ids_finales = validos
    else:
        render_label("Token de la cuenta (solo para la busqueda)")
        token_get = st.text_input(
            "Token GET visitas",
            type="password",
            label_visibility="collapsed",
            placeholder="Token de API de la cuenta donde estan las visitas",
            key="rwv_token_get",
        )
        if not token_get or not token_get.strip():
            render_tip("Ingresa el token de la cuenta para listar sus visitas. El envio del webhook seguira usando <code>checkout_token</code>.")
            return
        token_get = token_get.strip()

        valido, cuenta = _validar_cuenta(token_get)
        if not valido:
            st.error("Token invalido. Revisa el token de la cuenta.")
            return
        render_cuenta_badge(f"✓ Listando visitas de: <strong>{cuenta}</strong>")

        fecha_origen = st.date_input(
            "Fecha de las visitas",
            value=date.today(),
            format="DD/MM/YYYY",
            key="rwv_fecha",
        )

        if st.button("Buscar visitas", key="rwv_buscar"):
            st.session_state.pop("rwv_visitas", None)
            st.session_state.pop("rwv_editor", None)
            st.session_state.pop("rwv_sel", None)
            barra = st.progress(0, text="Descargando visitas...")
            visitas, status, err = _listar_visitas_paginated(token_get, fecha_origen.strftime("%Y-%m-%d"), progress_bar=barra)
            barra.empty()
            if status != 200:
                render_error_item(f"HTTP {status} al consultar visitas: {err or ''}")
                return
            st.session_state.rwv_visitas = visitas

        if "rwv_visitas" not in st.session_state:
            return

        visitas = st.session_state.rwv_visitas
        st.markdown(render_stat(len(visitas), "visita(s) encontrada(s)"), unsafe_allow_html=True)
        if not visitas:
            render_tip("No se encontraron visitas para esa fecha.")
            return

        if "rwv_sel" not in st.session_state:
            st.session_state.rwv_sel = {v["id"]: False for v in visitas}

        editor_state = st.session_state.get("rwv_editor", {})
        for row_idx_str, changes in editor_state.get("edited_rows", {}).items():
            if "☑" in changes:
                vid = visitas[int(row_idx_str)]["id"]
                st.session_state.rwv_sel[vid] = changes["☑"]

        all_selected = all(st.session_state.rwv_sel.get(v["id"], False) for v in visitas)
        btn_label = "Deseleccionar todas" if all_selected else "Seleccionar todas"
        if st.button(btn_label, key="rwv_toggle_all"):
            new_val = not all_selected
            st.session_state.rwv_sel = {v["id"]: new_val for v in visitas}
            st.session_state.pop("rwv_editor", None)
            st.rerun()

        df = pd.DataFrame([
            {
                "☑": st.session_state.rwv_sel.get(v["id"], False),
                "Visit ID": v.get("id", ""),
                "Reference": v.get("reference", ""),
                "Title": v.get("title", ""),
                "Address": v.get("address", ""),
            }
            for v in visitas
        ])
        edited_df = st.data_editor(
            df,
            column_config={
                "☑": st.column_config.CheckboxColumn(width="small"),
                "Visit ID": st.column_config.NumberColumn("Visit ID", width="small"),
                "Reference": st.column_config.TextColumn(width="small"),
                "Title": st.column_config.TextColumn(width="medium"),
                "Address": st.column_config.TextColumn(width="large"),
            },
            use_container_width=True,
            hide_index=True,
            disabled=["Visit ID", "Reference", "Title", "Address"],
            key="rwv_editor",
        )
        ids_finales = [visitas[i]["id"] for i, sel in enumerate(edited_df["☑"]) if sel]
        if not ids_finales:
            render_tip("Selecciona al menos una visita en la tabla.")
            return

    n_total = len(ids_finales)
    n_bloques = (n_total + VISIT_BATCH_SIZE - 1) // VISIT_BATCH_SIZE
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown(render_stat(n_total, "visita(s) a procesar"), unsafe_allow_html=True)
    with col_b:
        st.markdown(render_stat(n_bloques, f"bloque(s) de hasta {VISIT_BATCH_SIZE}"), unsafe_allow_html=True)

    if not st.button("Enviar webhooks on_its_way", type="primary", key="rwv_enviar"):
        return

    _procesar_envio_on_its_way(token_post, ids_finales)


# ── Entry point ───────────────────────────────────────────────────────────────

def pagina_reenvio_webhooks():
    render_header(
        "Reenvio de Webhooks",
        "Reenvia webhooks de eventos varios a SimpliRoute (planes, rutas, visitas)",
    )

    render_guide(
        steps=[
            '<strong>Elige el objeto</strong> — Planes, Rutas o Visitas (tabs).',
            '<strong>Selecciona el evento</strong> — Planes: <code>created</code>/<code>edited</code>. Rutas: <code>created</code>/<code>started</code>/<code>edited</code>/<code>finished</code>. Visitas: <code>on_its_way</code>.',
            '<strong>Origen de IDs</strong> — Pega IDs uno por linea o cargalos por fecha (token manual de la cuenta).',
            '<strong>Envia</strong> — Plan/Ruta: 1 POST por ID con delay de 1s. Visitas: bloques de hasta 500 IDs por request.',
        ],
        tip='El envio siempre usa <code>checkout_token</code> de secrets. El listado por fecha usa un token manual de la cuenta donde estan los datos.',
    )

    token_post = load_secret(
        "checkout_token",
        "No se encontro `checkout_token` en `.streamlit/secrets.toml`. Configura `[api_config]` con `checkout_token`.",
    )

    tab_planes, tab_rutas, tab_visitas = st.tabs(["Planes", "Rutas", "Visitas"])
    with tab_planes:
        _seccion_planes(token_post)
    with tab_rutas:
        _seccion_rutas(token_post)
    with tab_visitas:
        _seccion_visitas(token_post)
