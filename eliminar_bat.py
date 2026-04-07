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


def limpiar_visita(visit_id):
    url = f"{API_BASE}/routes/visits/{visit_id}"
    try:
        r = requests.put(
            url,
            headers=_headers(),
            json={"reference": "", "planned_date": "", "route": ""},
            timeout=REQUEST_TIMEOUT,
        )
        return r.status_code, r.text
    except requests.exceptions.RequestException as e:
        return 0, str(e)


def pagina_eliminar_bat():
    render_header(
        "Eliminar Visitas BAT",
        "Busca visitas por referencia y limpia su reference, fecha y ruta asignada",
    )

    render_guide(
        steps=[
            "<strong>Ingresa las referencias</strong> — Una por linea.",
            "<strong>Buscar</strong> — Se busca primero por referencia directa; si no aparece, se escanea un rango de \u00b130 dias en paralelo.",
            "<strong>Eliminar</strong> — Confirma y se envia un PUT por cada visita encontrada vaciando reference, planned_date y route.",
        ],
        tip="El token de BAT esta configurado de forma fija. No es necesario ingresar credenciales.",
    )

    render_label("Referencias a eliminar")
    referencias_raw = st.text_area(
        "Referencias",
        placeholder="9613078790\n9613078791\n9613078792",
        height=160,
        label_visibility="collapsed",
        key="bat_referencias",
    )

    referencias = [r.strip() for r in referencias_raw.splitlines() if r.strip()]

    st.markdown("---")

    # --- Boton Buscar ---
    if st.button("Buscar visitas", key="btn_bat_buscar"):
        if not referencias:
            st.warning("Ingresa al menos una referencia.")
        else:
            st.session_state.pop("bat_resultados", None)
            total = len(referencias)
            barra = st.progress(0, text="Buscando...")
            resultados = []

            for i, reference in enumerate(referencias):
                barra.progress((i + 0.3) / total, text=f"Buscando referencia {reference}...")
                visita, req_ref = buscar_por_reference(reference)

                req_fallback = None
                if not visita:
                    barra.progress((i + 0.7) / total, text=f"Fallback fechas {reference}...")
                    visita, req_fallback = buscar_por_fechas(reference)

                resultados.append({
                    "reference": reference,
                    "visita": visita,
                    "req_ref": req_ref,
                    "req_fallback": req_fallback,
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

        with st.expander(f"{icon} Ref {r['reference']} — {titulo_estado}", expanded=not r["visita"]):
            req_ref = r["req_ref"]
            st.markdown("**Busqueda por referencia directa:**")
            st.code(f"GET {req_ref['url']}", language="bash")
            st.markdown(f"Status: `{req_ref['status']}`")
            st.json(req_ref["response"])

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
        visit_id = r["visita"]["id"]
        status, resp_text = limpiar_visita(visit_id)
        if 200 <= status < 300:
            exitosos += 1
        else:
            with contenedor_errores:
                render_error_item(f"Ref {r['reference']} (ID {visit_id}) — Error HTTP {status}: {resp_text}")
        update_progress(barra, contador, i + 1, total)

    finish_progress(barra)

    if exitosos > 0:
        st.success(f"{exitosos} de {total} visitas limpiadas correctamente")
        st.session_state.pop("bat_resultados", None)
    if exitosos < total:
        st.error(f"{total - exitosos} visita(s) con error")
