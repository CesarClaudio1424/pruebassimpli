import streamlit as st
import requests
from config import API_BASE, REQUEST_TIMEOUT
from utils import (
    render_header, render_guide, render_label, render_stat,
    render_tip, render_error_item, render_cuenta_badge,
)

API_FLEETS = f"{API_BASE}/fleets/"
API_USERS = f"{API_BASE}/accounts/users/"
API_VEHICLES = f"{API_BASE}/routes/vehicles/"


def _headers(token):
    return {"Authorization": f"Token {token}", "Content-Type": "application/json"}


def _validar_cuenta(token):
    try:
        r = requests.get(f"{API_BASE}/accounts/me/", headers=_headers(token), timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return True, r.json().get("account", {}).get("name", "Sin nombre")
    except requests.exceptions.RequestException:
        pass
    return False, None


def _listar_flotas(token):
    try:
        r = requests.get(API_FLEETS, headers=_headers(token), timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return True, r.json(), None
        return False, [], f"HTTP {r.status_code}: {r.text[:300]}"
    except requests.exceptions.RequestException as e:
        return False, [], str(e)


def _listar_vehiculos(token):
    try:
        r = requests.get(API_VEHICLES, headers=_headers(token), timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            opciones = []
            for v in data:
                vid = v.get("id")
                nombre = v.get("name") or "(sin nombre)"
                placa = v.get("license_plate")
                label = f"{vid} — {nombre}" + (f" ({placa})" if placa else "")
                opciones.append((vid, label))
            opciones.sort(key=lambda x: x[1].lower())
            return True, opciones, None
        return False, [], f"HTTP {r.status_code}: {r.text[:300]}"
    except requests.exceptions.RequestException as e:
        return False, [], str(e)


def _listar_usuarios(token):
    try:
        r = requests.get(API_USERS, headers=_headers(token), timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            data = r.json()
            opciones = []
            for u in data:
                uid = u.get("id")
                nombre = u.get("name") or "(sin nombre)"
                username = u.get("username") or ""
                label = f"{uid} — {nombre}" + (f" ({username})" if username else "")
                opciones.append((uid, label))
            opciones.sort(key=lambda x: x[1].lower())
            return True, opciones, None
        return False, [], f"HTTP {r.status_code}: {r.text[:300]}"
    except requests.exceptions.RequestException as e:
        return False, [], str(e)


def _crear_flota(token, name, vehicles, users):
    payload = {"name": name, "vehicles": vehicles, "users": users}
    try:
        r = requests.post(API_FLEETS, headers=_headers(token), json=payload, timeout=REQUEST_TIMEOUT)
        if 200 <= r.status_code < 300:
            return True, r.json(), None
        return False, None, f"HTTP {r.status_code}: {r.text[:300]}"
    except requests.exceptions.RequestException as e:
        return False, None, str(e)


def _editar_flota(token, fleet_id, name, vehicles, users):
    payload = {"name": name, "vehicles": vehicles, "users": users}
    try:
        r = requests.put(f"{API_FLEETS}{fleet_id}/", headers=_headers(token), json=payload, timeout=REQUEST_TIMEOUT)
        if 200 <= r.status_code < 300:
            return True, r.json(), None
        return False, None, f"HTTP {r.status_code}: {r.text[:300]}"
    except requests.exceptions.RequestException as e:
        return False, None, str(e)


def _eliminar_flota(token, fleet_id):
    try:
        r = requests.delete(f"{API_FLEETS}{fleet_id}/", headers=_headers(token), timeout=REQUEST_TIMEOUT)
        if 200 <= r.status_code < 300:
            return True, None
        return False, f"HTTP {r.status_code}: {r.text[:300]}"
    except requests.exceptions.RequestException as e:
        return False, str(e)


def _parsear_ids(text):
    if not text:
        return []
    ids = []
    vistos = set()
    for chunk in text.replace(",", "\n").replace(";", "\n").split("\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            n = int(chunk)
        except ValueError:
            continue
        if n in vistos:
            continue
        vistos.add(n)
        ids.append(n)
    return ids


def _selector_dual(label_singular, label_plural, key_prefix, fetch_fn, token, valores_iniciales=None):
    """
    Selector dual texto / listado. Devuelve lista de IDs (int).
    valores_iniciales: lista de IDs pre-seleccionados (usada como default en ambos modos).
    """
    valores_iniciales = list(valores_iniciales or [])
    modo = st.radio(
        f"Modo de seleccion de {label_plural}",
        ["Listado", "Texto"],
        horizontal=True,
        key=f"{key_prefix}_modo",
    )

    if modo == "Texto":
        text_key = f"{key_prefix}_text"
        if text_key not in st.session_state:
            st.session_state[text_key] = "\n".join(str(v) for v in valores_iniciales)
        text = st.text_area(
            f"IDs de {label_plural} (uno por linea o separados por coma)",
            key=text_key,
            height=150,
        )
        ids = _parsear_ids(text)
        st.caption(f"{len(ids)} {label_plural} reconocidos")
        return ids

    # Listado
    cache_key = f"{key_prefix}_options"
    if cache_key not in st.session_state:
        if st.button(f"Cargar {label_plural}", key=f"{key_prefix}_btn_cargar"):
            with st.spinner(f"Cargando {label_plural}..."):
                ok, opciones, err = fetch_fn(token)
            if ok:
                st.session_state[cache_key] = opciones
                st.rerun()
            else:
                st.error(f"Error al cargar {label_plural}: {err}")
        if valores_iniciales:
            st.caption(f"{len(valores_iniciales)} {label_plural} actuales (carga la lista para verlos por nombre)")
        return valores_iniciales

    opciones = st.session_state[cache_key]
    id_to_label = {oid: lbl for oid, lbl in opciones}
    for vid in valores_iniciales:
        if vid not in id_to_label:
            id_to_label[vid] = f"{vid} — (no encontrado en lista)"

    # Estado de seleccion: set de IDs
    sel_key = f"{key_prefix}_sel"
    if sel_key not in st.session_state:
        st.session_state[sel_key] = set(valores_iniciales)

    seleccionados = st.session_state[sel_key]

    # Buscador
    search_key = f"{key_prefix}_search"
    busqueda = st.text_input(
        f"Buscar {label_plural}",
        key=search_key,
        placeholder=f"Filtrar {label_plural} por nombre o ID...",
        label_visibility="collapsed",
    )

    # Acciones rapidas
    col_a, col_b, col_c = st.columns([1, 1, 2])
    with col_a:
        if st.button(f"Todos", key=f"{key_prefix}_all", use_container_width=True):
            st.session_state[sel_key] = set(id_to_label.keys())
            st.rerun()
    with col_b:
        if st.button("Ninguno", key=f"{key_prefix}_none", use_container_width=True):
            st.session_state[sel_key] = set()
            st.rerun()
    with col_c:
        st.markdown(
            f'<div class="sr-stat" style="padding:0.4rem 0.6rem;">'
            f'<div class="sr-stat-number" style="font-size:1.1rem;">{len(seleccionados)} / {len(id_to_label)} seleccionados</div></div>',
            unsafe_allow_html=True,
        )

    # Filtrar y ordenar
    items = sorted(id_to_label.items(), key=lambda kv: str(kv[1]).lower())
    if busqueda and busqueda.strip():
        q = busqueda.strip().lower()
        items = [(oid, lbl) for oid, lbl in items if q in str(lbl).lower() or q in str(oid)]

    if not items:
        st.caption(f"Sin {label_plural} para mostrar.")
        return [int(x) for x in seleccionados]

    # Grid de botones (3 columnas)
    cols_per_row = 3
    for i in range(0, len(items), cols_per_row):
        cols = st.columns(cols_per_row)
        for j, (oid, lbl) in enumerate(items[i : i + cols_per_row]):
            btn_type = "primary" if oid in seleccionados else "secondary"
            with cols[j]:
                if st.button(lbl, key=f"{key_prefix}_btn_{oid}", type=btn_type, use_container_width=True):
                    if oid in seleccionados:
                        seleccionados.discard(oid)
                    else:
                        seleccionados.add(oid)
                    st.session_state[sel_key] = seleccionados
                    st.rerun()

    return [int(x) for x in seleccionados]


def _reset_form_state(prefix):
    """Borra las keys de session_state que arrancan con prefix."""
    for k in list(st.session_state.keys()):
        if k.startswith(prefix):
            del st.session_state[k]


def _tab_listar(token):
    if st.button("Refrescar", key="fl_listar_refresh"):
        st.session_state.pop("fl_flotas_cache", None)

    if "fl_flotas_cache" not in st.session_state:
        with st.spinner("Cargando flotas..."):
            ok, flotas, err = _listar_flotas(token)
        if not ok:
            st.error(f"Error: {err}")
            return
        st.session_state["fl_flotas_cache"] = flotas

    flotas = st.session_state["fl_flotas_cache"]

    if not flotas:
        render_tip("La cuenta no tiene flotas.")
        return

    total_v = sum(len(f.get("vehicles") or []) for f in flotas)
    total_u = sum(len(f.get("users") or []) for f in flotas)
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        st.markdown(render_stat(len(flotas), "flotas"), unsafe_allow_html=True)
    with col_b:
        st.markdown(render_stat(total_v, "vehiculos asignados"), unsafe_allow_html=True)
    with col_c:
        st.markdown(render_stat(total_u, "usuarios asignados"), unsafe_allow_html=True)

    st.markdown("&nbsp;", unsafe_allow_html=True)

    # Buscador
    busqueda = st.text_input(
        "Buscar flota",
        key="fl_listar_search",
        placeholder="Filtrar por nombre o ID...",
        label_visibility="collapsed",
    )
    flotas_vista = flotas
    if busqueda and busqueda.strip():
        q = busqueda.strip().lower()
        flotas_vista = [f for f in flotas if q in str(f.get("name", "")).lower() or q in str(f.get("id"))]
        if not flotas_vista:
            st.caption("Sin resultados.")
            return

    # Grid de cards (2 columnas)
    for i in range(0, len(flotas_vista), 2):
        cols = st.columns(2)
        for j, f in enumerate(flotas_vista[i : i + 2]):
            with cols[j]:
                with st.container(border=True):
                    nombre = f.get("name") or "(sin nombre)"
                    fid = f.get("id")
                    n_veh = len(f.get("vehicles") or [])
                    n_usr = len(f.get("users") or [])
                    st.markdown(
                        f'<div style="font-weight:700; font-size:1.05rem; line-height:1.2;">{nombre}</div>'
                        f'<div style="color:#888; font-size:0.8rem; margin-bottom:0.5rem;">ID: {fid}</div>',
                        unsafe_allow_html=True,
                    )
                    sub_a, sub_b = st.columns(2)
                    with sub_a:
                        st.markdown(render_stat(n_veh, "vehiculos"), unsafe_allow_html=True)
                    with sub_b:
                        st.markdown(render_stat(n_usr, "usuarios"), unsafe_allow_html=True)
                    with st.expander("Ver IDs", expanded=False):
                        st.markdown(f"**Vehiculos ({n_veh})**")
                        st.code(", ".join(str(v) for v in (f.get("vehicles") or [])) or "—", language=None)
                        st.markdown(f"**Usuarios ({n_usr})**")
                        st.code(", ".join(str(u) for u in (f.get("users") or [])) or "—", language=None)


def _tab_crear(token):
    render_label("Nombre de la flota")
    nombre = st.text_input("Nombre", key="fl_crear_nombre", label_visibility="collapsed", placeholder="Ej: Almacen Norte")

    render_label("Vehiculos")
    vehicles = _selector_dual("vehiculo", "vehiculos", "fl_crear_veh", _listar_vehiculos, token)

    render_label("Usuarios")
    users = _selector_dual("usuario", "usuarios", "fl_crear_usr", _listar_usuarios, token)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(render_stat(len(vehicles), "vehiculos"), unsafe_allow_html=True)
    with col2:
        st.markdown(render_stat(len(users), "usuarios"), unsafe_allow_html=True)

    if not st.button("Crear flota", type="primary", key="fl_crear_btn"):
        return

    if not nombre or not nombre.strip():
        st.error("El nombre es obligatorio.")
        return

    with st.spinner("Creando flota..."):
        ok, flota, err = _crear_flota(token, nombre.strip(), vehicles, users)

    if not ok:
        st.error(f"Error al crear: {err}")
        return

    st.success(f"Flota creada: [{flota.get('id')}] {flota.get('name')}")
    st.session_state.pop("fl_flotas_cache", None)
    _reset_form_state("fl_crear_")


def _tab_editar(token):
    with st.spinner("Cargando flotas..."):
        ok, flotas, err = _listar_flotas(token)
    if not ok:
        st.error(f"Error: {err}")
        return
    if not flotas:
        render_tip("La cuenta no tiene flotas para editar.")
        return

    render_label("Selecciona la flota a editar")
    flotas_por_id = {f.get("id"): f for f in flotas}
    opciones = [f"[{f.get('id')}] {f.get('name')}" for f in flotas]
    seleccion = st.selectbox("Flota", opciones, key="fl_edit_sel", label_visibility="collapsed")
    fleet_id = int(seleccion.split("]")[0].lstrip("["))

    # Reset al cambiar de flota
    if st.session_state.get("fl_edit_loaded_id") != fleet_id:
        _reset_form_state("fl_edit_veh")
        _reset_form_state("fl_edit_usr")
        st.session_state.pop("fl_edit_nombre", None)
        st.session_state["fl_edit_loaded_id"] = fleet_id

    flota = flotas_por_id[fleet_id]
    current_vehicles = list(flota.get("vehicles") or [])
    current_users = list(flota.get("users") or [])

    render_label("Nombre")
    if "fl_edit_nombre" not in st.session_state:
        st.session_state["fl_edit_nombre"] = flota.get("name") or ""
    nombre = st.text_input("Nombre", key="fl_edit_nombre", label_visibility="collapsed")

    render_label(f"Vehiculos (actual: {len(current_vehicles)})")
    vehicles = _selector_dual(
        "vehiculo", "vehiculos", "fl_edit_veh", _listar_vehiculos, token,
        valores_iniciales=current_vehicles,
    )

    render_label(f"Usuarios (actual: {len(current_users)})")
    users = _selector_dual(
        "usuario", "usuarios", "fl_edit_usr", _listar_usuarios, token,
        valores_iniciales=current_users,
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(render_stat(len(vehicles), "vehiculos"), unsafe_allow_html=True)
    with col2:
        st.markdown(render_stat(len(users), "usuarios"), unsafe_allow_html=True)
    with col3:
        delta_v = len(vehicles) - len(current_vehicles)
        delta_u = len(users) - len(current_users)
        st.markdown(render_stat(f"{delta_v:+d}V {delta_u:+d}U", "cambios"), unsafe_allow_html=True)

    if not st.button("Guardar cambios", type="primary", key="fl_edit_btn"):
        return

    if not nombre or not nombre.strip():
        st.error("El nombre es obligatorio.")
        return

    with st.spinner("Guardando..."):
        ok, _flota, err = _editar_flota(token, fleet_id, nombre.strip(), vehicles, users)

    if not ok:
        st.error(f"Error al guardar: {err}")
        return

    st.success(f"Flota [{fleet_id}] actualizada (vehiculos: {len(vehicles)}, usuarios: {len(users)})")
    st.session_state.pop("fl_flotas_cache", None)


def _tab_eliminar(token):
    with st.spinner("Cargando flotas..."):
        ok, flotas, err = _listar_flotas(token)
    if not ok:
        st.error(f"Error: {err}")
        return
    if not flotas:
        render_tip("La cuenta no tiene flotas para eliminar.")
        return

    render_label("Selecciona la(s) flota(s) a eliminar")

    col_a, col_b, col_c = st.columns([1, 1, 2])
    with col_a:
        if st.button("Todas", key="fl_del_all", use_container_width=True):
            st.session_state["fl_del_sel"] = [f"[{f.get('id')}] {f.get('name')}" for f in flotas]
            st.rerun()
    with col_b:
        if st.button("Ninguna", key="fl_del_none", use_container_width=True):
            st.session_state["fl_del_sel"] = []
            st.rerun()

    opciones = [f"[{f.get('id')}] {f.get('name')}" for f in flotas]
    seleccion = st.multiselect("Flotas", opciones, key="fl_del_sel", label_visibility="collapsed")
    if not seleccion:
        render_tip("Selecciona al menos una flota.")
        return

    ids = [int(s.split("]")[0].lstrip("[")) for s in seleccion]
    st.markdown(render_stat(len(ids), "flotas a eliminar"), unsafe_allow_html=True)

    es_total = len(ids) == len(flotas)
    advertencia = (
        "Estas a punto de eliminar <strong>TODAS</strong> las flotas de la cuenta. Esta accion es <strong>irreversible</strong>."
        if es_total else
        "Esta accion es <strong>irreversible</strong>. Las flotas seleccionadas se eliminaran."
    )
    render_tip(advertencia, warning=True)
    confirma = st.checkbox(f"Confirmo que quiero eliminar {len(ids)} flota(s)", key="fl_del_confirm")
    if not confirma:
        return

    label_btn = "Eliminar TODAS las flotas" if es_total else f"Eliminar {len(ids)} flota(s)"
    if not st.button(label_btn, type="primary", key="fl_del_btn"):
        return

    errores = []
    eliminadas = 0
    contenedor_errores = st.container()
    for fid in ids:
        ok, err = _eliminar_flota(token, fid)
        if ok:
            eliminadas += 1
        else:
            errores.append((fid, err))
            with contenedor_errores:
                render_error_item(f"[{fid}] — {err}")

    if eliminadas:
        st.success(f"{eliminadas} de {len(ids)} flota(s) eliminada(s)")
    if errores:
        st.error(f"{len(errores)} de {len(ids)} fallaron")

    st.session_state.pop("fl_flotas_cache", None)
    st.session_state.pop("fl_del_sel", None)
    st.session_state.pop("fl_del_confirm", None)


def pagina_flotas():
    render_header("Flotas", "Listar, crear, editar y eliminar flotas (addon fleets)")

    render_guide(
        steps=[
            "<strong>Ingresa el token</strong> — Token de API SimpliRoute. Se valida contra <code>/accounts/me/</code>.",
            "<strong>Listar</strong> — Tabla con todas las flotas de la cuenta (id, nombre, # vehiculos, # usuarios).",
            "<strong>Crear</strong> — Define nombre y selecciona vehiculos / usuarios (por listado o pegando IDs).",
            "<strong>Editar</strong> — Selecciona una flota, modifica nombre / vehiculos / usuarios. Guardar envia el array completo via <code>PUT</code>.",
            "<strong>Eliminar</strong> — Selecciona flota(s), confirma y se eliminan via <code>DELETE</code>.",
        ],
        tip="Para vehiculos y usuarios podes elegir entre <strong>Listado</strong> (carga via API y multiselect) o <strong>Texto</strong> (pega IDs separados por linea o coma). Cambia con el radio.",
    )

    render_label("Token de API")
    token = st.text_input(
        "Token",
        type="password",
        label_visibility="collapsed",
        placeholder="Token de API SimpliRoute",
        key="fl_token",
    )

    if not token:
        render_tip("Ingresa el token de la cuenta para continuar.")
        st.stop()

    ok_cuenta, nombre_cuenta = _validar_cuenta(token)
    if not ok_cuenta:
        st.error("Token invalido o sin acceso a la cuenta.")
        st.stop()
    render_cuenta_badge(f"Cuenta: {nombre_cuenta}")

    # Si el token cambio, invalida caches de listas/opciones
    if st.session_state.get("fl_last_token") != token:
        for k in list(st.session_state.keys()):
            if k.startswith("fl_") and k not in ("fl_token",):
                del st.session_state[k]
        st.session_state["fl_last_token"] = token

    tab_listar, tab_crear, tab_editar, tab_eliminar = st.tabs(["Listar", "Crear", "Editar", "Eliminar"])

    with tab_listar:
        _tab_listar(token)
    with tab_crear:
        _tab_crear(token)
    with tab_editar:
        _tab_editar(token)
    with tab_eliminar:
        _tab_eliminar(token)
