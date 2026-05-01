import time
import streamlit as st
import requests
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import API_BASE, API_SEND_WEBHOOKS, REQUEST_TIMEOUT, MAX_RETRIES, RETRY_BASE_DELAY
from utils import (
    render_header, render_guide, render_label, render_stat,
    render_error_item, load_secret,
    create_progress_tracker, update_progress, finish_progress,
)


def _headers(token):
    return {"Authorization": f"Token {token}", "Content-Type": "application/json"}


def _buscar_reference(reference, token):
    url = f"{API_BASE}/routes/visits/reference/{reference}/"
    try:
        r = requests.get(url, headers=_headers(token), timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and "results" in data:
                return reference, data["results"], None
            if isinstance(data, list):
                return reference, data, None
            if isinstance(data, dict) and data.get("id"):
                return reference, [data], None
            return reference, [], None
        return reference, [], f"HTTP {r.status_code}"
    except requests.exceptions.RequestException as e:
        return reference, [], str(e)


def _enviar_checkout(token, acc_id, planned_date, visit_id, reference):
    payload = {
        "account_ids": [int(acc_id)],
        "planned_date": planned_date,
        "visit_ids": [int(visit_id)],
    }
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.post(API_SEND_WEBHOOKS, headers=_headers(token), json=payload, timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                return reference, visit_id, True, ""
            if r.status_code >= 500 and attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                continue
            return reference, visit_id, False, f"HTTP {r.status_code}: {r.text[:120]}"
        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                continue
            return reference, visit_id, False, str(e)
    return reference, visit_id, False, "Reintentos agotados"


def _dedup_ordered(lst):
    seen = set()
    return [x for x in lst if not (x in seen or seen.add(x))]


def pagina_checkout_bat():
    render_header("Checkout BAT", "Busca visitas por referencia y envía webhook de checkout")

    render_guide(
        steps=[
            "<strong>Referencias</strong> — Una por línea en el campo de texto, o sube un Excel y elige la columna.",
            "<strong>Buscar</strong> — Consulta el endpoint de referencia (3 requests en paralelo).",
            "<strong>Checkout</strong> — Envía el webhook de checkout por cada visita encontrada (3 en paralelo).",
        ],
    )

    token = load_secret(
        "bat_token",
        "No se encontró `bat_token` en `.streamlit/secrets.toml`. Configura `[api_config]` con `bat_token`.",
    )

    # --- Input de referencias ---
    render_label("Paso 1 · Referencias a buscar")
    modo = st.radio(
        "Modo",
        ["Texto", "Excel"],
        horizontal=True,
        label_visibility="collapsed",
        key="bat_modo",
    )

    references = []

    if modo == "Texto":
        texto = st.text_area(
            "Referencias",
            placeholder="9613078790\n9613078791\n9613078792",
            height=150,
            label_visibility="collapsed",
            key="bat_texto",
        )
        if texto and texto.strip():
            references = _dedup_ordered(
                [r.strip() for r in texto.strip().splitlines() if r.strip()]
            )
    else:
        archivo = st.file_uploader(
            "Archivo Excel",
            type=["xlsx", "xls"],
            label_visibility="collapsed",
            key="bat_archivo",
        )
        if archivo:
            try:
                df_raw = pd.read_excel(archivo)
                columnas = list(df_raw.columns)
                render_label("Columna con las referencias")
                col_sel = st.selectbox(
                    "Columna",
                    columnas,
                    label_visibility="collapsed",
                    key="bat_columna",
                )
                references = _dedup_ordered([
                    str(v).strip()
                    for v in df_raw[col_sel].dropna()
                    if str(v).strip() and str(v).strip().lower() != "nan"
                ])
                st.caption(f"{len(references)} referencias únicas en la columna **{col_sel}**")
            except Exception as e:
                st.error(f"Error al leer el archivo: {e}")
                st.stop()

    if not references:
        st.stop()

    st.markdown(render_stat(len(references), "referencias a buscar"), unsafe_allow_html=True)

    # --- Buscar ---
    if st.button("Buscar visitas", key="bat_buscar"):
        st.session_state.pop("bat_resultados", None)
        total = len(references)
        barra = st.progress(0, text="Buscando...")
        completados = 0
        resultados = {}

        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = {ex.submit(_buscar_reference, ref, token): ref for ref in references}
            for future in as_completed(futures):
                ref, visitas, err = future.result()
                resultados[ref] = {"visitas": visitas, "error": err}
                completados += 1
                barra.progress(completados / total, text=f"Buscando... {completados}/{total}")

        barra.progress(1.0, text="Búsqueda completada")
        st.session_state.bat_resultados = resultados

    if "bat_resultados" not in st.session_state:
        st.stop()

    resultados = st.session_state.bat_resultados

    # --- Estadísticas ---
    encontradas = {ref: r for ref, r in resultados.items() if r["visitas"]}
    no_encontradas = {ref: r for ref, r in resultados.items() if not r["visitas"]}
    total_visitas = sum(len(r["visitas"]) for r in encontradas.values())

    render_label("Resultados de búsqueda")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(render_stat(len(encontradas), "referencias encontradas"), unsafe_allow_html=True)
    with col2:
        st.markdown(render_stat(total_visitas, "visitas a procesar"), unsafe_allow_html=True)
    with col3:
        st.markdown(
            render_stat(
                len(no_encontradas),
                "no encontradas",
                style="background: linear-gradient(135deg, #d32f2f 0%, #b71c1c 100%);",
            ),
            unsafe_allow_html=True,
        )

    if no_encontradas:
        with st.expander(f"No encontradas ({len(no_encontradas)})"):
            for ref, r in no_encontradas.items():
                render_error_item(f"{ref}" + (f" — {r['error']}" if r["error"] else ""))

    if not encontradas:
        st.stop()

    # Aplanar todas las visitas de todos los references
    items = []
    for ref, r in encontradas.items():
        for visita in r["visitas"]:
            items.append({
                "reference": ref,
                "visit_id": visita["id"],
                "account_id": visita["account_id"],
                "planned_date": visita["planned_date"],
            })

    render_label("Visitas a procesar")
    df_preview = pd.DataFrame([
        {
            "Referencia": it["reference"],
            "Visit ID": it["visit_id"],
            "Account ID": it["account_id"],
            "Fecha": it["planned_date"],
        }
        for it in items
    ])
    st.dataframe(df_preview, use_container_width=True, hide_index=True)

    if not st.button(f"Enviar checkout ({len(items)} visitas)", type="primary", key="bat_checkout"):
        st.stop()

    # --- Checkout concurrente ---
    total_co = len(items)
    exitosos = 0
    completados_co = 0
    barra_co, contador_co, contenedor_errores = create_progress_tracker(total_co, "Enviando checkout...")

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {
            ex.submit(_enviar_checkout, token, it["account_id"], it["planned_date"], it["visit_id"], it["reference"]): it
            for it in items
        }
        for future in as_completed(futures):
            ref, vid, ok, detalle = future.result()
            completados_co += 1
            if ok:
                exitosos += 1
            else:
                with contenedor_errores:
                    render_error_item(f"Ref {ref} (visita {vid}) — {detalle}")
            update_progress(barra_co, contador_co, completados_co, total_co, "Enviando checkout...")

    finish_progress(barra_co)

    if exitosos > 0:
        st.success(f"{exitosos} de {total_co} checkouts enviados correctamente")
    if exitosos < total_co:
        st.error(f"{total_co - exitosos} de {total_co} fallaron")
