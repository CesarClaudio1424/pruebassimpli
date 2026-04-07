import time
import xml.etree.ElementTree as ET
import requests
import streamlit as st
from config import REQUEST_TIMEOUT
from utils import (
    render_header, render_guide, render_label, render_tip,
    render_stat,
)

ZONA_DELAY = 0.5  # seconds between zone creation requests

# Spanish day name → English mapping (also handles abbreviations)
_DIA_MAP = {
    "LUNES": "Monday",
    "LUN": "Monday",
    "L": "Monday",
    "MARTES": "Tuesday",
    "MAR": "Tuesday",
    "MA": "Tuesday",
    "MIERCOLES": "Wednesday",
    "MIÉRCOLES": "Wednesday",
    "MIE": "Wednesday",
    "MIÉ": "Wednesday",
    "MI": "Wednesday",
    "X": "Wednesday",
    "JUEVES": "Thursday",
    "JUE": "Thursday",
    "J": "Thursday",
    "VIERNES": "Friday",
    "VIE": "Friday",
    "V": "Friday",
    "SABADO": "Saturday",
    "SÁBADO": "Saturday",
    "SAB": "Saturday",
    "SÁB": "Saturday",
    "S": "Saturday",
    "DOMINGO": "Sunday",
    "DOM": "Sunday",
    "D": "Sunday",
}

_ALL_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_DAY_ORDER = {d: i for i, d in enumerate(_ALL_DAYS)}

# Spanish abbreviated day names (single letter, miércoles = X)
_DIA_ABBR = {
    "LUNES": "L",   "LUN": "L",
    "MARTES": "M",  "MAR": "M",
    "MIERCOLES": "X", "MIÉRCOLES": "X", "MIE": "X", "MIÉ": "X",
    "JUEVES": "J",  "JUE": "J",
    "VIERNES": "V", "VIE": "V",
    "SABADO": "S",  "SÁBADO": "S", "SAB": "S", "SÁB": "S",
    "DOMINGO": "D", "DOM": "D",
}
_DIA_ORDER_ES = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"]
_DIA_ABBR_ALL = ["L", "M", "X", "J", "V", "S", "D"]


def _abbreviate_dias(raw: str, sep: str = " - ") -> str:
    """Convert a Spanish day string to abbreviated form, e.g. 'LUNES JUEVES' → 'L - J'."""
    text = raw.upper().strip()

    if any(kw in text for kw in ("TODOS", "TODA", "DIARIO", "DAILY")):
        return sep.join(_DIA_ABBR_ALL)

    # Range: "X A Y"
    if " A " in text:
        parts = text.split(" A ", 1)
        s_key = parts[0].strip()
        e_key = parts[1].strip()
        si = next((i for i, d in enumerate(_DIA_ORDER_ES) if d.startswith(s_key[:3])), None)
        ei = next((i for i, d in enumerate(_DIA_ORDER_ES) if d.startswith(e_key[:3])), None)
        if si is not None and ei is not None and si <= ei:
            return sep.join(_DIA_ABBR_ALL[si: ei + 1])

    # Space / comma separated
    tokens = [t.strip().rstrip(",") for t in text.replace(",", " ").split()]
    abbrs = [_DIA_ABBR[t] for t in tokens if t in _DIA_ABBR]
    seen, unique = set(), []
    for a in abbrs:
        if a not in seen:
            seen.add(a)
            unique.append(a)
    return sep.join(unique) if unique else raw


