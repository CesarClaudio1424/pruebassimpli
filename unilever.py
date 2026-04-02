import streamlit as st
import csv
import io
import time
import requests
import pandas as pd
from config import API_BASE, CLEANUP_TIMEOUT, EDIT_DELAY, MAX_BLOCK_SIZE
from utils import (
    render_header, render_guide, render_stat, render_label,
    render_tip, render_error_item,
    create_progress_tracker, update_progress, finish_progress, scroll_to_bottom,
)

AGENCIAS = ["Tláhuac", "Monterrey", "Hermosillo", "Mérida", "Mexicali"]

AGENCIA_TOKENS = {
    "Tláhuac": "token_tlahuac",
    "Monterrey": "token_monterrey",
    "Hermosillo": "token_hermosillo",
    "Mérida": "token_merida",
    "Mexicali": "token_mexicali",
}


def _leer_csv(archivo):
    contenido = archivo.read().decode("ISO-8859-1")
    lector = csv.DictReader(io.StringIO(contenido))
    return list(lector)


def _leer_xlsx(archivo):
    df = pd.read_excel(archivo, dtype=str)
    df = df.fillna("")
    return df.to_dict(orient="records")


def _load_token(agencia):
    key = AGENCIA_TOKENS[agencia]
    try:
        return getattr(st.secrets.cuentas_unilever, key)
    except (AttributeError, KeyError):
        return None


