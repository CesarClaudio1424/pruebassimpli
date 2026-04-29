import streamlit as st
import requests
import pandas as pd
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from config import API_BASE, REQUEST_TIMEOUT, EDIT_TIMEOUT, MAX_BLOCK_SIZE, MAX_RETRIES, RETRY_BASE_DELAY
from utils import (
    render_header, render_guide, render_label, render_stat,
    render_cuenta_badge, render_tip,
    create_progress_tracker, update_progress, finish_progress,
)

CLEANUP_WORKERS = 10


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
    """Agrupa por reference, conserva la visita con ID mas bajo, marca el resto."""
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


def _fetch_visita(visit_id, token):
    """GET /v1/routes/visits/{id}/ — retorna (id, visita_dict_or_None, error_or_None)"""
    url = f"{API_BASE}/routes/visits/{visit_id}/"
    try:
        r = requests.get(url, headers=_headers(token), timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return visit_id, r.json(), None
        return visit_id, None, f"HTTP {r.status_code}: {r.text[:200]}"
    except requests.exceptions.RequestException as e:
        return visit_id, None, str(e)


def _parsear_ids_texto(texto):
    ids = []
    for linea in texto.splitlines():
        val = linea.strip()
        if val:
            try:
                ids.append(int(val))
            except ValueError:
                pass
    return ids


def _parsear_ids_archivo(archivo):
    try:
        name = archivo.name.lower()
        if name.endswith(".xlsx"):
            df = pd.read_excel(archivo, header=0)
        else:
            try:
                df = pd.read_csv(archivo, encoding="utf-8")
            except UnicodeDecodeError:
                df = pd.read_csv(archivo, encoding="latin-1")
        col = next((c for c in df.columns if str(c).strip().lower() == "id"), df.columns[0])
        ids = []
        for val in df[col].dropna():
            try:
                ids.append(int(val))
            except (ValueError, TypeError):
                pass
        return ids, None
    except Exception as e:
        return [], str(e)


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


def _paso_token(key_prefix):
    """Renderiza el input de token, valida y retorna (token, cuenta) o (None, None)."""
    render_label("Paso 1 · Token de API")
    token_input = st.text_input(
        "Token",
        type="password",
        label_visibility="collapsed",
        placeholder="Ingresa el token de API",
        key=f"{key_prefix}token_input",
    )
    if not token_input:
        render_tip("Ingresa el token de API de la cuenta.")
        return None, None
    token = token_input.strip()
    valido, cuenta = validar_cuenta(token)
    if not valido:
        st.error("Token invalido. Revisa tu token de API.")
        return None, None
    render_cuenta_badge(f"✓ Conectado a: <strong>{cuenta}</strong>")
    return token, cuenta


def _paso_fecha_y_busqueda(token, cuenta, label_boton, spinner_fn, prefix):
    """Paso de fecha + boton de busqueda. spinner_fn(visitas) guarda resultados en session_state."""
    render_label("Paso 2 · Fecha de las visitas")
    fecha = st.date_input(
        "Fecha",
        value=date.today(),
        label_visibility="collapsed",
        key=f"{prefix}fecha_input",
    )
    fecha_str = fecha.strftime("%Y-%m-%d")

    if st.session_state.get(f"{prefix}fecha") != fecha_str or st.session_state.get(f"{prefix}token") != token:
        st.session_state.pop(f"{prefix}a_borrar", None)
        st.session_state.pop(f"{prefix}grupos", None)

    st.markdown("---")
    if st.button(label_boton, use_container_width=True, type="primary", key=f"{prefix}buscar_btn"):
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
            return

        spinner_fn(visitas)
        st.session_state[f"{prefix}visitas"] = visitas
        st.session_state[f"{prefix}fecha"] = fecha_str
        st.session_state[f"{prefix}token"] = token
        st.session_state[f"{prefix}cuenta"] = cuenta


def _ejecutar_borrado(a_borrar, token, cuenta, fecha_str, descripcion, data_keys):
    st.markdown("---")
    st.markdown(f"### 🗑️ Procesando... ({CLEANUP_WORKERS} en paralelo)")

    bloques = [a_borrar[i : i + MAX_BLOCK_SIZE] for i in range(0, len(a_borrar), MAX_BLOCK_SIZE)]
    barra, contador, cont_bloques = create_progress_tracker(len(bloques), "Eliminando...")
    eliminadas = 0
    errores = []
    completados = 0

    with ThreadPoolExecutor(max_workers=CLEANUP_WORKERS) as executor:
        futures = {
            executor.submit(limpiar_visitas_bloque, bloque, token): (idx, bloque)
            for idx, bloque in enumerate(bloques)
        }

        for future in as_completed(futures):
            idx, bloque = futures[future]
            ok, status, resp = future.result()

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

            completados += 1
            update_progress(barra, contador, completados, len(bloques))

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

    if fecha_str:
        ok_msg = f"✅ ¡Completado! Se eliminaron {eliminadas} {descripcion} de la fecha {fecha_str}."
        warn_msg = f"⚠️ Se eliminaron {eliminadas}/{len(a_borrar)} {descripcion}."
    else:
        ok_msg = f"✅ ¡Completado! Se eliminaron {eliminadas} {descripcion}."
        warn_msg = f"⚠️ Se eliminaron {eliminadas}/{len(a_borrar)} {descripcion}."

    if eliminadas == len(a_borrar):
        st.success(ok_msg)
    else:
        st.warning(warn_msg)

    for k in data_keys:
        st.session_state.pop(k, None)


# ── Secciones ─────────────────────────────────────────────────────────────────

_EVD_DATA = ["evd_visitas", "evd_a_borrar", "evd_grupos", "evd_fecha", "evd_token", "evd_cuenta"]
_EVT_DATA = ["evt_visitas", "evt_a_borrar", "evt_fecha", "evt_token", "evt_cuenta"]
_EVID_DATA = ["evid_encontradas", "evid_no_encontradas", "evid_cuenta", "evid_token"]


def _seccion_duplicados():
    render_guide(
        steps=[
            "<strong>Ingresa el token</strong> — Token de API de la cuenta donde estan las visitas.",
            "<strong>Elige la fecha</strong> — Fecha de las visitas a revisar.",
            "<strong>Buscar duplicados</strong> — Se detectan visitas con la misma reference.",
            "<strong>Confirmar eliminacion</strong> — Se conserva el ID mas bajo; el resto se limpia.",
        ],
        tip="Se conserva la visita con el ID mas bajo (la primera creada). El resto se mueve a planned_date=2020-01-01 con route=''.",
    )

    token, cuenta = _paso_token("evd_")
    if not token:
        return

    def _guardar(visitas):
        a_borrar, grupos = detectar_duplicados(visitas)
        st.session_state["evd_a_borrar"] = a_borrar
        st.session_state["evd_grupos"] = grupos

    _paso_fecha_y_busqueda(token, cuenta, "Buscar duplicados", _guardar, "evd_")

    if "evd_a_borrar" not in st.session_state:
        return

    visitas = st.session_state.get("evd_visitas", [])
    a_borrar = st.session_state["evd_a_borrar"]
    grupos = st.session_state.get("evd_grupos", [])
    fecha_str = st.session_state.get("evd_fecha", "")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(render_stat(len(visitas), "Visitas en la fecha"), unsafe_allow_html=True)
    with col2:
        st.markdown(render_stat(len(grupos), "References duplicadas"), unsafe_allow_html=True)
    with col3:
        st.markdown(render_stat(len(a_borrar), "Visitas a eliminar"), unsafe_allow_html=True)

    if not a_borrar:
        st.success("✅ No se detectaron duplicados en la fecha seleccionada.")
        return

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
        key="evd_confirmar",
    )
    if not confirmar:
        return

    if not st.button("Eliminar duplicados", use_container_width=True, type="primary", key="evd_eliminar_btn"):
        return

    _ejecutar_borrado(a_borrar, token, cuenta, fecha_str, "duplicada(s)", _EVD_DATA)


