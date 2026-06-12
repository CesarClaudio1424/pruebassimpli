import re
import streamlit as st
import pandas as pd
import requests as _requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from utils import (
    render_header, render_guide, render_stat, render_label,
    render_tip, render_error_item,
    create_progress_tracker, update_progress, finish_progress,
)

_LOADER_CSS = """
<style>
@keyframes sr-afu-spin { to { transform: rotate(360deg); } }
@keyframes sr-afu-pulse { 0%,100% { opacity:1; } 50% { opacity:.5; } }
.sr-afu-loader {
    display: flex; flex-direction: column; align-items: center;
    padding: 2rem 1rem; margin: 1rem 0; border-radius: 0.8rem;
    background: linear-gradient(135deg, rgba(42,43,161,0.08) 0%, rgba(54,156,255,0.08) 100%);
    border: 1px solid rgba(42,43,161,0.15);
}
.sr-afu-spinner {
    width: 56px; height: 56px; border-radius: 50%;
    border: 5px solid rgba(42,43,161,0.15);
    border-top-color: #2A2BA1; border-right-color: #369CFF;
    animation: sr-afu-spin 0.9s linear infinite;
}
.sr-afu-text {
    margin-top: 1rem; color: #2A2BA1; font-weight: 700;
    font-size: 1rem; letter-spacing: -0.01em;
    animation: sr-afu-pulse 1.4s ease-in-out infinite;
}
.sr-afu-sub { margin-top: 0.25rem; color: #666; font-size: 0.8rem; }
</style>
"""


def _render_loader(placeholder, mensaje, sub=""):
    sub_html = f'<div class="sr-afu-sub">{sub}</div>' if sub else ""
    placeholder.markdown(
        f'{_LOADER_CSS}<div class="sr-afu-loader">'
        f'<div class="sr-afu-spinner"></div>'
        f'<div class="sr-afu-text">{mensaje}</div>{sub_html}</div>',
        unsafe_allow_html=True,
    )

# La planeacion sobrevive solo como memoria de habilidades (cliente -> ruta fija);
# se auto-mantiene con "Actualizar habilidades desde el plan".
_TABLA_PLANEACION = "smart_route_planeacion"
UPSERT_BATCH_SIZE = 500

RUTAS_MONTERREY = [
    "R20082-MX01", "R20083-MX01", "R20312-MX01", "R20338-MX01",
    "R20340-MX01", "R20342-MX01", "R20343-MX01", "R20345-MX01", "R20348-MX01",
    "R20351-MX01", "R20352-MX01", "R20353-MX01", "R20355-MX01", "R20361-MX01",
    "R20362-MX01", "R20363-MX01", "R20364-MX01", "R20378-MX01", "R20384-MX01",
    "R21218-MX01",
]
ESPECIALES_MONTERREY = [
    "R1001FM-MX01",
    "R1001EV-MX01",
]


def _get_supabase_client():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
    except (KeyError, FileNotFoundError):
        st.error("Faltan credenciales de Supabase en secrets. Agregar [supabase] con url y key.")
        st.stop()
    from supabase import create_client
    return create_client(url, key)


def _rotar_habilidades(existentes, nueva):
    """
    Pone `nueva` en posicion 1 y recorre las demas sin duplicados.
    Trata el mismo numero con o sin prefijo F como el mismo skill
    (ej: '20020' y 'F20020' se consideran iguales) para migrar el
    formato viejo al nuevo de forma transparente.
    existentes: lista de 4 valores (pueden ser None/vacios).
    Retorna: lista de exactamente 4 valores.
    """
    nueva_num = nueva.lstrip("F")
    limpia = [
        h for h in existentes
        if h and str(h).strip() not in ("", "None", "null", "nan")
    ]
    limpia = [h for h in limpia if str(h).lstrip("F") != nueva_num]
    rotada = ([nueva] + limpia)[:4]
    while len(rotada) < 4:
        rotada.append(None)
    return rotada