def _obtener_visitas_fecha(token, fecha):
    headers = {"Authorization": f"Token {token}"}
    url = f"{API_BASE}/routes/visits/?planned_date={fecha}"
    visitas = []
    while url:
        resp = requests.get(url, headers=headers, timeout=CLEANUP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            visitas.extend(data)
            url = None
        else:
            visitas.extend(data.get("results", []))
            url = data.get("next")
    return visitas


def _calcular_tamano_bloque(total):
    bloque = total // 5
    if bloque >= MAX_BLOCK_SIZE:
        return MAX_BLOCK_SIZE
    if bloque < 1:
        return 1
    return bloque


def _enviar_visitas(bloque, token):
    headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
    try:
        response = requests.put(f"{API_BASE}/routes/visits/", headers=headers, json=bloque, timeout=CLEANUP_TIMEOUT)
        time.sleep(EDIT_DELAY)
        return response.status_code, response.text
    except requests.exceptions.RequestException as e:
        return 0, f"Error de conexion: {str(e)}"


def _to_number(value):
    if value is None:
        return None
    try:
        return float(str(value).strip().replace(",", "."))
    except (ValueError, TypeError):
        return None


def _construir_payload(visita_api, row_maestro, es_monterrey):
    payload = {
        "id": visita_api["id"],
        "reference": visita_api.get("reference", ""),
        "title": visita_api.get("title", ""),
        "address": visita_api.get("address", ""),
    }
    load_2 = _to_number(row_maestro.get("load_2", ""))
    load_3 = _to_number(row_maestro.get("load_3", ""))
    if load_2 is not None:
        payload["load_2"] = load_2
    if load_3 is not None:
        payload["load_3"] = load_3
    if es_monterrey:
        if row_maestro.get("window_start"):
            payload["window_start"] = row_maestro["window_start"]
        if row_maestro.get("window_end"):
            payload["window_end"] = row_maestro["window_end"]
    return payload


def pagina_unilever():
    render_header("Unilever", "Actualiza cargas y ventanas horarias por agencia")

    render_guide(
        steps=[
            '<strong>Sube el archivo maestro (Ruteo Dinámico)</strong> — CSV con columnas <code>ID</code>, <code>load_2</code>, <code>load_3</code> y opcionalmente <code>window_start</code>, <code>window_end</code>.',
            '<strong>Selecciona la fecha del ruteo</strong> — Se consultaran las visitas de esa fecha en cada cuenta para obtener los IDs de SimpliRoute.',
            '<strong>Sube los archivos por agencia</strong> — Cada agencia tiene su propio cuadro. El Excel (.xlsx) debe tener la columna <code>ID</code>.',
            '<strong>Procesa la edicion</strong> — Se cruzan los <code>ID</code> del archivo de agencia con el maestro y el <code>reference</code> de la API. Se actualizan <code>load_2</code> y <code>load_3</code>. Para <strong>Monterrey</strong> tambien ventanas horarias.',
        ],
        tip='Los tokens de cada agencia se cargan automaticamente desde la configuracion. El ID de cada visita en SimpliRoute se obtiene consultando la API por fecha y cruzando la columna <code>ID</code> con el campo <code>reference</code>.',
    )

    # --- Paso 1: Archivo maestro ---
    render_label("Paso 1 · Archivo maestro (Ruteo Dinámico)")
    archivo_maestro = st.file_uploader(
        "Ruteo Dinámico", type=["csv"], label_visibility="collapsed",
        help="CSV con ID, load_2, load_3, window_start, window_end",
        key="unilever_maestro",
    )

    if not archivo_maestro:
        render_tip(
            'Sube el archivo <strong>Ruteo Dinámico</strong> (CSV). Debe tener al menos la columna '
            '<code>ID</code> junto con <code>load_2</code>, <code>load_3</code> y opcionalmente '
            '<code>window_start</code>, <code>window_end</code>.'
        )
        st.stop()

    datos_maestro = _leer_csv(archivo_maestro)
    if not datos_maestro:
        st.error("El archivo maestro esta vacio o no se pudo leer.")
        st.stop()

    cols_maestro = list(datos_maestro[0].keys())
    if "ID" not in cols_maestro:
        st.error("El archivo maestro debe tener una columna **ID**.")
        st.stop()

    maestro_dict = {}
    for row in datos_maestro:
        ref = row.get("ID", "").strip()
        if ref and ref.lower() != "none":
            maestro_dict[ref] = row

    with st.expander(f"Vista previa maestro ({len(datos_maestro)} filas)"):
        st.dataframe(pd.DataFrame(datos_maestro[:20]), use_container_width=True)

    st.markdown(render_stat(f"{len(maestro_dict):,}", "references unicos en maestro"), unsafe_allow_html=True)

    # --- Paso 2: Fecha del ruteo ---
    render_label("Paso 2 · Fecha del ruteo")
    fecha_ruteo = st.date_input("Fecha", key="unilever_fecha", label_visibility="collapsed")

    if not fecha_ruteo:
        render_tip('Selecciona la fecha del ruteo para consultar las visitas en la API.')
        st.stop()

    fecha_str = fecha_ruteo.strftime("%Y-%m-%d")

    # --- Paso 3: Archivos por agencia ---
    render_label("Paso 3 · Archivos por agencia")

    # Verificar tokens disponibles
    tokens_faltantes = [ag for ag in AGENCIAS if not _load_token(ag)]
    if tokens_faltantes:
        render_tip(
            f'<strong>⚠️ Tokens no configurados:</strong> {", ".join(tokens_faltantes)}. '
            'Agrega los tokens en <code>[cuentas_unilever]</code> de <code>secrets.toml</code>.',
            warning=True,
        )

    tabs = st.tabs(AGENCIAS)
    archivos_agencia = {}

    for i, agencia in enumerate(AGENCIAS):
        with tabs[i]:
            token = _load_token(agencia)
            if not token:
                render_tip(
                    f'<strong>⚠️ Sin token:</strong> No se encontro <code>{AGENCIA_TOKENS[agencia]}</code> en '
                    '<code>[cuentas_unilever]</code> de <code>secrets.toml</code>.',
                    warning=True,
                )
                continue

            if agencia == "Monterrey":
                render_tip(
                    '<strong>Excepcion Monterrey:</strong> Ademas de <code>load_2</code> y <code>load_3</code>, '
                    'tambien se actualizaran <code>window_start</code> y <code>window_end</code> desde el archivo maestro.'
                )

            archivo = st.file_uploader(
                f"Archivo {agencia}", type=["xlsx"], label_visibility="collapsed",
                help=f"Excel con ID para {agencia}",
                key=f"unilever_{agencia}",
            )
            if archivo:
                datos = _leer_xlsx(archivo)
                if not datos:
                    st.error(f"El archivo de {agencia} esta vacio o no se pudo leer. Asegurate de que sea un archivo .xlsx valido.")
                    continue

                cols = list(datos[0].keys())
                if "ID" not in cols:
                    st.error(f"El archivo de **{agencia}** debe tener la columna **ID**.")
                    continue

                refs_agencia = [row.get("ID", "").strip() for row in datos if row.get("ID", "").strip() and row.get("ID", "").strip().lower() != "none"]
                archivos_agencia[agencia] = refs_agencia
                matches = sum(1 for ref in refs_agencia if ref in maestro_dict)

                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(render_stat(f"{len(refs_agencia):,}", "references cargados"), unsafe_allow_html=True)
                with col2:
                    st.markdown(render_stat(f"{matches:,}", "coincidencias con maestro"), unsafe_allow_html=True)

                with st.expander("Vista previa (primeras 20 filas)"):
                    st.dataframe(pd.DataFrame(datos[:20]), use_container_width=True)
            else:
                render_tip(f'Sube el archivo Excel (.xlsx) de <strong>{agencia}</strong> con la columna <code>ID</code>.')

    if not archivos_agencia:
        render_tip('Sube al menos un archivo de agencia para poder procesar.', warning=True)
        st.stop()

    # --- Paso 4: Procesar ---
    render_label("Paso 4 · Revisar y procesar")

    total_refs = sum(len(refs) for refs in archivos_agencia.values())
    total_matches_maestro = sum(
        sum(1 for ref in refs if ref in maestro_dict)
        for refs in archivos_agencia.values()
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(render_stat(len(archivos_agencia), "agencias cargadas"), unsafe_allow_html=True)
    with col2:
        st.markdown(render_stat(f"{total_refs:,}", "references totales"), unsafe_allow_html=True)
    with col3:
        st.markdown(render_stat(f"{total_matches_maestro:,}", "con datos en maestro"), unsafe_allow_html=True)

    if total_matches_maestro == 0:
        st.warning("No hay coincidencias entre el archivo maestro y los archivos de agencia. Verifica que los ID coincidan.")
        st.stop()

    render_tip(
        f'Se consultaran las visitas del <strong>{fecha_str}</strong> en cada cuenta '
        'para obtener los IDs y cruzar con los references cargados.'
    )

    if not st.button("Procesar edicion", type="primary", key="btn_unilever"):
        st.stop()

    # --- Envio por agencia ---
    total_editadas = 0
    total_sin_match = 0
    total_errores_bloques = 0

    for agencia, refs_agencia in archivos_agencia.items():
        es_monterrey = agencia == "Monterrey"
        token = _load_token(agencia)

        st.markdown(f"---")
        st.markdown(f"**{agencia}**")

        # 1) Consultar visitas de la fecha
        with st.spinner(f"Consultando visitas de {agencia} ({fecha_str})..."):
            try:
                visitas_api = _obtener_visitas_fecha(token, fecha_str)
            except Exception as e:
                st.error(f"Error al consultar visitas de {agencia}: {e}")
                continue

        # 2) Construir mapa reference -> visita desde la API
        api_ref_map = {}
        for v in visitas_api:
            ref_val = v.get("reference")
            if ref_val is None:
                continue
            ref = str(ref_val).strip()
            if ref:
                api_ref_map[ref] = v

        # 3) Cruzar: agencia file refs ∩ maestro ∩ API
        payloads = []
        sin_match_api = []
        sin_match_maestro = []

        for ref in refs_agencia:
            if ref not in maestro_dict:
                sin_match_maestro.append(ref)
                continue
            if ref not in api_ref_map:
                sin_match_api.append(ref)
                continue
            payloads.append(_construir_payload(api_ref_map[ref], maestro_dict[ref], es_monterrey))

        # Stats
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(render_stat(f"{len(visitas_api):,}", "visitas en API"), unsafe_allow_html=True)
        with col2:
            st.markdown(render_stat(f"{len(payloads):,}", "a editar"), unsafe_allow_html=True)
        with col3:
            sin_total = len(sin_match_api) + len(sin_match_maestro)
            st.markdown(render_stat(f"{sin_total:,}", "sin coincidencia"), unsafe_allow_html=True)

        if sin_match_api:
            with st.expander(f"{len(sin_match_api)} references no encontrados en API"):
                st.code("\n".join(sin_match_api[:100]))
        if sin_match_maestro:
            with st.expander(f"{len(sin_match_maestro)} references no encontrados en maestro"):
                st.code("\n".join(sin_match_maestro[:100]))

        total_sin_match += len(sin_match_api) + len(sin_match_maestro)

        if not payloads:
            st.info(f"{agencia}: sin visitas a editar.")
            continue

        # 4) Enviar en lotes
        block_size = _calcular_tamano_bloque(len(payloads))
        barra, contador, contenedor_errores = create_progress_tracker(len(payloads), f"Editando {agencia}...")
        editadas_agencia = 0

        for i in range(0, len(payloads), block_size):
            bloque = payloads[i : i + block_size]
            num_bloque = i // block_size + 1
            codigo, respuesta = _enviar_visitas(bloque, token)

            with st.expander(f"{agencia} — Bloque {num_bloque} (HTTP {codigo})", expanded=codigo != 200):
                st.markdown("**Request (payload enviado):**")
                st.json(bloque)
                st.markdown("**Response:**")
                st.code(respuesta, language="json")

            if codigo == 200:
                editadas_agencia += len(bloque)
            else:
                total_errores_bloques += 1
                with contenedor_errores:
                    render_error_item(f"{agencia} — Bloque {num_bloque} (HTTP {codigo}): {respuesta}")

            procesados = min(i + block_size, len(payloads))
            update_progress(barra, contador, procesados, len(payloads), f"Editando {agencia}...")

        finish_progress(barra)
        total_editadas += editadas_agencia

    # --- Resumen final ---
    st.markdown("---")
    if total_editadas > 0:
        st.success(f"{total_editadas} visitas editadas correctamente")
    if total_sin_match > 0:
        st.warning(f"{total_sin_match} references sin coincidencia (omitidos)")
    if total_errores_bloques > 0:
        st.error(f"{total_errores_bloques} bloque(s) con error")

    scroll_to_bottom()
