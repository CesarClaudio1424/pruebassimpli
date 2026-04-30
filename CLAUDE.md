# SimpliRoute Tools

## Descripcion
App Streamlit multi-herramienta con navegacion por sidebar. Incluye trece herramientas:
1. **Edicion Masiva de Visitas** — Sube un CSV y edita visitas en bloque via API SimpliRoute (PUT).
2. **Webhooks Likewise** — Envia webhooks a Google Cloud Functions para procesar rutas/visitas del middleware Likewise (POST).
3. **Mover Visitas Likewise** — Busca visitas por rango de fechas, filtra por reference o ID, y las mueve a una fecha destino en las 4 cuentas Likewise (GET + PUT).
4. **Bloqueo LVP** — Configura bloqueo de edicion y modo seguridad en cuentas Liverpool via API SimpliRoute (POST).
5. **Reporte Visitas/Rutas** — Genera reportes por rango de fechas dividido en sub-intervalos y los envia por correo via API SimpliRoute (GET).
6. **Checkout General** — Envia webhooks de checkout a SimpliRoute para rutas y visitas de cualquier cuenta (POST).
7. **Eliminar Visitas** — Busca todas las visitas de una fecha via endpoint paginado (`/routes/visits/paginated/`) y las "elimina" seteando `planned_date=2020-01-01` y `route=""`. Dos modos: duplicados (solo borra repetidos por reference conservando el ID mas bajo) o eliminacion total.
8. **Unilever** — Actualiza cargas (load_2, load_3) y ventanas horarias por agencia via API SimpliRoute (PUT).
9. **Zonas KML** — Crea zonas en SimpliRoute desde archivos KML (poligonos exportados de Google My Maps), o elimina zonas existentes de una cuenta.
10. **Recuperar Visitas LVP** — Busca visitas Liverpool por referencia y las asigna a la ruta/fecha correcta (GET + PUT).
11. **Eliminar Visitas BAT** — (herramienta secundaria, solo busqueda por API). La version completa con acceso a BD es una app Flet standalone en `C:\Proyectos\EliminarBAT\`.
12. **Asignacion Fija Uni** — Cuatro sub-tabs: (a) Actualizar planeacion nacional: sube Excel de planeacion y hace upsert en Supabase (`planeacion_nacional`); (b) Generar archivo de ruteo: rellena ventanas/lat/lon/habilidades desde Supabase y guarda datos en tablas provisionales por agencia; (c) Actualizar Habilidades: asigna habilidad F-prefijada (habilidad_1..4 con rotacion) desde archivo de planeacion; (d) Actualizar datos Simpli: sube Plan SimpliRoute, toma references (col N), los cruza con tabla provisional y hace PUT de ventanas y cargas en SimpliRoute.
13. **Cambio de Fechas** — Tres sub-tabs: (a) Cambiar Fecha de Plan: mueve un plan y sus rutas a nueva fecha; (b) Cambiar Fecha de Rutas: actualiza `planned_date` de rutas seleccionadas (cascadea a visitas, no al plan); (c) Cambiar Fecha de Visitas: actualiza `planned_date` de visitas en bulk (no afecta rutas ni plan).

## Stack
- **Python 3.12.3** con entorno virtual `.venv`
- **Streamlit** - Frontend web
- **requests** - Cliente HTTP

## Repositorios
- **Produccion:** CesarClaudio1424/simpliroute-tools (publico) — https://simpliroute-tools.streamlit.app/
- **Pruebas:** CesarClaudio1424/pruebassimpli (publico)

> **Regla de push:** Siempre hacer push solo al remote `pruebas`. Nunca hacer push a `origin` (produccion) sin instruccion explicita del usuario.

## Repositorios independientes
Estas apps viven en repos propios, separados de simpliroute-tools, y tienen su propio deploy en Streamlit Cloud:
- **Eliminacion de Visitas:** CesarClaudio1424/eliminacion-visitas — app de un solo archivo (`main.py`), elimina visitas en bloque via `POST /v1/bulk/delete/visits/`. No se agrega a este repo.

## Apps locales standalone
Apps que no se despliegan en Streamlit Cloud, se distribuyen como `.exe`:
- **Eliminar Visitas BAT (Flet):** `C:\Proyectos\EliminarBAT\` — app Flet (`main_flet.py`) empaquetada como `.exe` via `flet pack`. Busca visitas de la cuenta BAT (account_id 95718) que no tienen `planned_date` (invisibles para la API) conectandose directamente a la BD PostgreSQL via Cloud SQL Proxy, y las limpia via PUT. Flujo de busqueda: BD primero → API /reference/ → API fallback +-30 dias. Requiere `cloud-sql-proxy.exe.exe` en `C:\` y autenticacion gcloud. Tambien existe `main.py` (version Streamlit anterior, obsoleta).

## Estructura
```
main.py                              # Entry point: page config, sidebar, tema, dispatch
config.py                            # Constantes centralizadas (endpoints, timeouts, delays)
utils.py                             # Funciones UI compartidas (header, guide, stats, progress)
estilos.py                           # THEME dict + generador de CSS dinamico
edicion.py                           # Pagina Edicion Masiva (UI + helpers API/CSV)
pagina_webhooks.py                   # Pagina Webhooks Likewise (UI)
webhook.py                           # Backend webhooks Likewise (URLs, envio HTTP)
mover_visitas_likewise.py             # Pagina Mover Visitas Likewise (UI + busqueda por fecha + filtro reference/ID)
eliminar_bat.py                      # Pagina Eliminar Visitas BAT (herramienta secundaria)
eliminar_visitas.py                  # Pagina Eliminar Visitas (busqueda paginada + PUT bulk)
bloqueo_lvp.py                       # Pagina Bloqueo LVP (UI + API configs Liverpool)
reporte_visitas.py                   # Pagina Reporte Visitas/Rutas (UI + API reportes)
checkout_general.py                  # Pagina Checkout General (UI + API send-webhooks)
unilever.py                          # Pagina Unilever (UI + API edicion cargas/ventanas por agencia)
zonas_kml.py                         # Pagina Zonas KML (UI + API creacion/eliminacion de zonas)
recuperar_lvp.py                     # Pagina Recuperar Visitas LVP (UI + busqueda hibrida + asignacion)
cambiar_fecha_plan.py                # Pagina Cambio de Fechas: 3 tabs (Plan / Rutas / Visitas)
cuentas.csv                          # Cuentas Liverpool (nombre, id, token)
requirements.txt                     # Dependencias para Streamlit Cloud
runtime.txt                          # Pin Python 3.12 para Streamlit Cloud
.gitignore                           # Exclusiones de git
.claude/commands/simpliroute-api.md  # Skill con referencia de API SimpliRoute
.claude/commands/ticket.md           # Skill para generar tickets/reportes de bug con plantilla estandar
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
7. (Opcional) Al excluir, puede tambien limpiar las visitas de SimpliRoute:
   - Usuario marca checkbox "Tambien eliminar visitas de SimpliRoute" e ingresa rango de fechas (max 7 dias)
   - Token se carga desde `st.secrets.api_config.token_{cuenta}` (token_telefonica, token_entel, etc.)
   - GET visitas por cada dia del rango, filtra las excluidas sin ruta asignada
   - PUT bulk a `/routes/visits/` en lotes (total / 5, max 500 por lote) con `route: ""`, `planned_date: 2020-01-01`
   - Timeout de 600s para consultas y edicion de limpieza

