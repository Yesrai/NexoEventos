# Procedimiento T1–T8: pruebas obligatorias pendientes (rev. 2, 22-nov-2026)

**Borrador sin commit. NADA se ha ejecutado en ninguna nube.** Cada etapa pide su propia autorización específica (frase exacta) y tiene tope de gasto, hora límite, criterio de aceptación y rollback. Costos: tarifas públicas citadas en `entregable3/20`, **sin verificar con facturación**. Centro de operaciones: `docs/operacion/centro-operaciones-azure.md`.

## 0. Antes de empezar (D3, D4)
**Fecha tope de planificación:** las pruebas de AWS terminan **antes del 25-nov-2026 12:00 (Lima)**, con la limpieza hecha antes del vencimiento reportado (26-nov). El centro bloquea solicitudes cuando faltan < 12 h al vencimiento configurado (B03).
**D4 actualizado el 22-nov:** crédito de AWS Academy USD 50 / usado 27,30 / **restante 22,70**, indicador rojo (laboratorio no iniciado); **fecha de vencimiento aún sin confirmar**; OCI: límite `standard-e5-core-count` = 0 (probable fin del Free Trial). Detalle en `VENTANA-UNICA-AWS.md` §1.

**Dónde verificar tú misma el saldo y el vencimiento (no necesito tus credenciales):**
| Dato | Dónde mirar | Qué anotar |
|---|---|---|
| Saldo de AWS Academy | Canvas → tu curso → **Learner Lab** → al abrir/iniciar el laboratorio, el encabezado muestra el presupuesto («Used $X of $Y» / crédito restante) | Saldo y hora de la lectura; captura con fecha |
| Fecha de fin de Academy | Canvas → curso → **Inicio/Resumen** o **Configuración** (fechas del curso) y el aviso del docente; el Learner Lab no siempre muestra una fecha propia | Fecha exacta; si no aparece, pregúntala al docente y regístrala como «no verificada» |
| Vencimiento del Free Trial de OCI | Consola de OCI → menú de perfil (arriba a la derecha) → **Tenancy** / o **Governance & Administration → Billing & Cost Management → Subscriptions**; además, el banner superior de la consola indica «días restantes / crédito restante» | Fecha de vencimiento y crédito restante; si no se ve, «no verificado» |
| Crédito de Azure for Students | Portal de Azure → **Cost Management + Billing** → Credits (o la página de Microsoft Azure for Students) | Saldo restante |
La interfaz puede variar; si un menú no existe, anótalo y dímelo en lugar de adivinar. **Con esas lecturas se confirman fecha y saldo reales antes de ejecutar nada (D4).**
Si el saldo de Academy es < 5 USD o Academy vence antes del 25-nov, T5 y T6 **no se ejecutan** y quedan como pendientes obligatorios declarados, con su causa.

## 1. Orden y dependencias
L0 (hecho en local) → T1 → T2 → T3 → T4 → ventana AWS única (T5 → T6) → T7 → T8. T3 y T4 pueden ir el mismo día; T5/T6 solo si T1–T4 constan como PASS en el centro (barreras B06).