def _limpiar_nota_cliente(texto):
    """Quita el sufijo entre parentesis para el match.
    Ej: '30880451(F05 MTY)' -> '30880451'. Si no hay '(' devuelve el texto tal cual.
    """
    if not texto:
        return ""
    idx = texto.find("(")
    return (texto[:idx] if idx >= 0 else texto).strip()


def _num_habilidad(hab):
    """Normaliza cualquier formato de habilidad a su numero/especial pelon.
    'F20020' -> '20020', 'R20020-MX01' -> '20020', '20020' -> '20020',
    'R1001FM-MX01' -> '1001FM', 'Fuera'/vacio -> None.
    """
    if hab is None:
        return None
    s = str(hab).strip()
    if not s or s.lower() in ("fuera", "none", "nan", "null"):
        return None
    m = re.match(r'^R(.+?)-MX\d+$', s)
    if m:
        s = m.group(1)
    s = s.lstrip("F")
    return s or None


def _ruta_nombre(num):
    """Numero/especial pelon -> formato nuevo 'R20020-MX01'."""
    return f"R{num}-MX01"


_VEHICLE_PATTERN = re.compile(r'^R(\d+[A-Z]*)-MX\d+$')


def _extraer_num_vehiculo(texto):
    """R20020-MX01 → '20020',  '20020' → '20020',  otros → None."""
    texto = texto.strip()
    m = _VEHICLE_PATTERN.match(texto)
    if m:
        return m.group(1)
    if re.match(r'^\d+$', texto):
        return texto
    return None


def _fetch_planeacion_smart(supabase, clientes):
    """Busca clientes en la planeacion tolerando el sufijo entre parentesis
    del lado de la tabla (ej '30823403(F03 MTY)'). Devuelve dict keyed por
    cliente limpio (sin parentesis)."""
    datos = {}
    cols = "cliente,habilidad_1,habilidad_2,habilidad_3,habilidad_4"
    chunk = 50
    for i in range(0, len(clientes), chunk):
        lote = clientes[i:i + chunk]
        # ilike '{cod}*' atrae exactos y los que traen sufijo; se filtra abajo
        patrones = ",".join(f"cliente.ilike.{cod}*" for cod in lote)
        try:
            resp = supabase.table(_TABLA_PLANEACION).select(cols).or_(patrones).execute()
            for row in resp.data or []:
                clave = _limpiar_nota_cliente(str(row.get("cliente", "")))
                if clave and clave not in datos:
                    datos[clave] = row
        except Exception as e:
            st.warning(f"Error consultando Supabase: {e}")
            return datos
    return datos


