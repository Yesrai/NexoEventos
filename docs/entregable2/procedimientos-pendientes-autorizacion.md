# Pruebas y evidencias que requieren AWS o Azure — procedimientos listos (NO ejecutados)

Todo lo siguiente **necesita autorización explícita** de la propietaria antes de ejecutarse. Ninguna de estas pruebas se ha realizado; cada una indica qué sección y criterio del Entregable 2 mejora. Costos: estimaciones con tarifa pública (fuentes en la sección 18 del informe), no facturación observada. Reglas comunes: datos ficticios; `NEXO_ALLOW_CLOUD_CHANGES=YES` solo en la orden que lo exige; huella de datos antes y después; apagar al terminar y comprobar el estado final; sin secretos ni identificadores en las evidencias.

## Orden recomendado
| Sesión | Contenido | Costo extra | Cuándo |
|---|---|---|---|
| **AWS-1 (corta, solo lectura)** | **P0** + P1 + P2 + P8 + P9a (y, si se autoriza, reiniciar el reloj de la RDS) | ≈ 0 (sin encender recursos de cómputo) | **Antes del 30-oct** (reinicio automático estimado de la RDS) y **antes del 3-nov** (series de 1 min de CloudWatch) |
| **Azure-2** | P5 | ≈ 0,12 USD/h (≈ 0,5 USD para 4 h) | Cuando haya tiempo; no urgente |
| **AWS-3** | P3 + P4 (V2 con captura de consola y fallos) | ≈ 0,044/h (V1) y ≈ 0,11/h (V2): ≈ 1 USD en total | Después de AWS-1 |
| **AWS-4 (opcional)** | P6 recuperación completa en AWS | ≈ hasta 1,05 USD | Solo si se quiere acreditar el RTO en AWS |

> **Urgencia calculada:** la RDS quedó detenida el 23-oct (≈ 15:2x UTC, tras el respaldo). AWS la reinicia sola a los siete días: **≈ 30-oct**. Si ocurre, genera costo de Multi-AZ (≈ 0,036 USD/h) hasta detenerla. `[VERIFICAR con el estado real al iniciar el laboratorio]`.

---
## P0 · Sesión de AWS (bloqueo actual) — qué hay que autorizar
**Estado del 28-oct (19:5xZ):** el perfil `nexoeventos-lab` devuelve `ExpiredToken`; no se pudo consultar nada ([evidencia](../evidencias/multicloud/aws/20261028-estado-sin-sesion/resultado.md)). Para continuar con las verificaciones de solo lectura hacen falta, **en este orden y por separado**:
1. **Que la propietaria inicie el laboratorio (Start Lab) y renueve las credenciales** en su perfil (el agente no maneja credenciales). *Efecto conocido:* el 23-oct el reinicio del laboratorio encendió solo la EC2 de V1 (≈ 0,021 USD/h + IPv4 hasta detenerla). *Estimado de aviso:* el reinicio no cambia la parada de la RDS.
2. **Autorización para detener la EC2 de V1 si el laboratorio la enciende** (cambio de estado que reduce costo) — o que la propietaria la detenga en consola.
3. **Opcional, decisión de costo:** reiniciar el reloj de 7 días de la RDS con `start-db-instance` + `stop-db-instance` (≈ 6 min de arranque y ≈ 7 min de parada; ≈ 0,01 USD) **o** dejarla y aceptar un reinicio automático hacia el **30-oct 15:18Z** (≈ 0,86 USD/día hasta detenerla).
4. **Opcional, con cargo:** consultas de Cost Explorer (`ce`), ≈ 0,01 USD por solicitud (máx. 5 ≈ 0,05 USD). Alternativa sin cargo: captura manual del presupuesto de Academy.
Con la sesión activa, el agente solo ejecutaría: `python3 scripts/cloud/readonly-audit.py` (guarda en código que impide escrituras) y `python3 scripts/observability/export-cloudwatch.py` + `plot-cloudwatch.py` (solo lectura).

