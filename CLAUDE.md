# SimpliRoute Tools

## Descripcion
App Streamlit multi-herramienta con navegacion por sidebar. Incluye cuatro herramientas:
1. **Edicion Masiva de Visitas** — Sube un CSV y edita visitas en bloque via API SimpliRoute (PUT).
2. **Webhooks Likewise** — Envia webhooks a Google Cloud Functions para procesar rutas/visitas del middleware Likewise (POST).
3. **Bloqueo LVP** — Configura bloqueo de edicion y modo seguridad en cuentas Liverpool via API SimpliRoute (POST).
4. **Reporte Visitas/Rutas** — Genera reportes por rango de fechas dividido en sub-intervalos y los envia por correo via API SimpliRoute (GET).

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
bloqueo_lvp.py                       # Pagina Bloqueo LVP (UI + API configs Liverpool)
reporte_visitas.py                   # Pagina Reporte Visitas/Rutas (UI + API reportes)
cuentas.csv                          # 58 cuentas Liverpool (nombre, id)
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
- Todas las paginas comparten el mismo estilo visual (sr-header, sr-label, sr-stat, sr-tip, etc.)

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

## Flujo: Bloqueo LVP
1. Token se carga automaticamente desde `st.secrets.api_config.auth_token`
2. Selecciona cuenta Liverpool del dropdown (58 cuentas desde cuentas.csv)
3. Elige valor True (activar bloqueo) o False (desactivar)
4. Al procesar: envia 3 POST a `/accounts/{ID}/configs/` con las keys:
   - `disable_edit_for_active_and_finished_routes`
   - `enable_safety_mode`
   - `avoid_edit_checkout_after_route_finished`
5. Muestra resultado por cada configuracion

## Flujo: Reporte Visitas/Rutas
1. Usuario selecciona tipo de reporte (Visitas o Rutas)
2. Ingresa token de API y correo destino
3. Define rango de fechas e intervalo de division (Semanal/Quincenal/Mensual)
4. Al procesar: divide el rango en sub-intervalos y envia un GET por cada uno
5. Pausa de 3 segundos entre solicitudes para evitar rate limiting
6. Los reportes llegan al correo ingresado

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

### SimpliRoute (Bloqueo LVP)
- `POST /v1/accounts/{ACCOUNT_ID}/configs/` - Configuracion de cuenta
- Auth: `Authorization: Token {API_TOKEN}`

### Likewise Middleware (Webhooks)
- Base: `https://us-central1-likewizemiddleware-{empresa}.cloudfunctions.net/`
- `POST /likewize/webhook/plan/routes/support` - Creacion de rutas
- `POST /likewize/startRoutes` - Inicio de rutas
- `POST /likewize/webhook/routes/checkout` - Checkout de rutas
- `POST /likewize/webhook/visits/support` - Exclusion de visitas
- Sin auth (acceso por URL)

### SimpliRoute (Reporte Visitas/Rutas)
- `GET /v1/reports/visits/from/{start}/to/{end}/?email={email}` - Reporte de visitas (api.simpliroute.com)
- `GET /v1/reports/routes/from/{start}/to/{end}/?email={email}` - Reporte de rutas (api-gateway.simpliroute.com)
- Auth: `Authorization: Token {API_TOKEN}`