def _aplicar_rotacion_habilidades(supabase, pares, agencia, nota_exito=""):
    """Aplica rotacion (nueva a habilidad_1) y upsert en la planeacion.
    pares: lista de {"cliente", "habilidad"}."""
    loader2 = st.empty()
    _render_loader(loader2, "Consultando habilidades actuales...", f"{len(pares):,} clientes")
    clientes = [r["cliente"] for r in pares]
    existentes_map = {}
    for i in range(0, len(clientes), 500):
        lote = clientes[i:i + 500]
        try:
            resp = supabase.table(_TABLA_PLANEACION).select(
                "cliente,habilidad_1,habilidad_2,habilidad_3,habilidad_4"
            ).in_("cliente", lote).execute()
            for row in resp.data or []:
                existentes_map[row["cliente"]] = row
        except Exception as e:
            st.warning(f"No se pudieron consultar habilidades existentes: {e}")
    loader2.empty()

    # Construir payload con rotacion
    payload = []
    for r in pares:
        cliente = r["cliente"]
        nueva_hab = r["habilidad"]
        existente = existentes_map.get(cliente, {})
        actuales = [
            existente.get("habilidad_1"),
            existente.get("habilidad_2"),
            existente.get("habilidad_3"),
            existente.get("habilidad_4"),
        ]
        rotada = _rotar_habilidades(actuales, nueva_hab)
        payload.append({
            "cliente": cliente,
            "agencia": agencia,
            "habilidad_1": rotada[0],
            "habilidad_2": rotada[1],
            "habilidad_3": rotada[2],
            "habilidad_4": rotada[3],
        })

    total = len(payload)
    total_lotes = (total + UPSERT_BATCH_SIZE - 1) // UPSERT_BATCH_SIZE
    barra, contador, contenedor_errores = create_progress_tracker(total, text="Actualizando en Supabase...")

    procesados = 0
    errores = 0
    loader3 = st.empty()
    for i in range(0, total, UPSERT_BATCH_SIZE):
        lote_num = i // UPSERT_BATCH_SIZE + 1
        lote = payload[i:i + UPSERT_BATCH_SIZE]
        _render_loader(loader3, f"Subiendo lote {lote_num} de {total_lotes}...", f"{len(lote)} registros")
        try:
            supabase.table(_TABLA_PLANEACION).upsert(lote, on_conflict="cliente").execute()
        except Exception as e:
            errores += len(lote)
            with contenedor_errores:
                render_error_item(f"Lote {lote_num}: {e}")
        procesados += len(lote)
        update_progress(barra, contador, procesados, total, text="Actualizando en Supabase...")

    loader3.empty()
    finish_progress(barra)

    exitosos = total - errores
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(render_stat(exitosos, "Actualizados OK"), unsafe_allow_html=True)
    if errores:
        with col2:
            st.markdown(
                render_stat(errores, "Con error",
                            style="background: linear-gradient(135deg, #d32f2f 0%, #b71c1c 100%);"),
                unsafe_allow_html=True,
            )
        render_tip(f"Hubo {errores} registros con error. Revisa los mensajes arriba.", warning=True)
    else:
        msg = "Todos los registros se actualizaron correctamente"
        if nota_exito:
            msg += f" — {nota_exito}"
        render_tip(msg + ".")


# ---------------------------------------------------------------------------
# Asignar vehículos al plan (ruteo libre)
# ---------------------------------------------------------------------------
# Con el plan ruteado libre (vehículos genéricos), se lee el plan, se cruza el
# campo notes (cliente) contra la planeación y se propone el vehículo fijo con
# mayor % de coincidencia por ruta (asignación greedy 1 a 1).
_API_SR = "https://api.simpliroute.com/v1"
_ESPECIALES_NUMS = {_num_habilidad(v) for v in ESPECIALES_MONTERREY}
_PUT_RUTA_WORKERS = 10
_SIN_ASIGNAR = "(dejar como está)"


def _sr_headers(token):
    return {"Authorization": f"Token {token}", "Content-Type": "application/json"}


def _fetch_vehiculos_plan(token, fecha_str):
    """GET /plans/{fecha}/vehicles/ — vehiculos del plan con sus rutas."""
    try:
        r = _requests.get(
            f"{_API_SR}/plans/{fecha_str}/vehicles/",
            headers=_sr_headers(token), timeout=60,
        )
        if r.status_code != 200:
            return None, f"HTTP {r.status_code} — {r.text[:300]}"
        return r.json() or [], None
    except Exception as e:
        return None, str(e)


def _fetch_visitas_fecha(token, fecha_str):
    try:
        r = _requests.get(
            f"{_API_SR}/routes/visits/?planned_date={fecha_str}",
            headers=_sr_headers(token), timeout=120,
        )
        if r.status_code != 200:
            return None, f"HTTP {r.status_code} — {r.text[:300]}"
        data = r.json()
        if not isinstance(data, list):
            return None, f"Respuesta inesperada: {str(data)[:200]}"
        return data, None
    except Exception as e:
        return None, str(e)


