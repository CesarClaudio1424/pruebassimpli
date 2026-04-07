import time
import xml.etree.ElementTree as ET
import requests
import streamlit as st
from config import REQUEST_TIMEOUT
from utils import (
    render_header, render_guide, render_label, render_tip,
    render_error_item, create_progress_tracker, update_progress, finish_progress,
    render_stat,
)

ZONA_DELAY = 0.5  # seconds between zone creation requests

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


def _crear_zona(token: str, name: str, coordinates: str) -> tuple[bool, str]:
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json;charset=UTF-8",
        "accept": "application/json, text/plain, */*",
    }
    payload = {"name": name, "coordinates": coordinates, "vehicles": []}
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
    render_header("Zonas KML", "Carga poligonos desde archivos KML y crealos como zonas en SimpliRoute")

    render_guide(
        steps=[
            "<strong>Token</strong> — Ingresa el token de la cuenta donde se crearan las zonas.",
            "<strong>Sube el KML</strong> — Exporta el archivo desde Google My Maps u otra herramienta. Puede tener multiples poligonos.",
            "<strong>Configura el nombre</strong> — Haz clic en los campos para componerlo o usa nombres genericos secuenciales.",
            "<strong>Revisa el preview</strong> — Confirma los nombres y cantidad de puntos antes de enviar.",
            "<strong>Crea las zonas</strong> — Se envian una por una con un intervalo de 0.5 s. Solo se muestran los errores.",
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
                label = "kml_name" if field == "kml_name" else ("#" if field == "n" else field)
                if st.button(label, key=f"kml_chip_{field}", use_container_width=True):
                    cur = st.session_state.get("kml_template", "")
                    sep = st.session_state.get("kml_sep_choice", " - ")
                    st.session_state["kml_template"] = (cur + sep if cur.strip() else "") + f"{{{field}}}"
                    st.rerun()

        # Editable template + clear button
        col_tpl, col_clear = st.columns([5, 1])
        with col_tpl:
            render_label("Nombre resultante")
            st.text_input("Template", key="kml_template", label_visibility="collapsed")
        with col_clear:
            st.markdown('<div style="padding-top:1.85rem;"></div>', unsafe_allow_html=True)
            if st.button("Limpiar", key="kml_clear", use_container_width=True):
                st.session_state["kml_template"] = ""
                st.rerun()

        template = st.session_state.get("kml_template", "")
        nombres_finales = [_apply_name_template(z, template, i + 1) for i, z in enumerate(zones)]

    else:
        col_pref, col_start = st.columns([3, 1])
        with col_pref:
            prefijo = st.text_input("Prefijo", value="Zona", key="kml_prefijo")
        with col_start:
            inicio = st.number_input("Inicio", value=1, min_value=1, step=1, key="kml_inicio")
        nombres_finales = [f"{prefijo} {i + int(inicio)}" for i in range(len(zones))]

    # --- Preview de zonas ---
    st.markdown("---")
    render_label("Preview de zonas")

    preview_data = [
        {
            "N°": i + 1,
            "Nombre": nombre,
            "Puntos": len(z["coords"]),
        }
        for i, (z, nombre) in enumerate(zip(zones, nombres_finales))
    ]
    st.dataframe(preview_data, use_container_width=True, hide_index=True)

    nombres_vacios = [i + 1 for i, n in enumerate(nombres_finales) if not n.strip()]
    nombres_dup = list(dict.fromkeys(n for n in nombres_finales if nombres_finales.count(n) > 1))

    if nombres_vacios:
        render_tip(f"<strong>⚠️ Atencion:</strong> Zona(s) {nombres_vacios} con nombre vacio. Ajusta la plantilla.", warning=True)
    if nombres_dup:
        render_tip(f"<strong>⚠️ Atencion:</strong> Nombres duplicados: {nombres_dup}. SimpliRoute puede rechazarlos.", warning=True)

    # --- Crear zonas ---
    st.markdown("---")
    if not st.button("Crear zonas en SimpliRoute", type="primary", key="btn_crear_zonas"):
        st.stop()

    total = len(zones)
    exitosos = 0
    barra, contador, contenedor_errores = create_progress_tracker(total, "Creando zonas...")

    for i, (z, nombre) in enumerate(zip(zones, nombres_finales)):
        coords_str = _format_coordinates(z["coords"])
        ok, detalle = _crear_zona(token, nombre, coords_str)
        procesados = i + 1

        if ok:
            exitosos += 1
        else:
            with contenedor_errores:
                render_error_item(f"Zona {procesados} «{nombre}» — {detalle}")

        update_progress(barra, contador, procesados, total, "Creando zonas...")

        if procesados < total:
            time.sleep(ZONA_DELAY)

    finish_progress(barra)

    if exitosos == total:
        st.success(f"Todas las zonas creadas correctamente ({exitosos}/{total})")
    elif exitosos > 0:
        st.warning(f"{exitosos} de {total} zonas creadas. Revisa los errores arriba.")
    else:
        st.error("No se pudo crear ninguna zona. Revisa el token y los errores.")