## P1 · Exportar las series de 1 minuto de CloudWatch (solo lectura)
- **Objetivo:** conservar copia de las métricas de V1 (19-oct), V2 (22-oct) y RDS Multi-AZ (23-oct) antes de que pierdan resolución. **Mejora:** secciones 16–17, criterio 5.
- **Requiere:** laboratorio activo (credenciales temporales). **No** enciende recursos.
- **Pasos:** ver [`cloudwatch-evidencia-prioritaria.md`](cloudwatch-evidencia-prioritaria.md) (§2): `export-cloudwatch.py --selftest` (ya pasa) y exportación a `work/observability/aws-cloudwatch.json`.
- **Verificación:** el script informa las series omitidas; contar puntos por ventana; confirmar que no hay identificadores de cuenta.
- **Riesgo:** al iniciar el laboratorio la EC2 puede arrancar sola (ocurrió el 23-oct): comprobar y detener.

## P2 · Capturas de consola e inventario textual (EV02–EV08)
- **Objetivo:** las capturas de VPC, subredes, rutas, SG, RDS (Multi-AZ), S3 y CloudWatch que faltan. **Mejora:** secciones 10, 14 y 17, criterios 3 y 5.
- **Pasos:** `./scripts/cloud/capture-inventory.sh` (inventario textual sanitizado) y las capturas manuales de [`procedimientos-sesion-cloud.md`](../operacion/procedimientos-sesion-cloud.md) §2.2 (la operadora tapa identificadores con rectángulos opacos; nunca desenfoque).
- **Verificación:** revisión a 200 % de cada captura; README de cada EV con fecha, servicio, configuración y resultado.
- **Costo:** 0 con EC2/RDS detenidas (se ven igual en consola).

## P3 · Pruebas de seguridad contra el sitio público de V1
- **Objetivo:** repetir en AWS la ráfaga de inicios de sesión (hoy solo local) y evidenciar el límite de intentos y los controles HTTP. **Mejora:** secciones 8 y 16, criterios 2, 3 y 5.
- **Requiere:** EC2 + RDS encendidas (≈ 0,044 USD/h; ≈ 0,1 USD para 2 h) y la versión con el semáforo desplegada.
- **Pasos:** `NEXO_ALLOW_CLOUD_CHANGES=YES ./scripts/cloud/cloud-session.sh start` → `scripts/cloud/verify-login-burst.py` (≤ 50 simultáneos; corte automático) y `scripts/cloud/verify-public-flow.py` → `cloud-session.sh check` y `stop`.
- **Evidencia:** resultado JSON/MD en `docs/evidencias/` (sin cookies ni tokens); huella previa y posterior idénticas.
- **Riesgo:** memoria de la `t3.small` (por eso el límite de 50 y los criterios de parada).

## P4 · Ventana de V2: captura de consola, fallos mejor medidos y zona
- **Objetivo:** (a) capturas de ALB, target group y ASG; (b) **disponibilidad de la API durante la caída** con rutas aleatorias (limitación de la sección 12); (c) pérdida de las instancias de **una zona**; (d) medir V2 con RDS Multi-AZ activa. **Mejora:** secciones 11–13 y 17, criterio 4.
- **Requiere:** `terraform plan` y `apply` solo de `infra/aws-v2` (21 recursos), AMI vigente, certificado importado en ACM (vence el 1-ene-2027) y el secreto de la aplicación; ≈ 0,11 USD/h (3 h ≈ 0,33 USD) más Multi-AZ.
- **Pasos:** preparación con `scripts/cloud/v2-prepare.sh`; validación `scripts/cloud/verify-v2-flow.py`; medición `scripts/cloud/run-k6-ladder-v2.py` y `v2-measure.py`; fallos con `scripts/cloud/v2-failover-test.py` (con rutas en orden aleatorio) y escalado con `run-scale-test-v2.py`; **destruir** con `terraform plan -destroy` revisado.
- **Criterios de parada:** errores 5xx inesperados, p95 de login > 3 s sostenido, CPU > 85 %, memoria < 300 MB, conexiones de RDS > 50.
- **Nota:** el generador está limitado a 50 usuarios; **no** permite demostrar 100–5 000.

