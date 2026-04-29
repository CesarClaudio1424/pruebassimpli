import streamlit as st
import requests
import pandas as pd
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import API_BASE, REQUEST_TIMEOUT
from utils import (
    render_header, render_guide, render_label, render_stat,
    render_error_item, render_cuenta_badge,
    create_progress_tracker, update_progress, finish_progress,
)

FALLBACK_DAYS = 30


@st.cache_data
def cargar_cuentas():
    try:
        df = pd.read_csv("cuentas.csv", encoding="latin-1")
        return {
            nombre: {"id": str(id_), "token": str(token)}
            for nombre, id_, token in zip(df.nombre, df.id, df.token)
        }
    except FileNotFoundError:
        return None


def _headers(token):
    return {"Authorization": f"Token {token}", "Content-Type": "application/json"}


def buscar_por_reference(reference, token):
    """Returns (lista_visitas, req_info dict). Lista puede tener 0, 1 o N visitas."""
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
            if isinstance(data, dict) and "results" in data:
                return data["results"], info
            if isinstance(data, list):
                return data, info
            if isinstance(data, dict) and data.get("id"):
                return [data], info
    except requests.exceptions.RequestException as e:
        info["response"] = str(e)
    return [], info


def _buscar_en_fecha(fecha_str, reference, token):
    url = f"{API_BASE}/routes/visits/?planned_date={fecha_str}"
    try:
        r = requests.get(url, headers=_headers(token), timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            for v in (r.json() or []):
                if str(v.get("reference", "")) == str(reference):
                    return v, fecha_str
    except requests.exceptions.RequestException:
        pass
    return None, fecha_str


def buscar_por_fechas(reference, token):
    """Returns (visita | None, fallback_info dict)."""
    hoy = date.today()
    fechas = [
        (hoy + timedelta(days=d)).strftime("%Y-%m-%d")
        for d in range(-FALLBACK_DAYS, FALLBACK_DAYS + 1)
    ]
    info = {"total_fechas": len(fechas), "fecha_encontrada": None, "url": None, "response": None}

    executor = ThreadPoolExecutor(max_workers=10)
    futures = {executor.submit(_buscar_en_fecha, f, reference, token): f for f in fechas}
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


def obtener_ruta_id(vehiculo_nombre, fecha_str, token):
    """Returns (route_id | None, req_info dict)."""
    url = f"{API_BASE}/plans/{fecha_str}/vehicles/"
    info = {"url": url, "status": None, "response_match": None, "response_full": None}
    try:
        r = requests.get(url, headers=_headers(token), timeout=REQUEST_TIMEOUT)
        info["status"] = r.status_code
        if r.status_code == 200:
            vehiculos = r.json() or []
            for v in vehiculos:
                if v.get("name", "").strip().lower() == vehiculo_nombre.strip().lower():
                    rutas = v.get("routes", [])
                    if rutas:
                        info["response_match"] = v
                        return rutas[0]["id"], info
            info["response_full"] = vehiculos
    except requests.exceptions.RequestException as e:
        info["status"] = 0
        info["response_full"] = str(e)
    return None, info


def asignar_visita(visit_id, route_id, planned_date, token):
    url = f"{API_BASE}/routes/visits/{visit_id}"
    try:
        r = requests.put(
            url,
            headers=_headers(token),
            json={"route": route_id, "planned_date": planned_date},
            timeout=REQUEST_TIMEOUT,
        )
        return r.status_code, r.text
    except requests.exceptions.RequestException as e:
        return 0, str(e)


def _visita_resuelta(idx, r):
    """Returns the resolved visita for a result row, considering user disambiguation."""
    if r["visita"]:
        return r["visita"]
    if r["necesita_seleccion"]:
        return st.session_state.get("recuperar_selecciones", {}).get(idx)
    return None


def pagina_recuperar_lvp():
    render_header(
        "Recuperar Visitas LVP",
        "Busca y asigna visitas Liverpool a su ruta y fecha correspondiente",
    )

    render_guide(
        steps=[
            "<strong>Selecciona la cuenta</strong> — Elige la tienda Liverpool donde buscar las visitas.",
            "<strong>Agrega filas</strong> — Referencia de la visita, nombre del vehiculo destino y fecha de la ruta.",
            "<strong>Buscar</strong> — Se busca primero por referencia directa; si no aparece, se escanea un rango de ±30 dias en paralelo.",
            "<strong>Procesar</strong> — Revisa los resultados y confirma la asignacion a la ruta.",
        ],
        tip="El nombre del vehiculo debe coincidir (sin importar mayusculas/minusculas) con el registrado en SimpliRoute.",
    )

    # --- Cuenta Liverpool ---
    cuentas = cargar_cuentas()
    if cuentas is None:
        st.error("No se encontro el archivo `cuentas.csv`.")
        st.stop()

    render_label("Paso 1 · Cuenta Liverpool")
    cuenta_nombre = st.selectbox(
        "Cuenta",
        list(cuentas.keys()),
        label_visibility="collapsed",
        key="recuperar_cuenta",
    )
    cuenta = cuentas[cuenta_nombre]
    token = cuenta["token"]
    token_preview = f"{token[:6]}...{token[-4:]}" if len(token) > 10 else token
    render_cuenta_badge(f"Cuenta seleccionada: <strong>{cuenta_nombre}</strong> (ID: {cuenta['id']}) · Token: <code>{token_preview}</code>")

    # --- Session state para filas ---
    if "recuperar_filas" not in st.session_state:
        st.session_state.recuperar_filas = [
            {"reference": "", "vehiculo": "", "fecha": date.today()}
        ]

    # --- Filas dinamicas ---
    render_label("Paso 2 · Visitas a recuperar")
    h1, h2, h3, _ = st.columns([3, 3, 2, 1])
    h1.markdown('<div class="sr-label" style="margin-bottom:0.2rem;">Referencia</div>', unsafe_allow_html=True)
    h2.markdown('<div class="sr-label" style="margin-bottom:0.2rem;">Vehiculo</div>', unsafe_allow_html=True)
    h3.markdown('<div class="sr-label" style="margin-bottom:0.2rem;">Fecha</div>', unsafe_allow_html=True)

    for i, fila in enumerate(st.session_state.recuperar_filas):
        col1, col2, col3, col4 = st.columns([3, 3, 2, 1])
        with col1:
            st.session_state.recuperar_filas[i]["reference"] = st.text_input(
                "Referencia",
                value=fila["reference"],
                key=f"ref_{i}",
                placeholder="Ej: 9613078790",
                label_visibility="collapsed",
            )
        with col2:
            st.session_state.recuperar_filas[i]["vehiculo"] = st.text_input(
                "Vehiculo",
                value=fila["vehiculo"],
                key=f"veh_{i}",
                placeholder="Ej: CAMION-01",
                label_visibility="collapsed",
            )
        with col3:
            st.session_state.recuperar_filas[i]["fecha"] = st.date_input(
                "Fecha",
                value=fila["fecha"],
                key=f"fecha_{i}",
                format="DD/MM/YYYY",
                label_visibility="collapsed",
            )
        with col4:
            if len(st.session_state.recuperar_filas) > 1:
                if st.button("✕", key=f"del_{i}", use_container_width=True):
                    st.session_state.recuperar_filas.pop(i)
                    st.session_state.pop("recuperar_resultados", None)
                    st.rerun()

    if st.button("+ Agregar fila", key="btn_agregar"):
        st.session_state.recuperar_filas.append(
            {"reference": "", "vehiculo": "", "fecha": date.today()}
        )
        st.rerun()

    st.markdown("---")

    filas_validas = [
        f for f in st.session_state.recuperar_filas
        if f["reference"].strip() and f["vehiculo"].strip()
    ]

    # --- Boton Buscar ---
    if st.button("Buscar visitas y rutas", key="btn_buscar"):
        if not filas_validas:
            st.warning("Ingresa al menos una referencia y vehiculo.")
        else:
            st.session_state.pop("recuperar_resultados", None)
            st.session_state.pop("recuperar_selecciones", None)
            total_busqueda = len(filas_validas)
            barra_buscar = st.progress(0, text="Buscando...")
            resultados = []

            for i, fila in enumerate(filas_validas):
                reference = fila["reference"].strip()
                vehiculo = fila["vehiculo"].strip()
                fecha_str = fila["fecha"].strftime("%Y-%m-%d")
                fecha_display = fila["fecha"].strftime("%d/%m/%Y")

                barra_buscar.progress((i + 0.3) / total_busqueda, text=f"Buscando referencia {reference}...")
                candidatas, req_ref = buscar_por_reference(reference, token)
                # Ordenar de mas reciente a mas antigua (ID desc)
                candidatas = sorted(candidatas, key=lambda v: v.get("id", 0), reverse=True)

                req_fallback = None
                if not candidatas:
                    barra_buscar.progress((i + 0.6) / total_busqueda, text=f"Fallback fechas {reference}...")
                    visita_fb, req_fallback = buscar_por_fechas(reference, token)
                    candidatas = [visita_fb] if visita_fb else []

                # Auto-selecciona si hay exactamente 1 resultado
                visita = candidatas[0] if len(candidatas) == 1 else None
                necesita_seleccion = len(candidatas) > 1

                barra_buscar.progress((i + 0.9) / total_busqueda, text=f"Buscando ruta para {vehiculo}...")
                route_id, req_veh = obtener_ruta_id(vehiculo, fecha_str, token) if candidatas else (None, None)

                resultados.append({
                    "reference": reference,
                    "vehiculo": vehiculo,
                    "fecha_str": fecha_str,
                    "fecha_display": fecha_display,
                    "visitas_candidatas": candidatas,
                    "visita": visita,
                    "necesita_seleccion": necesita_seleccion,
                    "route_id": route_id,
                    "req_ref": req_ref,
                    "req_fallback": req_fallback,
                    "req_veh": req_veh,
                })
                barra_buscar.progress((i + 1) / total_busqueda, text=f"{i+1}/{total_busqueda} procesadas")

            barra_buscar.progress(1.0, text="Busqueda completada")
            st.session_state.recuperar_resultados = resultados

    # --- Mostrar resultados ---
    if "recuperar_resultados" not in st.session_state:
        st.stop()

    resultados = st.session_state.recuperar_resultados

    if "recuperar_selecciones" not in st.session_state:
        st.session_state.recuperar_selecciones = {}
    selecciones = st.session_state.recuperar_selecciones

    listos = [
        (i, r) for i, r in enumerate(resultados)
        if _visita_resuelta(i, r) is not None and r["route_id"]
    ]
    sin_visita = [r for r in resultados if not r["visitas_candidatas"]]
    sin_ruta = [
        (i, r) for i, r in enumerate(resultados)
        if _visita_resuelta(i, r) is not None and not r["route_id"]
    ]
    pendientes = [
        (i, r) for i, r in enumerate(resultados)
        if r["necesita_seleccion"] and i not in selecciones
    ]

    render_label("Resultados de busqueda")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(render_stat(len(listos), "listos para procesar"), unsafe_allow_html=True)
    with col2:
        st.markdown(
            render_stat(
                len(sin_ruta),
                "visita ok, ruta no encontrada",
                style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);",
            ),
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            render_stat(
                len(sin_visita),
                "visita no encontrada",
                style="background: linear-gradient(135deg, #d32f2f 0%, #b71c1c 100%);",
            ),
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(
            render_stat(
                len(pendientes),
                "pendiente de seleccion",
                style="background: linear-gradient(135deg, #7b2ff7 0%, #5b0de0 100%);",
            ),
            unsafe_allow_html=True,
        )

    for idx, r in enumerate(resultados):
        candidatas = r["visitas_candidatas"]
        visita_actual = _visita_resuelta(idx, r)

        if r["necesita_seleccion"]:
            ya_seleccionada = selecciones.get(idx)
            if ya_seleccionada:
                icon = "✓"
                titulo_estado = f"visita seleccionada (ID {ya_seleccionada['id']})"
            else:
                icon = "?"
                titulo_estado = f"selecciona entre {len(candidatas)} visitas encontradas"

            label_expander = f"{icon} Ref {r['reference']} · {r['vehiculo']} · {r['fecha_display']} — {titulo_estado}"
            with st.expander(label_expander, expanded=not ya_seleccionada):
                st.markdown(f"Se encontraron **{len(candidatas)}** visitas con esta referencia. Selecciona la correcta:")

                df_sel = pd.DataFrame([
                    {"ID": v.get("id"), "Reference": str(v.get("reference", ""))}
                    for v in candidatas
                ])
                event = st.dataframe(
                    df_sel,
                    on_select="rerun",
                    selection_mode="single-row",
                    use_container_width=True,
                    key=f"disamb_{idx}",
                    hide_index=True,
                )
                if event.selection.rows:
                    selecciones[idx] = candidatas[event.selection.rows[0]]

                with st.expander("Ver detalles de todas las candidatas"):
                    df_detail = pd.DataFrame([
                        {
                            "ID": v.get("id"),
                            "Reference": str(v.get("reference", "")),
                            "Titulo": v.get("title", ""),
                            "Fecha": v.get("planned_date", ""),
                            "Status": v.get("status", ""),
                            "SKU": v.get("sku", ""),
                        }
                        for v in candidatas
                    ])
                    st.dataframe(df_detail, use_container_width=True, hide_index=True)

                # --- Busqueda por reference ---
                req_ref = r["req_ref"]
                with st.expander("Ver detalles del request API"):
                    st.code(f"GET {req_ref['url']}", language="bash")
                    st.markdown(f"Status: `{req_ref['status']}`")
                    st.json(req_ref["response"])

        else:
            if visita_actual and r["route_id"]:
                icon = "✓"
                titulo_estado = "lista"
            elif visita_actual:
                icon = "⚠"
                titulo_estado = "visita ok / sin ruta"
            else:
                icon = "✗"
                titulo_estado = "no encontrada"

            has_error = visita_actual is None or not r["route_id"]
            label_expander = f"{icon} Ref {r['reference']} · {r['vehiculo']} · {r['fecha_display']} — {titulo_estado}"

            with st.expander(label_expander, expanded=has_error):
                # --- Busqueda por reference ---
                req_ref = r["req_ref"]
                st.markdown("**Busqueda por referencia directa:**")
                st.code(f"GET {req_ref['url']}", language="bash")
                st.markdown(f"Status: `{req_ref['status']}`")
                st.json(req_ref["response"])

                # --- Fallback por fechas ---
                req_fb = r.get("req_fallback")
                if req_fb is not None:
                    st.markdown(f"**Fallback — escaneadas {req_fb['total_fechas']} fechas (±{FALLBACK_DAYS} dias):**")
                    if req_fb["url"]:
                        st.markdown(f"Encontrada el `{req_fb['fecha_encontrada']}`")
                        st.code(f"GET {req_fb['url']}", language="bash")
                        st.json(req_fb["response"])
                    else:
                        st.markdown("No encontrada en ninguna fecha del rango.")

                # --- Busqueda de ruta ---
                req_veh = r.get("req_veh")
                if req_veh:
                    st.markdown("**Busqueda de ruta por vehiculo:**")
                    st.code(f"GET {req_veh['url']}", language="bash")
                    st.markdown(f"Status: `{req_veh['status']}`")
                    if req_veh["response_match"]:
                        st.json(req_veh["response_match"])
                    elif req_veh["response_full"] is not None:
                        st.markdown("Vehiculo no encontrado. Vehiculos disponibles en esa fecha:")
                        st.json(req_veh["response_full"])

    if not listos:
        if pendientes:
            st.info("Selecciona la visita correcta en cada fila con duplicados para continuar.")
        st.stop()

    if pendientes:
        st.info(f"Hay {len(pendientes)} referencia(s) con seleccion pendiente. Puedes procesar las {len(listos)} ya resueltas o completar las selecciones primero.")

    st.markdown("---")

    # --- Boton Procesar ---
    if not st.button(f"Procesar {len(listos)} visita(s)", type="primary", key="btn_procesar"):
        st.stop()

    total = len(listos)
    exitosos = 0
    barra, contador, contenedor_errores = create_progress_tracker(total, "Asignando visitas...")

    for i, (idx, r) in enumerate(listos):
        visita = _visita_resuelta(idx, r)
        status, resp_text = asignar_visita(visita["id"], r["route_id"], r["fecha_str"], token)
        if 200 <= status < 300:
            exitosos += 1
        else:
            with contenedor_errores:
                render_error_item(f"Ref {r['reference']} — Error al asignar (HTTP {status}): {resp_text}")
        update_progress(barra, contador, i + 1, total)

    finish_progress(barra)

    if exitosos > 0:
        st.success(f"{exitosos} de {total} visitas asignadas correctamente")
        st.session_state.pop("recuperar_resultados", None)
        st.session_state.pop("recuperar_selecciones", None)
    if exitosos < total:
        st.error(f"{total - exitosos} visita(s) con error al asignar")