def _fetch_flota(token):
    """GET /routes/vehicles/ — flota completa. Devuelve {num: {id, name, driver_id}}
    solo con los vehiculos fijos (nombre R#####-MX##)."""
    try:
        r = _requests.get(
            f"{_API_SR}/routes/vehicles/",
            headers=_sr_headers(token), timeout=60,
        )
        if r.status_code != 200:
            return None, f"HTTP {r.status_code} — {r.text[:300]}"
        data = r.json()
        lista = data.get("results", []) if isinstance(data, dict) else data
        flota = {}
        for v in lista or []:
            num = _extraer_num_vehiculo(str(v.get("name") or ""))
            if num and num not in flota:
                flota[num] = {
                    "id": v.get("id"),
                    "name": v.get("name"),
                    "driver_id": v.get("default_driver"),
                }
        return flota, None
    except Exception as e:
        return None, str(e)


def _fetch_conductores(token):
    """GET /accounts/drivers/ — {id: nombre} para mostrar el conductor propuesto."""
    try:
        r = _requests.get(
            f"{_API_SR}/accounts/drivers/",
            headers=_sr_headers(token), timeout=60,
        )
        if r.status_code != 200:
            return {}
        data = r.json()
        lista = data.get("results", []) if isinstance(data, dict) else data
        return {
            u["id"]: u.get("name") or u.get("username") or ""
            for u in lista or [] if u.get("id")
        }
    except Exception:
        return {}


def _cliente_de_visita(visita):
    cliente = _limpiar_nota_cliente(str(visita.get("notes") or "").strip())
    if not cliente or cliente.lower() in ("nan", "none", "null"):
        return None
    return cliente


def _proponer_asignacion(vehiculos_plan, visitas, lookup, flota):
    """Greedy 1:1: el par (ruta, vehiculo fijo) con mayor % de clientes gana primero.
    Rutas con vehiculo especial o ya fijo quedan bloqueadas y su vehiculo sale del pool."""
    rutas = {}
    usados = set()
    for v in vehiculos_plan:
        num_actual = _extraer_num_vehiculo(str(v.get("name") or ""))
        if num_actual in _ESPECIALES_NUMS:
            bloqueo = "especial — no se toca"
        elif num_actual and num_actual in flota:
            bloqueo = "ya tiene vehículo fijo"
            usados.add(num_actual)
        else:
            bloqueo = None
        for rt in v.get("routes", []):
            rid = rt.get("id")
            if rid:
                rutas[rid] = {
                    "uuid": rid,
                    "veh_actual": v.get("name", "—"),
                    "driver_actual": (v.get("driver") or {}).get("name", "—"),
                    "bloqueo": bloqueo,
                }

    # clientes unicos y conteo de visitas por ruta
    clientes_ruta = {}
    visitas_ruta = {}
    for vis in visitas:
        rid = vis.get("route")
        if not rid or rid not in rutas:
            continue
        visitas_ruta[rid] = visitas_ruta.get(rid, 0) + 1
        cliente = _cliente_de_visita(vis)
        if cliente:
            clientes_ruta.setdefault(rid, set()).add(cliente)

    candidatos = []
    propuestas = []
    for rid, info in rutas.items():
        clientes = clientes_ruta.get(rid, set())
        info.update({
            "visitas": visitas_ruta.get(rid, 0),
            "clientes": len(clientes),
            "propuesto": None, "pct": None, "votos_num": None,
        })
        propuestas.append(info)
        if info["bloqueo"] or not clientes:
            continue
        votos = {}
        for c in clientes:
            data = lookup.get(c)
            num = _num_habilidad(data.get("habilidad_1")) if data else None
            if num and num in flota and num not in _ESPECIALES_NUMS:
                votos[num] = votos.get(num, 0) + 1
        for num, n in votos.items():
            candidatos.append((n / len(clientes), n, rid, num))

    candidatos.sort(key=lambda t: (-t[0], -t[1]))
    asignadas = set()
    por_uuid = {p["uuid"]: p for p in propuestas}
    for pct, n, rid, num in candidatos:
        if rid in asignadas or num in usados:
            continue
        por_uuid[rid].update({"propuesto": num, "pct": pct, "votos_num": n})
        asignadas.add(rid)
        usados.add(num)
    return propuestas, usados


