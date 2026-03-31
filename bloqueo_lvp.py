import streamlit as st
import requests
import pandas as pd
from config import API_BASE, REQUEST_TIMEOUT
from utils import (
    render_header, render_guide, render_stat, render_label,
    render_tip, render_error_item, render_cuenta_badge, load_secret,
)

CONFIGS = [
    {"key": "disable_edit_for_active_and_finished_routes", "label": "Deshabilitar edicion de rutas activas y finalizadas"},
    {"key": "enable_safety_mode", "label": "Habilitar modo de seguridad"},
    {"key": "avoid_edit_checkout_after_route_finished", "label": "Evitar edicion de checkout despues de ruta finalizada"},
]


@st.cache_data
def cargar_cuentas():
    try:
        df = pd.read_csv("cuentas.csv")
        return pd.Series(df.id.astype(str).values, index=df.nombre).to_dict()
    except FileNotFoundError:
        return None


def actualizar_config(account_id, key, value, token):
    url = f"{API_BASE}/accounts/{account_id}/configs/"
    headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
    payload = {"key": key, "value": value}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
        return response.status_code
    except requests.exceptions.RequestException:
        return 0


def pagina_bloqueo_lvp():
    render_header("Bloqueo de Ediciones LVP", "Configuracion de seguridad para cuentas Liverpool")

    token = load_secret("auth_token", "No se encontro `auth_token` en `.streamlit/secrets.toml`. Configura `[api_config]` con `auth_token`.")

    render_guide(
        steps=[
            '<strong>Selecciona la cuenta</strong> — Elige la tienda Liverpool a configurar del listado.',
            '<strong>Elige el valor</strong> — <code>True</code> para activar el bloqueo, <code>False</code> para desactivarlo.',
            '<strong>Actualiza</strong> — Se envian tres configuraciones: bloqueo de edicion, modo de seguridad y bloqueo de checkout post-finalizacion.',
        ],
        tip='Las tres configuraciones se aplican con el mismo valor. Al activar (<code>True</code>), los conductores no podran editar rutas activas ni finalizadas, ni modificar checkouts.',
    )

    cuentas = cargar_cuentas()
    if cuentas is None:
        st.error("No se encontro el archivo `cuentas.csv`.")
        st.stop()

    # --- Paso 1: Cuenta ---
    render_label("Paso 1 · Cuenta Liverpool")
    cuenta_nombre = st.selectbox(
        "Cuenta",
        list(cuentas.keys()),
        label_visibility="collapsed",
    )

    render_cuenta_badge(f"Cuenta seleccionada: <strong>{cuenta_nombre}</strong> (ID: {cuentas[cuenta_nombre]})")

    # --- Paso 2: Valor ---
    render_label("Paso 2 · Valor")
    valor = st.radio(
        "Valor",
        ("True", "False"),
        horizontal=True,
        label_visibility="collapsed",
    )

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(render_stat(len(CONFIGS), "configuraciones a aplicar"), unsafe_allow_html=True)
    with col2:
        estado = "Activar bloqueo" if valor == "True" else "Desactivar bloqueo"
        color = "#29AB55" if valor == "True" else "#d32f2f"
        st.markdown(
            render_stat(
                estado,
                f"valor: {valor}",
                style=f"background: linear-gradient(135deg, {color} 0%, {color}cc 100%);",
                number_style="font-size:1.1rem;",
            ),
            unsafe_allow_html=True,
        )

    if not st.button("Actualizar configuraciones", type="primary", key="btn_bloqueo"):
        st.stop()

    # --- Procesamiento ---
    account_id = cuentas[cuenta_nombre]
    exitosos = 0
    errores = []

    barra = st.progress(0, text="Aplicando configuraciones...")

    for i, config in enumerate(CONFIGS):
        status = actualizar_config(account_id, config["key"], valor, token)
        procesados = i + 1

        if 200 <= status < 300:
            exitosos += 1
        else:
            errores.append({"config": config["label"], "codigo": status})

        barra.progress(procesados / len(CONFIGS), text=f"{procesados}/{len(CONFIGS)} configuraciones aplicadas")

    barra.progress(1.0, text="Finalizado")

    if exitosos > 0:
        st.success(f"{exitosos} de {len(CONFIGS)} configuraciones aplicadas correctamente a {cuenta_nombre}")

    if errores:
        st.error(f"{len(errores)} configuracion(es) con error")
        for err in errores:
            render_error_item(f'{err["config"]} — HTTP {err["codigo"]}')
