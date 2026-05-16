import streamlit as st
import requests
import pandas as pd
from datetime import date
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import API_BASE, REQUEST_TIMEOUT
from utils import (
    render_header, render_guide, render_label, render_stat,
    render_error_item, render_cuenta_badge,
    create_progress_tracker, update_progress, finish_progress,
)

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


def obtener_visita_completa(visit_id, token):
    """GET /v1/routes/visits/{id} - devuelve la visita con todos sus campos (items, reference, etc).
    Prueba con y sin trailing slash; algunos endpoints DRF requieren slash final."""
    for url in (f"{API_BASE}/routes/visits/{visit_id}/", f"{API_BASE}/routes/visits/{visit_id}"):
        try:
            r = requests.get(url, headers=_headers(token), timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                data = r.json()
                if data and data.get("title"):
                    return data
        except requests.exceptions.RequestException:
            continue
    return None


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


def asignar_visita(visita, route_id, planned_date, token):
    # Si la visita viene stripped (sin title/address), enriquecer con GET antes del PUT
    if not visita.get("title") or not visita.get("address"):
        full = obtener_visita_completa(visita["id"], token)
        if full:
            visita = full

    # Si todavia no tenemos title/address, abortar con mensaje claro
    if not visita.get("title") or not visita.get("address"):
        return 0, f"No se pudo obtener title/address de la visita {visita['id']} (GET de enriquecimiento sin datos)", None

    url = f"{API_BASE}/routes/visits/{visita['id']}"
    payload = {
        "id": visita["id"],
        "title": visita.get("title") or "",
        "address": visita.get("address") or "",
        "reference": visita.get("reference") or "",
        "route": route_id,
        "planned_date": planned_date,
    }
    try:
        r = requests.put(
            url,
            headers=_headers(token),
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        return r.status_code, r.text, {"url": url, "payload": payload}
    except requests.exceptions.RequestException as e:
        return 0, str(e), {"url": url, "payload": payload}


def _visitas_resueltas(idx, r):
    """Returns list of resolved visitas for a row (1 from auto-select, 1+ from manual multi-select)."""
    if r["visita"]:
        return [r["visita"]]
    if r["necesita_seleccion"]:
        sel = st.session_state.get("recuperar_selecciones", {}).get(idx)
        if isinstance(sel, list):
            return sel
        if sel:
            return [sel]
    return []


def pagina_recuperar_lvp():
    render_header(
        "Recuperar Visitas LVP",
        "Busca y asigna visitas Liverpool a su ruta y fecha correspondiente",
    )

    render_guide(
        steps=[
            "<strong>Selecciona la cuenta</strong> — Elige la tienda Liverpool donde buscar las visitas.",
            "<strong>Agrega filas</strong> — Referencia de la visita, nombre del vehiculo destino y fecha de la ruta.",
            "<strong>Buscar</strong> — Se busca por referencia directa contra la API.",
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

                # Enriquecer solo cuando hay multiples candidatas (para mostrar reference/SKU en tabla de seleccion).
                # En auto-select (1 candidata) no hace falta: asignar_visita ya enriquece defensivamente antes del PUT.
                if len(candidatas) > 1:
                    barra_buscar.progress((i + 0.75) / total_busqueda, text=f"Enriqueciendo {len(candidatas)} candidatas...")
                    with ThreadPoolExecutor(max_workers=10) as ex:
                        futures = {
                            ex.submit(obtener_visita_completa, c.get("id"), token): idx_c
                            for idx_c, c in enumerate(candidatas) if c.get("id")
                        }
                        for fut in as_completed(futures):
                            idx_c = futures[fut]
                            full = fut.result()
                            if full:
                                candidatas[idx_c] = full

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
        if _visitas_resueltas(i, r) and r["route_id"]
    ]
    sin_visita = [r for r in resultados if not r["visitas_candidatas"]]
    sin_ruta = [
        (i, r) for i, r in enumerate(resultados)
        if _visitas_resueltas(i, r) and not r["route_id"]
    ]
    pendientes = [
        (i, r) for i, r in enumerate(resultados)
        if r["necesita_seleccion"] and not _visitas_resueltas(i, r)
    ]
    total_visitas_listas = sum(len(_visitas_resueltas(i, r)) for i, r in listos)

    render_label("Resultados de busqueda")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(render_stat(total_visitas_listas, "listos para procesar"), unsafe_allow_html=True)
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
        visitas_actuales = _visitas_resueltas(idx, r)

        if r["necesita_seleccion"]:
            sel_actual = selecciones.get(idx) or []
            if isinstance(sel_actual, dict):
                sel_actual = [sel_actual]
            if sel_actual:
                icon = "✓"
                if len(sel_actual) == 1:
                    titulo_estado = f"visita seleccionada (ID {sel_actual[0]['id']})"
                else:
                    titulo_estado = f"{len(sel_actual)} visitas seleccionadas"
            else:
                icon = "?"
                titulo_estado = f"selecciona entre {len(candidatas)} visitas encontradas"

            label_expander = f"{icon} Ref {r['reference']} · {r['vehiculo']} · {r['fecha_display']} — {titulo_estado}"
            with st.expander(label_expander, expanded=not sel_actual):
                st.markdown(f"Se encontraron **{len(candidatas)}** visitas con esta referencia. Selecciona una o varias:")

                df_sel = pd.DataFrame([
                    {
                        "ID": v.get("id"),
                        "Reference": str(v.get("reference", "")),
                        "SKU": ", ".join(
                            str(i.get("reference", "")) for i in (v.get("items") or []) if i.get("reference")
                        ),
                        "Fecha": v.get("planned_date", ""),
                    }
                    for v in candidatas
                ])
                event = st.dataframe(
                    df_sel,
                    on_select="rerun",
                    selection_mode="multi-row",
                    use_container_width=True,
                    key=f"disamb_{idx}",
                    hide_index=True,
                )
                if event.selection.rows:
                    selecciones[idx] = [candidatas[r] for r in event.selection.rows]
                elif idx in selecciones:
                    del selecciones[idx]

                if st.checkbox("Ver detalles de todas las candidatas", key=f"disamb_detail_{idx}"):
                    with st.container(border=True):
                        df_detail = pd.DataFrame([
                            {
                                "ID": v.get("id"),
                                "Reference": str(v.get("reference", "")),
                                "Titulo": v.get("title", ""),
                                "Fecha": v.get("planned_date", ""),
                                "Status": v.get("status", ""),
                                "Order": v.get("order", ""),
                                "Route ID": v.get("route", ""),
                                "SKU": ", ".join(
                                    str(i.get("reference", "")) for i in (v.get("items") or []) if i.get("reference")
                                ),
                            }
                            for v in candidatas
                        ])
                        st.dataframe(df_detail, use_container_width=True, hide_index=True)

                # --- Busqueda por reference ---
                req_ref = r["req_ref"]
                if st.checkbox("Ver detalles del request API", key=f"disamb_req_{idx}"):
                    with st.container(border=True):
                        st.code(f"GET {req_ref['url']}", language="bash")
                        st.markdown(f"Status: `{req_ref['status']}`")
                        st.json(req_ref["response"])

        else:
            tiene_visita = bool(visitas_actuales)
            if tiene_visita and r["route_id"]:
                icon = "✓"
                titulo_estado = "lista"
            elif tiene_visita:
                icon = "⚠"
                titulo_estado = "visita ok / sin ruta"
            else:
                icon = "✗"
                titulo_estado = "no encontrada"

            has_error = not tiene_visita or not r["route_id"]
            label_expander = f"{icon} Ref {r['reference']} · {r['vehiculo']} · {r['fecha_display']} — {titulo_estado}"

            with st.expander(label_expander, expanded=has_error):
                # --- Busqueda por reference ---
                req_ref = r["req_ref"]
                st.markdown("**Busqueda por referencia directa:**")
                st.code(f"GET {req_ref['url']}", language="bash")
                st.markdown(f"Status: `{req_ref['status']}`")
                st.json(req_ref["response"])

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
    if not st.button(f"Procesar {total_visitas_listas} visita(s)", type="primary", key="btn_procesar"):
        st.stop()

    visitas_a_procesar = [
        (r, v)
        for idx, r in listos
        for v in _visitas_resueltas(idx, r)
    ]
    total = len(visitas_a_procesar)

    # Paso 1: enriquecer cada visita seleccionada con GET por ID (en paralelo)
    enrich_barra = st.progress(0, text="Obteniendo datos completos de las visitas...")
    contenedor_errores_enrich = st.container()
    visitas_enriquecidas = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {
            ex.submit(obtener_visita_completa, v["id"], token): (i, r, v)
            for i, (r, v) in enumerate(visitas_a_procesar)
        }
        completadas = 0
        for fut in as_completed(futures):
            i, r, v_orig = futures[fut]
            full = fut.result()
            if full and full.get("title") and full.get("address"):
                visitas_enriquecidas.append((r, full))
            else:
                with contenedor_errores_enrich:
                    render_error_item(
                        f"Ref {r['reference']} (ID {v_orig.get('id')}) — No se pudo obtener title/address con GET /routes/visits/{{id}}"
                    )
            completadas += 1
            enrich_barra.progress(completadas / total, text=f"Obteniendo datos... {completadas}/{total}")
    enrich_barra.empty()

    if not visitas_enriquecidas:
        st.error("No se pudo enriquecer ninguna visita. Revisa los errores arriba.")
        st.stop()

    # Paso 2: PUT por cada visita enriquecida
    exitosos = 0
    barra, contador, contenedor_errores = create_progress_tracker(len(visitas_enriquecidas), "Asignando visitas...")

    for i, (r, visita) in enumerate(visitas_enriquecidas):
        status, resp_text, req_info = asignar_visita(visita, r["route_id"], r["fecha_str"], token)
        if 200 <= status < 300:
            exitosos += 1
        else:
            with contenedor_errores:
                render_error_item(f"Ref {r['reference']} (ID {visita.get('id')}) — Error al asignar (HTTP {status}): {resp_text}")
                if req_info:
                    with st.expander(f"Ver request enviado (ID {visita.get('id')})"):
                        st.code(f"PUT {req_info['url']}", language="bash")
                        st.json(req_info["payload"])
        update_progress(barra, contador, i + 1, len(visitas_enriquecidas))

    finish_progress(barra)
    total = len(visitas_enriquecidas)

    if exitosos > 0:
        st.success(f"{exitosos} de {total} visitas asignadas correctamente")
        st.session_state.pop("recuperar_resultados", None)
        st.session_state.pop("recuperar_selecciones", None)
    if exitosos < total:
        st.error(f"{total - exitosos} visita(s) con error al asignar")
