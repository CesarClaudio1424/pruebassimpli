import streamlit as st
import pandas as pd
import unicodedata
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

AGENCIAS_VALIDAS = {"tlahuac": "Tláhuac", "monterrey": "Monterrey"}
HORA_INICIO_FIJA = "07:00"
HORA_FINAL_FIJA = "23:00"
DURACION_FIJA = 7
UPSERT_BATCH_SIZE = 500


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

    for _, row in df.iterrows():
        if len(row) <= max(COL_AGENCIA, COL_CLIENTE, COL_SECTOR):
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
            "hora_inicio": HORA_INICIO_FIJA,
            "hora_final": HORA_FINAL_FIJA,
            "duracion": DURACION_FIJA,
        })

    # Dedupe por cliente (primero gana)
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
            resp = supabase.table("planeacion_nacional").select("cliente").in_("cliente", lote).execute()
            for row in resp.data or []:
                existentes.add(row["cliente"])
        except Exception as e:
            st.warning(f"No se pudo contar existentes: {e}")
            return None
    return existentes


def _upsert_lote(supabase, registros):
    return supabase.table("planeacion_nacional").upsert(
        registros, on_conflict="cliente"
    ).execute()


def _seccion_actualizar_planeacion():
    render_label("Archivo Excel de planeacion")
    archivo = st.file_uploader(
        "Sube el archivo con la planeacion",
        type=["xlsx", "xls", "csv"],
        key="afu_archivo",
    )

    if not archivo:
        render_tip(
            "Columnas esperadas: <strong>C</strong> = Agencia, <strong>D</strong> = Cliente, "
            "<strong>AH</strong> = Sector. Solo se cargan filas de <strong>Tláhuac</strong> y <strong>Monterrey</strong>."
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

    if not st.button("Subir a Supabase", type="primary", use_container_width=True):
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


def pagina_asignacion_fija_uni():
    render_header("Asignacion Fija Uni", "Planeacion nacional de visitas Unilever")
    render_guide(
        [
            "Selecciona la accion a ejecutar.",
            "Sube el archivo Excel con la planeacion.",
            "Se filtran solo filas de Tláhuac y Monterrey (columna C).",
            "Se extraen Cliente (D) y Sector (AH). Hora inicio/final y duracion son fijas.",
            "Se hace upsert a Supabase: actualiza si el cliente existe, crea si no.",
        ],
        "El campo <strong>habilidad</strong> se cargara desde otro archivo en un paso posterior.",
    )

    accion = st.selectbox(
        "Accion",
        ["Actualizar planeacion nacional"],
        key="afu_accion",
    )

    if accion == "Actualizar planeacion nacional":
        _seccion_actualizar_planeacion()