def _listar_rutas_completas(token, fecha_str):
    """GET /routes/routes/?planned_date= — objetos completos para el PUT."""
    rutas = []
    url = f"{_API_SR}/routes/routes/?planned_date={fecha_str}"
    try:
        while url:
            r = _requests.get(url, headers=_sr_headers(token), timeout=60)
            if r.status_code != 200:
                return None, f"HTTP {r.status_code} — {r.text[:300]}"
            data = r.json()
            if isinstance(data, list):
                rutas.extend(data)
                break
            rutas.extend(data.get("results", []))
            url = data.get("next")
        return rutas, None
    except Exception as e:
        return None, str(e)


def _put_ruta_vehiculo(token, ruta_obj, veh_id, driver_id):
    payload = dict(ruta_obj)
    payload["vehicle"] = veh_id
    if driver_id:
        payload["driver"] = driver_id
    url = f"{_API_SR}/routes/routes/{ruta_obj['id']}/"
    try:
        r = _requests.put(url, headers=_sr_headers(token), json=payload, timeout=60)
        return r.status_code, r.text[:300]
    except Exception as e:
        return 0, str(e)


def _aplicar_asignacion(token, fecha_str, cambios, flota):
    loader = st.empty()
    _render_loader(loader, "Consultando rutas del plan...", fecha_str)
    rutas_full, err = _listar_rutas_completas(token, fecha_str)
    loader.empty()
    if err:
        st.error(f"Error al consultar rutas: {err}")
        return
    por_id = {r.get("id"): r for r in rutas_full}

    faltantes = [c for c in cambios if c["uuid"] not in por_id]
    cambios = [c for c in cambios if c["uuid"] in por_id]

    resultados = []
    if cambios:
        total = len(cambios)
        barra = st.progress(0, text=f"Actualizando {total} rutas...")
        with ThreadPoolExecutor(max_workers=_PUT_RUTA_WORKERS) as pool:
            futuros = {
                pool.submit(
                    _put_ruta_vehiculo, token, por_id[c["uuid"]],
                    flota[c["num"]]["id"], flota[c["num"]]["driver_id"],
                ): c
                for c in cambios
            }
            done = 0
            for fut in as_completed(futuros):
                resultados.append((futuros[fut],) + fut.result())
                done += 1
                barra.progress(done / total, text=f"Rutas actualizadas: {done}/{total}")
        barra.empty()

    ok = sum(1 for _, s, _ in resultados if s in (200, 201, 204))
    errores = [(c, s, t) for c, s, t in resultados if s not in (200, 201, 204)]
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(render_stat(ok, "Rutas actualizadas"), unsafe_allow_html=True)
    if errores or faltantes:
        with col2:
            st.markdown(
                render_stat(len(errores) + len(faltantes), "Con error",
                            style="background: linear-gradient(135deg, #d32f2f 0%, #b71c1c 100%);"),
                unsafe_allow_html=True,
            )
    for c in faltantes:
        render_error_item(f"Ruta {c['uuid']}: no apareció en /routes/routes/ de la fecha.")
    for c, s, t in errores:
        render_error_item(f"{c['veh_actual']} → {flota[c['num']]['name']}: HTTP {s} — {t}")
    if not errores and not faltantes:
        render_tip("Todos los vehículos se asignaron correctamente. Vuelve a leer el plan para verificar.")