## 2. Etapas
### T1 · Lease real **por PAR** en OCI (la primera operación Cloud) — 0 USD — tarjeta completa en `PRIMERA-OPERACION-CLOUD.md`
- **Corrección de la rev. 2:** el adaptador real exige `lease.store = par-http` (`failover_config`), no la CLI. Por eso T1 usa `scripts/multicloud/hybrid/oci_par_probe.py` (PAR sobre un objeto exacto, ≤ 55 min, sin listado; CAS solo con la URL del PAR; revoca y limpia al final) y **no** crea el bucket/usuario IAM de `entregable3/20` §A (queda como alternativa descartada: añadía identidades sin servir a la configuración real).
- **Aceptación y registro:** plantilla `ops_center/criterios/T1.json`, recolector `python -m ops_center evidence-*`.
### T2 · Cambio real de DNS en `nexoeventos-test` — 0 USD
- **Autorización:** `AUTORIZO el cambio de DNS de prueba en nexoeventos-test`. Requiere subdominio de pruebas y dos IP inocuas; **jamás** `nexoeventos-demo`.
- **Pasos / aceptación / rollback:** `entregable3/20` §B (plan → apply → verify → rollback). Aceptación: propagación en los 3 resolvedores ≤ 3 × TTL, reversión correcta, token ausente de toda salida, segundo cambio inmediato rechazado por intervalo mínimo.
- **Registro:** `record-evidence T2`.
### T3 · VM de OCI con el respaldo del 11-nov, app y entrada pública con TLS (la «O1») — ≈ 0,10 USD (≈ 0,05 USD/h × 2 h)
- **Prerrequisitos:** saldo/trial confirmados; cuota de cómputo (el 10-nov varias formas estaban en 0; A1 sin capacidad el 23-oct). Si no hay cuota, T3 y T6 se bloquean y se declara.
- **Autorización específica** con tope: 0,30 USD en OCI y 3 h. Crea VM temporal con Terraform de `infra/oci`, IGW + IP pública solo con NSG a 443 y a la IP /32 de la operadora para administración; restaurar con `run-from-mac.sh` / `app-recovery.sh`.
- **Aceptación:** huella 10/10 idéntica a la línea base; `/livez` y `/api/events` 200 por HTTPS; compuerta del standby: escritura **503**; RTO de restauración medido.
- **Rollback:** destruir VM, IGW, IP y reglas con plan guardado (esperado: solo esos recursos); `verify_clean.py --live` en OCI. **Riesgo:** abrir entrada pública; se mantiene el NSG mínimo y se destruye al terminar.
- **Registro:** `record-evidence T3`.
### T4 · Azure en vivo: sondas y panel hacia V2 y OCI — ≈ 0,11 USD/h × 2 h + fijos (≈ 0,33–0,43 USD/día mientras existan los discos)
- **Autorización:** encender la VM `vm-nexoeventos-obs` (apagado automático 17:38 UTC ya configurado) y desplegar `ops_center` + recolector.
- **Pasos:** actualizar IP /32 del NSG si cambió; `init-identities`; servicio systemd; Nginx `/ops/`; sondas de Zabbix a `/livez` de V2 y de OCI; recolector que escribe `status/cloud-status.json`; paneles de Grafana (ya existentes) con series vivas.
- **Aceptación:** panel accesible desde Azure **con AWS apagado** (demuestra independencia); tarjetas de AWS, OCI y Azure con origen y hora; una alerta real disparada por una sonda que falla (apagar a propósito el servicio de OCI/AWS de prueba) con correo recibido; captura con barra de direcciones y fecha.
- **Rollback:** detener el servicio, desasignar la VM, restaurar el apagado automático (patrón ya usado el 4/5-nov, con `--expect vm-off`).
- **Registro:** `record-evidence T4`.
### T5 · Capacidad 1: caída de una EC2 con ALB + Auto Scaling (ventana AWS única) — ≈ 0,10–0,15 USD
- **Autorización** con tope **1,50 USD** y hora límite (como el 20-nov): `rds-window.sh chain` con watchdog; revisar que el plan sea exactamente «8 creaciones + 1 modificación» **o** adaptar el caso de reanudación (3 + 6) tras decidir la reconciliación de Terraform (`aws-v2-reconciliacion-terraform.md`).
- **Prueba:** con 2 instancias sanas, detener solo la API de **una** EC2 (inyección reversible); medir con sondeo de 1 s.
- **Criterios (escritos antes):** `/livez` ≥ 99 % durante la prueba; detección ≤ 30 s; instancia sustituida y sana ≤ 5 min; 0 pérdida de datos. Si hay 5xx, se reportan tal cual.
- **Rollback:** el ASG repone; si no, ASG a 0 y limpieza estándar.
### T6 · Capacidad 2: failover real controlado AWS → OCI — ≈ 0,25–0,5 USD (AWS 0,15 + OCI 0,10)
- **Prerrequisitos (todos; brechas G1–G8 de `docs/operacion/auditoria-adaptadores-failover.md`):** T1–T4 en PASS en el centro; fábrica de adaptadores reales revisada (G1); testigo desplegado (G3, decisión D6); sello en OCI (G4); compuerta `enforce` y vallado en AWS (G5); clave C-04 fuera del repositorio (G7); `failover_config` válida con dominio de pruebas; compuerta en `enforce` en AWS **y** OCI; solicitud `failover_aws_a_oci` **VALIDADA y APROBADA** por la propietaria; `NEXO_ALLOW_FAILOVER_EXECUTE=YES` en el ejecutor; archivo `autorizacion-T6.json` con la frase `AUTORIZO EL FAILOVER REAL AWS A OCI T6` y vigencia ≤ 6 h; **cableado de los adaptadores reales** (único cambio de código pendiente y deliberado; hoy `REAL_EXECUTION_WIRED=False`). Hasta cumplirlos, el centro y la CLI se niegan.
- **Secuencia:** `entregable3/20` §C.2 (línea base 201 en AWS / 503 en OCI → respaldo reciente → inyección de fallo en la app de AWS → orquestador: DECIDE (quórum), PREPARE_STANDBY, FENCE_AND_ACQUIRE (espera TTL + margen), ENABLE_STANDBY, SWITCH_DNS solo del subdominio de pruebas, VERIFY).
- **Aceptación:** un solo escritor en todo momento (**0 respuestas 201 de AWS tras la toma**), DNS cambiado solo tras lease + datos verificados + standby listo, RTO y RPO medidos y documentados, verificación **por efecto** de que AWS no escribe, sin pérdida de reservas confirmadas.
- **Rollback / failback:** **manual**, con vallado del escritor de OCI primero (`failback.py`); si hay cualquier duda, **apagar primero** (ASG a 0, RDS detenida, VM de OCI destruida) y depurar después. Si hay más de un escritor, la prueba se declara **FALLIDA**.
### T7 · Capacidad 3: flujo desde Azure — incluido en T4/T6
Demostrar de extremo a extremo: estado de las 3 nubes en el panel → solicitud de TI → validación → aprobación de la propietaria → ejecución humana de T6 → registro en auditoría. **Aceptación:** capturas con fecha y barra de direcciones; `verify-audit` íntegro; ninguna acción ejecutada por el centro.
### T8 · Cierre y limpieza — ≈ 0 USD
Apagar/destruir todo lo temporal, `verify_clean.py --live` en AWS y OCI, RDS detenida (anotar el reinicio automático a los 7 días), VM de Azure desasignada, revocar tokens/claves temporales, copiar el último hash de auditoría fuera del servidor, actualizar matriz/informe y generar el paquete cifrado nuevo (copiarlo a Drive/OneDrive y reverificar).

