# Reporte: POST /v1/routes/visits/ puede crear visitas sin devolver respuesta, causando duplicados en reintentos

## Problema
Al enviar `POST /v1/routes/visits/` con payloads de **500 visitas** (patrón estándar de integración corporativa), ocasionalmente el servidor cierra la conexión TCP **después** de commitear las visitas en BD pero **antes** de enviar la respuesta 201. El cliente recibe `RemoteDisconnected` / `ConnectionError` (no un código HTTP), por lo que **no puede distinguir** entre "el servidor nunca recibió el request" y "el servidor procesó exitosamente pero no pudo responder". Si el cliente reintenta asumiendo fallo, se crean visitas duplicadas.

## Clientes afectados
Este bug impacta a **todos los clientes corporativos que inyectan visitas en bloques de 500**, incluyendo:
- **Arca Perú**
- **Arca Ecuador**
- **Koandina**
- Cualquier otro cliente corporativo cuya integración use el patrón de 500 visitas por llamada a `POST /v1/routes/visits/`

## Cuenta de prueba (reproducción controlada)
- **Cuenta:** Julio Mares SR Team (ID: 56065)
- **Plan/Fecha:** 2026-04-23
- **Total registros:** ~20,000 visitas creadas en batches para pruebas de carga
- **Registros afectados:** batch de 1,000 visitas con refs `TEST-LOAD-0009502` a `TEST-LOAD-0010501` (el problema se presenta desde 500 visitas por llamada)

## Pasos para reproducir

1. `POST https://api.simpliroute.com/v1/routes/visits/` con array de **500 o más** objetos visita válidos (title, address, lat/lng, planned_date, reference). Ejemplo de un elemento:
   ```json
   {"title":"Prueba 9502","address":"Av Reforma 1, CDMX","latitude":19.4326,"longitude":-99.1332,"planned_date":"2026-04-23","reference":"TEST-LOAD-0009502"}
   ```
   Headers: `Authorization: Token <token>`, `Content-Type: application/json`. Timeout cliente: 600s.

2. El cliente recibe:
   ```
   requests.exceptions.ConnectionError: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
   ```
   Sin status code HTTP.

3. Verificación vía API (5 refs del batch "fallido"):
   ```
   GET /v1/routes/visits/reference/TEST-LOAD-0009502/  → count: 1
   GET /v1/routes/visits/reference/TEST-LOAD-0009800/  → count: 1
   GET /v1/routes/visits/reference/TEST-LOAD-0010000/  → count: 1
   GET /v1/routes/visits/reference/TEST-LOAD-0010200/  → count: 1
   GET /v1/routes/visits/reference/TEST-LOAD-0010501/  → count: 1
   ```

4. **Resultado:** el servidor sí creó las visitas del batch. La transacción en BD completó antes de la desconexión. El cliente, sin embargo, reporta el batch como fallido y — si tiene lógica de retry sobre `ConnectionError` — genera visitas duplicadas al reintentar.

## Causa raíz

- **POST no es idempotente**: el endpoint no acepta `Idempotency-Key` header ni ningún otro mecanismo server-side para deduplicar reintentos.
- **Desalineación entre timeout del LB/proxy y tiempo de procesamiento**: desde 500 visitas por batch, el balanceador o proxy intermedio puede cerrar la conexión antes de que el backend termine y escriba la respuesta 201. El commit en BD ya ocurrió.
- **Cliente sin visibilidad**: un `ConnectionError` en HTTP no distingue fase de escritura/lectura; el cliente no puede saber si el servidor procesó.
- **Única verificación disponible es cara**: el cliente tendría que hacer `GET /v1/routes/visits/reference/{ref}/` por cada reference del batch para saber qué se creó realmente. Para batches de 500, son 500 GETs adicionales.

Este es el escenario que está ocurriendo en producción con Arca Perú, Arca Ecuador, Koandina y otros corporativos: sus integraciones implementan retry ante `ConnectionError`/`Timeout` y terminan duplicando registros.

## Comportamiento esperado

Cualquiera de estas soluciones resolvería el problema (en orden de preferencia):

1. **Aceptar header `Idempotency-Key`** (estilo Stripe): el servidor guarda el hash del request por N minutos y en retries con el mismo key devuelve la respuesta original sin duplicar.
2. **Endpoint asíncrono** (`202 Accepted` con `job_id`): el cliente consulta `GET /v1/jobs/{id}` para saber el estado y los IDs creados.
3. **Aumentar timeout del LB/proxy** para que los POST con 500+ visitas tengan margen de responder.
4. **Documentar tamaño máximo seguro** de batch que garantice respuesta antes del timeout del LB, y devolver 413 Payload Too Large para batches mayores.

## Evidencia

- Log del script de carga (`_tmp_progreso.log`):
  ```
  OK  batch 8502-9501 (1000) | total creadas: 8000 | elapsed: 481.0s
  EXC batch 9502-10501: ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response'))
  OK  batch 10502-11501 (1000) | total creadas: 9000 | elapsed: 594.5s
  ```
- Verificación por referencia: 5/5 refs del batch "fallido" existen en el sistema (`count:1`).
- **Discrepancia cliente vs servidor al final de la prueba**:
  | Fuente | Cuenta |
  |---|---|
  | Cliente (script) reporta creadas OK | 19,000 (1 + 500 + 1,000 + 17,499) |
  | Servidor realmente tiene (`GET /v1/routes/visits/paginated/?planned_date=2026-04-23` → `count`) | **20,000** |
  | Diferencia | **1,000** — exactamente el batch "fallido" |

  Si el script hubiera implementado retry sobre `ConnectionError`, el servidor habría quedado con 21,000 visitas (1,000 duplicadas). Este es el escenario activo en producción con clientes corporativos.
- Contraste con el error original reportado por el usuario: `GET /v1/routes/visits/?planned_date=` devuelve HTTP 500 con HTML cuando la cuenta tiene >17k visitas. Este es un **problema distinto** (server error al serializar respuestas grandes) pero comparte causa: endpoints de SimpliRoute no están dimensionados para payloads/respuestas grandes.
