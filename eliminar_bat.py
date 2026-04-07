import streamlit as st
import requests
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import API_BASE, REQUEST_TIMEOUT
from utils import (
    render_header, render_guide, render_label, render_stat,
    render_error_item,
    create_progress_tracker, update_progress, finish_progress,
)

BAT_TOKEN = "c2e6aa9459c12fcd597f5fb27e274411121f8244"
FALLBACK_DAYS = 30


def _headers():
    return {"Authorization": f"Token {BAT_TOKEN}", "Content-Type": "application/json"}


# --- Busqueda por Reference ---

def buscar_por_reference(reference):
    """Returns (visita | None, req_info dict)."""
    url = f"{API_BASE}/routes/visits/reference/{reference}/"
    info = {"url": url, "status": None, "response": None}
    try:
        r = requests.get(url, headers=_headers(), timeout=REQUEST_TIMEOUT)
        info["status"] = r.status_code
        try:
            info["response"] = r.json()
        except Exception:
            info["response"] = r.text
        if r.status_code == 200:
            data = r.json()
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


def _buscar_en_fecha(fecha_str, reference):
    url = f"{API_BASE}/routes/visits/?planned_date={fecha_str}"
    try:
        r = requests.get(url, headers=_headers(), timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            for v in (r.json() or []):
                if str(v.get("reference", "")) == str(reference):
                    return v, fecha_str
    except requests.exceptions.RequestException:
        pass
    return None, fecha_str


def buscar_por_fechas(reference):
    """Returns (visita | None, fallback_info dict)."""
    hoy = date.today()
    fechas = [
        (hoy + timedelta(days=d)).strftime("%Y-%m-%d")
        for d in range(-FALLBACK_DAYS, FALLBACK_DAYS + 1)
    ]
    info = {"total_fechas": len(fechas), "fecha_encontrada": None, "url": None, "response": None}

    executor = ThreadPoolExecutor(max_workers=10)
    futures = {executor.submit(_buscar_en_fecha, f, reference): f for f in fechas}
    resultado = None
    for future in as_completed(futures):
        visita, fecha_str = future.result()
        if visita:
            resultado = visita
            info["fecha_encontrada"] = fecha_str
            info["url"] = f"{API_BASE}/routes/visits/?planned_date={fecha_str}"
            info["response"] = visita
            break
    executor.shutdown(wait=False)
    return resultado, info


# --- Busqueda por ID ---

def buscar_por_id(visit_id):
    """Returns (visita | None, req_info dict)."""
    url = f"{API_BASE}/routes/visits/{visit_id}/"
    info = {"url": url, "status": None, "response": None}
    try:
        r = requests.get(url, headers=_headers(), timeout=REQUEST_TIMEOUT)
        info["status"] = r.status_code
        try:
            info["response"] = r.json()
        except Exception:
            info["response"] = r.text
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, dict) and data.get("id"):
                return data, info
    except requests.exceptions.RequestException as e:
        info["response"] = str(e)
    return None, info


# --- PUT limpieza ---

