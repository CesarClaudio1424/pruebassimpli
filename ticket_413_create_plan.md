## Reporte: Error 413 Content Too Large al crear planes con 2200+ visitas (POST /v1/plans/create-plan/)

### Problema
Al guardar un plan en la plataforma con un volumen alto de visitas (>~95 rutas / ~2200 visitas), el endpoint `POST /v1/plans/create-plan/` rechaza el request con error **413 Content Too Large**. El usuario alcanza el final del flujo de planeación (vehículos → visitas → rutas → optimización) pero al hacer click en "Finish/Guardar" no puede persistir el plan. En la pestaña Network del navegador el response se muestra como 413 con Content-Length 578.

A nivel de transporte el comportamiento real es que el proxy/load balancer cierra la conexión SSL antes de devolver respuesta HTTP (`SSLError EOF`), lo que en cliente se manifiesta como 413. Esto explica también por qué "Copy as cURL" en DevTools devuelve vacío: el request nunca completó.

### Cuenta afectada
- **Cuenta:** Ransa El Salvador exclusivos (ID: 96737)
- **País:** SV
- **Plan/Fecha:** Plan "complementos prueba" con fecha destino 2026-05-16 (origen visitas 2026-05-14)
- **Total registros:** 2,257 visitas pending del visit_type `calleja_seco` (33715), distribuidas en 116 rutas usando flota CALLEJA SECO (46726)
- **Registros afectados:** Todos los planes que excedan ~20 MB de payload JSON. En esta cuenta, cualquier intento de guardar un plan con >95 rutas / >2200 visitas del tipo Calleja Seco

### Pasos para reproducir

1. **Consultar visitas pendientes (GET):**
   ```
   GET https://api.simpliroute.com/v1/routes/visits/paginated/
       ?page=1&page_size=500
       &planned_date=2026-05-14
       &status=pending
       &visit_types=33715
   Authorization: Token {API_TOKEN}
   ```
   Devuelve 2257 visitas paginadas. Promedio de 74 items por visita (167,242 items totales).

2. **Construir payload create-plan** con esas 2257 visitas distribuidas en 116 rutas de la fleet CALLEJA SECO (46726), con la misma estructura que el endpoint espera (visitas con items completos: id, status, visit, title, load, load_2, load_3, load_4, reference, notes, quantity_planned, quantity_delivered).

3. **Enviar POST:**
   ```
   POST https://api.simpliroute.com/v1/plans/create-plan/
   Authorization: Token {API_TOKEN}
   Content-Type: application/json;charset=UTF-8

   {
     "name": "...",
     "start_date": "2026-05-16",
     "end_date": "2026-05-16",
     "fleet": 46726,
     "routes": [ ...116 rutas con ~19-20 visitas cada una... ],
     "plan_metadata": {...}
   }
   ```
   Content-Length del request: **24.76 MB**

4. **Verificación en plataforma:** Reproducido desde el UI siguiendo: fecha planeación 16/05/2026, flota Calleja Seco con todos los vehículos, importar visitas pendientes del 14/05 visit_type Calleja Seco, modificar VH (00-12 y 12:01-23:59), prioridad media, skill SECO, click crear rutas, guardar como "complementos prueba".

5. **Resultado:** La conexión se cierra antes de respuesta HTTP. En navegador aparece como `413 Content Too Large`. El plan no se guarda y todo el trabajo de optimización (116 rutas calculadas) se pierde.

### Causa raíz

El proxy/load balancer frente al API tiene un límite de tamaño de body de aproximadamente **20 MB** (consistente con `client_max_body_size 20m` en nginx o configuración equivalente en Cloudflare/ALB). Bisección empírica del umbral:

| Rutas en payload | Tamaño | Resultado |
|---|---|---|
| 95 | 19.92 MB | ✅ Aceptado por proxy (backend responde con validación de contenido) |
| 96 | 20.13 MB | ❌ Conexión cerrada (sin response HTTP) |
| 100 | 20.88 MB | ❌ Conexión cerrada |
| 116 (real) | 24.76 MB | ❌ Conexión cerrada |

**Distribución del peso del payload** (analizado sobre las 2257 visitas reales):

| Componente | Tamaño | % del total |
|---|---|---|
| `items[]` dentro de visitas | 41.91 MB | **97.3%** |
| Resto de campos de visita | ~1.2 MB | 2.7% |

Dentro de `items[]`:
- `title` de los items: 7.13 MB (productos con nombres largos, ej. "483521C - CAFE INSTANTENEO NESCAFE LIST 60 S 1.7 g")
- `id`, `status`, `visit`: 1.44 MB cada uno
- `quantity_planned`, `quantity_delivered`, `reference`, `notes`, `load_*`: <1 MB cada uno

El endpoint exige los items completos al crear el plan aunque varios campos sean redundantes para el motor de ruteo (`quantity_delivered: 0`, `load_4: 0`, `status: pending` en visitas nuevas).

### Comportamiento esperado

1. El endpoint `POST /v1/plans/create-plan/` debería aceptar payloads de planes operativos reales del cliente. Con catálogos amplios (2200 visitas × 74 items) un payload de ~25 MB es razonable.
2. **Solicitud:** subir `client_max_body_size` del endpoint a **al menos 30 MB** (idealmente 50 MB para dar margen).
3. Adicionalmente, cuando se exceda el límite, devolver una respuesta HTTP 413 estructurada en lugar de cerrar la conexión SSL — eso permite al frontend mostrar un error claro al usuario en lugar de un fallo opaco.
4. (Mejora opcional) Revisar si el endpoint realmente necesita el array `items[]` completo en create-plan, o si bastaría con un resumen (count + load total) cuando los items ya existen en la BD.

### Evidencia

- **Screenshot original:** DevTools mostrando `POST create-plan/` con `413 Content Too Large`, Content-Length 578, planificador con 116 rutas / 116 vehículos usados.
- **Curl funcional de referencia:** Plan "PRUEBA 1" con 2 visitas creado exitosamente en la misma cuenta (~0.25 MB).
- **Pruebas de bisección reproducibles:** Scripts en `c:\Proyectos\Edicion\test_413_*.py` que consultan, arman y envían payloads de distintos tamaños. Las pruebas de bisección usaron payloads con `name=""` para evitar crear planes reales — el backend responde `{"name":["This field may not be blank."]}` cuando el tamaño está dentro del límite, lo que confirma que el rechazo a tamaños mayores ocurre antes de llegar al backend (en el proxy).
- **Datos de prueba en la cuenta:** Visit type `Calleja Seco` (33715), fleet `CALLEJA SECO` (46726) con 295 vehículos, skill `SECO` (95615), 2257 visitas pending del 2026-05-14.
