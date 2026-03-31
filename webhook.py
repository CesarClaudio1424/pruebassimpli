import requests
import time

DELAY = 0.4

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


def enviar_webhook(url, payload):
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, headers=headers, json=payload)
    return response.status_code, response.text


def procesar_ruta(ruta, url):
    payload = {"routes": [ruta]}
    status, body = enviar_webhook(url, payload)
    time.sleep(DELAY)
    ok = status == 200 and body.strip() != ""
    return ok, status, body


def procesar_exclusion(visita_ids, url):
    payload = {"visits": [int(v) for v in visita_ids]}
    status, body = enviar_webhook(url, payload)
    time.sleep(DELAY)
    ok = status == 200 and body.strip() != ""
    return ok, status, body