## P5 · Segunda ventana de Azure (evidencias que faltan)
- **Objetivo:** (a) capturas de los paneles de Grafana y Zabbix (la operadora inicia sesión; el agente **no** escribe contraseñas por ella); (b) **entrega real de un correo de alerta** con el receptor ya verificado; (c) enlazar el agente de Zabbix a `127.0.0.1`; (d) opcional: probar las alertas de memoria y disponibilidad. **Mejora:** secciones 14, 16 y 17, criterios 3 y 5.
- **Pasos:** `scripts/observability/azure-set-shutdown-window.sh --hours 4` (**obligatorio**: la hora del auto-shutdown diario sigue siendo la del 28-oct) → `azure-window-preflight.sh` (exige GO) → arranque de la VM → `azure-verify-hostkey.sh` → Ansible → pruebas → `az vm deallocate` y `azure-verify-clean.sh --expect vm-off`.
- **Costo:** ≈ 0,12 USD/h; la carga de CPU de 20 min ≈ 0,04 USD.
- **Cierre:** solo se declara entregada la alerta cuando la operadora ve el correo en su buzón.

## P6 · Recuperación completa del servicio en AWS (DNS + HTTPS)
- **Objetivo:** cerrar T3/T4 del ensayo del 12-oct y medir un RTO del servicio completo en AWS. **Mejora:** sección 15, criterio 4.
- **Requiere:** `infra/aws-recovery` (11 recursos temporales), certificado y DNS; costo acotado ≈ hasta 1,05 USD; fase larga y con riesgo de sesión. **Mientras no exista**, la recuperación acreditada es la de OCI.

## P7 · Respaldo programado (RPO ≤ 24 h)
- **Estado:** el respaldo lógico cifrado es manual; **no hay programación**. **Diseño propuesto** (no implementado): temporizador `systemd` en la EC2 que ejecute el mismo flujo de `scripts/cloud/db-backup-cms.py` (volcado → CMS con certificado público → S3) y un verificador de antigüedad en `cloud-session.sh check`. **Mejora:** sección 15, criterio 4. Requiere desplegar con Ansible en una ventana de V1.

## P8 · Comprobaciones de solo lectura de identidad y registros
- `aws cloudtrail describe-trails` y `get-trail-status` (¿existe y registra?), `aws iam get-role` del rol de instancia y lista de políticas adjuntas, para sustituir los `[NO VERIFICADO]` de las secciones 07 y 09. **Mejora:** criterio 3. Costo 0; misma sesión AWS-1.

## P9 · Costos observados
- (a) AWS Academy: captura del presupuesto («Used $X of $50») y de la facturación si la consola lo permite. (b) Azure: `az rest` de Cost Management (`ActualCost`, mes hasta hoy) **48 h después** de la ventana del 28-oct (hoy devuelve 0 filas por retraso). **Mejora:** sección 18, criterio 5. Costo 0.

## P10 · Detalle de seguridad de AWS (solo lectura) — pendiente por sesión terminada
El 29-oct 01:37Z el rol del laboratorio dejó de autorizar consultas (`AccessDenied` incluso en `rds:Describe`): la sesión de Academy terminó. Con un laboratorio activo (iniciado por la propietaria), ejecutar **una vez** `python3 scripts/cloud/readonly-audit-detalle.py docs/evidencias/multicloud/aws/20261028-auditoria-solo-lectura` (solo `describe/get/list`; sin cargos; no enciende nada). Obtiene: documentos de las políticas de `LabRole`, `rds.force_ssl`, política del bucket, opciones de metadatos de la EC2 y detalle de la alarma. Si el laboratorio enciende la EC2 al iniciar, hay que detenerla (requiere autorización).

**P10 ejecutado el 29-oct 02:19Z**: ver `docs/evidencias/multicloud/aws/20261028-auditoria-solo-lectura/resultado.md` (adenda). Pendiente solo lo no legible (`VocLabPolicy1–3`).

