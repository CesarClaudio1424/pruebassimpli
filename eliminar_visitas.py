import streamlit as st
import requests
import pandas as pd
import time
from collections import defaultdict
from datetime import date
from config import API_BASE, REQUEST_TIMEOUT, EDIT_TIMEOUT, EDIT_DELAY, MAX_BLOCK_SIZE, MAX_RETRIES, RETRY_BASE_DELAY
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


PAGINATED_PAGE_SIZE = 500


def buscar_visitas_por_fecha(planned_date, token, on_progress=None, on_retry=None):
    """Recupera todas las visitas de una fecha via endpoint paginado.

    Usa /routes/visits/paginated/ en vez de /routes/visits/?planned_date= porque el
    viejo revienta con HTTP 500 cuando la fecha tiene >15k visitas (el backend no
    puede serializar la respuesta completa).

    GET es idempotente: reintentamos con backoff sobre 5xx y ConnectionError.

    on_progress: callback opcional (page, count_total, acumulado) para UI.
    on_retry: callback opcional (page, attempt, max_retries, wait_s, err) para UI.
    """
    url = f"{API_BASE}/routes/visits/paginated/"
    visitas = []
    page = 1
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
                    try:
                        data = r.json()
                    except ValueError as e:
                        return visitas, r.status_code, f"Respuesta no-JSON: {e}"
                    break
                last_err = r.text[:500]
                if r.status_code < 500:
                    return visitas, r.status_code, last_err
            except requests.exceptions.RequestException as e:
                last_status = 0
                last_err = str(e)

            if attempt >= MAX_RETRIES:
                return visitas, last_status, last_err
            wait = RETRY_BASE_DELAY * (2 ** attempt)
            if on_retry:
                on_retry(page, attempt + 1, MAX_RETRIES, wait, last_err)
            time.sleep(wait)

        if data is None:
            return visitas, last_status, last_err

        results = data.get("results", [])
        count = data.get("count", 0)
        visitas.extend(results)

        if on_progress:
            on_progress(page, count, len(visitas))

        if not results or len(visitas) >= count:
            break
        page += 1

    return visitas, 200, None


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


def limpiar_visitas_bloque(visitas, token, on_retry=None):
    """PUT bulk de limpieza con retry sobre 5xx y ConnectionError.

    PUT con IDs explicitos es idempotente: si el servidor ya aplico el cambio
    antes de la desconexion, reaplicarlo produce el mismo estado. Seguro reintentar.

    on_retry: callback opcional (attempt, max_retries, wait_s, err) para la UI.
    """
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
    last_status = 0
    last_resp = ""
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.put(url, headers=_headers(token), json=payload, timeout=EDIT_TIMEOUT)
            if r.status_code == 200:
                return True, r.status_code, r.text
            last_status = r.status_code
            last_resp = r.text
            if r.status_code < 500:
                return False, r.status_code, r.text
        except requests.exceptions.RequestException as e:
            last_status = 0
            last_resp = str(e)

        if attempt >= MAX_RETRIES:
            break
        wait = RETRY_BASE_DELAY * (2 ** attempt)
        if on_retry:
            on_retry(attempt + 1, MAX_RETRIES, wait, last_resp)
        time.sleep(wait)

    return False, last_status, last_resp


def _reset_estado():
    for k in [
        "ev_visitas", "ev_a_borrar", "ev_grupos",
        "ev_fecha", "ev_token", "ev_cuenta", "ev_modo",
    ]:
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
            "<strong>Selecciona la opcion</strong> — <em>Eliminar duplicados</em> (solo los repetidos) o <em>Eliminacion total</em> (todas las visitas del dia).",
            "<strong>Elige la fecha</strong> — Fecha de las visitas a revisar.",
            "<strong>Buscar y revisar</strong> — Se listaran las visitas afectadas.",
            "<strong>Confirmar eliminacion</strong> — Se limpiara <code>planned_date</code> a 2020-01-01 y se quitara la ruta en bloques.",
        ],
        tip="Duplicados: se conserva la visita con el ID mas bajo (la primera creada). Eliminacion total: se borran TODAS las visitas de la fecha.",
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
        ["Eliminar duplicados", "Eliminacion total"],
        horizontal=True,
        label_visibility="collapsed",
    )

    # Reset si cambia la opcion
    if st.session_state.get("ev_opcion") != opcion:
        _reset_estado()
        st.session_state.ev_opcion = opcion

    if opcion == "Eliminar duplicados":
        _flujo_duplicados(token, cuenta)
    else:
        _flujo_total(token, cuenta)