## 3. Costos y riesgos resumidos
| Concepto | Estimado | Tope propuesto |
|---|---|---|
| OCI (T3 + T6) | ≈ 0,20 USD | 0,30 USD |
| AWS (T5 + T6, una ventana) | ≈ 0,35–0,65 USD | 1,50 USD |
| Azure (T4, 2 h + fijos) | ≈ 0,22 USD + 0,33–0,43 USD/día | 1,00 USD |
| **Total** | **≈ 0,8–1,5 USD** | |
Riesgos principales: **doble escritor** (mitigado por lease + compuerta + vallado en la base + sello; si ocurre, FALLIDA); Academy expira o saldo insuficiente (bloquea T5/T6); cuota o trial de OCI vencido (bloquea T3/T6); tiempo (≈ 3 días útiles); error humano al cablear adaptadores (revisión de código antes de T6).

## 4. Calendario (ajustado; si no cabe, lo no ejecutado se declara pendiente obligatorio, no opcional)
| Día | Actividad |
|---|---|
| 22–23-nov | D4 (lecturas de saldo/fechas); revisión de L0; T1 y T2 con sus autorizaciones |
| 24-nov | T3 y T4; cableado y revisión de adaptadores para T6 |
| 25-nov (mañana) | Ventana AWS única: T5 → T6; T7; limpieza |
| 25–26-nov | T8, informe, paquete cifrado nuevo |
