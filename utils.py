import streamlit as st
import re


def render_header(title, subtitle):
    st.markdown(
        f'<div class="sr-header"><h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def render_guide(steps, tip):
    steps_html = "".join(
        f'<div class="sr-step"><div class="sr-step-num">{i}</div>'
        f'<div class="sr-step-text">{text}</div></div>'
        for i, text in enumerate(steps, 1)
    )
    with st.expander("📖 ¿Como funciona? — Guia rapida", expanded=False):
        st.markdown(f'<div class="sr-guide">{steps_html}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="sr-tip"><strong>💡 Tip:</strong> {tip}</div>',
            unsafe_allow_html=True,
        )


def render_stat(number, label, style="", number_style=""):
    stat_extra = f' style="{style}"' if style else ""
    num_extra = f' style="{number_style}"' if number_style else ""
    return (
        f'<div class="sr-stat"{stat_extra}>'
        f'<div class="sr-stat-number"{num_extra}>{number}</div>'
        f'<div class="sr-stat-label">{label}</div></div>'
    )


def render_tip(text, warning=False):
    border = ' style="border-left-color: #d32f2f;"' if warning else ""
    st.markdown(f'<div class="sr-tip"{border}>{text}</div>', unsafe_allow_html=True)


def render_error_item(text):
    st.markdown(
        f'<div class="sr-result sr-result-err">✗ {text}</div>',
        unsafe_allow_html=True,
    )


def render_cuenta_badge(text):
    st.markdown(f'<div class="sr-cuenta">{text}</div>', unsafe_allow_html=True)


def render_label(text):
    st.markdown(f'<div class="sr-label">{text}</div>', unsafe_allow_html=True)


def create_progress_tracker(total, text="Procesando..."):
    col_barra, col_contador = st.columns([5, 1])
    with col_barra:
        barra = st.progress(0, text=text)
    with col_contador:
        contador = st.empty()
        _update_counter(contador, 0, total)
    contenedor_errores = st.container()
    return barra, contador, contenedor_errores


def update_progress(barra, contador, procesados, total, text="Procesando..."):
    barra.progress(procesados / total, text=text)
    _update_counter(contador, procesados, total)


def finish_progress(barra):
    barra.progress(1.0, text="Finalizado")


def _update_counter(contador, current, total):
    contador.markdown(
        f'<div class="sr-stat" style="padding:0.4rem 0.6rem;">'
        f'<div class="sr-stat-number" style="font-size:1.1rem;">{current}/{total}</div></div>',
        unsafe_allow_html=True,
    )


def load_secret(key, error_msg):
    try:
        return getattr(st.secrets.api_config, key)
    except (AttributeError, KeyError):
        st.error(error_msg)
        st.stop()


def validar_email(email):
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))
