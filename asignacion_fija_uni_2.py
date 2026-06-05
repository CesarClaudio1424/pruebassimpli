import re
import streamlit as st
import pandas as pd
import requests as _requests
import unicodedata
import io
import json
import os
from datetime import date, datetime
from utils import (
    render_header, render_guide, render_stat, render_label,
    render_tip, render_error_item,
    create_progress_tracker, update_progress, finish_progress,
)

_LOADER_CSS = """
<style>
@keyframes sr-afu-spin { to { transform: rotate(360deg); } }
@keyframes sr-afu-pulse { 0%,100% { opacity:1; } 50% { opacity:.5; } }
.sr-afu-loader {
    display: flex; flex-direction: column; align-items: center;
    padding: 2rem 1rem; margin: 1rem 0; border-radius: 0.8rem;
    background: linear-gradient(135deg, rgba(42,43,161,0.08) 0%, rgba(54,156,255,0.08) 100%);
    border: 1px solid rgba(42,43,161,0.15);
}
.sr-afu-spinner {
    width: 56px; height: 56px; border-radius: 50%;
    border: 5px solid rgba(42,43,161,0.15);
    border-top-color: #2A2BA1; border-right-color: #369CFF;
    animation: sr-afu-spin 0.9s linear infinite;
}
.sr-afu-text {
    margin-top: 1rem; color: #2A2BA1; font-weight: 700;
    font-size: 1rem; letter-spacing: -0.01em;
    animation: sr-afu-pulse 1.4s ease-in-out infinite;
}
.sr-afu-sub { margin-top: 0.25rem; color: #666; font-size: 0.8rem; }
</style>
"""


def _render_loader(placeholder, mensaje, sub=""):
    sub_html = f'<div class="sr-afu-sub">{sub}</div>' if sub else ""
    placeholder.markdown(
        f'{_LOADER_CSS}<div class="sr-afu-loader">'
        f'<div class="sr-afu-spinner"></div>'
        f'<div class="sr-afu-text">{mensaje}</div>{sub_html}</div>',
        unsafe_allow_html=True,
    )

# Tablas Supabase propias de esta seccion (independientes del proceso original)
_TABLA_PLANEACION = "smart_route_planeacion"

AGENCIAS_VALIDAS = {"tlahuac": "Tláhuac", "monterrey": "Monterrey"}
HORA_INICIO_FIJA = "07:00"
HORA_FINAL_FIJA = "23:00"
DURACION_FIJA = 7
UPSERT_BATCH_SIZE = 500

RUTAS_MONTERREY = [
    "R20082-MX01", "R20083-MX01", "R20312-MX01", "R20338-MX01",
    "R20340-MX01", "R20342-MX01", "R20343-MX01", "R20345-MX01", "R20348-MX01",
    "R20351-MX01", "R20352-MX01", "R20353-MX01", "R20355-MX01", "R20361-MX01",
    "R20362-MX01", "R20363-MX01", "R20364-MX01", "R20378-MX01", "R20384-MX01",
    "R21218-MX01",
]
ESPECIALES_MONTERREY = [
    "R1001FM-MX01",
    "R1001EV-MX01",
]


def _col_letter_to_index(letter):
    letter = letter.upper()
    result = 0
    for c in letter:
        result = result * 26 + (ord(c) - ord("A") + 1)
    return result - 1


COL_AGENCIA = _col_letter_to_index("C")
COL_CLIENTE = _col_letter_to_index("D")
COL_SECTOR = _col_letter_to_index("AH")


def _sin_acentos(texto):
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _normalizar_agencia(valor):
    clave = _sin_acentos(str(valor).strip()).lower()
    return AGENCIAS_VALIDAS.get(clave)


def _get_supabase_client():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
    except (KeyError, FileNotFoundError):
        st.error("Faltan credenciales de Supabase en secrets. Agregar [supabase] con url y key.")
        st.stop()
    from supabase import create_client
    return create_client(url, key)


def _leer_archivo(archivo):
    nombre = archivo.name.lower()
    if nombre.endswith(".csv"):
        df = pd.read_csv(archivo, dtype=str, header=0, encoding="ISO-8859-1")
    else:
        df = pd.read_excel(archivo, dtype=str, header=0)
    return df.fillna("")


def _extraer_registros(df):
    registros = []
    descartados_agencia = 0
    descartados_vacios = 0

    max_col = max(COL_AGENCIA, COL_CLIENTE, COL_SECTOR)
    for _, row in df.iterrows():
        if len(row) <= max_col:
            descartados_vacios += 1
            continue

        agencia_raw = str(row.iloc[COL_AGENCIA]).strip()
        cliente = str(row.iloc[COL_CLIENTE]).strip()
        sector = str(row.iloc[COL_SECTOR]).strip()

        if not cliente:
            descartados_vacios += 1
            continue

        agencia = _normalizar_agencia(agencia_raw)
        if agencia is None:
            descartados_agencia += 1
            continue

        registros.append({
            "cliente": cliente,
            "sector": sector,
            "agencia": agencia,
        })

    vistos = set()
    unicos = []
    duplicados = 0
    for r in registros:
        if r["cliente"] in vistos:
            duplicados += 1
            continue
        vistos.add(r["cliente"])
        unicos.append(r)

    return unicos, {
        "descartados_agencia": descartados_agencia,
        "descartados_vacios": descartados_vacios,
        "duplicados": duplicados,
    }