def _actualizar_habilidades_desde_plan(token, fecha_str, agencia):
    loader = st.empty()
    _render_loader(loader, "Leyendo plan...", fecha_str)
    vehiculos_plan, err = _fetch_vehiculos_plan(token, fecha_str)
    if err or not vehiculos_plan:
        loader.empty()
        st.error(f"No se pudo leer el plan: {err}" if err else "El plan no tiene rutas en esa fecha.")
        return
    _render_loader(loader, "Consultando visitas...", fecha_str)
    visitas, err = _fetch_visitas_fecha(token, fecha_str)
    loader.empty()
    if err:
        st.error(f"Error al consultar visitas: {err}")
        return

    num_por_ruta = {}
    for v in vehiculos_plan:
        num = _extraer_num_vehiculo(str(v.get("name") or ""))
        for rt in v.get("routes", []):
            if rt.get("id"):
                num_por_ruta[rt["id"]] = num

    # cliente -> conteo por vehiculo fijo (si quedo repartido gana el de mas visitas);
    # especiales y vehiculos genericos no actualizan habilidad
    conteos = {}
    for vis in visitas:
        num = num_por_ruta.get(vis.get("route"))
        if not num or num in _ESPECIALES_NUMS:
            continue
        cliente = _cliente_de_visita(vis)
        if not cliente:
            continue
        por_num = conteos.setdefault(cliente, {})
        por_num[num] = por_num.get(num, 0) + 1

    pares = [
        {"cliente": c, "habilidad": max(nums, key=nums.get)}
        for c, nums in conteos.items()
    ]
    if not pares:
        render_tip(
            "Ninguna visita del plan quedó en un vehículo fijo R#####-MX## "
            "con cliente en Notas — no hay habilidades que actualizar.",
            warning=True,
        )
        return

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(render_stat(len(visitas), "Visitas en la fecha"), unsafe_allow_html=True)
    with col2:
        st.markdown(render_stat(len(pares), "Clientes a actualizar"), unsafe_allow_html=True)

    supabase = _get_supabase_client()
    _aplicar_rotacion_habilidades(
        supabase, pares, agencia,
        nota_exito=f"<strong>{agencia}</strong> · plan {fecha_str}",
    )