def _parse_schedules(dia_value: str) -> list[str]:
    """
    Parse a Spanish day string into a list of English day names.
    Examples:
      "LUNES JUEVES"      → ["Monday", "Thursday"]
      "LUNES A VIERNES"   → ["Monday","Tuesday","Wednesday","Thursday","Friday"]
      "TODOS LOS DIAS"    → all 7 days
      "LUNES A SABADO"    → Mon–Sat
    Returns [] if nothing can be parsed.
    """
    text = dia_value.upper().strip()

    # Full-week shorthands
    if any(kw in text for kw in ("TODOS", "TODA", "DIARIO", "DAILY")):
        return list(_ALL_DAYS)

    # Range: "X A Y"
    if " A " in text:
        parts = text.split(" A ", 1)
        start = _DIA_MAP.get(parts[0].strip())
        end = _DIA_MAP.get(parts[1].strip())
        if start and end:
            si, ei = _DAY_ORDER[start], _DAY_ORDER[end]
            if si <= ei:
                return _ALL_DAYS[si: ei + 1]

    # Space / comma separated list
    tokens = [t.strip().rstrip(",") for t in text.replace(",", " ").split()]
    days = [_DIA_MAP[t] for t in tokens if t in _DIA_MAP]
    seen, unique = set(), []
    for d in days:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return sorted(unique, key=lambda d: _DAY_ORDER[d])


# KML namespaces to try
_KML_NS = [
    "http://www.opengis.net/kml/2.2",
    "http://earth.google.com/kml/2.2",
    "http://earth.google.com/kml/2.1",
    "",
]


def _find(element, tag, namespaces):
    for ns in namespaces:
        prefix = f"{{{ns}}}" if ns else ""
        found = element.find(f".//{prefix}{tag}")
        if found is not None:
            return found
    return None


def _findall(element, tag, namespaces):
    results = []
    for ns in namespaces:
        prefix = f"{{{ns}}}" if ns else ""
        results.extend(element.findall(f".//{prefix}{tag}"))
    return results


