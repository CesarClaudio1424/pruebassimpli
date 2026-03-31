# Edicion Masiva de Visitas - SimpliRoute

## Descripcion
App Streamlit para edicion masiva de visitas a traves de la API de SimpliRoute. El usuario sube un CSV con los datos a editar y la app los envia en bloques via PUT.

## Stack
- **Python 3.12.3** con entorno virtual `.venv`
- **Streamlit** - Frontend web
- **requests** - Cliente HTTP

## Estructura
```
main.py                              # App Streamlit (unico archivo)
.claude/commands/simpliroute-api.md  # Skill con referencia de API SimpliRoute
```

## UI
- Estilo visual basado en SimpliRoute: azul #2A2BA1, verde #29AB55, celeste #369CFF
- Fuente Inter
- Soporte dark/light mode con toggle (st.session_state, sin JS)
- CSS dinámico generado con dict THEME segun el modo activo

## Flujo de la app
1. Usuario ingresa token de API
2. Se valida contra `GET /accounts/me/`
3. Usuario sube CSV (encoding ISO-8859-1)
4. Se muestra preview de los datos
5. Al procesar: convierte fechas dd/mm/yyyy -> yyyy-mm-dd
6. Divide datos en bloques (max 500) y envia via `PUT /routes/visits/`
7. Muestra progreso en tiempo real y errores por bloque

## Ejecutar
```bash
source .venv/Scripts/activate
streamlit run main.py
```

## API SimpliRoute usada
- `GET /v1/accounts/me/` - Validacion de cuenta
- `PUT /v1/routes/visits/` - Edicion masiva de visitas
- Auth: `Authorization: Token {API_TOKEN}`