## Flujo: Mover Visitas Likewise
1. Usuario elige tipo de busqueda: **Reference** o **ID** de visita
2. Selecciona una de las 4 cuentas Likewise (Telefonica, Entel, Omnicanalidad, Biobio)
3. Ingresa rango de fechas de origen (Desde/Hasta, max 7 dias) — la fecha en la que estan las visitas actualmente
4. Ingresa valores a buscar (referencias o IDs, uno por linea)
5. Elige fecha destino para mover las visitas
6. **Buscar Visitas** — por cada dia del rango:
   - `GET /v1/routes/visits/?planned_date={YYYY-MM-DD}` — trae todas las visitas del dia
   - Combina todas las visitas del rango y filtra localmente por reference o ID
   - Muestra visitas encontradas vs no encontradas
7. **Mover Visitas** — preview en tabla, luego:
   - Divide visitas en bloques (max 500) y envia via `PUT /routes/visits/`
   - Respeta delay entre bloques (EDIT_DELAY de config.py)
8. Muestra progreso en tiempo real, resultados por bloque, y estadisticas finales
- Token se carga desde `st.secrets.api_config.token_{cuenta}` con `.strip()` para limpiar whitespace
- Datos intermedios se persisten en `st.session_state` (prefijo `mvl_`) para sobrevivir reruns de Streamlit