def _contar_existentes(supabase, clientes):
    existentes = set()
    for i in range(0, len(clientes), 500):
        lote = clientes[i:i + 500]
        try:
            resp = supabase.table(_TABLA_PLANEACION).select("cliente").in_("cliente", lote).execute()
            for row in resp.data or []:
                existentes.add(row["cliente"])
        except Exception as e:
            st.warning(f"No se pudo contar existentes: {e}")
            return None
    return existentes


def _upsert_lote(supabase, registros):
    return supabase.table(_TABLA_PLANEACION).upsert(
        registros, on_conflict="cliente"
    ).execute()


_META_FILE = os.path.join(os.path.dirname(__file__), ".smart_planeacion_meta.json")


def _get_last_updated() -> dict | None:
    try:
        with open(_META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _set_last_updated(exitosos: int, total: int):
    data = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "exitosos": exitosos,
        "total": total,
    }
    try:
        with open(_META_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def _rotar_habilidades(existentes, nueva):
    """
    Pone `nueva` en posicion 1 y recorre las demas sin duplicados.
    Trata el mismo numero con o sin prefijo F como el mismo skill
    (ej: '20020' y 'F20020' se consideran iguales) para migrar el
    formato viejo al nuevo de forma transparente.
    existentes: lista de 4 valores (pueden ser None/vacios).
    Retorna: lista de exactamente 4 valores.
    """
    nueva_num = nueva.lstrip("F")
    limpia = [
        h for h in existentes
        if h and str(h).strip() not in ("", "None", "null", "nan")
    ]
    limpia = [h for h in limpia if str(h).lstrip("F") != nueva_num]
    rotada = ([nueva] + limpia)[:4]
    while len(rotada) < 4:
        rotada.append(None)
    return rotada


def _seccion_actualizar_planeacion():
    meta = _get_last_updated()
    if meta:
        render_tip(
            f"Última actualización: <strong>{meta['ts']}</strong> — "
            f"{meta['exitosos']:,} de {meta['total']:,} registros subidos"
        )
    else:
        render_tip("Sin actualizaciones registradas aún.")

    render_label("Archivo Excel de planeacion")
    archivo = st.file_uploader(
        "Sube el archivo con la planeacion",
        type=["xlsx", "xls", "csv"],
        key="afu2_archivo",
    )

    if not archivo:
        render_tip(
            "Columnas esperadas: <strong>C</strong> = Agencia, <strong>D</strong> = Cliente, "
            "<strong>AH</strong> = Sector. "
            "Solo se cargan filas de <strong>Tláhuac</strong> y <strong>Monterrey</strong>."
        )
        return

    loader = st.empty()
    _render_loader(loader, "Leyendo archivo...", f"Procesando {archivo.name}")
    try:
        df = _leer_archivo(archivo)
    except Exception as e:
        loader.empty()
        st.error(f"Error al leer el archivo: {e}")
        return

    _render_loader(loader, "Extrayendo registros validos...", f"{len(df):,} filas detectadas")
    registros, stats = _extraer_registros(df)
    loader.empty()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(render_stat(len(df), "Filas leidas"), unsafe_allow_html=True)
    with col2:
        n_tlahuac = sum(1 for r in registros if r["agencia"] == "Tláhuac")
        st.markdown(render_stat(n_tlahuac, "Tláhuac"), unsafe_allow_html=True)
    with col3:
        n_mty = sum(1 for r in registros if r["agencia"] == "Monterrey")
        st.markdown(render_stat(n_mty, "Monterrey"), unsafe_allow_html=True)
    with col4:
        st.markdown(render_stat(len(registros), "A subir"), unsafe_allow_html=True)

    if stats["descartados_agencia"] or stats["descartados_vacios"] or stats["duplicados"]:
        render_tip(
            f"Descartes — otras agencias: <strong>{stats['descartados_agencia']}</strong> · "
            f"vacios: <strong>{stats['descartados_vacios']}</strong> · "
            f"duplicados: <strong>{stats['duplicados']}</strong>"
        )

    if not registros:
        render_tip("No hay filas validas para subir.", warning=True)
        return

    render_label("Vista previa")
    st.dataframe(pd.DataFrame(registros).head(20), use_container_width=True)

    if not st.button("Subir a Supabase", type="primary", use_container_width=True, key="afu2_btn_subir"):
        return

    supabase = _get_supabase_client()
    loader = st.empty()

    _render_loader(loader, "Consultando clientes existentes...", f"{len(registros):,} a verificar")
    clientes = [r["cliente"] for r in registros]
    existentes = _contar_existentes(supabase, clientes)

    total = len(registros)
    total_lotes = (total + UPSERT_BATCH_SIZE - 1) // UPSERT_BATCH_SIZE
    barra, contador, contenedor_errores = create_progress_tracker(total, text="Subiendo a Supabase...")

    procesados = 0
    errores = 0
    for i in range(0, total, UPSERT_BATCH_SIZE):
        lote_num = i // UPSERT_BATCH_SIZE + 1
        _render_loader(loader, f"Subiendo lote {lote_num} de {total_lotes}...", f"{len(registros[i:i+UPSERT_BATCH_SIZE])} registros en este lote")
        lote = registros[i:i + UPSERT_BATCH_SIZE]
        try:
            _upsert_lote(supabase, lote)
        except Exception as e:
            errores += len(lote)
            with contenedor_errores:
                render_error_item(f"Lote {lote_num}: {e}")
        procesados += len(lote)
        update_progress(barra, contador, procesados, total, text="Subiendo a Supabase...")

    loader.empty()
    finish_progress(barra)

    exitosos = total - errores
    nuevos = exitosos - len(existentes) if existentes is not None else None
    actualizados = len(existentes) if existentes is not None else None

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(render_stat(exitosos, "Procesados OK"), unsafe_allow_html=True)
    with col2:
        if nuevos is not None:
            st.markdown(render_stat(nuevos, "Nuevos"), unsafe_allow_html=True)
    with col3:
        if actualizados is not None:
            st.markdown(render_stat(actualizados, "Actualizados"), unsafe_allow_html=True)

    if errores:
        render_tip(f"Hubo {errores} registros con error. Revisa los mensajes arriba.", warning=True)
    else:
        render_tip("Todos los registros se subieron correctamente.")
        _set_last_updated(exitosos, total)


HAB_COL_B_HABILIDAD = 1
HAB_COL_S_CLIENTE = 18


def _limpiar_nota_cliente(texto):
    """Quita el sufijo entre parentesis para el match.
    Ej: '30880451(F05 MTY)' -> '30880451'. Si no hay '(' devuelve el texto tal cual.
    """
    if not texto:
        return ""
    idx = texto.find("(")
    return (texto[:idx] if idx >= 0 else texto).strip()


# ---------------------------------------------------------------------------
# Tab 2 — Generar archivos de ruteo (Smart Route)
# ---------------------------------------------------------------------------
# Entrada: "Monitoreo de Pedidos" -> se usa SOLO la hoja "BD".
# Posiciones de columna en la hoja BD:
BD_SHEET = "BD"
BD_COL_CODIGO = 0          # A  Codigo (codigo de pedido, ej MOBMX...)
BD_COL_TIPO = 1            # B  Tipo (Sales order / otros)
BD_COL_CODIGO_CLIENTE = 3  # D  Codigo Cliente (ej 0010757344-MX01)
BD_COL_RUTEO = 8           # I  Ruteo (REP ELECT / PREVENTA / ...)
BD_COL_CANT_PEDIDO = 13    # N  Cant. Pedido  -> Carga 2
BD_COL_TOTAL_IMP = 17      # R  Total + Impuestos -> Carga 3

RUTEO_VALIDOS = {"REP ELECT", "PREVENTA"}

# Salida A: formato "ruta fija" (Corte 1). La penultima columna (N) va sin encabezado.
SALIDA_A_COLS = [
    "customer_id_sap", "nombre", "tiempo_de_servicio", "horario_de_inicio",
    "horario_de_fin", "latitud", "longitud", "Telefono", "tiene_ruta_fija",
    "nombre_ruta", "secuencia_en_ruta_fija", "estado_de_consideracion",
    "estado_de_ruta_especial_puebla", "", "Cliente",
]

# Salida B: formato RUTEO_DINAMICO (el que ya se usa hoy) solo para los "Fuera".
RUTEO_DINAMICO_COLS = [
    "Titulo", "Direccion", "Carga", "Hora Inicial", "Hora Final",
    "Tiempo Servicio", "Notas", "Latitud", "Longitud", "ID",
    "Habilidades requeridas", "Habilidades Opcionales", "Persona de contacto",
    "Telefono de contacto", "Hora Inicial 2", "Hora Final 2", "Carga 2",
    "Carga 3", "Prioridad", "SMS", "Correo electronico de contacto",
    "Pick Carga", "Pick Carga 2", "Pick Carga 3", "Fecha Programada",
    "Tipo de Visita", "Agencia",
]


def _limpiar_codigo_cliente(valor):
    """'0010757344-MX01' -> '10757344'. Quita sufijo -MX## y ceros a la izquierda."""
    s = str(valor).strip()
    if not s:
        return ""
    s = s.split("-")[0]
    s = s.lstrip("0")
    return s


def _num_habilidad(hab):
    """Normaliza cualquier formato de habilidad a su numero/especial pelon.
    'F20020' -> '20020', 'R20020-MX01' -> '20020', '20020' -> '20020',
    'R1001FM-MX01' -> '1001FM', 'Fuera'/vacio -> None.
    """
    if hab is None:
        return None
    s = str(hab).strip()
    if not s or s.lower() in ("fuera", "none", "nan", "null"):
        return None
    m = re.match(r'^R(.+?)-MX\d+$', s)
    if m:
        s = m.group(1)
    s = s.lstrip("F")
    return s or None


def _ruta_nombre(num):
    """Numero/especial pelon -> formato nuevo 'R20020-MX01'."""
    return f"R{num}-MX01"


def _fmt_hora(val, default):
    s = str(val or "").strip()
    if not s or s.lower() in ("none", "nan", "null"):
        return default
    partes = s.split(":")
    if len(partes) == 2:
        return f"{s}:00"
    return s


def _tabla_ruteo_dia(agencia):
    return "smart_tlahuac" if agencia == "Tláhuac" else "smart_monterrey"


def _guardar_ruteo_dia(supabase, filas, agencia):
    tabla = _tabla_ruteo_dia(agencia)
    try:
        supabase.table(tabla).upsert(filas, on_conflict="reference").execute()
    except Exception as e:
        st.warning(f"No se pudo guardar en {tabla}: {e}")


def _fetch_planeacion_smart(supabase, clientes):
    datos = {}
    for i in range(0, len(clientes), 500):
        lote = clientes[i:i + 500]
        try:
            resp = supabase.table(_TABLA_PLANEACION).select(
                "cliente,nombre,direccion,latitud,longitud,"
                "hora_inicio,hora_final,duracion,"
                "habilidad_1,habilidad_2,habilidad_3,habilidad_4"
            ).in_("cliente", lote).execute()
            for row in resp.data or []:
                datos[row["cliente"]] = row
        except Exception as e:
            st.warning(f"Error consultando Supabase: {e}")
            return datos
    return datos


def _try_num(val):
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.lower() in ("none", "nan", "null", ""):
        return None
    try:
        f = float(s)
        return int(f) if f == int(f) else f
    except (ValueError, TypeError):
        return None


def _escribir_excel(df, sheet_name, num_cols=()):
    """Escribe un df a xlsx, coercionando a numerico las columnas indicadas."""
    df = df.copy()
    for c in num_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    buffer.seek(0)
    return buffer


def _procesar_ruteo_2(df_bd, nombre_original, habilidades_disponibles, agencia):
    loader = st.empty()
    supabase = _get_supabase_client()

    _render_loader(loader, "Filtrando pedidos...", f"{len(df_bd):,} filas en hoja BD")

    # 1. Filtro por Ruteo (col I) y armado de filas
    filas = []
    descartados = {}
    for idx in range(len(df_bd)):
        ruteo_val = (
            str(df_bd.iat[idx, BD_COL_RUTEO]).strip().upper()
            if df_bd.shape[1] > BD_COL_RUTEO else ""
        )
        if ruteo_val not in RUTEO_VALIDOS:
            clave = ruteo_val or "(vacío)"
            descartados[clave] = descartados.get(clave, 0) + 1
            continue

        order_code = str(df_bd.iat[idx, BD_COL_CODIGO]).strip()
        match_code = _limpiar_codigo_cliente(df_bd.iat[idx, BD_COL_CODIGO_CLIENTE])
        if not match_code:
            descartados["(sin código cliente)"] = descartados.get("(sin código cliente)", 0) + 1
            continue
        tipo = str(df_bd.iat[idx, BD_COL_TIPO]).strip()
        cant = str(df_bd.iat[idx, BD_COL_CANT_PEDIDO]).strip() if df_bd.shape[1] > BD_COL_CANT_PEDIDO else ""
        total = str(df_bd.iat[idx, BD_COL_TOTAL_IMP]).strip() if df_bd.shape[1] > BD_COL_TOTAL_IMP else ""
        filas.append({
            "order": order_code, "cliente": match_code,
            "tipo": tipo, "cant": cant, "total": total,
        })

    # 2. Lookup planeacion
    clientes = list({f["cliente"] for f in filas})
    _render_loader(loader, "Consultando planeación...", f"{len(clientes):,} clientes")
    lookup = _fetch_planeacion_smart(supabase, clientes)

    # 3. Clasificacion
    _render_loader(loader, "Clasificando ruta fija / fuera...", f"{len(filas):,} pedidos")
    salida_a = {}      # cliente -> fila (unico por cliente)
    salida_b_rows = []  # por pedido
    smart_dia = []      # upsert smart_* (solo fuera, por reference de pedido)

    for f in filas:
        data = lookup.get(f["cliente"])
        ruta_num = None
        if data:
            for n in range(1, 5):
                num = _num_habilidad(data.get(f"habilidad_{n}"))
                if num and num in habilidades_disponibles:
                    ruta_num = num
                    break

        if ruta_num:
            # SALIDA A — ruta fija (dedup por cliente)
            if f["cliente"] not in salida_a:
                dur = data.get("duracion")
                salida_a[f["cliente"]] = {
                    "customer_id_sap": f["cliente"],
                    "nombre": data.get("nombre") or "",
                    "tiempo_de_servicio": dur if (dur not in (None, "")) else 15,
                    "horario_de_inicio": _fmt_hora(data.get("hora_inicio"), "08:00:00"),
                    "horario_de_fin": _fmt_hora(data.get("hora_final"), "20:00:00"),
                    "latitud": data.get("latitud") or "",
                    "longitud": data.get("longitud") or "",
                    "Telefono": "",
                    "tiene_ruta_fija": "enabled",
                    "nombre_ruta": _ruta_nombre(ruta_num),
                    "secuencia_en_ruta_fija": "",
                    "estado_de_consideracion": "enabled",
                    "estado_de_ruta_especial_puebla": "disabled",
                    "": "",
                    "Cliente": f["cliente"],
                }
        else:
            # SALIDA B — Fuera (por pedido)
            titulo = (data.get("nombre") if data else "") or ""
            direccion = (data.get("direccion") if data else "") or ""
            lat = (data.get("latitud") if data else "") or ""
            lon = (data.get("longitud") if data else "") or ""
            carga = 1 if f["tipo"].strip().lower() == "sales order" else 0

            row_b = {c: "" for c in RUTEO_DINAMICO_COLS}
            row_b["Titulo"] = titulo
            row_b["Direccion"] = direccion
            row_b["Carga"] = carga
            row_b["Hora Inicial"] = "08:00:00"
            row_b["Hora Final"] = "20:00:00"
            row_b["Tiempo Servicio"] = 15
            row_b["Notas"] = f["cliente"]
            row_b["Latitud"] = lat
            row_b["Longitud"] = lon
            row_b["ID"] = f["order"]
            row_b["Habilidades requeridas"] = "Fuera"
            row_b["Carga 2"] = f["cant"]
            row_b["Carga 3"] = f["total"]
            row_b["Agencia"] = agencia
            salida_b_rows.append(row_b)

            if f["order"] and f["order"] not in ("", "nan", "None"):
                smart_dia.append({
                    "reference": f["order"],
                    "hora_inicio": "08:00",
                    "hora_final": "20:00",
                    "duracion": "15",
                    "carga_2": _try_num(f["cant"]),
                    "carga_3": _try_num(f["total"]),
                })

    # 4. Guardar en smart_* (Fuera) para el tab de Actualizar datos Simpli
    if smart_dia:
        _guardar_ruteo_dia(supabase, smart_dia, agencia)

    # 5. Construir archivos
    _render_loader(loader, "Generando archivos...", "Escribiendo xlsx")
    df_a = pd.DataFrame(list(salida_a.values()), columns=SALIDA_A_COLS)
    df_b = pd.DataFrame(salida_b_rows, columns=RUTEO_DINAMICO_COLS)

    buffer_a = _escribir_excel(
        df_a, "Hoja1",
        num_cols=["tiempo_de_servicio", "latitud", "longitud"],
    )
    buffer_b = _escribir_excel(
        df_b, "RUTEO_DINAMICO",
        num_cols=["Carga", "Tiempo Servicio", "Carga 2", "Carga 3", "Latitud", "Longitud"],
    )
    loader.empty()

    # 6. Stats
    total_filas = len(df_bd)
    kept = len(filas)
    descartados_total = total_filas - kept

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(render_stat(total_filas, "Filas en BD"), unsafe_allow_html=True)
    with col2:
        st.markdown(render_stat(len(df_a), "Ruta fija (Salida A)"), unsafe_allow_html=True)
    with col3:
        st.markdown(render_stat(len(df_b), 'Fuera (Salida B)'), unsafe_allow_html=True)
    with col4:
        st.markdown(
            render_stat(descartados_total, "Descartados",
                        style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);"),
            unsafe_allow_html=True,
        )

    if descartados:
        det = pd.DataFrame(
            sorted(descartados.items(), key=lambda kv: -kv[1]),
            columns=["Motivo (valor de Ruteo)", "Pedidos descartados"],
        )
        render_label("Pedidos no tomados")
        st.dataframe(det, use_container_width=True, hide_index=True)

    base = nombre_original.rsplit(".", 1)[0]
    col_a, col_b = st.columns(2)
    with col_a:
        st.download_button(
            "Descargar Salida A — Ruta fija",
            buffer_a,
            file_name=f"{base}_ruta_fija.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
            key="agr2_dl_a",
        )
    with col_b:
        st.download_button(
            "Descargar Salida B — Fuera (RUTEO_DINAMICO)",
            buffer_b,
            file_name=f"{base}_fuera.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
            key="agr2_dl_b",
        )


_VEHICLE_PATTERN = re.compile(r'^R(\d+[A-Z]*)-MX\d+$')


def _extraer_num_vehiculo(texto):
    """R20020-MX01 → '20020',  '20020' → '20020',  otros → None."""
    texto = texto.strip()
    m = _VEHICLE_PATTERN.match(texto)
    if m:
        return m.group(1)
    if re.match(r'^\d+$', texto):
        return texto
    return None


def _seccion_generar_ruteo():
    render_label("Agencia")
    agencia = st.radio(
        "Agencia",
        ["Tláhuac", "Monterrey"],
        horizontal=True,
        key="agr2_agencia",
        label_visibility="collapsed",
    )

    habilidades_disponibles = set()

    if agencia == "Tláhuac":
        render_label("Vehículos activos este día")
        vehiculos_txt = st.text_area(
            "Vehiculos",
            placeholder="Un vehículo por línea\nEj: R20020-MX01 ó 20020",
            key="agr2_vehiculos",
            label_visibility="collapsed",
            height=120,
        )
        nums_activos = {n for line in vehiculos_txt.splitlines() if (n := _extraer_num_vehiculo(line))}
        habilidades_disponibles = set(nums_activos)

        if nums_activos:
            render_tip(
                f"<strong>{len(nums_activos)}</strong> vehículos activos — "
                "habilidades: "
                + ", ".join(f"<code>{_ruta_nombre(n)}</code>" for n in sorted(nums_activos))
                + " — los demás quedarán como <strong>Fuera</strong>."
            )
    else:
        col_a, col_b = st.columns(2)
        with col_a:
            render_label(f"Cuántas rutas (max {len(RUTAS_MONTERREY)})")
            n_rutas = st.number_input(
                "Rutas",
                min_value=0,
                max_value=len(RUTAS_MONTERREY),
                value=min(18, len(RUTAS_MONTERREY)),
                key="agr2_n_rutas",
                label_visibility="collapsed",
            )
        with col_b:
            render_label(f"Cuántas especiales (max {len(ESPECIALES_MONTERREY)})")
            n_especiales = st.number_input(
                "Especiales",
                min_value=0,
                max_value=len(ESPECIALES_MONTERREY),
                value=0,
                key="agr2_n_especiales",
                label_visibility="collapsed",
            )

        vehiculos_seleccionados = (
            RUTAS_MONTERREY[:int(n_rutas)] + ESPECIALES_MONTERREY[:int(n_especiales)]
        )
        nums_activos = set()
        for v in vehiculos_seleccionados:
            m = _VEHICLE_PATTERN.match(v)
            if m:
                nums_activos.add(m.group(1))
        habilidades_disponibles = set(nums_activos)

        if vehiculos_seleccionados:
            render_tip(
                f"<strong>{len(vehiculos_seleccionados)}</strong> vehículos activos: "
                + ", ".join(f"<code>{v}</code>" for v in vehiculos_seleccionados)
                + " — los demás quedarán como <strong>Fuera</strong>."
            )

    st.markdown("---")

    render_label("Archivo Monitoreo de Pedidos")
    archivo = st.file_uploader(
        "Sube el archivo Monitoreo de Pedidos",
        type=["xlsx", "xls"],
        key="agr2_archivo",
        label_visibility="collapsed",
    )

    if not archivo:
        render_tip(
            "Se usa <strong>solo la hoja BD</strong>. Se toman las filas cuyo "
            "<strong>Ruteo (col I)</strong> sea <code>REP ELECT</code> o <code>PREVENTA</code> "
            "(el resto se reporta como descartado). "
            "Match por <strong>Código Cliente (col D)</strong> sin ceros ni <code>-MX01</code> "
            "contra la planeación. "
            "Genera dos archivos: <strong>Salida A</strong> (ruta fija) con los que tienen habilidad, "
            "y <strong>Salida B</strong> (RUTEO_DINAMICO) con los <strong>Fuera</strong>."
        )
        return

    loader = st.empty()
    _render_loader(loader, "Leyendo archivo...", f"Procesando {archivo.name}")
    try:
        df_bd = pd.read_excel(archivo, sheet_name=BD_SHEET, dtype=str, header=0).fillna("")
    except ValueError:
        loader.empty()
        st.error(f"El archivo no contiene la hoja '{BD_SHEET}'.")
        return
    except Exception as e:
        loader.empty()
        st.error(f"Error al leer el archivo: {e}")
        return
    loader.empty()

    if habilidades_disponibles:
        render_tip(
            f"<strong>{len(habilidades_disponibles)}</strong> habilidades activas: "
            + ", ".join(f"<code>{_ruta_nombre(n)}</code>" for n in sorted(habilidades_disponibles))
        )
    else:
        render_tip("No hay vehículos/rutas activos. Todos los clientes quedarán como <strong>Fuera</strong>.", warning=True)

    st.markdown(render_stat(len(df_bd), "Filas en hoja BD"), unsafe_allow_html=True)
    render_label("Vista previa (primeras 10 filas)")
    st.dataframe(df_bd.head(10), use_container_width=True)

    if st.button("Procesar y generar archivos", type="primary", use_container_width=True, key="agr2_btn_procesar"):
        _procesar_ruteo_2(df_bd, archivo.name, habilidades_disponibles, agencia)


def _seccion_actualizar_habilidades():
    render_label("Agencia")
    agencia = st.radio(
        "Agencia",
        ["Tláhuac", "Monterrey"],
        horizontal=True,
        key="afh2_agencia",
        label_visibility="collapsed",
    )

    render_label("Fecha de entrega del ruteo")
    fecha_ruteo = st.date_input(
        "Fecha de entrega del ruteo",
        value=date.today(),
        key="afh2_fecha",
        format="DD/MM/YYYY",
        label_visibility="collapsed",
    )

    render_label("Archivo SimpliRoute Plan")
    archivo = st.file_uploader(
        "Sube el archivo SimpliRoute_Plan_...",
        type=["xlsx", "xls"],
        key="afh2_archivo",
        label_visibility="collapsed",
    )

    if not archivo:
        render_tip(
            "Formato esperado: <strong>SimpliRoute_Plan_YYYY-MM-DD.xlsx</strong>. "
            "Columna <strong>S</strong> = Cliente (clave de match), "
            "<strong>B</strong> = Habilidad (formato R20020-MX01 → se guarda el número 20020). "
            "La habilidad se coloca en <strong>habilidad_1</strong> y se recorren las existentes."
        )
        return

    loader = st.empty()
    _render_loader(loader, "Leyendo archivo...", archivo.name)
    try:
        df = pd.read_excel(archivo, dtype=str, header=0).fillna("")
    except Exception as e:
        loader.empty()
        st.error(f"Error al leer el archivo: {e}")
        return
    loader.empty()

    registros = []
    sin_cliente = 0
    for _, row in df.iterrows():
        if len(row) <= HAB_COL_S_CLIENTE:
            sin_cliente += 1
            continue
        cliente = _limpiar_nota_cliente(str(row.iloc[HAB_COL_S_CLIENTE]))
        if not cliente or cliente.lower() in ("nan", "none", ""):
            sin_cliente += 1
            continue
        hab_raw = str(row.iloc[HAB_COL_B_HABILIDAD]).strip() if len(row) > HAB_COL_B_HABILIDAD else ""
        habilidad = hab_raw.lstrip("R").split("-")[0] if hab_raw else ""
        registros.append({"cliente": cliente, "habilidad": habilidad})

    vistos = set()
    unicos = []
    for r in registros:
        if r["cliente"] not in vistos:
            vistos.add(r["cliente"])
            unicos.append(r)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(render_stat(len(df), "Filas en archivo"), unsafe_allow_html=True)
    with col2:
        st.markdown(render_stat(len(unicos), "Clientes unicos"), unsafe_allow_html=True)
    with col3:
        st.markdown(
            render_stat(sin_cliente, "Sin cliente (descartados)",
                        style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);"),
            unsafe_allow_html=True,
        )

    if not unicos:
        render_tip("No se encontraron clientes validos en la columna S.", warning=True)
        return

    render_label("Vista previa")
    st.dataframe(pd.DataFrame(unicos).head(20), use_container_width=True, hide_index=True)

    if not st.button("Actualizar habilidades en Supabase", type="primary", use_container_width=True, key="afh2_btn"):
        return

    supabase = _get_supabase_client()

    # Leer habilidades actuales de Supabase para aplicar rotacion
    loader2 = st.empty()
    _render_loader(loader2, "Consultando habilidades actuales...", f"{len(unicos):,} clientes")
    clientes = [r["cliente"] for r in unicos]
    existentes_map = {}
    for i in range(0, len(clientes), 500):
        lote = clientes[i:i + 500]
        try:
            resp = supabase.table(_TABLA_PLANEACION).select(
                "cliente,habilidad_1,habilidad_2,habilidad_3,habilidad_4"
            ).in_("cliente", lote).execute()
            for row in resp.data or []:
                existentes_map[row["cliente"]] = row
        except Exception as e:
            st.warning(f"No se pudieron consultar habilidades existentes: {e}")
    loader2.empty()

    # Construir payload con rotacion
    payload = []
    for r in unicos:
        cliente = r["cliente"]
        nueva_hab = r["habilidad"]
        existente = existentes_map.get(cliente, {})
        actuales = [
            existente.get("habilidad_1"),
            existente.get("habilidad_2"),
            existente.get("habilidad_3"),
            existente.get("habilidad_4"),
        ]
        rotada = _rotar_habilidades(actuales, nueva_hab)
        payload.append({
            "cliente": cliente,
            "agencia": agencia,
            "habilidad_1": rotada[0],
            "habilidad_2": rotada[1],
            "habilidad_3": rotada[2],
            "habilidad_4": rotada[3],
        })

    total = len(payload)
    total_lotes = (total + UPSERT_BATCH_SIZE - 1) // UPSERT_BATCH_SIZE
    barra, contador, contenedor_errores = create_progress_tracker(total, text="Actualizando en Supabase...")

    procesados = 0
    errores = 0
    loader3 = st.empty()
    for i in range(0, total, UPSERT_BATCH_SIZE):
        lote_num = i // UPSERT_BATCH_SIZE + 1
        lote = payload[i:i + UPSERT_BATCH_SIZE]
        _render_loader(loader3, f"Subiendo lote {lote_num} de {total_lotes}...", f"{len(lote)} registros")
        try:
            supabase.table(_TABLA_PLANEACION).upsert(lote, on_conflict="cliente").execute()
        except Exception as e:
            errores += len(lote)
            with contenedor_errores:
                render_error_item(f"Lote {lote_num}: {e}")
        procesados += len(lote)
        update_progress(barra, contador, procesados, total, text="Actualizando en Supabase...")

    loader3.empty()
    finish_progress(barra)

    exitosos = total - errores
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(render_stat(exitosos, "Actualizados OK"), unsafe_allow_html=True)
    if errores:
        with col2:
            st.markdown(
                render_stat(errores, "Con error",
                            style="background: linear-gradient(135deg, #d32f2f 0%, #b71c1c 100%);"),
                unsafe_allow_html=True,
            )
        render_tip(f"Hubo {errores} registros con error. Revisa los mensajes arriba.", warning=True)
    else:
        render_tip(
            f"Todos los registros se actualizaron correctamente — "
            f"<strong>{agencia}</strong> · {fecha_ruteo.strftime('%d/%m/%Y')}."
        )


def _enviar_actualizaciones(token, visitas_put):
    MAX_BLOCK = 100
    bloques = [visitas_put[i:i + MAX_BLOCK] for i in range(0, len(visitas_put), MAX_BLOCK)]
    total_bloques = len(bloques)
    headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}

    barra = st.progress(0, text=f"Enviando {len(visitas_put)} visitas en {total_bloques} bloques...")
    resultados = {}

    for i, lote in enumerate(bloques):
        try:
            r = _requests.put(
                "https://api.simpliroute.com/v1/routes/visits/",
                json=lote, headers=headers, timeout=300,
            )
            resultados[i] = (len(lote), r.status_code, r.text[:200])
        except Exception as e:
            resultados[i] = (len(lote), 0, str(e))
        completados = i + 1
        barra.progress(completados / total_bloques, text=f"Bloques completados: {completados}/{total_bloques}")

    barra.empty()

    ok = sum(n for n, status, _ in resultados.values() if status in (200, 201, 204))
    errores_put = [
        f"Bloque {i + 1}: HTTP {status} — {text}"
        for i, (n, status, text) in sorted(resultados.items())
        if status not in (200, 201, 204)
    ]

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(render_stat(ok, "Actualizados OK"), unsafe_allow_html=True)
    with col2:
        if errores_put:
            st.markdown(
                render_stat(len(errores_put), "Bloques con error",
                            style="background: linear-gradient(135deg, #d32f2f 0%, #b71c1c 100%);"),
                unsafe_allow_html=True,
            )
    for e in errores_put:
        render_error_item(e)
    if not errores_put:
        render_tip("Todos los registros actualizados correctamente.")