## P11–P15 · Riesgos técnicos: lo corregido en local y lo que requiere autorización (29-oct)
| ID | Qué | Estado | Autorización / procedimiento seguro |
|---|---|---|---|
| P11 | TLS `verify-full` hacia RDS | **Implementado y probado en local** (52/52; prueba con CA propia). Sin desplegar | (1) Autorizar la descarga del paquete público de CA de RDS (≈ 160 KB) para revisarlo y fijar su SHA-256; (2) en una ventana con RDS encendida: instalar el paquete con `deploy/install-rds-ca-bundle.sh`, regenerar `backend.env`/`migration.env` con `bootstrap-rds-secrets.sh`, desplegar y verificar la conexión (`pg_stat_ssl`); reversión: restaurar las URL anteriores. Coste: el de la ventana de la RDS (≈ 0,03 USD/h) |
| P12 | Ciclo de vida de S3 (`database-backups/` → `backups/database/`) | Terraform local **ya corregido** (propuesta 0003) | `terraform plan` dirigido (lectura) y, con autorización, `apply` dirigido de 1 cambio; sin coste |
| P13 | CI sobre los cambios locales | Hay 31 ejecuciones reales (30 OK); los cambios locales (47 archivos) no se han ejecutado | Autorizar **commit y push** (o abrir un PR) para obtener una ejecución verificable; ninguna credencial de nube interviene |
| P14 | CloudTrail persistente | Ausente (verificado). Propuesta: 1 trail de gestión multi-región hacia un bucket S3 privado y cifrado con validación de integridad; los eventos de gestión del primer trail no cobran, el almacenamiento es mínimo | Crea recursos: requiere autorización y comprobar que Academy permite `cloudtrail:CreateTrail` (puede estar denegado) |
| P15 | Máximo de autoescalado de RDS = 20 GiB (aviso de AWS) | **Decisión deliberada** (propuesta 0002: sin autoescalado para acotar costos) | Sin acción; declararlo como límite |

### Pruebas pendientes: indispensables frente a opcionales
| Prueba | ¿Indispensable? | Por qué | Procedimiento seguro |
|---|---|---|---|
| Capturas manuales (CloudTrail, EC2, Azure, OCI) | **Sí** (evidencia, no prueba) | Cierran criterios 3 y 5 | Ninguna interacción con recursos |
| Lectura de permisos efectivos de `LabRole` (`iam simulate-principal-policy`) | **Sí** (solo lectura) | Distingue política de permiso efectivo | Con sesión de AWS activa; puede salir denegada |
| Paneles de Grafana/Zabbix y entrega real del correo de alerta | Recomendada | Única prueba de monitoreo pendiente | `azure-set-shutdown-window.sh --hours 2`, preflight, encender la VM, provocar alerta una vez, capturar, desasignar; ≈ 0,11 USD/h |
| Despliegue de `verify-full` en una RDS real (P11) | Opcional | Cierra la mejora de TLS; el diseño ya está probado en local | Ver P11 |
| Carga ≥ 100 usuarios, caída de AZ, **AWS FIS** | **No** | **Siguen NO EJECUTADOS**; se declaran como proyección/diseño | Plan en `plan-caos-fis.md` (redespliegue de V2, ≈ 0,5 USD, 3 h, reversión con `destroy` + `stop-db-instance`) |
| Recuperación completa en AWS (DNS + HTTPS) | No | Está acreditada en OCI; en AWS se declara incompleta | — |

## Advertencia sobre P12 (lifecycle de S3), 3-nov
Alinear el prefijo del lifecycle con `backups/database/` **con una retención de 7 días habría borrado los respaldos reales**. El código ya separa la retención de S3 (`s3_backup_retention_days`, 90 por defecto, mínimo 30) de la de RDS. Antes de aplicar P12: `terraform plan` y comprobar que la regla resultante es de ≥ 30 días sobre `backups/database/`.
