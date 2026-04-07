import streamlit as st
from estilos import generar_tema, generar_css
from edicion import pagina_edicion
from pagina_webhooks import pagina_webhooks
from bloqueo_lvp import pagina_bloqueo_lvp
from reporte_visitas import pagina_reporte_visitas
from checkout_general import pagina_checkout_general
from eliminacion_items import pagina_eliminacion_items
from unilever import pagina_unilever
from zonas_kml import pagina_zonas_kml
from recuperar_lvp import pagina_recuperar_lvp
from eliminar_bat import pagina_eliminar_bat

st.set_page_config(
    page_title="SimpliRoute Tools",
    page_icon="🚚",
    layout="centered",
)

# --- Tema ---
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = False

dark = st.session_state.dark_mode
THEME = generar_tema(dark)

# --- Estilos ---
st.markdown(generar_css(THEME, dark), unsafe_allow_html=True)

# --- Sidebar ---
with st.sidebar:
    st.markdown(
        """
        <div style="background: linear-gradient(135deg, #2A2BA1 0%, #1a1b6b 100%);
                    padding: 1rem; border-radius: 0.6rem; text-align: center; margin-bottom: 1rem;">
            <div style="color: white; font-size: 1.1rem; font-weight: 700; letter-spacing: -0.02em;">
                SimpliRoute
            </div>
            <div style="color: rgba(255,255,255,0.7); font-size: 0.75rem;">Tools</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    pagina = st.radio(
        "Herramienta",
        ["Edicion Masiva de Visitas", "Webhooks Likewise", "Bloqueo LVP", "Reporte Visitas/Rutas", "Checkout General", "Eliminacion de Items", "Unilever", "Zonas KML", "Recuperar Visitas LVP", "Eliminar Visitas BAT"],
        label_visibility="collapsed",
    )

    st.markdown("---")

    icon = "☀️" if dark else "🌙"
    mode_label = "Modo claro" if dark else "Modo oscuro"
    if st.button(f"{icon} {mode_label}", key="theme_toggle", use_container_width=True):
        st.session_state.dark_mode = not dark
        st.rerun()

# --- Dispatch ---
if pagina == "Edicion Masiva de Visitas":
    pagina_edicion()
elif pagina == "Webhooks Likewise":
    pagina_webhooks()
elif pagina == "Bloqueo LVP":
    pagina_bloqueo_lvp()
elif pagina == "Reporte Visitas/Rutas":
    pagina_reporte_visitas()
elif pagina == "Checkout General":
    pagina_checkout_general()
elif pagina == "Eliminacion de Items":
    pagina_eliminacion_items()
elif pagina == "Unilever":
    pagina_unilever()
elif pagina == "Zonas KML":
    pagina_zonas_kml()
elif pagina == "Recuperar Visitas LVP":
    pagina_recuperar_lvp()
else:
    pagina_eliminar_bat()
