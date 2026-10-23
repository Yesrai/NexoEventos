# Failover Multi-AZ de la RDS de V1 — 2026-10-23 (UTC)

Una sola ejecución de `scripts/cloud/rds-failover-test.py --execute` (sin reintentos). Datos crudos: `resultado.json`, `healthz-1s.json`, `rds-2s.json`, `preflight.json`.
Snapshot manual previo: `nexoeventos-academy-prefailover-20261023t0105z` (available, 69 s). Sin usuarios ni transacciones abiertas en el preflight (1 sesión inactiva del pool de la API).

## Tiempos medidos
- `reboot-db-instance --force-failover` aceptado: 01:08:51.6–01:08:52.5 (estado `rebooting`).
- Eventos RDS: failover iniciado 01:08:57.2, instancia reiniciada 01:09:13.7, failover completado 01:09:37.0.
- **PostgreSQL desde la EC2 (`select 1`/1 s):** caída 01:08:57.3 → 01:09:10.5 (12 fallos); primer éxito 01:09:11.5. **Interrupción ≈ 14 s.**
- **`/healthz` público (1 s):** 000 (timeout 5 s) a 01:08:57.7; 503 de 01:09:02.7 a 01:09:09.8; 200 desde 01:09:10.8. **Interrupción ≈ 13 s.** La API recuperó la conexión sin reiniciarla.
- Anomalía sin explicar: 2 timeouts aislados de `/healthz` (código 000, 3 s) a 01:09:50.9 y 01:09:57.9, con PostgreSQL ya disponible. No se investigó la causa (no es atribuible con los datos recogidos).
- API de RDS: `rebooting` 01:08:52 → `available` 01:09:55 (63 s). El cambio de AZ primaria apareció en `describe-db-instances` recién en la muestra de 01:12:36 (el script dio por "recuperado estable" 01:12:38 por ese retraso de metadatos, no por el servicio, que ya estaba sano desde ~01:09:11).
- Zona primaria: us-east-1b → **us-east-1a**; secundaria us-east-1a → us-east-1b.

## Integridad
Huella idéntica antes/después: reservations 135 (md5 cbe0c1c2…), tickets 135, users 25, events 35 (md5 0733e3db…), access_logs 9, alembic 0008.

## Limitaciones
Muestreo de 1 s; la sonda de PostgreSQL corre en la EC2 y la de `/healthz` en la estación local (relojes distintos, diferencia ≤ ~1 s). Una sola ejecución; sin carga de usuarios. Mide caída de lectura (`select 1` y readiness), no escrituras concurrentes.

## Apagado
- EC2 V1: `stopped` confirmada por el script a las 01:54:00Z.
- RDS: `stop-db-instance` aceptada (respuesta `stopping`). El token del laboratorio expiró durante la espera (`ExpiredToken`); tras renovar la sesión (2026-10-23 ~13:00 UTC) se verificó RDS `stopped` (Multi-AZ conservado).
- EC2 V1 se encendió sola con el reinicio del laboratorio (12:58 UTC), sin tareas activas; se detuvo y quedó `stopped` a las 13:05:02Z.
- `cloud-session.sh stop` quedó esperando una confirmación interactiva y se canceló; el apagado se hizo con comandos directos autorizados.