## Flujo: Bloqueo LVP
1. Token se carga automaticamente desde `st.secrets.api_config.auth_token`
2. Selecciona cuenta Liverpool del dropdown (58 cuentas desde cuentas.csv)
3. Elige valor True (activar bloqueo) o False (desactivar)
4. Al procesar: envia 3 POST a `/accounts/{ID}/configs/` con las keys:
   - `disable_edit_for_active_and_finished_routes`
   - `enable_safety_mode`
   - `avoid_edit_checkout_after_route_finished`
5. Muestra resultado por cada configuracion

## Flujo: Checkout General
1. Token se carga automaticamente desde `st.secrets.api_config.checkout_token`
2. Usuario pega datos tabulados (Fecha [tab] AccountID [tab] ID), uno por linea
3. Deteccion automatica: ID con mas de 9 caracteres = ruta, sino = visita
4. Al procesar: envia un POST por cada fila a `/v1/mobile/send-webhooks`
5. Solo muestra errores en la lista; contador de procesados junto a la barra de progreso

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

### SimpliRoute (Limpieza post-exclusion)
- `GET /v1/routes/visits/?planned_date={YYYY-MM-DD}` - Obtener visitas por fecha (una consulta por dia del rango)
- `PUT /v1/routes/visits/` - Edicion bulk: quitar ruta y mover fecha a 2020-01-01 (lotes de total/5, max 500)
- Auth: `Authorization: Token {token_cuenta}` (desde secrets: token_telefonica, token_entel, etc.)
- Matching: visitas se identifican por campo `reference`, solo se limpian las que no tienen ruta asignada
- Timeout: 600s (CLEANUP_TIMEOUT en config.py)

### SimpliRoute (Checkout General)
- `POST /v1/mobile/send-webhooks` - Envio de webhooks para rutas/visitas
- Payload: `{ "account_ids": [int], "planned_date": "YYYY-MM-DD", "route_ids"|"visit_ids": [int] }`
- Auth: `Authorization: Token {CHECKOUT_TOKEN}` (desde secrets)

### SimpliRoute (Mover Visitas Likewise)
- `GET /v1/routes/visits/?planned_date={YYYY-MM-DD}` - Obtener todas las visitas de una fecha (una consulta por dia del rango, max 7 dias)
- `PUT /v1/routes/visits/` - Edicion bulk: actualiza planned_date de visitas
- Auth: `Authorization: Token {token_cuenta}` (desde secrets: token_telefonica, token_entel, token_omnicanalidad, token_biobio)
- Payload PUT: array de objetos con id, reference, title, address, planned_date (nueva fecha)
- Filtrado local: las visitas obtenidas por fecha se filtran por reference o ID segun la seleccion del usuario
- Bloqueo maximo: 500 visitas por request, delay entre bloques de EDIT_DELAY segundos

### SimpliRoute (Unilever)
- `GET /v1/routes/visits/?planned_date={YYYY-MM-DD}` - Obtener visitas por fecha para cruzar references
- `PUT /v1/routes/visits/` - Edicion bulk: actualiza load_2, load_3 (y window_start/window_end para Monterrey)
- Auth: `Authorization: Token {token_agencia}` (desde secrets: `[cuentas_unilever]` con keys token_tlahuac, token_monterrey, token_hermosillo, token_merida, token_mexicali)
- Payload incluye siempre: id, reference, title, address. load_2/load_3 solo si son numericos validos.
- Matching: campo `reference` de la API se cruza con columna `ID` del archivo de agencia y del maestro