def _paso_fecha_y_busqueda(token, cuenta, label_boton, spinner_fn):
    """Paso 3 (fecha) + boton de busqueda. spinner_fn(visitas) -> None guarda en session_state."""
    render_label("Paso 3 · Fecha de las visitas")
    fecha = st.date_input(
        "Fecha",
        value=date.today(),
        label_visibility="collapsed",
        key="ev_fecha_input",
    )
    fecha_str = fecha.strftime("%Y-%m-%d")

    if st.session_state.get("ev_fecha") != fecha_str or st.session_state.get("ev_token") != token:
        if "ev_a_borrar" in st.session_state:
            _reset_estado()

    st.markdown("---")
    if st.button(label_boton, use_container_width=True, type="primary"):
        barra = st.progress(0.0, text=f"Consultando visitas del {fecha_str}...")
        state = {"pct": 0.0}

        def _on_progress(page, count_total, acumulado):
            if count_total <= 0:
                state["pct"] = 1.0
                barra.progress(1.0, text="Sin visitas en la fecha")
                return
            total_pag = (count_total + PAGINATED_PAGE_SIZE - 1) // PAGINATED_PAGE_SIZE
            pct = min(acumulado / count_total, 1.0)
            state["pct"] = pct
            barra.progress(pct, text=f"Pagina {page} de {total_pag} — {acumulado}/{count_total} visitas")

        def _on_retry(page, attempt, max_r, wait, err):
            short = (err or "")[:80]
            barra.progress(
                state["pct"],
                text=f"Pagina {page} — reintentando {attempt}/{max_r} en {wait}s ({short})",
            )

        visitas, status, err = buscar_visitas_por_fecha(
            fecha_str, token, on_progress=_on_progress, on_retry=_on_retry
        )
        barra.empty()

        if err or status != 200:
            st.error(f"Error al consultar visitas (HTTP {status}): {err or 'sin detalle'}")
            st.stop()

        spinner_fn(visitas)
        st.session_state.ev_visitas = visitas
        st.session_state.ev_fecha = fecha_str
        st.session_state.ev_token = token
        st.session_state.ev_cuenta = cuenta


def _flujo_duplicados(token, cuenta):
    def _guardar(visitas):
        a_borrar, grupos = detectar_duplicados(visitas)
        st.session_state.ev_a_borrar = a_borrar
        st.session_state.ev_grupos = grupos
        st.session_state.ev_modo = "duplicados"

    _paso_fecha_y_busqueda(token, cuenta, "Buscar duplicados", _guardar)

    if st.session_state.get("ev_modo") != "duplicados" or "ev_a_borrar" not in st.session_state:
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
        st.dataframe(_df_visitas(a_borrar), use_container_width=True, hide_index=True)

    render_tip(
        f"Se enviara un PUT bulk a <code>/routes/visits/</code> con <code>planned_date=2020-01-01</code> "
        f"y <code>route=\"\"</code> para <strong>{len(a_borrar)}</strong> visita(s), "
        f"en bloques de hasta {MAX_BLOCK_SIZE}."
    )

    confirmar = st.checkbox(
        f"Confirmo que quiero eliminar {len(a_borrar)} visita(s) duplicada(s) "
        f"de la cuenta {cuenta} en la fecha {fecha_str}",
        key="ev_confirmar_dup",
    )

    if not confirmar:
        st.stop()

    if not st.button("Eliminar duplicados", use_container_width=True, type="primary"):
        st.stop()

    _ejecutar_borrado(a_borrar, token, cuenta, fecha_str, descripcion="duplicada(s)")