def limpiar_visita(visita):
    visit_id = visita["id"]
    url = f"{API_BASE}/routes/visits/{visit_id}"
    payload = {
        "reference": None,
        "planned_date": None,
        "route": None,
        "title": visita.get("title") or "Unnamed",
        "address": visita.get("address") or "Unknown",
    }
    try:
        r = requests.put(
            url,
            headers=_headers(),
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        return r.status_code, r.text
    except requests.exceptions.RequestException as e:
        return 0, str(e)


# --- Pagina ---

def pagina_eliminar_bat():
    render_header(
        "Eliminar Visitas BAT",
        "Busca visitas por referencia o ID y limpia su reference, fecha y ruta asignada",
    )

    render_guide(
        steps=[
            "<strong>Selecciona el modo</strong> — Por <em>Reference</em>: busqueda directa + fallback \u00b130 dias. Por <em>ID</em>: consulta directa al endpoint de la visita.",
            "<strong>Ingresa los valores</strong> — Uno por linea.",
            "<strong>Buscar</strong> — Verifica que las visitas existen antes de procesar.",
            "<strong>Eliminar</strong> — Se envia un PUT por cada visita encontrada vaciando reference, planned_date y route.",
        ],
        tip="El token de BAT esta configurado de forma fija. No es necesario ingresar credenciales.",
    )

    # --- Selector de modo ---
    render_label("Modo de busqueda")
    modo = st.radio(
        "Modo",
        ["Reference", "ID"],
        horizontal=True,
        label_visibility="collapsed",
        key="bat_modo",
    )

    # Limpiar resultados al cambiar de modo
    modo_anterior = st.session_state.get("bat_modo_anterior")
    if modo_anterior != modo:
        st.session_state.pop("bat_resultados", None)
        st.session_state.bat_modo_anterior = modo

    # --- Input ---
    if modo == "Reference":
        render_label("Referencias")
        valores_raw = st.text_area(
            "Referencias",
            placeholder="9613078790\n9613078791\n9613078792",
            height=160,
            label_visibility="collapsed",
            key="bat_valores",
        )
    else:
        render_label("IDs de visita")
        valores_raw = st.text_area(
            "IDs",
            placeholder="819028155\n819028156\n819028157",
            height=160,
            label_visibility="collapsed",
            key="bat_valores",
        )

    valores = [v.strip() for v in valores_raw.splitlines() if v.strip()]

    st.markdown("---")

    # --- Boton Buscar ---
    if st.button("Buscar visitas", key="btn_bat_buscar"):
        if not valores:
            st.warning(f"Ingresa al menos un {'reference' if modo == 'Reference' else 'ID'}.")
        else:
            st.session_state.pop("bat_resultados", None)
            total = len(valores)
            barra = st.progress(0, text="Buscando...")
            resultados = []

            for i, valor in enumerate(valores):
                if modo == "Reference":
                    barra.progress((i + 0.3) / total, text=f"Buscando referencia {valor}...")
                    visita, req_principal = buscar_por_reference(valor)

                    req_fallback = None
                    if not visita:
                        barra.progress((i + 0.7) / total, text=f"Fallback fechas {valor}...")
                        visita, req_fallback = buscar_por_fechas(valor)

                    resultados.append({
                        "valor": valor,
                        "modo": "Reference",
                        "visita": visita,
                        "req_principal": req_principal,
                        "req_fallback": req_fallback,
                    })
                else:
                    barra.progress((i + 0.5) / total, text=f"Buscando ID {valor}...")
                    visita, req_principal = buscar_por_id(valor)

                    resultados.append({
                        "valor": valor,
                        "modo": "ID",
                        "visita": visita,
                        "req_principal": req_principal,
                        "req_fallback": None,
                    })

                barra.progress((i + 1) / total, text=f"{i+1}/{total} procesadas")

            barra.progress(1.0, text="Busqueda completada")
            st.session_state.bat_resultados = resultados

    if "bat_resultados" not in st.session_state:
        st.stop()

    resultados = st.session_state.bat_resultados
    encontradas = [r for r in resultados if r["visita"]]
    no_encontradas = [r for r in resultados if not r["visita"]]

    render_label("Resultados de busqueda")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(render_stat(len(encontradas), "visitas encontradas"), unsafe_allow_html=True)
    with col2:
        st.markdown(
            render_stat(
                len(no_encontradas),
                "no encontradas",
                style="background: linear-gradient(135deg, #d32f2f 0%, #b71c1c 100%);",
            ),
            unsafe_allow_html=True,
        )

    for r in resultados:
        if r["visita"]:
            icon, titulo_estado = "\u2713", "encontrada"
        else:
            icon, titulo_estado = "\u2717", "no encontrada"

        prefijo = "Ref" if r["modo"] == "Reference" else "ID"
        with st.expander(f"{icon} {prefijo} {r['valor']} — {titulo_estado}", expanded=not r["visita"]):
            req_p = r["req_principal"]
            label_busqueda = "Busqueda por referencia directa:" if r["modo"] == "Reference" else "Consulta por ID:"
            st.markdown(f"**{label_busqueda}**")
            st.code(f"GET {req_p['url']}", language="bash")
            st.markdown(f"Status: `{req_p['status']}`")
            st.json(req_p["response"])

            req_fb = r.get("req_fallback")
            if req_fb is not None:
                st.markdown(f"**Fallback — escaneadas {req_fb['total_fechas']} fechas (\u00b1{FALLBACK_DAYS} dias):**")
                if req_fb["url"]:
                    st.markdown(f"Encontrada el `{req_fb['fecha_encontrada']}`")
                    st.code(f"GET {req_fb['url']}", language="bash")
                    st.json(req_fb["response"])
                else:
                    st.markdown("No encontrada en ninguna fecha del rango.")

    if not encontradas:
        st.stop()

    st.markdown("---")

    if not st.button(
        f"Eliminar {len(encontradas)} visita(s)",
        type="primary",
        key="btn_bat_eliminar",
    ):
        st.stop()

    total = len(encontradas)
    exitosos = 0
    barra, contador, contenedor_errores = create_progress_tracker(total, "Limpiando visitas...")

    for i, r in enumerate(encontradas):
        visita = r["visita"]
        status, resp_text = limpiar_visita(visita)
        prefijo = "Ref" if r["modo"] == "Reference" else "ID"
        if 200 <= status < 300:
            exitosos += 1
        else:
            with contenedor_errores:
                render_error_item(f"{prefijo} {r['valor']} (ID {visita['id']}) — Error HTTP {status}: {resp_text}")
        update_progress(barra, contador, i + 1, total)

    finish_progress(barra)

    if exitosos > 0:
        st.success(f"{exitosos} de {total} visitas limpiadas correctamente")
        st.session_state.pop("bat_resultados", None)
    if exitosos < total:
        st.error(f"{total - exitosos} visita(s) con error")
