import streamlit as st
import webhook


def pagina_webhooks():
    # Header
    st.markdown(
        """
        <div class="sr-header">
            <h1>Procesamiento de Webhooks Likewise</h1>
            <p>Automatizacion de rutas y visitas</p>
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
                    <div class="sr-step-text"><strong>Selecciona la cuenta</strong> — Elige la empresa del middleware Likewise a la que quieres enviar los webhooks.</div>
                </div>
                <div class="sr-step">
                    <div class="sr-step-num">2</div>
                    <div class="sr-step-text"><strong>Elige las acciones</strong> — Puedes ejecutar Creacion, Inicio de ruta, Checkout, o Exclusion de visitas. No puedes mezclar Exclusiones con las demas.</div>
                </div>
                <div class="sr-step">
                    <div class="sr-step-num">3</div>
                    <div class="sr-step-text"><strong>Ingresa los datos</strong> — Numeros de ruta o IDs de visita (para exclusiones), uno por linea.</div>
                </div>
                <div class="sr-step">
                    <div class="sr-step-num">4</div>
                    <div class="sr-step-text"><strong>Procesa</strong> — Las rutas se envian una a una. Las exclusiones se envian todas en un solo request.</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class="sr-tip">
                <strong>💡 Tip:</strong> Las exclusiones trabajan con IDs de visita (numeros enteros), mientras que las demas acciones trabajan con numeros de ruta.
            </div>
            """,
            unsafe_allow_html=True,
        )

    # --- Paso 1: Cuenta ---
    st.markdown('<div class="sr-label">Paso 1 · Cuenta</div>', unsafe_allow_html=True)
    cuenta = st.radio(
        "Cuenta",
        list(webhook.ENDPOINTS.keys()),
        horizontal=True,
        label_visibility="collapsed",
    )

    st.markdown(
        f'<div class="sr-cuenta">Cuenta seleccionada: <strong>{cuenta}</strong></div>',
        unsafe_allow_html=True,
    )

    # --- Paso 2: Acciones ---
    st.markdown('<div class="sr-label">Paso 2 · Acciones</div>', unsafe_allow_html=True)

    col_a, col_b, col_c, col_d = st.columns(4)
    with col_a:
        creacion = st.checkbox("Creacion", key="wh_creacion")
    with col_b:
        inicio = st.checkbox("Inicio", key="wh_inicio")
    with col_c:
        checkout = st.checkbox("Checkout", key="wh_checkout")
    with col_d:
        exclusion = st.checkbox("Exclusiones", key="wh_exclusion")

    if exclusion and (creacion or inicio or checkout):
        st.markdown(
            """
            <div class="sr-tip" style="border-left-color: #d32f2f;">
                <strong>⚠️ Atencion:</strong> No puedes mezclar Exclusiones con las demas acciones. Desmarca una de las opciones.
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.stop()

    if not (creacion or inicio or checkout or exclusion):
        st.markdown(
            """
            <div class="sr-tip">
                Selecciona al menos una accion para continuar.
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.stop()

    # --- Paso 3: Datos ---
    st.markdown('<div class="sr-label">Paso 3 · Rutas o visitas</div>', unsafe_allow_html=True)

    placeholder = "Ingresa los IDs de visita (uno por linea)" if exclusion else "Ingresa los numeros de ruta (uno por linea)"
    rutas_input = st.text_area(
        "Datos",
        placeholder=placeholder,
        label_visibility="collapsed",
        height=150,
    )

    if not rutas_input or not rutas_input.strip():
        st.markdown(
            f"""
            <div class="sr-tip">
                Ingresa {"los IDs de visita" if exclusion else "los numeros de ruta"} a procesar, uno por linea.
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.stop()

    items = [line.strip() for line in rutas_input.strip().split("\n") if line.strip()]

    # Stats
    acciones_sel = []
    if creacion:
        acciones_sel.append("Creacion")
    if inicio:
        acciones_sel.append("Inicio")
    if checkout:
        acciones_sel.append("Checkout")
    if exclusion:
        acciones_sel.append("Exclusiones")

    col_stat1, col_stat2 = st.columns(2)
    with col_stat1:
        st.markdown(
            f"""
            <div class="sr-stat">
                <div class="sr-stat-number">{len(items)}</div>
                <div class="sr-stat-label">{"visitas" if exclusion else "rutas"} a procesar</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with col_stat2:
        st.markdown(
            f"""
            <div class="sr-stat">
                <div class="sr-stat-number">{len(acciones_sel)}</div>
                <div class="sr-stat-label">{"accion" if len(acciones_sel) == 1 else "acciones"}: {", ".join(acciones_sel)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if not st.button("Procesar webhooks", type="primary", key="btn_webhooks"):
        st.stop()

    # --- Procesamiento ---
    urls = webhook.ENDPOINTS[cuenta]

    if exclusion:
        # Exclusiones: enviar TODOS los IDs en un solo request
        barra = st.progress(0, text="Enviando exclusiones...")
        ok, status, body = webhook.procesar_exclusion(items, urls["exclusion"])
        barra.progress(1.0, text="Finalizado")

        if ok:
            st.success(f"{len(items)} visitas excluidas correctamente")
        else:
            detalle = "respuesta vacia" if status == 200 else f"HTTP {status}"
            st.markdown(
                f'<div class="sr-result sr-result-err">✗ Error al excluir las visitas ({detalle})</div>',
                unsafe_allow_html=True,
            )
            if body.strip():
                with st.expander("Detalle del error"):
                    st.code(body[:500])
    else:
        # Rutas: enviar una por una
        operaciones = []
        if creacion:
            for item in items:
                operaciones.append(("Creacion", item, urls["creacion"]))
        if inicio:
            for item in items:
                operaciones.append(("Inicio", item, urls["inicio"]))
        if checkout:
            for item in items:
                operaciones.append(("Checkout", item, urls["checkout"]))

        total = len(operaciones)
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

        for i, (accion, item, url) in enumerate(operaciones):
            ok, status, body = webhook.procesar_ruta(item, url)
            procesados = i + 1

            if ok:
                exitosos += 1
            else:
                detalle = "respuesta vacia" if status == 200 else f"HTTP {status}"
                fallidos.append((accion, item, detalle))
                with contenedor_errores:
                    st.markdown(
                        f'<div class="sr-result sr-result-err">✗ {accion}: ruta {item} — {detalle}</div>',
                        unsafe_allow_html=True,
                    )

            barra.progress(procesados / total, text=f"Procesando webhooks...")
            contador.markdown(
                f'<div class="sr-stat" style="padding:0.4rem 0.6rem;"><div class="sr-stat-number" style="font-size:1.1rem;">{procesados}/{total}</div></div>',
                unsafe_allow_html=True,
            )

        barra.progress(1.0, text="Finalizado")

        if exitosos > 0:
            st.success(f"{exitosos} de {total} procesados correctamente")
        if fallidos:
            st.error(f"{len(fallidos)} de {total} fallaron")