### SimpliRoute (Reporte Visitas/Rutas)
- `GET /v1/reports/visits/from/{start}/to/{end}/?email={email}` - Reporte de visitas (api.simpliroute.com)
- `GET /v1/reports/routes/from/{start}/to/{end}/?email={email}` - Reporte de rutas (api-gateway.simpliroute.com)
- Auth: `Authorization: Token {API_TOKEN}`

### SimpliRoute (Recuperar Visitas LVP)
- `GET /v1/routes/visits/reference/{reference}/` - Busqueda por referencia (con trailing slash; respuesta paginada `{count, results}`)
- `GET /v1/routes/visits/?planned_date={YYYY-MM-DD}` - Fallback: busqueda por fecha filtrando por `reference`
- `GET /v1/plans/{YYYY-MM-DD}/vehicles/` - Listar vehiculos/rutas de una fecha para resolver route_id
- `PUT /v1/routes/visits/{id}` - Asignar visita a ruta: payload `{"route": route_id, "planned_date": "YYYY-MM-DD"}`
- Auth: `Authorization: Token {token}` (desde columna `token` de `cuentas.csv` segun cuenta seleccionada)
- Fallback paralelo: `ThreadPoolExecutor` con 10 hilos, ±30 dias desde hoy

### SimpliRoute (Asignacion Fija Uni — Actualizar datos Simpli)
- `GET /v1/routes/visits/reference/{reference}/` — busqueda por referencia (respuesta paginada `{count, results}`)
- `PUT /v1/routes/visits/` — edicion bulk: actualiza `window_start`, `window_end`, `time_at_stop`, `load_2`, `load_3`
- Auth: `Authorization: Token {token}` (desde secrets: `cuentas_unilever.token_tlahuac` o `token_monterrey`)
- Supabase tablas provisionales: `ruteo_dia_tlahuac` / `ruteo_dia_monterrey` — se rellenan al generar archivo de ruteo

### SimpliRoute (Zonas KML)
- `POST /v1/zones/` - Crear zona. Payload: `{ "name", "coordinates", "vehicles": [], "schedules": [] }`
- `GET /v1/zones/` - Listar zonas de la cuenta (response: lista o `{results: [...]}`)
- `DELETE /v1/zones/{id}` - Eliminar zona por ID (sin trailing slash; 204 o 200 = exito)
- Auth: `Authorization: Token {API_TOKEN}` (token ingresado manualmente, no desde secrets)
- `coordinates` es un string con formato Python: `[{'lat': '19.4','lng': '-99.1'},...]`
- `schedules` siempre se incluye (lista vacia o dias en ingles: Monday, Tuesday, etc.)
- Delay entre requests: 0.5s (ZONA_DELAY)

## Flujo: Recuperar Visitas LVP
1. Token se carga automaticamente desde `cuentas.csv` segun la cuenta seleccionada (columna `token`)
2. Selecciona cuenta Liverpool del dropdown
3. Agrega filas dinamicas: referencia, nombre de vehiculo, fecha destino (boton "+ Agregar fila")
4. **Buscar visitas y rutas** — por cada fila:
   - `GET /v1/routes/visits/reference/{reference}/` — busqueda directa (respuesta paginada `{count, results}`)
   - Si no encuentra: fallback paralelo con `ThreadPoolExecutor` (10 hilos, ±30 dias desde hoy)
   - `GET /v1/plans/{fecha}/vehicles/` — resuelve route_id por nombre de vehiculo (case-insensitive)
   - Muestra request + response en expanders por fila (expandido si hay error)