def _flujo_total(token, cuenta):
    def _guardar(visitas):
        st.session_state.ev_a_borrar = list(visitas)
        st.session_state.ev_modo = "total"

    _paso_fecha_y_busqueda(token, cuenta, "Buscar visitas del dia", _guardar)

    if st.session_state.get("ev_modo") != "total" or "ev_a_borrar" not in st.session_state:
        st.stop()

    visitas = st.session_state.ev_visitas
    a_borrar = st.session_state.ev_a_borrar
    fecha_str = st.session_state.ev_fecha

    # --- Stats ---
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(render_stat(len(visitas), "Visitas en la fecha"), unsafe_allow_html=True)
    with col2:
        st.markdown(render_stat(len(a_borrar), "Visitas a eliminar"), unsafe_allow_html=True)

    if not a_borrar:
        st.info("No hay visitas en esa fecha.")
        st.stop()

    with st.expander(f"📄 Detalle de visitas a eliminar ({len(a_borrar)})", expanded=False):
        st.dataframe(_df_visitas(a_borrar), use_container_width=True, hide_index=True)

    render_tip(
        f"⚠️ <strong>Eliminacion total</strong>: se borraran <strong>TODAS</strong> las {len(a_borrar)} "
        f"visita(s) de la fecha {fecha_str} (sin filtrar duplicados). "
        f"PUT bulk a <code>/routes/visits/</code> con <code>planned_date=2020-01-01</code> y "
        f"<code>route=\"\"</code>, en bloques de hasta {MAX_BLOCK_SIZE}.",
        warning=True,
    )

    confirmar = st.checkbox(
        f"Confirmo eliminar TODAS las {len(a_borrar)} visita(s) "
        f"de la cuenta {cuenta} en la fecha {fecha_str}",
        key="ev_confirmar_total",
    )

    if not confirmar:
        st.stop()

    if not st.button("Eliminar todas las visitas", use_container_width=True, type="primary"):
        st.stop()

    _ejecutar_borrado(a_borrar, token, cuenta, fecha_str, descripcion="visita(s)")


def _df_visitas(visitas):
    return pd.DataFrame([
        {
            "ID": v.get("id"),
            "Reference": v.get("reference"),
            "Title": v.get("title", ""),
            "Address": v.get("address", ""),
            "Ruta actual": v.get("route", ""),
        }
        for v in visitas
    ])


def _ejecutar_borrado(a_borrar, token, cuenta, fecha_str, descripcion):
    st.markdown("---")
    st.markdown("### 🗑️ Procesando...")

    bloques = [a_borrar[i : i + MAX_BLOCK_SIZE] for i in range(0, len(a_borrar), MAX_BLOCK_SIZE)]
    barra, contador, cont_bloques = create_progress_tracker(len(bloques), "Eliminando...")
    eliminadas = 0
    errores = []
    retry_msg = st.empty()
    retry_state = {"idx": 0, "total": len(bloques)}

    def _on_retry(attempt, max_r, wait, err):
        short = (err or "")[:80]
        retry_msg.warning(
            f"Bloque {retry_state['idx'] + 1}/{retry_state['total']}: "
            f"reintentando {attempt}/{max_r} en {wait}s ({short})"
        )

    for idx, bloque in enumerate(bloques):
        retry_state["idx"] = idx
        ok, status, resp = limpiar_visitas_bloque(bloque, token, on_retry=_on_retry)
        retry_msg.empty()

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

    st.markdown("---")
    st.markdown("### 📊 Resumen")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.markdown(render_stat(cuenta, "Cuenta"), unsafe_allow_html=True)
    with col_b:
        st.markdown(render_stat(eliminadas, "Visitas eliminadas"), unsafe_allow_html=True)
    with col_c:
        st.markdown(render_stat(len(errores), "Bloques con error"), unsafe_allow_html=True)

    if eliminadas == len(a_borrar):
        st.success(f"✅ ¡Completado! Se eliminaron {eliminadas} {descripcion} de la fecha {fecha_str}.")
    else:
        st.warning(f"⚠️ Se eliminaron {eliminadas}/{len(a_borrar)} {descripcion}.")

    _reset_estado()


if __name__ == "__main__":
    pagina_eliminar_visitas()
