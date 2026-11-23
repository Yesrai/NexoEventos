# Entregable 3 · Prueba local de failover de aplicación (9-nov-2026)

Todo se ejecutó en la Mac de la usuaria con Docker. No se usó AWS, Azure, OCI ni Google Cloud; no hubo costos ni credenciales cloud; datos ficticios; sin commits ni push. Evidencia: `docs/entregable3/evidencias/local-20261109/` (`consola.txt`, `resultados.json`). Código: `scripts/failover-lab/`.

## 1. Qué se probó y qué NO
| Se probó | No se probó |
|---|---|
| Failover de la **aplicación** (2 copias del backend actual detrás de HAProxy) | Failover de la **base de datos** (hay una sola PostgreSQL compartida) |
| Reservas, sesiones y QR con conmutación de instancia | Replicación entre sitios: **RPO no medido; no se declara RPO cero** |
| Caída de la BD: la app no conmuta y se recupera sola | Latencia, red ni DNS reales entre AWS y OCI |

## 2. Montaje
- Proyecto Compose aislado `nexo-failover-lab`: `db` (postgres:18, volumen propio, puerto 127.0.0.1:55433), `app-aws` (18001), `app-oci` (18002), `haproxy` (18080; estadísticas 18404). Imagen del backend ya construida (`nexoeventos-dev-backend:latest`), sin reconstruir. No se tocaron contenedores ni volúmenes de otros proyectos.
- HAProxy: `GET /health` cada 1 s, `fall 2`, `rise 3`, `on-marked-down shutdown-sessions`, `retries 1`, `option redispatch`, `timeout connect 1s`. `aws` principal, `oci` respaldo (activo-pasivo). La configuración va embebida en `compose.yml` (Docker Desktop no deja montar archivos de esa carpeta).
- Clave Fernet aleatoria en `work/failover-lab/key.env` (ignorada por Git). Datos: eventos ficticios 990001 (40 asientos) y 990002 (general).

## 3. Cómo repetirla
```bash
scripts/failover-lab/lab.sh up
scripts/failover-lab/psql.sh -f - < scripts/failover-lab/seed.sql      # solo la primera vez
python3 scripts/failover-lab/failover_test.py --out docs/entregable3/evidencias/local-AAAAMMDD --runs 5
scripts/failover-lab/lab.sh down                                       # borra solo este laboratorio (contenedores y volumen)
```
Duración: unos 20 minutos. `--only T1,T3` ejecuta escenarios sueltos.

## 4. Resultados reales (16 de 16 comprobaciones OK)
### T1 caída dura (`docker kill` de app-aws) y T2 congelación (`docker pause`), 5 repeticiones cada una, ≈ 20 solicitudes/s
Tiempos contados desde justo antes de la orden docker (criterio conservador).

| Métrica | T1 kill (mín / mediana / máx) | T2 pause (mín / mediana / máx) |
|---|---|---|
| Solicitudes fallidas (de ≈ 430) | 4 / 8 / 9 | 8 / 8 / 8 |
| Tasa de éxito | 97,9 / 98,1 / 99,1 % | 98,1 / 98,1 / 98,1 % |
| HAProxy marca `aws` caído | 1,7 / 3,1 / 3,3 s | 3,1 / 3,3 / 3,3 s |
| Último error tras la falla | 0,25 / 2,2 / 2,3 s | 2,2 / 2,2 / 2,3 s |
| Mayor silencio entre respuestas exitosas | 1,6 / 3,1 / 3,3 s | 3,1 / 3,2 / 3,3 s |
| Retorno automático a `aws` tras reiniciarla | 2,6 / 2,9 / 3,2 s | 1,2 / 1,3 / 1,5 s |

Errores observados: `RemoteDisconnected` (cortes por `shutdown-sessions`), `TimeoutError` (cliente de 2 s) y un 502 aislado. **Conclusión medida:** la interrupción visible ronda 2–3,3 s con ≈ 2 % de solicitudes fallidas; las lecturas pasan a `oci` sin intervención. Esto cumple "≤ 10 s" **para este montaje local y solo lectura**; no se extrapola a AWS–OCI reales. Con `timeout connect` y `retries` más ajustados la ventana podría reducirse (no medido).
Nota: el retorno a `aws` es automático porque HAProxy trata `oci` como `backup`; en el diseño real el retorno debe ser planificado.