5. Stats: listos / visita ok sin ruta / no encontradas / pendiente de seleccion (morado)
6. Si el endpoint devuelve multiples visitas para un mismo reference: muestra tabla seleccionable (`st.dataframe` con `on_select="rerun"`) para que el usuario elija la correcta. Seleccion se guarda en `st.session_state.recuperar_selecciones[idx]`.
7. **Procesar N visita(s)** — solo las que tienen visita y ruta encontradas (incluyendo selecciones manuales)
   - `PUT /v1/routes/visits/{id}` con `route` y `planned_date`
- `cuentas.csv` se lee con `encoding="latin-1"` (tiene acentos en nombres)
- Respuesta del endpoint reference puede ser lista, objeto con `id`, o paginada `{results: [...]}`
- Duplicados de reference: se muestra tabla de desambiguacion ordenada por ID desc para elegir la visita correcta

## Flujo: Zonas KML
1. Usuario ingresa token de API
2. Elige modo via radio selector: **Crear zonas desde KML** o **Eliminar zonas de la cuenta**
3. **Modo Crear:**
   - Sube archivo KML (exportado de Google My Maps u otra herramienta)
   - Configura nombre: chips clicables para componer plantilla con atributos del KML, o nombre generico secuencial
   - Chip "N°" = numero secuencial `{n}` (era "#" pero quedaba en blanco por conflicto con markdown de Streamlit)
   - Opcionalmente configura schedules desde un campo de dia del KML (rangos "LUNES A VIERNES", listas, "TODOS LOS DIAS"; formato abreviado L-M-X-J-V-S-D)
   - Preview de zonas antes de enviar
   - Procesa una zona por rerun via POST; barra de progreso + boton Cancelar aparecen al fondo de la pagina
   - Errores en expanders con el detalle del response
4. **Modo Eliminar:**
   - Boton "Leer zonas de la cuenta" → GET /v1/zones/
   - Multiselect con todas las zonas seleccionadas por defecto (formato "nombre (#id)")
   - Checkbox de confirmacion antes de eliminar
   - Procesa una zona por rerun via DELETE; barra de progreso + boton Cancelar aparecen al fondo
   - Errores en expanders con URL del request y body del response
- El Cancelar funciona entre reruns: detiene el siguiente item, puede eliminar/crear 1 extra despues del clic

## Flujo: Unilever
1. Usuario elige tipo de archivo maestro: **Archivo 4** (Ruteo Dinámico) o **Archivo 1** (Monitoreo de Pedidos)
2. Sube el archivo maestro (CSV o Excel):
   - Archivo 4: columnas `ID`, `Carga 2`→load_2, `Carga 3`→load_3, `Hora Inicial`→window_start, `Hora Final`→window_end
   - Archivo 1: columnas `Código`→ID, `Total + Impuestos`→load_2, `Cant. Pedido`→load_3 (sin ventanas horarias)
3. Selecciona fecha del ruteo
4. Sube archivos por agencia (Excel .xlsx con columna `ID`), uno por tab
5. Al procesar: consulta visitas de la fecha en cada cuenta, cruza `reference` API con `ID` del archivo agencia y del maestro
6. Edita en lotes via PUT. Muestra request y response por bloque (expandido si hay error)
7. **Excepcion Monterrey:** ademas de load_2/load_3, actualiza window_start/window_end (solo con Archivo 4)
- Agencias: Tláhuac, Monterrey, Hermosillo, Mérida, Mexicali
- Columnas normalizadas automaticamente (español → nombre interno) via `_COLUMN_MAP` en unilever.py
- IDs vacios o con valor literal "None" se filtran y no se procesan

## Flujo: Cambio de Fechas
Tres sub-tabs en `cambiar_fecha_plan.py`. Todas validan token contra `/accounts/me/` y muestran badge de cuenta.

### Tab 1 — Cambiar Fecha de Plan
1. Token → validacion de cuenta
2. Rango de busqueda → `GET /v1/routes/plans/?start_date=&end_date=`
3. Tarjetas de planes en grid 2 columnas (seleccion con boton por tarjeta)
4. Nuevas fechas de inicio/fin → `PUT /v1/routes/plans/{uuid}/` con objeto completo
5. Si el PUT del plan es exitoso: `PUT /v1/routes/routes/{uuid}/` por cada ruta del plan (10 workers paralelos) con objeto completo (GET previo si no se tiene)

