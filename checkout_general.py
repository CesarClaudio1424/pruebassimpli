import streamlit as st
import requests

API_URL = "https://api.simpliroute.com/v1/mobile/send-webhooks"


def enviar_webhook(token, acc_id, date, id_obj, tipo):
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "account_ids": [int(acc_id)],
        "planned_date": date,
        tipo: [int(id_obj)],
    }
    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=15)
        if response.status_code == 200:
            return True, ""
        else:
            return False, f"HTTP {response.status_code}: {response.text[:200]}"
    except Exception as e:
        return False, f"Error de conexion: {str(e)}"


def pagina_checkout_general():
    # Header
    st.markdown(
        """
        <div class="sr-header">
            <h1>Webhook Checkout General</h1>
            <p>Envio de webhooks para rutas y visitas de cualquier cuenta</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # --- Guia de uso ---
    with st.expander("📖 ¿Como funciona? — Guia rapida", expanded=False):
        st.markdown(
            """
            <div class="sr-guide">
                <div class="sr-step">
                    <div class="sr-step-num">1</div>
                    <div class="sr-step-text"><strong>Pega los datos</strong> — Formato: <code>Fecha [tab] AccountID [tab] ID</code>, uno por linea. Puedes copiar directamente desde una hoja de calculo.</div>
                </div>
                <div class="sr-step">
                    <div class="sr-step-num">2</div>
                    <div class="sr-step-text"><strong>Deteccion automatica</strong> — Si el ID tiene mas de 9 caracteres se trata como <strong>ruta</strong>, de lo contrario como <strong>visita</strong>.</div>
                </div>
                <div class="sr-step">
                    <div class="sr-step-num">3</div>
                    <div class="sr-step-text"><strong>Procesa</strong> — Cada fila se envia como un webhook individual a la API de SimpliRoute. Solo se muestran los errores.</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class="sr-tip">
                <strong>💡 Tip:</strong> Puedes mezclar rutas y visitas de distintas cuentas y fechas en un mismo envio. El formato esperado es tabulado (copiar desde Excel o Google Sheets funciona directamente).
            </div>
            """,
            unsafe_allow_html=True,
        )

    # --- Queries de consulta ---
    with st.expander("🔍 Queries SQL — Como obtener los datos", expanded=False):
        st.markdown('<div class="sr-label">Visitas por ID</div>', unsafe_allow_html=True)
        st.code("""SELECT
    routes_visit.planned_date,
    routes_visit.account_id,
    routes_visit."id"
FROM
    routes_visit
WHERE
    routes_visit."id" IN (750012931)""", language="sql")

        st.markdown('<div class="sr-label">Visitas por reference</div>', unsafe_allow_html=True)
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

        st.markdown('<div class="sr-label">Listado de rutas de una cuenta</div>', unsafe_allow_html=True)
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

        st.markdown('<div class="sr-label">Rutas por ID (si ya tienes el ID)</div>', unsafe_allow_html=True)
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

        st.markdown(
            """
            <div class="sr-tip">
                <strong>💡 Tip:</strong> El resultado de estas queries ya viene en el formato necesario (planned_date, account_id, id). Copia las filas directamente y pegalas en el campo de datos.
            </div>
            """,
            unsafe_allow_html=True,
        )

    # --- Token desde secrets ---
    try:
        token = st.secrets.api_config.checkout_token
    except (AttributeError, KeyError):
        st.error("No se encontro `checkout_token` en `.streamlit/secrets.toml`. Configura `[api_config]` con `checkout_token`.")
        st.stop()

    # --- Paso 1: Datos ---
    st.markdown('<div class="sr-label">Paso 1 · Datos (Fecha [tab] AccountID [tab] ID)</div>', unsafe_allow_html=True)

    datos_input = st.text_area(
        "Datos",
        placeholder="2024-05-09\t31150\t415132837\n2024-05-10\t31150\tR-1234567890",
        label_visibility="collapsed",
        height=200,
    )

    if not datos_input or not datos_input.strip():
        st.markdown(
            """
            <div class="sr-tip">
                Pega los datos a procesar. Cada linea debe tener tres campos separados por tabulador: Fecha, AccountID e ID.
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.stop()

    # Parsear lineas
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
        tipo = "route_ids" if len(id_obj) > 9 else "visit_ids"
        etiqueta = "Ruta" if tipo == "route_ids" else "Visita"
        items.append((date, acc_id, id_obj, tipo, etiqueta))

    if errores_formato:
        for err in errores_formato:
            st.markdown(
                f'<div class="sr-result sr-result-err">✗ {err}</div>',
                unsafe_allow_html=True,
            )

    if not items:
        st.markdown(
            """
            <div class="sr-tip" style="border-left-color: #d32f2f;">
                <strong>⚠️ Atencion:</strong> No se encontraron filas validas. Verifica que los datos esten separados por tabulador.
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.stop()

    # Stats
    rutas = sum(1 for _, _, _, t, _ in items if t == "route_ids")
    visitas = sum(1 for _, _, _, t, _ in items if t == "visit_ids")

    col_stat1, col_stat2, col_stat3 = st.columns(3)
    with col_stat1:
        st.markdown(
            f"""
            <div class="sr-stat">
                <div class="sr-stat-number">{len(items)}</div>
                <div class="sr-stat-label">total a procesar</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_stat2:
        st.markdown(
            f"""
            <div class="sr-stat">
                <div class="sr-stat-number">{rutas}</div>
                <div class="sr-stat-label">rutas</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_stat3:
        st.markdown(
            f"""
            <div class="sr-stat">
                <div class="sr-stat-number">{visitas}</div>
                <div class="sr-stat-label">visitas</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if not st.button("Procesar webhooks", type="primary", key="btn_checkout"):
        st.stop()

    # --- Procesamiento ---
    total = len(items)
    exitosos = 0
    fallidos = []

    col_barra, col_contador = st.columns([5, 1])
    with col_barra:
        barra = st.progress(0, text="Procesando webhooks...")
    with col_contador:
        contador = st.empty()
        contador.markdown(
            f'<div class="sr-stat" style="padding:0.4rem 0.6rem;"><div class="sr-stat-number" style="font-size:1.1rem;">0/{total}</div></div>',
            unsafe_allow_html=True,
        )

    contenedor_errores = st.container()

    for i, (date, acc_id, id_obj, tipo, etiqueta) in enumerate(items):
        ok, detalle = enviar_webhook(token, acc_id, date, id_obj, tipo)
        procesados = i + 1

        if ok:
            exitosos += 1
        else:
            fallidos.append((etiqueta, id_obj, detalle))
            with contenedor_errores:
                st.markdown(
                    f'<div class="sr-result sr-result-err">✗ {etiqueta} {id_obj} (cuenta {acc_id}) — {detalle}</div>',
                    unsafe_allow_html=True,
                )

        barra.progress(procesados / total, text="Procesando webhooks...")
        contador.markdown(
            f'<div class="sr-stat" style="padding:0.4rem 0.6rem;"><div class="sr-stat-number" style="font-size:1.1rem;">{procesados}/{total}</div></div>',
            unsafe_allow_html=True,
        )

    barra.progress(1.0, text="Finalizado")

    if exitosos > 0:
        st.success(f"{exitosos} de {total} procesados correctamente")
    if fallidos:
        st.error(f"{len(fallidos)} de {total} fallaron")
