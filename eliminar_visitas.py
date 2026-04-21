import streamlit as st
import requests
import pandas as pd
import time
from collections import defaultdict
from datetime import date
from config import API_BASE, REQUEST_TIMEOUT, EDIT_TIMEOUT, EDIT_DELAY, MAX_BLOCK_SIZE
from utils import (
    render_header, render_guide, render_label, render_stat,
    render_cuenta_badge, render_tip,
    create_progress_tracker, update_progress, finish_progress,
)


def _headers(token):
    return {"Authorization": f"Token {token}", "Content-Type": "application/json"}


def validar_cuenta(token):
    try:
        r = requests.get(f"{API_BASE}/accounts/me/", headers=_headers(token), timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return True, r.json().get("account", {}).get("name", "Sin nombre")
    except requests.exceptions.RequestException:
        pass
    return False, None


def buscar_visitas_por_fecha(planned_date, token):
    url = f"{API_BASE}/routes/visits/?planned_date={planned_date}"
    try:
        r = requests.get(url, headers=_headers(token), timeout=EDIT_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            return (data if isinstance(data, list) else []), r.status_code, None
        return [], r.status_code, r.text[:500]
    except requests.exceptions.RequestException as e:
        return [], 0, str(e)


def detectar_duplicados(visitas):
    """Agrupa por reference, conserva la visita con ID mas bajo, marca el resto.

    Returns: (a_borrar, grupos) donde
      a_borrar = lista de visitas a limpiar
      grupos = lista de dicts {reference, keep_id, delete_ids, total}
    """
    por_ref = defaultdict(list)
    for v in visitas:
        ref = v.get("reference")
        if ref is None or str(ref).strip() == "":
            continue
        por_ref[str(ref).strip()].append(v)

    a_borrar = []
    grupos = []
    for ref, lista in por_ref.items():
        if len(lista) < 2:
            continue
        lista_ordenada = sorted(lista, key=lambda v: int(v.get("id", 0)))
        keep = lista_ordenada[0]
        resto = lista_ordenada[1:]
        a_borrar.extend(resto)
        grupos.append({
            "reference": ref,
            "keep_id": keep.get("id"),
            "delete_ids": [v.get("id") for v in resto],
            "total": len(lista),
        })

    return a_borrar, grupos


def limpiar_visitas_bloque(visitas, token):
    url = f"{API_BASE}/routes/visits/"
    payload = [
        {
            "id": v.get("id"),
            "title": v.get("title", ""),
            "address": v.get("address", ""),
            "route": "",
            "planned_date": "2020-01-01",
        }
        for v in visitas
    ]
    try:
        r = requests.put(url, headers=_headers(token), json=payload, timeout=EDIT_TIMEOUT)
        return r.status_code == 200, r.status_code, r.text
    except requests.exceptions.RequestException as e:
        return False, 0, str(e)


def _reset_estado():
    for k in ["ev_visitas", "ev_a_borrar", "ev_grupos", "ev_fecha", "ev_token", "ev_cuenta"]:
        if k in st.session_state:
            del st.session_state[k]


def pagina_eliminar_visitas():
    render_header(
        "Eliminar Visitas",
        "Herramienta general para eliminar visitas de cualquier cuenta",
    )

    render_guide(
        steps=[
            "<strong>Ingresa el token</strong> — Token de API de la cuenta donde estan las visitas.",
            "<strong>Confirma la cuenta</strong> — Se validara y se mostrara el nombre.",
            "<strong>Selecciona la opcion</strong> — Por ahora disponible: Eliminar duplicados.",
            "<strong>Elige la fecha</strong> — Fecha de las visitas a revisar.",
            "<strong>Buscar y revisar</strong> — Se listaran los duplicados detectados.",
            "<strong>Confirmar eliminacion</strong> — Se limpiara <code>planned_date</code> a 2020-01-01 y se quitara la ruta en bloques.",
        ],
        tip="Para duplicados: se conserva la visita con el ID mas bajo (la primera creada) y se eliminan las demas.",
    )

    # --- Paso 1: Token ---
    render_label("Paso 1 · Token de API")
    token_input = st.text_input(
        "Token",
        type="password",
        label_visibility="collapsed",
        placeholder="Ingresa el token de API",
        key="ev_token_input",
    )

    if not token_input:
        render_tip("Ingresa el token de API de la cuenta.")
        st.stop()

    token = token_input.strip()
    valido, cuenta = validar_cuenta(token)
    if not valido:
        st.error("Token invalido. Revisa tu token de API.")
        st.stop()

    render_cuenta_badge(f"✓ Conectado a: <strong>{cuenta}</strong>")

    # --- Paso 2: Opcion ---
    render_label("Paso 2 · Opcion")
    opcion = st.radio(
        "Opcion",
        ["Eliminar duplicados"],
        horizontal=True,
        label_visibility="collapsed",
    )

    if opcion == "Eliminar duplicados":
        _flujo_duplicados(token, cuenta)


def _flujo_duplicados(token, cuenta):
    # --- Paso 3: Fecha ---
    render_label("Paso 3 · Fecha de las visitas")
    fecha = st.date_input(
        "Fecha",
        value=date.today(),
        label_visibility="collapsed",
        key="ev_fecha_input",
    )
    fecha_str = fecha.strftime("%Y-%m-%d")

    # Reset si cambia token/fecha
    if st.session_state.get("ev_fecha") != fecha_str or st.session_state.get("ev_token") != token:
        if "ev_a_borrar" in st.session_state:
            _reset_estado()

    st.markdown("---")
    if st.button("Buscar duplicados", use_container_width=True, type="primary"):
        with st.spinner(f"Consultando visitas del {fecha_str}..."):
            visitas, status, err = buscar_visitas_por_fecha(fecha_str, token)

        if err or status != 200:
            st.error(f"Error al consultar visitas (HTTP {status}): {err or 'sin detalle'}")
            st.stop()

        a_borrar, grupos = detectar_duplicados(visitas)

        st.session_state.ev_visitas = visitas
        st.session_state.ev_a_borrar = a_borrar
        st.session_state.ev_grupos = grupos
        st.session_state.ev_fecha = fecha_str
        st.session_state.ev_token = token
        st.session_state.ev_cuenta = cuenta

    if "ev_a_borrar" not in st.session_state:
        st.stop()

    visitas = st.session_state.ev_visitas
    a_borrar = st.session_state.ev_a_borrar
    grupos = st.session_state.ev_grupos
    fecha_str = st.session_state.ev_fecha

    # --- Stats ---
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(render_stat(len(visitas), "Visitas en la fecha"), unsafe_allow_html=True)
    with col2:
        st.markdown(render_stat(len(grupos), "References duplicadas"), unsafe_allow_html=True)
    with col3:
        st.markdown(render_stat(len(a_borrar), "Visitas a eliminar"), unsafe_allow_html=True)

    if not a_borrar:
        st.success("✅ No se detectaron duplicados en la fecha seleccionada.")
        st.stop()

    # --- Preview ---
    with st.expander(f"📋 References duplicadas ({len(grupos)})", expanded=True):
        df_grupos = pd.DataFrame([
            {
                "Reference": g["reference"],
                "Total": g["total"],
                "Se conserva (ID)": g["keep_id"],
                "Se eliminan (IDs)": ", ".join(str(i) for i in g["delete_ids"]),
            }
            for g in grupos
        ])
        st.dataframe(df_grupos, use_container_width=True, hide_index=True)

    with st.expander(f"📄 Detalle de visitas a eliminar ({len(a_borrar)})", expanded=False):
        df_borrar = pd.DataFrame([
            {
                "ID": v.get("id"),
                "Reference": v.get("reference"),
                "Title": v.get("title", ""),
                "Address": v.get("address", ""),
                "Ruta actual": v.get("route", ""),
            }
            for v in a_borrar
        ])
        st.dataframe(df_borrar, use_container_width=True, hide_index=True)

    render_tip(
        f"Se enviara un PUT bulk a <code>/routes/visits/</code> con <code>planned_date=2020-01-01</code> "
        f"y <code>route=\"\"</code> para <strong>{len(a_borrar)}</strong> visita(s), "
        f"en bloques de hasta {MAX_BLOCK_SIZE}."
    )

    confirmar = st.checkbox(
        f"Confirmo que quiero eliminar {len(a_borrar)} visita(s) duplicada(s) de la cuenta {st.session_state.ev_cuenta} en la fecha {fecha_str}",
        key="ev_confirmar",
    )

    if not confirmar:
        st.stop()

    if not st.button("Eliminar duplicados", use_container_width=True, type="primary"):
        st.stop()

    # --- Procesamiento ---
    st.markdown("---")
    st.markdown("### 🗑️ Procesando...")

    bloques = [a_borrar[i : i + MAX_BLOCK_SIZE] for i in range(0, len(a_borrar), MAX_BLOCK_SIZE)]
    barra, contador, cont_bloques = create_progress_tracker(len(bloques), "Eliminando...")
    eliminadas = 0
    errores = []

    for idx, bloque in enumerate(bloques):
        ok, status, resp = limpiar_visitas_bloque(bloque, st.session_state.ev_token)

        with cont_bloques:
            if ok:
                eliminadas += len(bloque)
                with st.expander(f"✅ Bloque {idx + 1}/{len(bloques)} — {len(bloque)} visita(s)", expanded=False):
                    st.code(f"PUT {API_BASE}/routes/visits/", language="bash")
                    st.markdown(f"Status: `{status}`")
            else:
                errores.append((idx + 1, status, resp))
                with st.expander(f"❌ Bloque {idx + 1}/{len(bloques)} — ERROR", expanded=True):
                    st.code(f"PUT {API_BASE}/routes/visits/", language="bash")
                    st.markdown(f"Status: `{status}`")
                    st.write(resp)

        update_progress(barra, contador, idx + 1, len(bloques))
        time.sleep(EDIT_DELAY)

    finish_progress(barra)

    # --- Resumen ---
    st.markdown("---")
    st.markdown("### 📊 Resumen")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.markdown(render_stat(st.session_state.ev_cuenta, "Cuenta"), unsafe_allow_html=True)
    with col_b:
        st.markdown(render_stat(eliminadas, "Visitas eliminadas"), unsafe_allow_html=True)
    with col_c:
        st.markdown(render_stat(len(errores), "Bloques con error"), unsafe_allow_html=True)

    if eliminadas == len(a_borrar):
        st.success(f"✅ ¡Completado! Se eliminaron {eliminadas} visita(s) duplicada(s) de la fecha {fecha_str}.")
    else:
        st.warning(f"⚠️ Se eliminaron {eliminadas}/{len(a_borrar)} visita(s).")

    _reset_estado()


if __name__ == "__main__":
    pagina_eliminar_visitas()