### T3 escrituras durante la caída
60 clientes, 40 cupos, `aws` muerta a 1,0 s: 40 aceptadas, 20 rechazadas por agotado (409), 0 sin respuesta, 57 reintentos (34 clientes) con la **misma Idempotency-Key**, 26 atendidas por `aws` y 14 por `oci`; BD: 40 reservas, 40 entradas, `reserved_count` 40, 0 clientes duplicados → **sin sobreventa ni duplicados**.
T3b: reserva creada en `aws` (201); tras la caída el reintento con la misma clave llegó a `oci` (200, misma reserva, tras 2 errores transitorios 503 y corte); 1 sola reserva en la BD. La sesión creada en `aws` siguió válida en `oci` (sesiones en PostgreSQL).
**Límite:** no se forzó el caso "la instancia confirma en la BD y muere antes de responder"; la idempotencia lo cubre por diseño, pero no se provocó de forma determinista.

### T4 y T5
- Mismo asiento disputado por 8 clientes repartidos entre las dos instancias: 1 ganador (201), 7 × 409, 1 entrada en BD.
- QR emitido en `aws`, leído y validado en `oci` (200); repetición en `aws` rechazada (409); 1 entrada marcada usada.

### T6 caída de PostgreSQL (app ≠ base de datos)
Con la BD detenida: `/health` 200 y HAProxy mantiene ambas apps UP (**no conmuta**), `/ready` 503 y `/api/events` 500. **CORRECCIÓN (10-nov):** ese 500 NO lo produce el código actual. El laboratorio usó la imagen `nexoeventos-dev-backend:latest`, construida el 22-oct, que no incluye los manejadores de errores de base de datos que el repositorio añadió después (commit `ca983f1`); con el código actual del repositorio las pruebas devuelven 503 (ver `04-prueba-replicacion-failover-bd.md`, etapa E). El 401 de `/api/auth/session` tampoco era un fallo: se llamó sin cookie y la aplicación responde 401 antes de consultar la base.

## 5. Hallazgos para la aplicación (sin modificar código)
1. ~~Con la BD inaccesible `/api/events` devuelve 500~~ **Retirado (10-nov): era un artefacto de la imagen antigua del laboratorio, no un defecto del código actual.** Con el código actual del repositorio, la BD inaccesible produce 503 en lecturas y escrituras (`/health` sigue en 200).
2. `/health` (liveness) no refleja la BD a propósito: sirve para conmutar app, no para conmutar base.

## 6. Qué falta para un failover real AWS ↔ OCI
1. **Base de datos:** réplica lógica asíncrona RDS → PostgreSQL en OCI (grupo de parámetros propio, reinicio, relé en la VPC, control de slots y disco), con RPO medido; o Patroni si se exige RPO ≈ 0 (no probado).
2. **Promoción y regla de escritor único:** endpoint `/role` y enrutamiento por rol, para no escribir en dos bases (split-brain). Sin esto un failover automático de BD es inseguro.
3. **Gateway redundante** (≥ 2 instancias, 2 zonas/nubes) con TLS y dominio; hoy es un solo HAProxy local.
4. **Decisión externa:** sondas independientes (Azure/OCI) y quórum; DNS o balanceador que apunte al gateway.
5. **Secretos y configuración:** `TICKET_ENCRYPTION_KEY` y `SECURITY_HASH_KEY` idénticas en ambos sitios; `FRONTEND_ORIGINS`/cookies seguras.
6. **Sincronía de esquema** (Alembic) y de secuencias; la réplica lógica no copia DDL ni secuencias.
7. **Reintentos del cliente** con Idempotency-Key ante 5xx/cortes (el frontend debe hacerlo; no se verificó aquí).
8. **Failback planificado**, runbook y pruebas repetidas con medición sobre infraestructura real.

## 7. Estado del laboratorio
Los contenedores del laboratorio quedan encendidos hasta ejecutar `lab.sh down` (solo borra `nexo-failover-lab`). Imagen descargada: `haproxy:lts-alpine`.
