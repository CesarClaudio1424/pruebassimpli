def generar_tema(dark):
    return {
        "bg": "#0e1117" if dark else "#f5f7fb",
        "text": "#e0e0e0" if dark else "#1a1a1a",
        "label": "#7b8cff" if dark else "#2A2BA1",
        "input_border": "#3a3f4b" if dark else "#e0e3ea",
        "input_bg": "#1a1e2a" if dark else "white",
        "input_text": "#e0e0e0" if dark else "#1a1a1a",
        "uploader_border": "#3a3f4b" if dark else "#d0d5dd",
    }


def generar_css(THEME, dark):
    return f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="st-"] {{
        font-family: 'Inter', sans-serif;
    }}

    #MainMenu, header, footer {{visibility: hidden;}}

    .stApp {{
        background: {THEME["bg"]};
        color: {THEME["text"]};
    }}

    .block-container {{
        padding-top: 1rem !important;
        padding-bottom: 1rem !important;
    }}

    /* Header */
    .sr-header {{
        background: linear-gradient(135deg, #2A2BA1 0%, #1a1b6b 100%);
        padding: 1.5rem 2rem 1.2rem 2rem;
        border-radius: 0.8rem;
        text-align: center;
        margin-bottom: 1rem;
    }}
    .sr-header h1 {{
        color: white;
        font-size: 1.5rem;
        font-weight: 700;
        margin: 0;
        letter-spacing: -0.02em;
    }}
    .sr-header p {{
        color: rgba(255,255,255,0.7);
        font-size: 0.85rem;
        margin: 0.2rem 0 0 0;
    }}

    /* Cuenta badge */
    .sr-cuenta {{
        background: linear-gradient(135deg, #29AB55 0%, #1e8a42 100%);
        color: white;
        padding: 0.5rem 1rem;
        border-radius: 0.5rem;
        font-size: 0.85rem;
        font-weight: 500;
        margin-bottom: 0.5rem;
    }}

    /* Stat box */
    .sr-stat {{
        background: linear-gradient(135deg, #369CFF 0%, #2A2BA1 100%);
        color: white;
        padding: 0.8rem 1rem;
        border-radius: 0.6rem;
        text-align: center;
        margin-bottom: 0.5rem;
    }}
    .sr-stat-number {{
        font-size: 1.6rem;
        font-weight: 700;
        line-height: 1;
    }}
    .sr-stat-label {{
        font-size: 0.75rem;
        opacity: 0.85;
        margin-top: 0.15rem;
    }}

    /* Label mini */
    .sr-label {{
        font-size: 0.7rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: {THEME["label"]};
        margin-bottom: 0.3rem;
    }}

    /* Solo boton primario con gradiente */
    button[data-testid="stBaseButton-primary"] {{
        background: linear-gradient(135deg, #2A2BA1 0%, #1a1b6b 100%) !important;
        color: white !important;
        border: none !important;
        border-radius: 0.5rem !important;
        padding: 0.6rem 2rem !important;
        font-weight: 600 !important;
        font-size: 0.9rem !important;
        transition: all 0.2s ease !important;
        width: 100% !important;
    }}
    button[data-testid="stBaseButton-primary"]:hover {{
        transform: translateY(-1px) !important;
        box-shadow: 0 4px 12px rgba(42, 43, 161, 0.35) !important;
    }}

    /* Boton descargar plantilla */
    .stDownloadButton > button {{
        background: {"rgba(255,255,255,0.06)" if dark else "rgba(42,43,161,0.06)"} !important;
        border: 1.5px dashed {"#3a3f4b" if dark else "#b0b5dd"} !important;
        border-radius: 0.5rem !important;
        padding: 0.5rem 1.2rem !important;
        font-size: 0.82rem !important;
        font-weight: 500 !important;
        color: {THEME["label"]} !important;
        width: 100% !important;
        min-height: 2.4rem !important;
    }}
    .stDownloadButton > button:hover {{
        background: {"rgba(255,255,255,0.1)" if dark else "rgba(42,43,161,0.12)"} !important;
        border-color: #2A2BA1 !important;
    }}

    /* Input fields */
    .stTextInput > div > div > input {{
        border-radius: 0.5rem !important;
        border: 1.5px solid {THEME["input_border"]} !important;
        background: {THEME["input_bg"]} !important;
        color: {THEME["input_text"]} !important;
        padding: 0.6rem 0.8rem !important;
        font-size: 0.9rem !important;
    }}
    .stTextInput > div > div > input:focus {{
        border-color: #2A2BA1 !important;
        box-shadow: 0 0 0 3px rgba(42, 43, 161, 0.15) !important;
    }}

    /* Text area */
    .stTextArea > div > div > textarea {{
        border-radius: 0.5rem !important;
        border: 1.5px solid {THEME["input_border"]} !important;
        background: {THEME["input_bg"]} !important;
        color: {THEME["input_text"]} !important;
        padding: 0.6rem 0.8rem !important;
        font-size: 0.9rem !important;
    }}
    .stTextArea > div > div > textarea:focus {{
        border-color: #2A2BA1 !important;
        box-shadow: 0 0 0 3px rgba(42, 43, 161, 0.15) !important;
    }}

    /* File uploader */
    .stFileUploader > div {{
        border-radius: 0.6rem !important;
        border: 2px dashed {THEME["uploader_border"]} !important;
    }}

    /* Progress bar */
    .stProgress > div > div > div {{
        background: linear-gradient(90deg, #2A2BA1, #369CFF) !important;
        border-radius: 1rem !important;
    }}

    /* Expander */
    .streamlit-expanderHeader {{
        font-size: 0.85rem !important;
        font-weight: 500 !important;
        color: {THEME["label"]} !important;
    }}

    .stElementContainer {{
        margin-bottom: 0.3rem !important;
    }}

    a {{ color: {THEME["label"]} !important; }}

    /* Guia pasos */
    .sr-guide {{
        background: {"#1a1e2a" if dark else "#f0f2ff"};
        border: 1px solid {"#2a2f3f" if dark else "#d0d5ff"};
        border-radius: 0.6rem;
        padding: 1rem 1.2rem;
        margin-bottom: 0.8rem;
    }}
    .sr-guide h4 {{
        color: {THEME["label"]};
        margin: 0 0 0.5rem 0;
        font-size: 0.9rem;
    }}
    .sr-step {{
        display: flex;
        align-items: flex-start;
        gap: 0.6rem;
        margin-bottom: 0.5rem;
    }}
    .sr-step-num {{
        background: linear-gradient(135deg, #2A2BA1 0%, #369CFF 100%);
        color: white;
        width: 1.4rem;
        height: 1.4rem;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 0.7rem;
        font-weight: 700;
        flex-shrink: 0;
        margin-top: 0.1rem;
    }}
    .sr-step-text {{
        font-size: 0.82rem;
        color: {THEME["text"]};
        line-height: 1.4;
    }}
    .sr-step-text strong {{
        color: {THEME["label"]};
    }}

    /* Tabla campos */
    .sr-fields-table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 0.78rem;
        margin-top: 0.5rem;
    }}
    .sr-fields-table th {{
        background: {"#252a3a" if dark else "#e8ebff"};
        color: {THEME["label"]};
        padding: 0.4rem 0.6rem;
        text-align: left;
        font-weight: 600;
        border-bottom: 2px solid {"#3a3f4b" if dark else "#c0c5dd"};
    }}
    .sr-fields-table td {{
        padding: 0.35rem 0.6rem;
        border-bottom: 1px solid {"#2a2f3f" if dark else "#e0e3ea"};
        color: {THEME["text"]};
    }}
    .sr-fields-table tr:hover td {{
        background: {"#1e2233" if dark else "#f5f7ff"};
    }}
    .sr-tag {{
        display: inline-block;
        padding: 0.1rem 0.4rem;
        border-radius: 0.25rem;
        font-size: 0.7rem;
        font-weight: 600;
    }}
    .sr-tag-req {{
        background: #29AB5520;
        color: #29AB55;
    }}
    .sr-tag-opt {{
        background: {"#369CFF20" if dark else "#369CFF15"};
        color: #369CFF;
    }}

    /* Tip box */
    .sr-tip {{
        background: {"#1a2a1e" if dark else "#edf7f0"};
        border-left: 3px solid #29AB55;
        padding: 0.5rem 0.8rem;
        border-radius: 0 0.4rem 0.4rem 0;
        font-size: 0.8rem;
        color: {THEME["text"]};
        margin: 0.5rem 0;
    }}

    /* Sidebar */
    [data-testid="stSidebar"] {{
        background: {"#161b22" if dark else "#f0f2ff"} !important;
    }}
    [data-testid="stSidebar"] > div:first-child {{
        padding-top: 0.5rem;
    }}
    [data-testid="stSidebar"] .stRadio > div[role="radiogroup"] > label {{
        padding: 0.4rem 0.6rem !important;
        border-radius: 0.4rem !important;
        color: {THEME["text"]} !important;
    }}
    [data-testid="stSidebar"] .stRadio > div[role="radiogroup"] > label:hover {{
        background: {"rgba(255,255,255,0.05)" if dark else "rgba(42,43,161,0.06)"} !important;
    }}

    /* Contraste radio buttons y checkboxes */
    .stRadio > div[role="radiogroup"] > label {{
        color: {THEME["text"]} !important;
        font-weight: 500 !important;
    }}
    .stCheckbox > label {{
        color: {THEME["text"]} !important;
        font-weight: 500 !important;
    }}
    .stRadio > div[role="radiogroup"] > label > div:last-child {{
        color: {THEME["text"]} !important;
    }}
    .stCheckbox > label > div:last-child {{
        color: {THEME["text"]} !important;
    }}

    /* Resultado item */
    .sr-result {{
        padding: 0.3rem 0.6rem;
        border-radius: 0.4rem;
        font-size: 0.82rem;
        margin-bottom: 0.2rem;
    }}
    .sr-result-ok {{
        background: {"#1a2a1e" if dark else "#edf7f0"};
        color: #29AB55;
    }}
    .sr-result-err {{
        background: {"#2a1a1e" if dark else "#fdedf0"};
        color: {"#ff6b6b" if dark else "#d32f2f"};
    }}
    </style>
    """
