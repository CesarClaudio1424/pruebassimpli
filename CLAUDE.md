# SimpliRoute Tools

## Descripcion
App Streamlit multi-herramienta con navegacion por sidebar. Incluye dos herramientas:
1. **Edicion Masiva de Visitas** — Sube un CSV y edita visitas en bloque via API SimpliRoute (PUT).
2. **Webhooks Likewise** — Envia webhooks a Google Cloud Functions para procesar rutas/visitas del middleware Likewise (POST).

## Stack
- **Python 3.12.3** con entorno virtual `.venv`
- **Streamlit** - Frontend web
- **requests** - Cliente HTTP

## Repositorio
- **GitHub:** CesarClaudio1424/simpliroute-tools (publico)
- **Deploy:** Streamlit Community Cloud — https://simpliroute-tools.streamlit.app/

## Estructura
```
main.py                              # Entry point: page config, sidebar, tema, dispatch
estilos.py                           # THEME dict + generador de CSS dinamico
edicion.py                           # Pagina Edicion Masiva (UI + helpers API/CSV)
pagina_webhooks.py                   # Pagina Webhooks Likewise (UI)
webhook.py                           # Backend webhooks Likewise (URLs, envio HTTP)
requirements.txt                     # Dependencias para Streamlit Cloud
.gitignore                           # Exclusiones de git
.claude/commands/simpliroute-api.md  # Skill con referencia de API SimpliRoute
```

## UI
- Sidebar izquierdo con navegacion entre herramientas y toggle de tema
- Estilo visual basado en SimpliRoute: azul #2A2BA1, verde #29AB55, celeste #369CFF
- Fuente Inter
- Soporte dark/light mode con toggle (st.session_state, sin JS)
- CSS dinamico generado con dict THEME segun el modo activo
- Ambas paginas comparten el mismo estilo visual (sr-header, sr-label, sr-stat, sr-tip, etc.)

## Flujo: Edicion Masiva
1. Usuario ingresa token de API
2. Se valida contra `GET /accounts/me/`
3. Usuario sube CSV (encoding ISO-8859-1)
4. Se muestra preview de los datos
5. Al procesar: convierte fechas dd/mm/yyyy -> yyyy-mm-dd
6. Divide datos en bloques (max 500) y envia via `PUT /routes/visits/`
7. Muestra progreso en tiempo real y errores por bloque

## Flujo: Webhooks Likewise
1. Usuario selecciona cuenta (Telefonica, Entel, Omnicanalidad, Biobio)
2. Elige acciones (Creacion, Inicio, Checkout o Exclusiones)
3. Ingresa numeros de ruta o IDs de visita (uno por linea)
4. Al procesar: rutas se envian una a una; exclusiones en un solo request con array de IDs
5. Valida status 200 + body no vacio (body vacio = error)
6. Solo muestra errores en la lista; contador de procesados junto a la barra de progreso

## Ejecutar
```bash
source .venv/Scripts/activate
streamlit run main.py
```

## APIs usadas
### SimpliRoute (Edicion Masiva)
- `GET /v1/accounts/me/` - Validacion de cuenta
- `PUT /v1/routes/visits/` - Edicion masiva de visitas
- Auth: `Authorization: Token {API_TOKEN}`

### Likewise Middleware (Webhooks)
- Base: `https://us-central1-likewizemiddleware-{empresa}.cloudfunctions.net/`
- `POST /likewize/webhook/plan/routes/support` - Creacion de rutas
- `POST /likewize/startRoutes` - Inicio de rutas
- `POST /likewize/webhook/routes/checkout` - Checkout de rutas
- `POST /likewize/webhook/visits/support` - Exclusion de visitas
- Sin auth (acceso por URL)