def _parse_kml_bytes(content: bytes) -> list[dict]:
    """Parse KML and return list of zone dicts with kml_name, attrs, coords."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise ValueError(f"KML invalido: {e}")

    ns_used = ""
    if root.tag.startswith("{"):
        ns_used = root.tag[1:root.tag.index("}")]
    ns_list = [ns_used] + [n for n in _KML_NS if n != ns_used]

    placemarks = _findall(root, "Placemark", ns_list)
    zones = []

    for pm in placemarks:
        name_el = _find(pm, "name", ns_list)
        kml_name = (name_el.text or "").strip() if name_el is not None else ""

        attrs = {}
        for data_el in _findall(pm, "Data", ns_list):
            key = data_el.get("name", "")
            val_el = _find(data_el, "value", ns_list)
            if key and val_el is not None and val_el.text:
                attrs[key] = val_el.text.strip()
        for sd_el in _findall(pm, "SimpleData", ns_list):
            key = sd_el.get("name", "")
            if key and sd_el.text:
                attrs[key] = sd_el.text.strip()

        coords_el = _find(pm, "coordinates", ns_list)
        if coords_el is None or not coords_el.text:
            continue

        coords = []
        for point in coords_el.text.strip().split():
            parts = point.split(",")
            if len(parts) >= 2:
                try:
                    coords.append({"lat": str(float(parts[1])), "lng": str(float(parts[0]))})
                except ValueError:
                    continue

        if len(coords) < 3:
            continue

        zones.append({"kml_name": kml_name, "attrs": attrs, "coords": coords})

    return zones


def _format_coordinates(coords: list[dict]) -> str:
    parts = [f"{{'lat': '{c['lat']}','lng': '{c['lng']}'}}" for c in coords]
    return "[" + ",".join(parts) + "]"


def _apply_name_template(zone: dict, template: str, index: int) -> str:
    name = template
    for key, val in zone["attrs"].items():
        name = name.replace(f"{{{key}}}", val)
    name = name.replace("{kml_name}", zone["kml_name"])
    name = name.replace("{n}", str(index))
    return name.strip() or f"Zona {index}"


def _listar_zonas(token: str) -> tuple[list[dict], str]:
    """GET /v1/zones/ — returns (list of {id, name}, error_msg)."""
    headers = {
        "Authorization": f"Token {token}",
        "accept": "application/json, text/plain, */*",
    }
    try:
        resp = requests.get(
            "https://api.simpliroute.com/v1/zones/",
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict):
                data = data.get("results", [])
            return [{"id": z["id"], "name": z.get("name", str(z["id"]))} for z in data], ""
        return [], f"HTTP {resp.status_code}: {resp.text[:200]}"
    except requests.exceptions.RequestException as e:
        return [], f"Error de conexion: {e}"


def _eliminar_zona_api(token: str, zone_id: int) -> tuple[bool, str, str]:
    """DELETE /v1/zones/{id}/. Returns (ok, url, error_detail)."""
    url = f"https://api.simpliroute.com/v1/zones/{zone_id}"
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json;charset=UTF-8",
    }
    try:
        resp = requests.delete(url, headers=headers, timeout=REQUEST_TIMEOUT)
        if resp.status_code in (200, 204):
            return True, url, ""
        return False, url, f"HTTP {resp.status_code}: {resp.text[:400]}"
    except requests.exceptions.RequestException as e:
        return False, url, f"Error de conexion: {e}"


def _crear_zona(token: str, name: str, coordinates: str, schedules: list[str] | None = None) -> tuple[bool, str]:
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json;charset=UTF-8",
        "accept": "application/json, text/plain, */*",
    }
    payload: dict = {
        "name": name,
        "coordinates": coordinates,
        "vehicles": [],
        "schedules": schedules if schedules else [],
    }
    try:
        resp = requests.post(
            "https://api.simpliroute.com/v1/zones/",
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code in (200, 201):
            return True, ""
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except requests.exceptions.RequestException as e:
        return False, f"Error de conexion: {e}"


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def pagina_zonas_kml():
    render_header("Zonas KML", "Crea zonas desde archivos KML o elimina zonas existentes de una cuenta SimpliRoute")

    render_guide(
        steps=[
            "<strong>Token</strong> — Ingresa el token de la cuenta donde operar.",
            "<strong>Elige el modo</strong> — <em>Crear zonas desde KML</em> para subir un archivo, o <em>Eliminar zonas de la cuenta</em> para borrar zonas existentes.",
            "<strong>Crear:</strong> Sube el KML, configura el nombre con los campos del archivo y revisa el preview antes de enviar.",
            "<strong>Eliminar:</strong> Carga las zonas de la cuenta, selecciona las que quieres borrar y confirma.",
            "<strong>Procesa</strong> — Las operaciones se ejecutan una por una con un intervalo de 0.5 s. Solo se muestran los errores.",
        ],
        tip="El archivo KML puede venir de Google My Maps (Exportar capa > KML). Cada poligono del KML se convierte en una zona de SimpliRoute.",
    )

    # --- Token ---
    render_label("Token de API")
    token = st.text_input(
        "Token", type="password", placeholder="5d1fe9e...",
        label_visibility="collapsed", key="kml_token",
    )
    if not token:
        render_tip("Ingresa el token de la cuenta SimpliRoute donde se crearan las zonas.")
        st.stop()

    # --- Modo ---
    modo = st.radio(
        "Accion",
        ["Crear zonas desde KML", "Eliminar zonas de la cuenta"],
        horizontal=True,
        label_visibility="collapsed",
        key="kml_modo",
    )

    if modo == "Eliminar zonas de la cuenta":
        st.markdown("---")

        # Clear cache if token changed
        if st.session_state.get("_kml_del_token") != token:
            for k in ("_kml_zonas_lista", "_kml_del_active", "_kml_del_queue",
                      "_kml_del_total", "_kml_del_done", "_kml_del_errors"):
                st.session_state.pop(k, None)
            st.session_state["_kml_del_token"] = token

        # --- Sesion de eliminacion activa ---
        if st.session_state.get("_kml_del_active"):
            queue = st.session_state.get("_kml_del_queue", [])
            total_del = st.session_state["_kml_del_total"]
            procesados = total_del - len(queue)
            errores_del: list[dict] = st.session_state["_kml_del_errors"]

            # Progreso
            st.progress(min(procesados / total_del, 1.0), text="Eliminando zonas...")
            col_stat_del, col_cancel = st.columns([4, 1])
            with col_stat_del:
                st.markdown(render_stat(f"{procesados}/{total_del}", "procesadas"), unsafe_allow_html=True)
            with col_cancel:
                st.markdown('<div style="padding-top:1.4rem;"></div>', unsafe_allow_html=True)
                if queue and st.button("Cancelar", key="kml_btn_cancelar", use_container_width=True):
                    st.session_state["_kml_del_active"] = False
                    st.session_state.pop("_kml_del_queue", None)
                    done_so_far = st.session_state.get("_kml_del_done", 0)
                    st.warning(f"Proceso cancelado. {done_so_far} zona(s) eliminadas antes de cancelar.")
                    st.stop()

            # Errores acumulados
            for err_item in errores_del:
                with st.expander(f"✗ {err_item['label']}", expanded=True):
                    st.code(f"DELETE {err_item['url']}", language=None)
                    st.code(err_item["detail"], language=None)

            # Procesar siguiente o finalizar
            if queue:
                next_zone = queue[0]
                ok_d, url_d, det_d = _eliminar_zona_api(token, next_zone["id"])
                if ok_d:
                    st.session_state["_kml_del_done"] += 1
                else:
                    st.session_state["_kml_del_errors"].append({
                        "label": f"Zona \u00ab{next_zone['name']}\u00bb (#{next_zone['id']})",
                        "url": url_d,
                        "detail": det_d,
                    })
                st.session_state["_kml_del_queue"] = queue[1:]
                time.sleep(ZONA_DELAY)
                st.rerun()
            else:
                # Terminado
                st.session_state["_kml_del_active"] = False
                exitosos_del = st.session_state["_kml_del_done"]
                st.session_state.pop("_kml_zonas_lista", None)
                if exitosos_del == total_del:
                    st.success(f"Todas las zonas eliminadas ({exitosos_del}/{total_del})")
                elif exitosos_del > 0:
                    st.warning(f"{exitosos_del} de {total_del} zonas eliminadas.")
                else:
                    st.error("No se pudo eliminar ninguna zona.")
            st.stop()

        # --- Lista de zonas ---
        if st.button("Leer zonas de la cuenta", key="kml_btn_cargar_zonas"):
            zonas_api, err_api = _listar_zonas(token)
            if err_api:
                st.error(f"Error al cargar zonas: {err_api}")
            else:
                st.session_state["_kml_zonas_lista"] = zonas_api

        zonas_lista = st.session_state.get("_kml_zonas_lista")
        if zonas_lista is not None:
            if not zonas_lista:
                render_tip("La cuenta no tiene zonas registradas.")
            else:
                st.markdown(render_stat(len(zonas_lista), "zonas en la cuenta"), unsafe_allow_html=True)
                opciones = [f"{z['name']} (#{z['id']})" for z in zonas_lista]
                seleccion = st.multiselect(
                    "Zonas a eliminar",
                    opciones,
                    default=opciones,
                    key="kml_zonas_sel",
                )
                zonas_a_eliminar = [zonas_lista[i] for i, opt in enumerate(opciones) if opt in seleccion]

                if zonas_a_eliminar:
                    confirmar_del = st.checkbox(
                        f"Confirmo que quiero eliminar {len(zonas_a_eliminar)} zona(s)",
                        key="kml_confirmar_del",
                    )
                    if confirmar_del and st.button(
                        "Eliminar zonas seleccionadas", type="primary", key="btn_eliminar_zonas"
                    ):
                        st.session_state["_kml_del_active"] = True
                        st.session_state["_kml_del_queue"] = zonas_a_eliminar
                        st.session_state["_kml_del_total"] = len(zonas_a_eliminar)
                        st.session_state["_kml_del_done"] = 0
                        st.session_state["_kml_del_errors"] = []
                        st.rerun()

        st.stop()

    # --- Sesion de creacion activa ---
    if st.session_state.get("_kml_crear_active"):
        queue_cr = st.session_state.get("_kml_crear_queue", [])
        total_cr = st.session_state["_kml_crear_total"]
        procesados_cr = total_cr - len(queue_cr)
        errores_cr: list[dict] = st.session_state["_kml_crear_errors"]

        st.markdown("---")
        st.progress(min(procesados_cr / total_cr, 1.0), text="Creando zonas...")
        col_stat_cr, col_cancel_cr = st.columns([4, 1])
        with col_stat_cr:
            st.markdown(render_stat(f"{procesados_cr}/{total_cr}", "creadas"), unsafe_allow_html=True)
        with col_cancel_cr:
            st.markdown('<div style="padding-top:1.4rem;"></div>', unsafe_allow_html=True)
            if queue_cr and st.button("Cancelar", key="kml_btn_cancelar_crear", use_container_width=True):
                st.session_state["_kml_crear_active"] = False
                st.session_state.pop("_kml_crear_queue", None)
                done_cr = st.session_state.get("_kml_crear_done", 0)
                st.warning(f"Proceso cancelado. {done_cr} zona(s) creadas antes de cancelar.")
                st.stop()

        for err_item in errores_cr:
            with st.expander(f"✗ {err_item['label']}", expanded=True):
                st.code(err_item["detail"], language=None)

        if queue_cr:
            next_cr = queue_cr[0]
            ok_c, det_c = _crear_zona(token, next_cr["nombre"], next_cr["coords"], next_cr["schedules"])
            if ok_c:
                st.session_state["_kml_crear_done"] += 1
            else:
                st.session_state["_kml_crear_errors"].append({
                    "label": f"Zona \u00ab{next_cr['nombre']}\u00bb",
                    "detail": det_c,
                })
            st.session_state["_kml_crear_queue"] = queue_cr[1:]
            time.sleep(ZONA_DELAY)
            st.rerun()
        else:
            st.session_state["_kml_crear_active"] = False
            exitosos_cr = st.session_state["_kml_crear_done"]
            if exitosos_cr == total_cr:
                st.success(f"Todas las zonas creadas correctamente ({exitosos_cr}/{total_cr})")
            elif exitosos_cr > 0:
                st.warning(f"{exitosos_cr} de {total_cr} zonas creadas.")
            else:
                st.error("No se pudo crear ninguna zona. Revisa el token y los errores.")
        st.stop()

    # --- Upload KML ---
    render_label("Archivo KML")
    kml_file = st.file_uploader("Subir KML", type=["kml"], label_visibility="collapsed", key="kml_file")
    if kml_file is None:
        render_tip("Sube un archivo KML. Puede tener multiples poligonos (uno por Placemark).")
        st.stop()

    try:
        zones = _parse_kml_bytes(kml_file.read())
    except ValueError as e:
        st.error(str(e))
        st.stop()

    if not zones:
        st.warning("No se encontraron poligonos validos en el KML.")
        st.stop()

    # Ordered list of attribute keys across all placemarks
    all_attr_keys: list[str] = []
    seen_keys: set[str] = set()
    for z in zones:
        for k in z["attrs"]:
            if k not in seen_keys:
                all_attr_keys.append(k)
                seen_keys.add(k)

    st.markdown(render_stat(len(zones), "poligonos encontrados"), unsafe_allow_html=True)

    # --- Preview de campos (atributos del KML) ---
    if all_attr_keys:
        with st.expander("🔎 Preview de campos del KML", expanded=False):
            rows = []
            for i, z in enumerate(zones):
                row = {"N°": i + 1, "kml_name": z["kml_name"]}
                for k in all_attr_keys:
                    row[k] = z["attrs"].get(k, "")
                rows.append(row)
            st.dataframe(rows, use_container_width=True, hide_index=True)

    # --- Name configuration ---
    st.markdown("---")
    render_label("Configuracion de nombres")

    modo_nombre = st.radio(
        "Modo",
        ["Usar atributos del KML", "Nombre generico secuencial"],
        horizontal=True,
        label_visibility="collapsed",
        key="kml_modo_nombre",
    )

    if modo_nombre == "Usar atributos del KML":

        # Reset template when a new file is uploaded
        file_id = getattr(kml_file, "file_id", kml_file.name)
        if st.session_state.get("_kml_file_id") != file_id:
            st.session_state["_kml_file_id"] = file_id
            default = f"{{{all_attr_keys[0]}}}" if all_attr_keys else "{kml_name}"
            st.session_state["kml_template"] = default

        # Separator selector
        available_fields = all_attr_keys + ["kml_name", "n"]
        sep_options = [" - ", " | ", " ", "_"]

        col_sep_label, col_sep = st.columns([1, 3])
        with col_sep_label:
            st.markdown('<div style="padding-top:0.55rem;">Separador</div>', unsafe_allow_html=True)
        with col_sep:
            sep_choice = st.selectbox(
                "Separador",
                sep_options,
                label_visibility="collapsed",
                key="kml_sep_choice",
            )

        # Clickable field chips
        render_label("Campos disponibles — haz clic para agregar al nombre")
        chip_cols = st.columns(min(len(available_fields), 7))
        for i, field in enumerate(available_fields):
            with chip_cols[i % 7]:
                label = "kml_name" if field == "kml_name" else ("N°" if field == "n" else field)
                if st.button(label, key=f"kml_chip_{field}", use_container_width=True):
                    cur = st.session_state.get("kml_template", "")
                    sep = st.session_state.get("kml_sep_choice", " - ")
                    st.session_state["kml_template"] = (cur + sep if cur.strip() else "") + f"{{{field}}}"
                    st.rerun()

        # Editable template + clear button
        def _clear_template():
            st.session_state["kml_template"] = ""

        col_tpl, col_clear = st.columns([5, 1])
        with col_tpl:
            render_label("Nombre resultante")
            st.text_input("Template", key="kml_template", label_visibility="collapsed")
        with col_clear:
            st.markdown('<div style="padding-top:1.85rem;"></div>', unsafe_allow_html=True)
            st.button("Limpiar", key="kml_clear", on_click=_clear_template, use_container_width=True)

        template = st.session_state.get("kml_template", "")
        nombres_finales = [_apply_name_template(z, template, i + 1) for i, z in enumerate(zones)]

    else:
        col_pref, col_start = st.columns([3, 1])
        with col_pref:
            prefijo = st.text_input("Prefijo", value="Zona", key="kml_prefijo")
        with col_start:
            inicio = st.number_input("Inicio", value=1, min_value=1, step=1, key="kml_inicio")
        nombres_finales = [f"{prefijo} {i + int(inicio)}" for i in range(len(zones))]

    # --- Configuracion de dias (opcional) ---
    # Auto-detect a field that looks like a day field
    dia_field_default = next(
        (k for k in all_attr_keys if "dia" in k.lower() or "día" in k.lower() or "day" in k.lower()),
        None,
    )
    schedules_por_zona: list[list[str]] = [[] for _ in zones]

    if all_attr_keys:
        st.markdown("---")
        usar_dias = st.checkbox(
            "Configurar dias (schedules) desde el KML",
            value=dia_field_default is not None,
            key="kml_usar_dias",
        )

        if usar_dias:
            col_campo, col_fmt = st.columns([3, 2])
            with col_campo:
                campo_dia = st.selectbox(
                    "Campo de dias",
                    all_attr_keys,
                    index=all_attr_keys.index(dia_field_default) if dia_field_default else 0,
                    key="kml_campo_dia",
                )
            with col_fmt:
                fmt_dia = st.radio(
                    "Formato en el nombre",
                    ["Completo", "Abreviado (L - J)"],
                    horizontal=True,
                    key="kml_fmt_dia",
                )

            abreviar = fmt_dia == "Abreviado (L - J)"
            sep_abbr = st.session_state.get("kml_sep_choice", " - ")

            # Parse schedules and optionally build abbreviated attrs override
            parsed_rows = []
            for i, z in enumerate(zones):
                raw = z["attrs"].get(campo_dia, "")
                days = _parse_schedules(raw) if raw else []
                schedules_por_zona[i] = days
                abbr = _abbreviate_dias(raw, sep_abbr) if abreviar and raw else raw
                parsed_rows.append({
                    "N°": i + 1,
                    "Nombre": nombres_finales[i],
                    "Valor en KML": raw,
                    "Abreviado": abbr,
                    "Dias (EN)": ", ".join(days) if days else "— sin parsear —",
                })

            with st.expander("Preview de dias por zona", expanded=True):
                st.dataframe(parsed_rows, use_container_width=True, hide_index=True)

            sin_dias = [r["N°"] for r in parsed_rows if "sin parsear" in r["Dias (EN)"]]
            if sin_dias:
                render_tip(
                    f"<strong>⚠️ Atencion:</strong> No se pudieron parsear los dias de las zonas {sin_dias}. "
                    "Se enviaran sin <code>schedules</code>.",
                    warning=True,
                )

            # Apply abbreviation override to attrs used for name template
            if abreviar:
                nombres_finales = [
                    _apply_name_template(
                        {**z, "attrs": {**z["attrs"], campo_dia: parsed_rows[i]["Abreviado"]}},
                        st.session_state.get("kml_template", "") if modo_nombre == "Usar atributos del KML" else "",
                        i + 1,
                    )
                    if modo_nombre == "Usar atributos del KML"
                    else nombres_finales[i]
                    for i, z in enumerate(zones)
                ]

    # --- Preview de zonas ---
    st.markdown("---")
    render_label("Preview de zonas")

    preview_data = []
    for i, (z, nombre) in enumerate(zip(zones, nombres_finales)):
        row = {"N°": i + 1, "Nombre": nombre, "Puntos": len(z["coords"])}
        if any(schedules_por_zona):
            row["Dias"] = ", ".join(schedules_por_zona[i]) if schedules_por_zona[i] else "—"
        preview_data.append(row)
    st.dataframe(preview_data, use_container_width=True, hide_index=True)

    nombres_vacios = [i + 1 for i, n in enumerate(nombres_finales) if not n.strip()]
    nombres_dup = list(dict.fromkeys(n for n in nombres_finales if nombres_finales.count(n) > 1))

    if nombres_vacios:
        render_tip(f"<strong>⚠️ Atencion:</strong> Zona(s) {nombres_vacios} con nombre vacio. Ajusta la plantilla.", warning=True)
    if nombres_dup:
        render_tip(f"<strong>⚠️ Atencion:</strong> Nombres duplicados: {nombres_dup}. SimpliRoute puede rechazarlos.", warning=True)

    # --- Crear zonas ---
    st.markdown("---")
    if st.button("Crear zonas en SimpliRoute", type="primary", key="btn_crear_zonas"):
        queue_items = [
            {
                "nombre": nombre,
                "coords": _format_coordinates(z["coords"]),
                "schedules": schedules_por_zona[i] if schedules_por_zona[i] else None,
            }
            for i, (z, nombre) in enumerate(zip(zones, nombres_finales))
        ]
        st.session_state["_kml_crear_active"] = True
        st.session_state["_kml_crear_queue"] = queue_items
        st.session_state["_kml_crear_total"] = len(queue_items)
        st.session_state["_kml_crear_done"] = 0
        st.session_state["_kml_crear_errors"] = []
        st.rerun()