def _seccion_actualizar_datos_simpli():
    render_label("Cuenta")
    cuenta = st.radio(
        "Cuenta",
        ["Tláhuac", "Monterrey"],
        horizontal=True,
        key="ads2_cuenta",
        label_visibility="collapsed",
    )
    token_key = "token_tlahuac" if cuenta == "Tláhuac" else "token_monterrey"
    try:
        token = st.secrets["cuentas_unilever"][token_key].strip()
    except Exception:
        render_tip("Token no configurado en secrets.", warning=True)
        return

    render_label("Fecha de entrega")
    fecha = st.date_input(
        "Fecha",
        value=date.today(),
        key="ads2_fecha",
        format="DD/MM/YYYY",
        label_visibility="collapsed",
    )
    fecha_str = fecha.strftime("%Y-%m-%d")

    if st.button("Consultar visitas", use_container_width=True, key="ads2_btn_consultar"):
        st.session_state.pop("ads2_visitas_put", None)
        st.session_state.pop("ads2_total_visitas", None)

        loader = st.empty()
        headers = {"Authorization": f"Token {token}"}

        _render_loader(loader, "Consultando visitas en SimpliRoute...", fecha_str)
        try:
            r = _requests.get(
                f"https://api.simpliroute.com/v1/routes/visits/?planned_date={fecha_str}",
                headers=headers, timeout=60,
            )
            r.raise_for_status()
            visitas = r.json()
        except Exception as e:
            loader.empty()
            st.error(f"Error al consultar SimpliRoute: {e}")
            return
        loader.empty()

        if not isinstance(visitas, list):
            st.error(f"Respuesta inesperada de la API: {str(visitas)[:200]}")
            return

        referencias_visitas = [v.get("reference", "") for v in visitas if v.get("reference")]

        supabase = _get_supabase_client()
        lookup_ruteo = {}
        for i in range(0, len(referencias_visitas), 500):
            lote = referencias_visitas[i:i + 500]
            try:
                resp = supabase.table(_tabla_ruteo_dia(cuenta)).select(
                    "reference,hora_inicio,hora_final,duracion,carga_2,carga_3"
                ).in_("reference", lote).execute()
                for row in resp.data or []:
                    lookup_ruteo[row["reference"]] = row
            except Exception as e:
                st.warning(f"Error consultando tabla de ruteo: {e}")

        visitas_put = []
        for v in visitas:
            ref = v.get("reference", "")
            if not ref or ref not in lookup_ruteo:
                continue
            ruteo = lookup_ruteo[ref]
            item = {
                "id": v["id"],
                "reference": ref,
                "title": v.get("title", ""),
                "address": v.get("address", ""),
                "planned_date": v.get("planned_date", ""),
                "route": v.get("route", ""),
                "window_start": ruteo.get("hora_inicio") or "",
                "window_end": ruteo.get("hora_final") or "",
            }
            dur_min = _try_num(ruteo.get("duracion"))
            if dur_min is not None:
                m = int(dur_min)
                item["duration"] = f"{m // 60:02d}:{m % 60:02d}:00"
            for campo_api, campo_ruteo in (
                ("load_2", "carga_2"),
                ("load_3", "carga_3"),
            ):
                val = _try_num(ruteo.get(campo_ruteo))
                if val is not None:
                    item[campo_api] = val
            visitas_put.append(item)

        st.session_state["ads2_visitas_put"] = visitas_put
        st.session_state["ads2_total_visitas"] = len(visitas)

    if "ads2_visitas_put" not in st.session_state:
        render_tip(
            "Ingresa la fecha de entrega y pulsa <strong>Consultar visitas</strong>. "
            "Los valores de ventana y carga provienen del último archivo procesado en "
            "<em>Generar archivos de ruteo</em>."
        )
        return

    total_visitas = st.session_state["ads2_total_visitas"]
    visitas_put = st.session_state["ads2_visitas_put"]
    sin_datos = total_visitas - len(visitas_put)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(render_stat(total_visitas, "Visitas en la fecha"), unsafe_allow_html=True)
    with col2:
        st.markdown(render_stat(len(visitas_put), "Con datos de ruteo"), unsafe_allow_html=True)
    with col3:
        st.markdown(render_stat(sin_datos, "Sin datos de ruteo"), unsafe_allow_html=True)

    if not visitas_put:
        render_tip(
            "Ninguna visita tiene datos en la tabla de ruteo. "
            "Primero genera el archivo de ruteo en la tab <em>Generar archivos de ruteo</em>.",
            warning=True,
        )
        return

    if sin_datos:
        render_tip(f"{sin_datos} visitas no tienen datos en ruteo y serán omitidas.", warning=True)

    if st.button("Actualizar en SimpliRoute", type="primary", use_container_width=True, key="ads2_btn_actualizar"):
        _enviar_actualizaciones(token, visitas_put)


def pagina_asignacion_fija_uni_2():
    render_header("Asignacion Fija Uni 2", "Smart Route — planeacion de visitas Unilever")
    render_guide(
        [
            "Selecciona la accion a ejecutar.",
            "Actualizar planeacion: sube el Excel y se filtran filas de Tláhuac y Monterrey (columna C).",
            "Generar archivos de ruteo: sube el Monitoreo de Pedidos (hoja BD); genera Salida A (ruta fija) y Salida B (Fuera).",
            "Actualizar Habilidades: guarda la habilidad como número (ej 20020) con rotacion.",
            "Tablas Supabase propias: smart_route_planeacion, smart_tlahuac, smart_monterrey.",
        ],
        "El proceso original (Asignacion Fija Uni) queda intacto como respaldo.",
    )

    tab1, tab2, tab3, tab4 = st.tabs([
        "Actualizar planeacion nacional",
        "Generar archivos de ruteo",
        "Actualizar Habilidades",
        "Actualizar datos Simpli",
    ])
    with tab1:
        _seccion_actualizar_planeacion()
    with tab2:
        _seccion_generar_ruteo()
    with tab3:
        _seccion_actualizar_habilidades()
    with tab4:
        _seccion_actualizar_datos_simpli()
