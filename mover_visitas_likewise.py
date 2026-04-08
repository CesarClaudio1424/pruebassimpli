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


def buscar_por_reference(reference, token):
    """Busca visita por reference. Returns (visita | None, req_info dict)."""
    url = f"{API_BASE}/routes/visits/reference/{reference}/"
    info = {"url": url, "status": None, "response": None}
    try:
        r = requests.get(url, headers=_headers(token), timeout=REQUEST_TIMEOUT)
        info["status"] = r.status_code
        try:
            info["response"] = r.json()
        except Exception:
            info["response"] = r.text
        if r.status_code == 200:
            data = r.json()
            # Respuesta paginada: {"count": N, "results": [...]}
            if isinstance(data, dict) and "results" in data:
                results = data["results"]
                return (results[0] if results else None), info
            if isinstance(data, list):
                return (data[0] if data else None), info
            if isinstance(data, dict) and data.get("id"):
                return data, info
    except requests.exceptions.RequestException as e:
        info["response"] = str(e)
    return None, info


def buscar_por_id(visit_id, token):
    """Busca visita por ID directo. Returns (visita | None, req_info dict)."""
    url = f"{API_BASE}/routes/visits/{visit_id}/"
    info = {"url": url, "status": None, "response": None}
    try:
        r = requests.get(url, headers=_headers(token), timeout=REQUEST_TIMEOUT)
        info["status"] = r.status_code
        try:
            info["response"] = r.json()
        except Exception:
            info["response"] = r.text
        if r.status_code == 200:
            return r.json(), info
    except requests.exceptions.RequestException as e:
        info["response"] = str(e)
    return None, info


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
            "<strong>Ingresa los valores</strong> — Referencias o IDs, uno por linea.",
            "<strong>Elige fecha destino</strong> — La fecha a la que se moveran las visitas.",
            "<strong>Busca y procesa</strong> — Se mostraran los resultados y se actualizaran en bloques de 500.",
        ],
        tip="Puedes buscar multiples visitas a la vez ingresando varias referencias o IDs separadas por saltos de linea.",
    )

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

    # --- Paso 3: Ingreso de valores ---
    render_label(f"Paso 3 · Ingresa {tipo_busqueda}s")
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

    # --- Paso 4: Fecha destino ---
    render_label("Paso 4 · Fecha destino")
    fecha_destino = st.date_input(
        "Fecha",
        value=date.today(),
        label_visibility="collapsed",
    )
    fecha_destino_str = fecha_destino.strftime("%Y-%m-%d")

    # --- Boton de busqueda ---
    st.markdown("---")
    if st.button("Buscar Visitas", use_container_width=True, type="primary"):
        # Buscar todas las visitas
        visitas_encontradas = []
        no_encontradas = []
        errores = []

        barra, contador, contenedor_errores = create_progress_tracker(len(valores), f"Buscando visita(s)...")

        for idx, valor in enumerate(valores):
            try:
                if tipo_busqueda == "Reference":
                    visita, req_info = buscar_por_reference(valor, token)
                else:
                    visita, req_info = buscar_por_id(valor, token)

                if visita:
                    # Mantener el valor original ingresado como reference si no viene en la respuesta
                    if "reference" not in visita or not visita.get("reference"):
                        visita["reference"] = valor
                    visitas_encontradas.append(visita)
                else:
                    no_encontradas.append(valor)
                    # Mostrar error en expander
                    with contenedor_errores:
                        with st.expander(f"❌ No encontrado: {valor}"):
                            st.code(f"GET {req_info['url']}", language="bash")
                            if req_info.get("status"):
                                st.markdown(f"Status: `{req_info['status']}`")
                            if req_info.get("response"):
                                st.json(req_info["response"])

            except Exception as e:
                errores.append((valor, str(e)))
                no_encontradas.append(valor)

            update_progress(barra, contador, idx + 1, len(valores))

        finish_progress(barra)

        # --- Estadisticas ---
        col1, col2, col3 = st.columns(3)
        with col1:
            render_stat(len(visitas_encontradas), "Visitas encontradas")
        with col2:
            render_stat(len(no_encontradas), "No encontradas")
        with col3:
            render_stat(len(errores), "Errores")

        if visitas_encontradas:
            st.success(f"✅ {len(visitas_encontradas)} visita(s) lista(s) para mover")

            # Mostrar preview
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

                except Exception as e:
                    st.error(f"❌ Error al procesar: {str(e)}")
                    import traceback
                    st.code(traceback.format_exc())


if __name__ == "__main__":
    pagina_mover_visitas_likewise()