def _seccion_asignar_vehiculos():
    render_label("Cuenta")
    cuenta = st.radio(
        "Cuenta",
        ["Tláhuac", "Monterrey"],
        horizontal=True,
        key="avp2_cuenta",
        label_visibility="collapsed",
    )
    token_key = "token_tlahuac" if cuenta == "Tláhuac" else "token_monterrey"
    try:
        token = st.secrets["cuentas_unilever"][token_key].strip()
    except Exception:
        render_tip("Token no configurado en secrets.", warning=True)
        return

    render_label("Fecha del plan")
    fecha = st.date_input(
        "Fecha del plan",
        value=date.today(),
        key="avp2_fecha",
        format="DD/MM/YYYY",
        label_visibility="collapsed",
    )
    fecha_str = fecha.strftime("%Y-%m-%d")

    if cuenta == "Tláhuac":
        render_label("Vehículos activos este día")
        activos_txt = st.text_area(
            "Vehículos activos",
            placeholder="Un vehículo por línea\nEj: R20020-MX01 ó 20020\nVacío = toda la flota R#####-MX## de la cuenta",
            key="avp2_activos",
            label_visibility="collapsed",
            height=120,
        )
        nums_activos = {n for line in activos_txt.splitlines() if (n := _extraer_num_vehiculo(line))}
    else:
        render_label(f"Cuántas rutas (max {len(RUTAS_MONTERREY)})")
        n_rutas = st.number_input(
            "Rutas",
            min_value=1,
            max_value=len(RUTAS_MONTERREY),
            value=min(18, len(RUTAS_MONTERREY)),
            key="avp2_n_rutas",
            label_visibility="collapsed",
        )
        nums_activos = {n for v in RUTAS_MONTERREY[:int(n_rutas)] if (n := _extraer_num_vehiculo(v))}

    if nums_activos:
        render_tip(
            f"<strong>{len(nums_activos)}</strong> vehículos activos para el match: "
            + ", ".join(f"<code>{_ruta_nombre(n)}</code>" for n in sorted(nums_activos))
        )

    if st.button("Leer plan y proponer asignación", use_container_width=True, key="avp2_btn_leer"):
        for k in ("avp2_propuestas", "avp2_flota", "avp2_usados", "avp2_conductores", "avp2_fecha_leida"):
            st.session_state.pop(k, None)

        loader = st.empty()
        _render_loader(loader, "Leyendo plan...", fecha_str)
        vehiculos_plan, err = _fetch_vehiculos_plan(token, fecha_str)
        if err or not vehiculos_plan:
            loader.empty()
            st.error(f"No se pudo leer el plan: {err}" if err else "El plan no tiene rutas en esa fecha.")
            return

        _render_loader(loader, "Consultando visitas...", fecha_str)
        visitas, err = _fetch_visitas_fecha(token, fecha_str)
        if err:
            loader.empty()
            st.error(f"Error al consultar visitas: {err}")
            return

        _render_loader(loader, "Consultando flota...")
        flota, err = _fetch_flota(token)
        if err or not flota:
            loader.empty()
            st.error(f"Error al consultar la flota: {err}" if err else "La cuenta no tiene vehículos R#####-MX##.")
            return
        if nums_activos:
            sin_flota = sorted(nums_activos - set(flota))
            flota = {n: v for n, v in flota.items() if n in nums_activos}
            if sin_flota:
                render_tip(
                    "Vehículos activos que no están en la flota de Simpli (se ignoran): "
                    + ", ".join(f"<code>{_ruta_nombre(n)}</code>" for n in sin_flota),
                    warning=True,
                )
        if not flota:
            loader.empty()
            st.error("Ningún vehículo activo está en la flota de Simpli.")
            return
        conductores = _fetch_conductores(token)

        clientes = sorted({c for vis in visitas if (c := _cliente_de_visita(vis))})
        _render_loader(loader, "Consultando planeación...", f"{len(clientes):,} clientes")
        supabase = _get_supabase_client()
        lookup = _fetch_planeacion_smart(supabase, clientes)
        loader.empty()

        propuestas, usados = _proponer_asignacion(vehiculos_plan, visitas, lookup, flota)
        st.session_state["avp2_propuestas"] = propuestas
        st.session_state["avp2_flota"] = flota
        st.session_state["avp2_usados"] = sorted(usados)
        st.session_state["avp2_conductores"] = conductores
        st.session_state["avp2_fecha_leida"] = fecha_str

    _subseccion_propuesta(token, fecha_str)

    st.markdown("---")
    render_label("Actualizar habilidades desde el plan")
    render_tip(
        "Cuando el plan quede final (vehículos asignados y ajustes manuales hechos), "
        "esto lee el plan de la fecha directo de la API y guarda en la planeación la ruta "
        "donde quedó cada cliente (rotación: la nueva entra a <code>habilidad_1</code>). "
        "Especiales y vehículos genéricos se omiten; los clientes nuevos se registran solos."
    )
    if st.button("Actualizar habilidades desde el plan", use_container_width=True, key="avp2_btn_feedback"):
        _actualizar_habilidades_desde_plan(token, fecha_str, cuenta)


