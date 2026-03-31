import streamlit as st
import webhook
from utils import (
    render_header, render_guide, render_stat, render_label,
    render_tip, render_error_item, render_cuenta_badge,
    create_progress_tracker, update_progress, finish_progress,
)


def pagina_webhooks():
    render_header("Procesamiento de Webhooks Likewise", "Automatizacion de rutas y visitas")

    render_guide(
        steps=[
            '<strong>Selecciona la cuenta</strong> — Elige la empresa del middleware Likewise a la que quieres enviar los webhooks.',
            '<strong>Elige las acciones</strong> — Puedes ejecutar Creacion, Inicio de ruta, Checkout, o Exclusion de visitas. No puedes mezclar Exclusiones con las demas.',
            '<strong>Ingresa los datos</strong> — Numeros de ruta o IDs de visita (para exclusiones), uno por linea.',
            '<strong>Procesa</strong> — Las rutas se envian una a una. Las exclusiones se envian todas en un solo request.',
        ],
        tip='Las exclusiones trabajan con IDs de visita (numeros enteros), mientras que las demas acciones trabajan con numeros de ruta.',
    )

    # --- Paso 1: Cuenta ---
    render_label("Paso 1 · Cuenta")
    cuenta = st.radio(
        "Cuenta",
        list(webhook.ENDPOINTS.keys()),
        horizontal=True,
        label_visibility="collapsed",
    )

    render_cuenta_badge(f"Cuenta seleccionada: <strong>{cuenta}</strong>")

    # --- Paso 2: Acciones ---
    render_label("Paso 2 · Acciones")

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
        render_tip(
            "<strong>⚠️ Atencion:</strong> No puedes mezclar Exclusiones con las demas acciones. Desmarca una de las opciones.",
            warning=True,
        )
        st.stop()

    if not (creacion or inicio or checkout or exclusion):
        render_tip("Selecciona al menos una accion para continuar.")
        st.stop()

    # --- Paso 3: Datos ---
    render_label("Paso 3 · Rutas o visitas")

    placeholder = "Ingresa los IDs de visita (uno por linea)" if exclusion else "Ingresa los numeros de ruta (uno por linea)"
    rutas_input = st.text_area(
        "Datos",
        placeholder=placeholder,
        label_visibility="collapsed",
        height=150,
    )

    if not rutas_input or not rutas_input.strip():
        render_tip(f'Ingresa {"los IDs de visita" if exclusion else "los numeros de ruta"} a procesar, uno por linea.')
        st.stop()

    items = [line.strip() for line in rutas_input.strip().split("\n") if line.strip()]

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
            render_stat(len(items), f'{"visitas" if exclusion else "rutas"} a procesar'),
            unsafe_allow_html=True,
        )
    with col_stat2:
        st.markdown(
            render_stat(len(acciones_sel), f'{"accion" if len(acciones_sel) == 1 else "acciones"}: {", ".join(acciones_sel)}'),
            unsafe_allow_html=True,
        )

    if not st.button("Procesar webhooks", type="primary", key="btn_webhooks"):
        st.stop()

    # --- Procesamiento ---
    urls = webhook.ENDPOINTS[cuenta]

    if exclusion:
        barra = st.progress(0, text="Enviando exclusiones...")
        ok, status, body = webhook.procesar_exclusion(items, urls["exclusion"])
        barra.progress(1.0, text="Finalizado")

        if ok:
            st.success(f"{len(items)} visitas excluidas correctamente")
        else:
            detalle = "respuesta vacia" if status == 200 else f"HTTP {status}"
            render_error_item(f"Error al excluir las visitas ({detalle})")
            if body.strip():
                with st.expander("Detalle del error"):
                    st.code(body[:500])
    else:
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

        barra, contador, contenedor_errores = create_progress_tracker(total, "Procesando webhooks...")

        for i, (accion, item, url) in enumerate(operaciones):
            ok, status, body = webhook.procesar_ruta(item, url)
            procesados = i + 1

            if ok:
                exitosos += 1
            else:
                detalle = "respuesta vacia" if status == 200 else f"HTTP {status}"
                fallidos.append((accion, item, detalle))
                with contenedor_errores:
                    render_error_item(f"{accion}: ruta {item} — {detalle}")

            update_progress(barra, contador, procesados, total, "Procesando webhooks...")

        finish_progress(barra)

        if exitosos > 0:
            st.success(f"{exitosos} de {total} procesados correctamente")
        if fallidos:
            st.error(f"{len(fallidos)} de {total} fallaron")
