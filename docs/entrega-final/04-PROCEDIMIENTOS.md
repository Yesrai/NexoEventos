# 04 · Procedimientos técnicos y operativos

Todos los procedimientos que tocan una nube requieren **autorización específica de la propietaria** (frase exacta, una sola ejecución) y se ejecutan con criterios escritos antes (`ops_center/criterios/T*.json`). Este documento **no** autoriza nada. Procedimientos detallados previos: `docs/evidencias/PROCEDIMIENTOS-T2-T4.md`, `docs/evidencias/PLAN-PRUEBAS-OBLIGATORIAS-CLOUD.md`, `docs/entregable3/20-procedimientos-cloud-pendientes.md`.

## 1. Reglas comunes de toda ventana en nube

1. **Antes:** tarjeta de autorización con alcance, techo de costo (USD 1,5), plazo y regla de aborto; plan Terraform guardado y aceptado por el revisor del escenario; lectura de solo lectura del inventario previo; reloj sincronizado.
2. **Durante:** expediente en `work/evidencias/<T>-<UTC>-<id>/` con `umask 077`; marcas UTC con milisegundos; ninguna URL de PAR, token o credencial en archivos.
3. **Después:** limpieza con guarda; inventario posterior de solo lectura comparado con el previo; manifiesto SHA-256 verificado; veredicto calculado por el recolector (no editado a mano); un FAIL se conserva y no se repite sin nueva autorización.

## 2. Procedimientos operativos ya ejecutados (referencia)

| Procedimiento | Pasos clave | Evidencia |
|---|---|---|
| Ventana AWS con RDS | `rds-window.sh chain` (watchdog de parada), plan revisado, apply, pruebas, limpieza (ASG 0, ALB eliminado, RDS `stopped` verificada) | T5 |
| Reconstrucción en OCI | apply (11) → `quiesce-vm.sh` → `ensure-swap.sh` → `safe-dnf.sh` → PostgreSQL → descarga y verificación SHA-256 → descifrado CMS → restauración → humo (fase A, solo lectura) → fase B funcional en copia desechable → destroy con guarda | T3 intento 3 |
| Cambio de DNS de pruebas | 3 negativos de seguridad → plan → apply A→B → verify en 3 resolvedores → intento inmediato rechazado (300 s) → rollback → verify | T2 |
| Ventana Azure | encender VM → NTP → sondas → pruebas → retirar artefactos temporales → desasignar y restaurar el apagado automático exacto | T4, T5 |
| Prueba del lease | lectura previa → 3 PAR temporales → CAS y carrera de lease → revocación → verificación 401 → lectura posterior | T1 |

## 3. Secuencia de respaldo fresco para T6 (DISEÑO — no ejecutada)

Objetivo: que **ninguna reserva confirmada** quede fuera del respaldo usado, y medir un **RPO real**. Hoy el último respaldo tiene ≈ 93 h, por lo que el criterio `rpo_s ≤ 5400` fallaría (`docs/evidencias/T6-PREPARACION-SOLO-LECTURA.md` §4).

| Paso | Acción | Verificación | Marca UTC a registrar |
|---|---|---|---|
| 0 | Precondiciones: RDS disponible, EC2 de V2 con `backup_cycle.py`, PAR **nuevo** de escritura sin sobrescritura en OCI, compuerta desplegada (D1) | `rds-window.sh check`; plan revisado | `t_pre` |
| 1 | **Congelar escrituras** en AWS: compuerta `WRITE_GATE_MODE=enforce` sin lease ⇒ las rutas de escritura responden 503/403 | Verificación por efecto: un intento de reserva **no** devuelve 201 | `t_freeze` |
| 2 | **Drenar**: esperar a que terminen las transacciones en curso; comprobar 0 transacciones de escritura abiertas en RDS | `pg_stat_activity` sin escrituras activas; contador de reservas estable dos lecturas seguidas | `t_drain` |
| 3 | **Respaldo final**: `pg_dump -Fc` de RDS | tamaño, firma `PGDMP`, huella de datos (10 claves) | `t_dump` |
| 4 | **Cifrar y verificar**: CMS AES-256 con el certificado público; SHA-256; manifiesto; ningún texto plano en disco | descifrado de prueba en memoria; SHA-256 coincide | `t_enc` |
| 5 | **Subir a OCI** con `If-None-Match` (sin sobrescritura) y revocar el PAR | descarga y SHA-256 en OCI; PAR → 401 | `t_up` |
| 6 | **Restaurar en OCI** (standby) | SHA-256 OK, conteos (reservas/tickets) y 10/10 huellas **iguales a los del paso 3** | `t_restore` |
| 7 | **Verificar datos**: la última reserva confirmada antes de `t_freeze` existe en OCI | consulta por id / huella | `t_verify` |
| 8 | **RPO real** = `t_freeze − marca de la última escritura incluida` (debe ser 0 reservas confirmadas perdidas); **edad del respaldo** = `t_switch − t_dump` para el criterio `rpo_s` | cálculo en el expediente | — |

**Decisión pendiente (declarada):** si el congelamiento (pasos 1–2) cuenta dentro del RTO. La propuesta es medir y reportar ambos: RTO desde la inyección del fallo y duración de la congelación.

## 4. Flujo T6 previsto (DISEÑO, BLOCKED)

Etapas del orquestador (`scripts/multicloud/failover/orchestrator.py`): `PRECHECK → DECIDE → PREPARE_STANDBY → FENCE_AND_ACQUIRE → FENCE_CHECK → HEALTH_GATE → ENABLE_STANDBY → SWITCH_DNS → VERIFY`; antes, T6.0 (ensayo en seco con adaptadores reales en `dry_run`), y después, failback manual (vallar primero el escritor de OCI). Cada etapa y su barrera: `diagramas/04-flujo-t6-previsto.svg`. **Reglas:** cancelar tras el lease y antes de `ENABLE_STANDBY` deja cero escritores nuevos; si el standby no está listo, `HEALTH_GATE` aborta, libera el lease y no toca el DNS.

**Regla de parada (de la preparación de T6):** si a la hora límite no constan con evidencia real G2–G6, G9 y el cierre de B-T6-1/D1–D8, T6 **no se ejecuta** y queda como pendiente obligatorio con su causa.

## 5. Procedimientos de cierre T8 (pendientes de ejecución)

1. Inventario de solo lectura en AWS, OCI y Azure (criterios `ops_center/criterios/T8.json`).
2. Revocar tokens del centro, tokens temporales y regenerar el token de DuckDNS.
3. Generar el paquete cifrado nuevo de reconstrucción, copiarlo a Drive/OneDrive y reverificarlo (como en `docs/evidencias/20261122-copia-externa-respaldo/resultado.md`).
4. Custodiar `work/evidencias/` con su manifiesto (sin secretos en Git).

## 6. Procedimientos locales (sin nube) — reproducibles

Ver `10-DEMO.md` (comandos exactos de pruebas y demo de NexoOps).