def _seccion_total():
    render_guide(
        steps=[
            "<strong>Ingresa el token</strong> — Token de API de la cuenta donde estan las visitas.",
            "<strong>Elige la fecha</strong> — Fecha cuyas visitas quieres eliminar.",
            "<strong>Buscar visitas</strong> — Se listan todas las visitas del dia.",
            "<strong>Confirmar eliminacion</strong> — Se limpian TODAS las visitas de esa fecha.",
        ],
        tip="Eliminacion total: se borran TODAS las visitas de la fecha, sin importar duplicados. Esta accion no se puede deshacer.",
    )

    token, cuenta = _paso_token("evt_")
    if not token:
        return

    def _guardar(visitas):
        st.session_state["evt_a_borrar"] = list(visitas)

    _paso_fecha_y_busqueda(token, cuenta, "Buscar visitas del dia", _guardar, "evt_")

    if "evt_a_borrar" not in st.session_state:
        return

    visitas = st.session_state.get("evt_visitas", [])
    a_borrar = st.session_state["evt_a_borrar"]
    fecha_str = st.session_state.get("evt_fecha", "")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(render_stat(len(visitas), "Visitas en la fecha"), unsafe_allow_html=True)
    with col2:
        st.markdown(render_stat(len(a_borrar), "Visitas a eliminar"), unsafe_allow_html=True)

    if not a_borrar:
        st.info("No hay visitas en esa fecha.")
        return

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
        key="evt_confirmar",
    )
    if not confirmar:
        return

    if not st.button("Eliminar todas las visitas", use_container_width=True, type="primary", key="evt_eliminar_btn"):
        return

    _ejecutar_borrado(a_borrar, token, cuenta, fecha_str, "visita(s)", _EVT_DATA)


