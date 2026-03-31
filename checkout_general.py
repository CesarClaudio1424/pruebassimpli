import streamlit as st
import requests
from config import API_SEND_WEBHOOKS, REQUEST_TIMEOUT
from utils import (
    render_header, render_guide, render_stat, render_label,
    render_tip, render_error_item, load_secret,
    create_progress_tracker, update_progress, finish_progress,
)


def enviar_webhook(token, acc_id, date, id_obj, tipo):
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
    }
    try:
        id_value = int(id_obj)
    except ValueError:
        id_value = id_obj
    payload = {
        "account_ids": [int(acc_id)],
        "planned_date": date,
        tipo: [id_value],
    }
    try:
        response = requests.post(API_SEND_WEBHOOKS, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            return True, ""
        return False, f"HTTP {response.status_code}: {response.text}"
    except requests.exceptions.RequestException as e:
        return False, f"Error de conexion: {str(e)}"


def pagina_checkout_general():
    render_header("Webhook Checkout General", "Envio de webhooks para rutas y visitas de cualquier cuenta")

    render_guide(
        steps=[
            '<strong>Pega los datos</strong> — Formato: <code>Fecha [tab] AccountID [tab] ID</code>, uno por linea. Puedes copiar directamente desde una hoja de calculo.',
            '<strong>Deteccion automatica</strong> — Si el ID tiene mas de 9 caracteres se trata como <strong>ruta</strong> (UUID), de lo contrario como <strong>visita</strong> (entero).',
            '<strong>Procesa</strong> — Cada fila se envia como un webhook individual a la API de SimpliRoute. Solo se muestran los errores.',
        ],
        tip='Puedes mezclar rutas y visitas de distintas cuentas y fechas en un mismo envio. El formato esperado es tabulado (copiar desde Excel o Google Sheets funciona directamente).',
    )

    # --- Queries de consulta ---
    with st.expander("🔍 Queries SQL — Como obtener los datos", expanded=False):
        render_label("Visitas por ID")
        st.code("""SELECT
    routes_visit.planned_date,
    routes_visit.account_id,
    routes_visit."id"
FROM
    routes_visit
WHERE
    routes_visit."id" IN (750012931)""", language="sql")

        render_label("Visitas por reference")
        st.code("""SELECT
    routes_visit.planned_date,
    routes_visit.account_id,
    routes_visit."id"
FROM
    routes_visit
WHERE
    routes_visit.account_id = 29642 AND
    routes_visit.planned_date = '2025-09-04' AND
    routes_visit.reference IN ('51289023')""", language="sql")

        render_label("Listado de rutas de una cuenta")
        st.code("""SELECT
    "public".routes_route.planned_date,
    "public".routes_plan.account_id,
    "public".routes_route."id"
FROM
    "public".routes_route
INNER JOIN "public".routes_plan ON "public".routes_route.plan_id = "public".routes_plan."id"
WHERE
    "public".routes_plan.account_id = 60481 AND
    "public".routes_route.planned_date = '2025-02-07'
ORDER BY 1""", language="sql")

        render_label("Rutas por ID (si ya tienes el ID)")
        st.code("""SELECT
    routes_route.planned_date,
    routes_plan.account_id,
    routes_route."id"
FROM
    routes_route
INNER JOIN routes_plan ON routes_route.plan_id = routes_plan."id"
WHERE
    routes_route."id" IN ('18e2e0b8-4db5-4a17-bb39-d5b3a9c5e393')
ORDER BY 1 ASC""", language="sql")

        render_tip('<strong>💡 Tip:</strong> El resultado de estas queries ya viene en el formato necesario (planned_date, account_id, id). Copia las filas directamente y pegalas en el campo de datos.')

    # --- Token desde secrets ---
    token = load_secret("checkout_token", "No se encontro `checkout_token` en `.streamlit/secrets.toml`. Configura `[api_config]` con `checkout_token`.")

    # --- Paso 1: Datos ---
    render_label("Paso 1 · Datos (Fecha [tab] AccountID [tab] ID)")

    datos_input = st.text_area(
        "Datos",
        placeholder="2024-05-09\t31150\t415132837\n2024-05-10\t31150\tR-1234567890",
        label_visibility="collapsed",
        height=200,
    )

    if not datos_input or not datos_input.strip():
        render_tip("Pega los datos a procesar. Cada linea debe tener tres campos separados por tabulador: Fecha, AccountID e ID.")
        st.stop()

    lineas = [line.strip() for line in datos_input.strip().split("\n") if line.strip()]
    errores_formato = []
    items = []

    for i, linea in enumerate(lineas):
        campos = linea.split("\t")
        if len(campos) < 3:
            errores_formato.append(f"Linea {i + 1}: formato incorrecto ({linea[:50]})")
            continue
        date = campos[0].strip()
        acc_id = campos[1].strip()
        id_obj = campos[2].strip()

        if not acc_id.isdigit():
            errores_formato.append(f"Linea {i + 1}: AccountID '{acc_id}' no es numerico")
            continue

        # Route UUIDs tienen 36 chars, visit IDs son enteros de hasta 9 digitos
        tipo = "route_ids" if len(id_obj) > 9 else "visit_ids"
        etiqueta = "Ruta" if tipo == "route_ids" else "Visita"
        items.append((date, acc_id, id_obj, tipo, etiqueta))

    if errores_formato:
        for err in errores_formato:
            render_error_item(err)

    if not items:
        render_tip(
            "<strong>⚠️ Atencion:</strong> No se encontraron filas validas. Verifica que los datos esten separados por tabulador.",
            warning=True,
        )
        st.stop()

    rutas = sum(1 for _, _, _, t, _ in items if t == "route_ids")
    visitas = sum(1 for _, _, _, t, _ in items if t == "visit_ids")

    col_stat1, col_stat2, col_stat3 = st.columns(3)
    with col_stat1:
        st.markdown(render_stat(len(items), "total a procesar"), unsafe_allow_html=True)
    with col_stat2:
        st.markdown(render_stat(rutas, "rutas"), unsafe_allow_html=True)
    with col_stat3:
        st.markdown(render_stat(visitas, "visitas"), unsafe_allow_html=True)

    if not st.button("Procesar webhooks", type="primary", key="btn_checkout"):
        st.stop()

    # --- Procesamiento ---
    total = len(items)
    exitosos = 0
    fallidos = []

    barra, contador, contenedor_errores = create_progress_tracker(total, "Procesando webhooks...")

    for i, (date, acc_id, id_obj, tipo, etiqueta) in enumerate(items):
        ok, detalle = enviar_webhook(token, acc_id, date, id_obj, tipo)
        procesados = i + 1

        if ok:
            exitosos += 1
        else:
            fallidos.append((etiqueta, id_obj, detalle))
            with contenedor_errores:
                render_error_item(f"{etiqueta} {id_obj} (cuenta {acc_id}) — {detalle}")

        update_progress(barra, contador, procesados, total, "Procesando webhooks...")

    finish_progress(barra)

    if exitosos > 0:
        st.success(f"{exitosos} de {total} procesados correctamente")
    if fallidos:
        st.error(f"{len(fallidos)} de {total} fallaron")
