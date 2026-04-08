import streamlit as st
import requests
import pandas as pd
from datetime import date
from config import API_BASE, REQUEST_TIMEOUT, MAX_BLOCK_SIZE, EDIT_DELAY
from utils import (
    render_header, render_guide, render_label, render_stat,
    render_error_item, render_cuenta_badge, render_tip,
    create_progress_tracker, update_progress, finish_progress,
    load_secret, scroll_to_bottom,
)
import time

# Cuentas Likewise con sus tokens
CUENTAS_LIKEWISE = {
    "Telefonica": "token_telefonica",
    "Entel": "token_entel",
    "Omnicanalidad": "token_omnicanalidad",
    "Biobio": "token_biobio",
}


def _headers(token):
    return {"Authorization": f"Token {token}", "Content-Type": "application/json"}


def buscar_visitas_por_fecha(planned_date, token):
    """Obtiene todas las visitas de una fecha. Returns (lista de visitas, req_info dict)."""
    url = f"{API_BASE}/routes/visits/?planned_date={planned_date}"
    info = {"url": url, "status": None, "response": None}
    try:
        r = requests.get(url, headers=_headers(token), timeout=30)
        info["status"] = r.status_code

        # Intentar parsear como JSON
        try:
            info["response"] = r.json()
        except Exception as json_err:
            # Si no es JSON, guardar el texto
            info["response"] = f"HTTP {r.status_code}: {r.text[:500]}"

        # Solo retornar si fue exitoso (200)
        if r.status_code == 200:
            try:
                return r.json() or [], info
            except:
                return [], info
        else:
            # Si no es 200, mostrar el error
            return [], info

    except requests.exceptions.RequestException as e:
        info["status"] = 0
        info["response"] = f"Error de conexion: {str(e)}"

    return [], info


def filtrar_visitas(visitas, valores, tipo_busqueda):
    """Filtra visitas por reference o ID. Returns lista de visitas encontradas."""
    encontradas = []
    valores_set = set(str(v).strip().lower() for v in valores)

    for v in visitas:
        if tipo_busqueda == "Reference":
            ref = str(v.get("reference", "")).strip().lower()
            if ref in valores_set:
                encontradas.append(v)
        else:  # ID
            vid = str(v.get("id", "")).strip().lower()
            if vid in valores_set:
                encontradas.append(v)

    return encontradas