def _subseccion_propuesta(token, fecha_str):
    propuestas = st.session_state.get("avp2_propuestas")
    if not propuestas:
        render_tip(
            "Rutea libre en Simpli (sin habilidades) y, con el plan creado, pulsa "
            "<strong>Leer plan y proponer asignación</strong>: cada ruta se cruza con la "
            "planeación por el campo <em>Notas</em> (cliente) y se propone el vehículo fijo "
            "con mayor % de coincidencia (asignación 1 a 1, gana el % más alto). "
            "Las rutas de especiales 1001FM/1001EV no se tocan."
        )
        return

    if st.session_state["avp2_fecha_leida"] != fecha_str:
        render_tip("La fecha cambió desde la última lectura — vuelve a leer el plan.", warning=True)
        return

    flota = st.session_state["avp2_flota"]
    usados = set(st.session_state["avp2_usados"])
    conductores = st.session_state["avp2_conductores"]

    def _nombre_conductor(num):
        d_id = flota[num]["driver_id"]
        return conductores.get(d_id, "—") if d_id else "—"

    sin_match = [p for p in propuestas if not p["bloqueo"] and not p["propuesto"]]
    n_con = sum(1 for p in propuestas if p["propuesto"])
    n_bloq = sum(1 for p in propuestas if p["bloqueo"])

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(render_stat(len(propuestas), "Rutas en el plan"), unsafe_allow_html=True)
    with col2:
        st.markdown(render_stat(n_con, "Con propuesta"), unsafe_allow_html=True)
    with col3:
        st.markdown(
            render_stat(len(sin_match), "Sin propuesta",
                        style="background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);"),
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(render_stat(n_bloq, "Bloqueadas (especial/fija)"), unsafe_allow_html=True)

    filas = []
    for p in propuestas:
        if p["bloqueo"]:
            prop, conductor, match = f"({p['bloqueo']})", "—", "—"
        elif p["propuesto"]:
            prop = flota[p["propuesto"]]["name"]
            conductor = _nombre_conductor(p["propuesto"])
            match = f"{p['pct'] * 100:.0f}% ({p['votos_num']}/{p['clientes']})"
        else:
            prop, conductor, match = "—", "—", "—"
        filas.append({
            "Vehículo actual": p["veh_actual"],
            "Conductor actual": p["driver_actual"],
            "Vehículo propuesto": prop,
            "Conductor propuesto": conductor,
            "% match": match,
            "Clientes": p["clientes"],
            "Visitas": p["visitas"],
        })
    render_label("Propuesta de asignación")
    st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)

    manuales = {}
    sobrantes = sorted(n for n in flota if n not in usados and n not in _ESPECIALES_NUMS)
    if sin_match and sobrantes:
        render_label("Rutas sin propuesta — asignación manual (opcional)")
        opciones = [_SIN_ASIGNAR] + [flota[n]["name"] for n in sobrantes]
        for p in sin_match:
            sel = st.selectbox(
                f"{p['veh_actual']} — {p['visitas']} visitas, {p['clientes']} clientes",
                opciones,
                key=f"avp2_manual_{p['uuid']}",
            )
            if sel != _SIN_ASIGNAR:
                manuales[p["uuid"]] = _extraer_num_vehiculo(sel)

        elegidos = list(manuales.values())
        duplicados = {n for n in elegidos if elegidos.count(n) > 1}
        if duplicados:
            render_tip(
                "Hay vehículos repetidos en la asignación manual: "
                + ", ".join(flota[n]["name"] for n in sorted(duplicados)),
                warning=True,
            )
            return

    cambios = [
        {"uuid": p["uuid"], "veh_actual": p["veh_actual"], "num": num}
        for p in propuestas
        if not p["bloqueo"] and (num := p["propuesto"] or manuales.get(p["uuid"]))
    ]
    if not cambios:
        render_tip("No hay cambios por aplicar — ninguna ruta tiene vehículo propuesto o manual.")
        return

    if st.button(
        f"Aplicar asignación en SimpliRoute ({len(cambios)} rutas)",
        type="primary", use_container_width=True, key="avp2_btn_aplicar",
    ):
        _aplicar_asignacion(token, st.session_state["avp2_fecha_leida"], cambios, flota)


def pagina_asignacion_fija_uni_2():
    render_header("Asignacion Fija Uni 2", "Smart Route — asignacion de vehiculos Unilever")
    render_guide(
        [
            "Rutea libre en Simpli (vehículos genéricos, sin zonas ni habilidades); las especiales 1001FM/1001EV ya van asignadas desde el ruteo.",
            "Indica los vehículos activos del día: listado en Tláhuac, cantidad de rutas en Monterrey.",
            "Leer plan: cruza el campo Notas (cliente) contra la planeación y propone el vehículo fijo con mayor % de match (asignación 1 a 1).",
            "Aplicar: actualiza vehículo y conductor de cada ruta vía PUT.",
            "Con el plan final, Actualizar habilidades desde el plan: guarda la rotación en Supabase; los clientes nuevos se registran solos.",
        ],
        "El proceso original (Asignacion Fija Uni) queda intacto como respaldo.",
    )
    _seccion_asignar_vehiculos()
