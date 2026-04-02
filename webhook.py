import requests
import time
from config import API_BASE, REQUEST_TIMEOUT, CLEANUP_TIMEOUT, WEBHOOK_DELAY

ENDPOINTS = {
    "Telefonica": {
        "creacion": "https://us-central1-likewizemiddleware-telefonica.cloudfunctions.net/likewize/webhook/plan/routes/support",
        "inicio": "https://us-central1-likewizemiddleware-telefonica.cloudfunctions.net/likewize/startRoutes",
        "checkout": "https://us-central1-likewizemiddleware-telefonica.cloudfunctions.net/likewize/webhook/routes/checkout",
        "exclusion": "https://us-central1-likewizemiddleware-telefonica.cloudfunctions.net/likewize/webhook/visits/support",
    },
    "Entel": {
        "creacion": "https://us-central1-likewizemiddleware-entel.cloudfunctions.net/likewize/webhook/plan/routes/support",
        "inicio": "https://us-central1-likewizemiddleware-entel.cloudfunctions.net/likewize/startRoutes",
        "checkout": "https://us-central1-likewizemiddleware-entel.cloudfunctions.net/likewize/webhook/routes/checkout",
        "exclusion": "https://us-central1-likewizemiddleware-entel.cloudfunctions.net/likewize/webhook/visits/support",
    },
    "Omnicanalidad": {
        "creacion": "https://us-central1-likewizemiddleware-omni.cloudfunctions.net/likewize/webhook/plan/routes/support",
        "inicio": "https://us-central1-likewizemiddleware-omni.cloudfunctions.net/likewize/startRoutes",
        "checkout": "https://us-central1-likewizemiddleware-omni.cloudfunctions.net/likewize/webhook/routes/checkout",
        "exclusion": "https://us-central1-likewizemiddleware-omni.cloudfunctions.net/likewize/webhook/visits/support",
    },
    "Biobio": {
        "creacion": "https://us-central1-likewizemiddleware-biobio.cloudfunctions.net/likewize/webhook/plan/routes/support",
        "inicio": "https://us-central1-likewizemiddleware-biobio.cloudfunctions.net/likewize/startRoutes",
        "checkout": "https://us-central1-likewizemiddleware-biobio.cloudfunctions.net/likewize/webhook/routes/checkout",
        "exclusion": "https://us-central1-likewizemiddleware-biobio.cloudfunctions.net/likewize/webhook/visits/support",
    },
}


ACCOUNT_TOKENS = {
    "Telefonica": "token_telefonica",
    "Entel": "token_entel",
    "Omnicanalidad": "token_omnicanalidad",
    "Biobio": "token_biobio",
}


def obtener_visitas_fecha(token, fecha):
    headers = {"Authorization": f"Token {token}"}
    url = f"{API_BASE}/routes/visits/?planned_date={fecha}"
    visitas = []
    while url:
        resp = requests.get(url, headers=headers, timeout=CLEANUP_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            visitas.extend(data)
            url = None
        else:
            visitas.extend(data.get("results", []))
            url = data.get("next")
    return visitas


def limpiar_visitas_batch(token, visitas):
    url = f"{API_BASE}/routes/visits/"
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json",
    }
    payload = [{"id": v["id"], "route": None, "planned_date": "2020-01-01"} for v in visitas]
    try:
        resp = requests.put(url, headers=headers, json=payload, timeout=CLEANUP_TIMEOUT)
        return resp.status_code == 200, resp.status_code, resp.text
    except requests.exceptions.RequestException as e:
        return False, 0, f"Error de conexion: {str(e)}"


def enviar_webhook(url, payload):
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT)
    return response.status_code, response.text


def procesar_ruta(ruta, url):
    payload = {"routes": [ruta]}
    try:
        status, body = enviar_webhook(url, payload)
        time.sleep(WEBHOOK_DELAY)
        ok = status == 200 and body.strip() != ""
        return ok, status, body
    except requests.exceptions.RequestException as e:
        return False, 0, f"Error de conexion: {str(e)}"


def procesar_exclusion(visita_ids, url):
    payload = {"visits": [int(v) for v in visita_ids]}
    try:
        status, body = enviar_webhook(url, payload)
        time.sleep(WEBHOOK_DELAY)
        ok = status == 200 and body.strip() != ""
        return ok, status, body
    except requests.exceptions.RequestException as e:
        return False, 0, f"Error de conexion: {str(e)}"