def editar_visitas_bloque(visitas, planned_date, token):
    """Edita un bloque de visitas. Returns (success, status, response)."""
    url = f"{API_BASE}/routes/visits/"
    payload = []

    for v in visitas:
        # Mantener campos importantes, cambiar planned_date
        item = {
            "id": v.get("id"),
            "reference": v.get("reference"),
            "title": v.get("title"),
            "address": v.get("address"),
            "planned_date": planned_date,
        }
        payload.append(item)

    try:
        r = requests.put(
            url,
            headers=_headers(token),
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        return r.status_code == 200, r.status_code, r.text
    except requests.exceptions.RequestException as e:
        return False, 0, str(e)


def pagina_mover_visitas_likewise():
    render_header(
        "Mover Visitas Likewise",
        "Busca visitas y actualiza su fecha de planificacion",
    )

    render_guide(
        steps=[
            "<strong>Selecciona tipo de busqueda</strong> — Puedes buscar por Reference o por ID de visita.",
            "<strong>Elige la cuenta</strong> — Selecciona una de las cuatro cuentas Likewise.",
            "<strong>Ingresa fecha de origen</strong> — La fecha en la que estan las visitas actualmente.",
            "<strong>Ingresa los valores</strong> — Referencias o IDs, uno por linea.",
            "<strong>Elige fecha destino</strong> — La fecha a la que se moveran las visitas.",
            "<strong>Busca y procesa</strong> — Se mostraran los resultados y se actualizaran en bloques de 500.",
        ],
        tip="La busqueda filtra por fecha y luego por reference o ID, lo que es mas eficiente que buscar uno por uno.",
    )

    # Inicializar session_state
    if "mvl_visitas_encontradas" not in st.session_state:
        st.session_state.mvl_visitas_encontradas = None
    if "mvl_fecha_origen_str" not in st.session_state:
        st.session_state.mvl_fecha_origen_str = None
    if "mvl_fecha_destino_str" not in st.session_state:
        st.session_state.mvl_fecha_destino_str = None
    if "mvl_token" not in st.session_state:
        st.session_state.mvl_token = None

    # --- Paso 1: Tipo de busqueda ---
    render_label("Paso 1 · Tipo de busqueda")
    tipo_busqueda = st.radio(
        "Buscar por",
        ["Reference", "ID"],
        horizontal=True,
        label_visibility="collapsed",
    )

    # --- Paso 2: Cuenta ---
    render_label("Paso 2 · Cuenta")
    cuenta = st.radio(
        "Cuenta",
        list(CUENTAS_LIKEWISE.keys()),
        horizontal=True,
        label_visibility="collapsed",
    )
    render_cuenta_badge(f"Cuenta seleccionada: <strong>{cuenta}</strong>")

    # Cargar token desde secrets
    token_key = CUENTAS_LIKEWISE[cuenta]
    token = load_secret(token_key, f"Token de {cuenta} no encontrado en secrets. Configura `[api_config]` con `{token_key}`.")
    if not token:
        st.stop()

    # --- Paso 3: Fecha de origen ---
    render_label("Paso 3 · Fecha de origen")
    fecha_origen = st.date_input(
        "Fecha donde están las visitas",
        value=date.today(),
        label_visibility="collapsed",
    )
    fecha_origen_str = fecha_origen.strftime("%Y-%m-%d")

    # --- Paso 4: Ingreso de valores ---
    render_label(f"Paso 4 · Ingresa {tipo_busqueda}s")
    placeholder = f"Ingresa los {tipo_busqueda.lower()}s a buscar (uno por linea)"
    valores_input = st.text_area(
        "Valores",
        placeholder=placeholder,
        label_visibility="collapsed",
        height=150,
    )

    if not valores_input or not valores_input.strip():
        render_tip(f'Ingresa al menos un {tipo_busqueda.lower()} para continuar.')
        st.stop()

    valores = [line.strip() for line in valores_input.strip().split("\n") if line.strip()]

    # --- Paso 5: Fecha destino ---
    render_label("Paso 5 · Fecha destino")
    fecha_destino = st.date_input(
        "Fecha",
        value=date.today(),
        label_visibility="collapsed",
    )
    fecha_destino_str = fecha_destino.strftime("%Y-%m-%d")

    # --- Boton de busqueda ---
    st.markdown("---")
    if st.button("Buscar Visitas", use_container_width=True, type="primary"):
        barra, contador, contenedor_errores = create_progress_tracker(1, f"Buscando visita(s) en {fecha_origen_str}...")

        try:
            # Debug: mostrar token parcialmente
            token_debug = token[:10] + "..." + token[-10:] if token else "SIN TOKEN"

            st.info(f"🔍 **Debug Info:**\n- URL: `{API_BASE}/routes/visits/?planned_date={fecha_origen_str}`\n- Token: `{token_debug}`\n- Tipo búsqueda: {tipo_busqueda}\n- Valores a buscar: {', '.join(valores)}")

            # Obtener todas las visitas de la fecha de origen
            todas_visitas, req_info = buscar_visitas_por_fecha(fecha_origen_str, token)

            with contenedor_errores:
                with st.expander("📋 Request de busqueda (expandir para detalles)", expanded=True):
                    st.code(f"GET {req_info['url']}", language="bash")
                    st.markdown(f"**Status:** `{req_info['status']}`")
                    st.markdown(f"**Total de visitas en {fecha_origen_str}:** `{len(todas_visitas)}`")
                    if req_info.get('response'):
                        st.markdown("**Response preview:**")
                        st.json(req_info['response'][:3] if isinstance(req_info['response'], list) else req_info['response'])

            # Filtrar por reference o ID
            visitas_encontradas = filtrar_visitas(todas_visitas, valores, tipo_busqueda)
            no_encontradas = [v for v in valores if v not in [
                str(vis.get("reference" if tipo_busqueda == "Reference" else "id", "")).strip()
                for vis in visitas_encontradas
            ]]

            st.info(f"✅ **Resultados:** {len(visitas_encontradas)} encontradas, {len(no_encontradas)} no encontradas")

            update_progress(barra, contador, 1, 1)

        except Exception as e:
            with contenedor_errores:
                st.error(f"Error al buscar: {str(e)}")
            visitas_encontradas = []
            no_encontradas = valores

        finish_progress(barra)

        # Guardar en session_state
        st.session_state.mvl_visitas_encontradas = visitas_encontradas
        st.session_state.mvl_fecha_origen_str = fecha_origen_str
        st.session_state.mvl_fecha_destino_str = fecha_destino_str
        st.session_state.mvl_token = token

        # --- Estadisticas ---
        col1, col2 = st.columns(2)
        with col1:
            render_stat(len(visitas_encontradas), "Visitas encontradas")
        with col2:
            render_stat(len(no_encontradas), "No encontradas")

        if visitas_encontradas:
            st.success(f"✅ {len(visitas_encontradas)} visita(s) lista(s) para mover")

    # --- Mostrar preview si hay visitas ---
    if st.session_state.mvl_visitas_encontradas:
        visitas_encontradas = st.session_state.mvl_visitas_encontradas
        fecha_destino_str = st.session_state.mvl_fecha_destino_str
        token = st.session_state.mvl_token

        with st.expander("📋 Preview de visitas a mover", expanded=False):
            df_preview = pd.DataFrame([
                {
                    "ID": v.get("id"),
                    "Reference": v.get("reference"),
                    "Title": v.get("title", ""),
                    "Fecha actual": v.get("planned_date", ""),
                    "Nueva fecha": fecha_destino_str,
                }
                for v in visitas_encontradas
            ])
            st.dataframe(df_preview, use_container_width=True, hide_index=True)

        # Boton para procesar
        if st.button("Mover Visitas (actualizar en SimpliRoute)", use_container_width=True, type="primary"):
            try:
                st.markdown("---")
                st.markdown("### 📤 Procesando...")

                # Dividir en bloques
                bloques = [
                    visitas_encontradas[i : i + MAX_BLOCK_SIZE]
                    for i in range(0, len(visitas_encontradas), MAX_BLOCK_SIZE)
                ]

                barra, contador, contenedor_bloques = create_progress_tracker(len(bloques), f"Moviendo visita(s)...")
                procesadas = 0
                errores_edicion = []

                for bloque_idx, bloque in enumerate(bloques):
                    success, status, response = editar_visitas_bloque(bloque, fecha_destino_str, token)

                    if success:
                        procesadas += len(bloque)
                        with st.expander(f"✅ Bloque {bloque_idx + 1}/{len(bloques)} — {len(bloque)} visita(s)", expanded=False):
                            st.code(f"PUT {API_BASE}/routes/visits/", language="bash")
                            st.markdown(f"Status: `{status}`")
                    else:
                        errores_edicion.append((bloque_idx + 1, status, response))
                        with st.expander(f"❌ Bloque {bloque_idx + 1}/{len(bloques)} — ERROR", expanded=True):
                            st.code(f"PUT {API_BASE}/routes/visits/", language="bash")
                            st.markdown(f"Status: `{status}`")
                            st.write(response)

                    update_progress(barra, contador, bloque_idx + 1, len(bloques))
                    time.sleep(EDIT_DELAY)

                finish_progress(barra)

                # Resultado final
                st.markdown("---")
                col1, col2 = st.columns(2)
                with col1:
                    render_stat(procesadas, "Visitas movidas")
                with col2:
                    render_stat(len(errores_edicion), "Bloques con error")

                if procesadas == len(visitas_encontradas):
                    st.success(f"✅ ¡Completado! Se movieron {procesadas} visita(s) a {fecha_destino_str}")
                else:
                    st.warning(f"⚠️ Se movieron {procesadas}/{len(visitas_encontradas)} visitas")

                # Limpiar session_state
                st.session_state.mvl_visitas_encontradas = None
                st.session_state.mvl_fecha_origen_str = None
                st.session_state.mvl_fecha_destino_str = None
                st.session_state.mvl_token = None

            except Exception as e:
                st.error(f"❌ Error al procesar: {str(e)}")
                import traceback
                st.code(traceback.format_exc())


if __name__ == "__main__":
    pagina_mover_visitas_likewise()
