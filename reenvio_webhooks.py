import re
import time
import streamlit as st
import requests
from config import API_SEND_PLAN_WEBHOOKS, REQUEST_TIMEOUT, MAX_RETRIES, RETRY_BASE_DELAY
from utils import (
    render_header, render_guide, render_stat, render_label,
    render_tip, render_error_item, load_secret,
    create_progress_tracker, update_progress, finish_progress,
)


UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def enviar_plan_webhook(token, plan_id, action):
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
    }
    payload = {"plan_id": plan_id, "action": action}
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(
                API_SEND_PLAN_WEBHOOKS,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT,
            )
            if response.status_code == 200:
                return True, ""
            if response.status_code >= 500 and attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                continue
            return False, f"HTTP {response.status_code}: {response.text}"
        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY * (2 ** attempt))
                continue
            return False, f"Error de conexion: {str(e)}"
    return False, "Reintentos agotados"


def pagina_reenvio_webhooks():
    render_header(
        "Reenvio de Webhooks",
        "Reenvia webhooks de eventos varios a SimpliRoute",
    )

    render_guide(
        steps=[
            '<strong>Pega los plan IDs</strong> — UUIDs de planes, uno por linea.',
            '<strong>Validacion</strong> — Cada linea se valida contra formato UUID antes de enviar.',
            '<strong>Procesa</strong> — Se envia un POST por cada plan_id al endpoint <code>/mobile/send-plan-webhooks</code> con <code>action: plan_created</code>.',
        ],
        tip='Si necesitas obtener los plan_id, consultalos en la tabla <code>routes_plan</code> de la BD o en la respuesta de <code>GET /v1/routes/plans/</code>.',
    )

    token = load_secret(
        "checkout_token",
        "No se encontro `checkout_token` en `.streamlit/secrets.toml`. Configura `[api_config]` con `checkout_token`.",
    )

    render_label("Paso 1 · Plan IDs (UUID, uno por linea)")

    datos_input = st.text_area(
        "Plan IDs",
        placeholder="07e69fb2-7175-44af-9a18-2388a16c091f\nb1c2d3e4-5678-90ab-cdef-1234567890ab",
        label_visibility="collapsed",
        height=200,
    )

    if not datos_input or not datos_input.strip():
        render_tip("Pega los plan_id a procesar. Cada linea debe ser un UUID.")
        st.stop()

    lineas = [line.strip() for line in datos_input.strip().split("\n") if line.strip()]
    errores_formato = []
    plan_ids = []

    for i, linea in enumerate(lineas):
        if not UUID_RE.match(linea):
            errores_formato.append(f"Linea {i + 1}: '{linea[:50]}' no tiene formato UUID")
            continue
        plan_ids.append(linea)

    if errores_formato:
        for err in errores_formato:
            render_error_item(err)

    if not plan_ids:
        render_tip(
            "<strong>⚠️ Atencion:</strong> No se encontraron plan_ids validos.",
            warning=True,
        )
        st.stop()

    col_stat1, col_stat2 = st.columns(2)
    with col_stat1:
        st.markdown(render_stat(len(plan_ids), "planes a procesar"), unsafe_allow_html=True)
    with col_stat2:
        st.markdown(render_stat("plan_created", "evento"), unsafe_allow_html=True)

    if not st.button("Enviar webhooks", type="primary", key="btn_reenvio_plan"):
        st.stop()

    total = len(plan_ids)
    exitosos = 0
    fallidos = []

    barra, contador, contenedor_errores = create_progress_tracker(total, "Enviando webhooks...")

    for i, plan_id in enumerate(plan_ids):
        ok, detalle = enviar_plan_webhook(token, plan_id, "plan_created")
        procesados = i + 1

        if ok:
            exitosos += 1
        else:
            fallidos.append((plan_id, detalle))
            with contenedor_errores:
                render_error_item(f"Plan {plan_id} — {detalle}")

        update_progress(barra, contador, procesados, total, "Enviando webhooks...")

    finish_progress(barra)

    if exitosos > 0:
        st.success(f"{exitosos} de {total} procesados correctamente")
    if fallidos:
        st.error(f"{len(fallidos)} de {total} fallaron")