### Tab 2 — Cambiar Fecha de Rutas
1. Token → validacion
2. Fecha origen → `GET /v1/routes/routes/?planned_date=` + `GET /v1/plans/{fecha}/vehicles/` (paralelo, para nombres de vehiculo/conductor)
3. Nombres de planes: `GET /v1/routes/plans/{uuid}/` en paralelo por cada UUID unico
4. Botones de filtro por plan (columna izquierda: "Todas"; columna derecha: grid 2 cols con nombre completo de plan). Seleccionado = azul primario.
5. Tabla `st.data_editor`: ☑ | Plan | ID de ruta | Vehiculo | Conductor | Visitas. Empieza sin seleccion.
6. Nueva fecha → `PUT /v1/routes/routes/{uuid}/` con objeto completo (10 workers paralelos)
- **Advertencia:** cambiar fecha de rutas cascadea a sus visitas. El plan NO se modifica.

### Tab 3 — Cambiar Fecha de Visitas
1. Token → validacion
2. Fecha origen → `GET /v1/routes/visits/paginated/` (con retry/backoff, igual que Eliminar Visitas)
3. Nueva fecha → `PUT /v1/routes/visits/` bulk en bloques de MAX_BLOCK_SIZE
- **Nota:** solo cambia visitas. Rutas y plan NO se modifican.

## Flujo: Asignacion Fija Uni
Cuatro tabs en `asignacion_fija_uni.py`. Supabase client se obtiene via `_get_supabase_client()` (secrets `supabase.url` + `supabase.key`).

### Tab 1 — Actualizar planeacion nacional
1. Sube Excel de planeacion Unilever
2. Filtra filas de Tláhuac y Monterrey (columna C)
3. Extrae: cliente (D), sector (AH), agencia, latitud (X), longitud (Y)
4. Upsert en `planeacion_nacional` on_conflict=cliente — NO toca habilidad_1..4

### Tab 2 — Generar archivo de ruteo
1. Elige agencia (Tláhuac o Monterrey)
2. Tláhuac: pega numeros de vehiculos activos (acepta `R20020-MX01` o `20020`) → `habilidades_disponibles = {F20020, ...}`
3. Monterrey: define cuantas rutas + cuentas especiales
4. Sube Excel de ruteo → `_procesar_ruteo`: rellena col D/E/F (ventanas/duracion), H/I (lat/lon), K (habilidad) desde `planeacion_nacional`, vacia Q/R
5. Al terminar: guarda reference (col J), hora_inicio, hora_final, duracion, carga_2 (col Q original), carga_3 (col R original) en `ruteo_dia_tlahuac` o `ruteo_dia_monterrey` via upsert
- Habilidad: prioridad habilidad_1 → habilidad_2 → habilidad_3 → habilidad_4, primera que este en habilidades_disponibles gana; si ninguna → "Fuera"

### Tab 3 — Actualizar Habilidades
1. Sube archivo de planeacion con col B (habilidad formato R20020-MX01 → extrae F20020) y col S (cliente)
2. Lee habilidades existentes de `planeacion_nacional` para cada cliente
3. Rotacion: nueva habilidad va a habilidad_1, las demas se recorren sin duplicados (compara sin prefijo F)
4. Upsert en `planeacion_nacional`: habilidad_1..4 + agencia (NOT NULL)
- Tlahuac: boton "Actualizar skills en SimpliRoute" → PATCH vehiculos R#####-MX## con skill F{num} (activos) o Fuera (inactivos)

### Tab 4 — Actualizar datos Simpli
1. Selecciona cuenta (Tláhuac o Monterrey) — token desde secrets
2. Sube Plan SimpliRoute exportado → extrae references de col N (indice 13)
3. Busca cada reference en `ruteo_dia_tlahuac` / `ruteo_dia_monterrey`
4. Para cada reference encontrado: GET visit por reference → obtiene id, title, address, planned_date, route
5. PUT bulk con window_start, window_end, time_at_stop, load_2, load_3
- References no encontrados en ruteo_dia se omiten (requiere haber generado el archivo de ruteo primero)