def _seccion_por_id():
    render_guide(
        steps=[
            "<strong>Ingresa el token</strong> — Token de API de la cuenta donde estan las visitas.",
            "<strong>Ingresa los IDs</strong> — Escribe uno por linea en el cuadro de texto, o sube un archivo CSV o XLSX.",
            "<strong>Buscar visitas</strong> — Se consultara cada ID via API.",
            "<strong>Confirmar eliminacion</strong> — Se limpia <code>planned_date</code> a 2020-01-01 y se quita la ruta.",
        ],
        tip="Solo se eliminan las visitas encontradas. Los IDs no encontrados se reportan por separado.",
    )

    token, cuenta = _paso_token("evid_")
    if not token:
        return

    render_label("Paso 2 · IDs de visitas")
    metodo = st.radio(
        "Metodo",
        ["Escribir IDs", "Subir archivo (CSV/XLSX)"],
        horizontal=True,
        key="evid_metodo",
        label_visibility="collapsed",
    )

    ids_raw = []

    if metodo == "Escribir IDs":
        texto = st.text_area(
            "IDs",
            placeholder="Un ID por linea\n123456\n789012\n...",
            height=180,
            key="evid_texto",
            label_visibility="collapsed",
        )
        if texto:
            ids_raw = _parsear_ids_texto(texto)
    else:
        archivo = st.file_uploader(
            "Archivo CSV o XLSX",
            type=["csv", "xlsx"],
            key="evid_archivo",
            label_visibility="collapsed",
        )
        if archivo:
            ids_raw, err_arch = _parsear_ids_archivo(archivo)
            if err_arch:
                st.error(f"Error al leer el archivo: {err_arch}")
                return

    if not ids_raw:
        render_tip("Ingresa al menos un ID de visita.")
        return

    ids_unicos = list(dict.fromkeys(ids_raw))
    st.markdown(render_stat(len(ids_unicos), "IDs ingresados"), unsafe_allow_html=True)

    st.markdown("---")
    if st.button("Buscar visitas", use_container_width=True, type="primary", key="evid_buscar"):
        barra = st.progress(0.0, text="Consultando visitas...")
        encontradas = []
        no_encontradas = []

        with ThreadPoolExecutor(max_workers=CLEANUP_WORKERS) as executor:
            futures = {executor.submit(_fetch_visita, vid, token): vid for vid in ids_unicos}
            completados = 0
            for future in as_completed(futures):
                vid, visita, error = future.result()
                completados += 1
                barra.progress(completados / len(ids_unicos), text=f"Consultando... {completados}/{len(ids_unicos)}")
                if visita is not None:
                    encontradas.append(visita)
                else:
                    no_encontradas.append({"ID": vid, "Error": error})

        barra.empty()
        st.session_state["evid_encontradas"] = encontradas
        st.session_state["evid_no_encontradas"] = no_encontradas
        st.session_state["evid_cuenta"] = cuenta
        st.session_state["evid_token"] = token

    if "evid_encontradas" not in st.session_state:
        return

    encontradas = st.session_state["evid_encontradas"]
    no_encontradas = st.session_state["evid_no_encontradas"]
    cuenta_guardada = st.session_state.get("evid_cuenta", cuenta)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(render_stat(len(encontradas), "Visitas encontradas"), unsafe_allow_html=True)
    with col2:
        st.markdown(render_stat(len(no_encontradas), "IDs no encontrados"), unsafe_allow_html=True)

    if no_encontradas:
        with st.expander(f"⚠️ IDs no encontrados ({len(no_encontradas)})", expanded=False):
            st.dataframe(pd.DataFrame(no_encontradas), use_container_width=True, hide_index=True)

    if not encontradas:
        st.info("No se encontro ninguna visita con los IDs ingresados.")
        return

    with st.expander(f"📄 Visitas a eliminar ({len(encontradas)})", expanded=False):
        st.dataframe(_df_visitas(encontradas), use_container_width=True, hide_index=True)

    render_tip(
        f"Se enviara un PUT bulk a <code>/routes/visits/</code> con <code>planned_date=2020-01-01</code> "
        f"y <code>route=\"\"</code> para <strong>{len(encontradas)}</strong> visita(s), "
        f"en bloques de hasta {MAX_BLOCK_SIZE}."
    )

    confirmar = st.checkbox(
        f"Confirmo que quiero eliminar {len(encontradas)} visita(s) de la cuenta {cuenta_guardada}",
        key="evid_confirmar",
    )
    if not confirmar:
        return

    if not st.button("Eliminar visitas", use_container_width=True, type="primary", key="evid_eliminar_btn"):
        return

    _ejecutar_borrado(encontradas, token, cuenta_guardada, None, "visita(s)", _EVID_DATA)


# ── Entry point ───────────────────────────────────────────────────────────────

def pagina_eliminar_visitas():
    render_header(
        "Eliminar Visitas",
        "Herramienta general para eliminar visitas de cualquier cuenta",
    )

    tab1, tab2, tab3 = st.tabs(["Eliminar duplicados", "Eliminacion total", "Eliminar por ID"])
    with tab1:
        _seccion_duplicados()
    with tab2:
        _seccion_total()
    with tab3:
        _seccion_por_id()


if __name__ == "__main__":
    pagina_eliminar_visitas()