### SimpliRoute (Cambio de Fechas)
- `GET /v1/routes/plans/?start_date={}&end_date={}` — listar planes por rango
- `PUT /v1/routes/plans/{uuid}/` — actualizar plan (objeto completo requerido)
- `GET /v1/routes/routes/?planned_date={YYYY-MM-DD}` — listar rutas por fecha
- `PUT /v1/routes/routes/{uuid}/` — actualizar ruta (objeto completo requerido; solo `planned_date` da HTTP 400)
- `GET /v1/plans/{YYYY-MM-DD}/vehicles/` — vehiculo y conductor por ruta de una fecha
- `GET /v1/routes/plans/{uuid}/` — nombre completo de un plan
- `GET /v1/routes/visits/paginated/` — visitas paginadas por fecha (con retry)
- `PUT /v1/routes/visits/` — edicion bulk de visitas
- Auth: `Authorization: Token {token}` (ingresado manualmente)

---

# Guia de razonamiento (reduce errores comunes)

Lineamientos para mejorar la calidad de las respuestas. Sesgan hacia precaucion sobre velocidad — para tareas triviales, usa criterio.

## 1. Pensar antes de codear

**No asumir. No ocultar confusion. Hacer explicitos los tradeoffs.**

Antes de implementar:
- Declarar supuestos explicitamente. Si hay duda, preguntar.
- Si existen varias interpretaciones, presentarlas — no elegir en silencio.
- Si hay un enfoque mas simple, decirlo. Empujar de regreso cuando se justifique.
- Si algo no esta claro, parar. Nombrar la confusion. Preguntar.

## 2. Simplicidad primero

**Codigo minimo que resuelva el problema. Nada especulativo.**

- Sin features mas alla de lo pedido.
- Sin abstracciones para codigo de un solo uso.
- Sin "flexibilidad" o "configurabilidad" no solicitada.
- Sin manejo de errores para escenarios imposibles.
- Si escribiste 200 lineas y podrian ser 50, reescribir.

Pregunta clave: "¿Un ingeniero senior diria que esto esta sobrecomplicado?" Si si, simplificar.

## 3. Cambios quirurgicos

**Tocar solo lo necesario. Limpiar solo lo que tu mismo ensuciaste.**

Al editar codigo existente:
- No "mejorar" codigo, comentarios o formato adyacente.
- No refactorizar lo que no esta roto.
- Respetar el estilo existente, aunque tu lo hicieras distinto.
- Si notas codigo muerto no relacionado, mencionarlo — no borrarlo.

Cuando tus cambios crean huerfanos:
- Quitar imports/variables/funciones que TUS cambios dejaron sin uso.
- No remover codigo muerto previo salvo que se pida.

Test: cada linea cambiada debe trazarse directamente al pedido del usuario.

## 4. Ejecucion guiada por objetivos

**Definir criterios de exito. Iterar hasta verificar.**

Convertir tareas en metas verificables:
- "Agregar validacion" → "Escribir tests con inputs invalidos, luego hacerlos pasar"
- "Arreglar el bug" → "Escribir un test que lo reproduzca, luego hacerlo pasar"
- "Refactorizar X" → "Asegurar que los tests pasan antes y despues"

Para tareas multi-step, declarar un plan breve:
```
1. [Paso] → verificar: [check]
2. [Paso] → verificar: [check]
3. [Paso] → verificar: [check]
```

Criterios de exito fuertes permiten iterar de forma independiente. Criterios debiles ("hazlo funcionar") obligan a clarificar todo el tiempo.

**Estos lineamientos funcionan si:** menos cambios innecesarios en los diffs, menos reescrituras por sobrecomplicacion, y las preguntas aclaratorias llegan antes de implementar — no despues del error.
