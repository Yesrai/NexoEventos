# Guía de capturas de consola (pantalla por pantalla)

Reglas: capturas **reales** hechas por ti; no las generes ni edites. Antes de guardar, tapa con un rectángulo opaco el **ID de cuenta, tu nombre/correo, IP públicas, ARN completos y claves**. Guárdalas en `docs/evidencias/capturas/<nube>/NN-descripcion.png` y dime los nombres para enlazarlas en §17. Estas capturas **no encienden nada** salvo donde se indica.

## Capturas indispensables (en este orden)
1. **A5** RDS (seguridad + disponibilidad) · 2. **A2** SG web (red) · 3. **A1** EC2/IMDSv2 · 4. **A10** ASG en CloudWatch (escalabilidad) · 5. **A11** 5xx del ALB (tolerancia a fallos) · 6. **A8** CloudTrail sin trails (control ausente, honesto) · 7. **B3** alerta de Azure disparada y resuelta (monitoreo). El resto es opcional.

## A. AWS Academy (lab activo; región us-east-1) — no requieren encender recursos
| # | Consola → ruta | Qué debe verse | Respalda |
|---|---|---|---|
| A1 | EC2 → Instancias → `nexoeventos-academy-app` → pestaña *Seguridad* y *Detalles* | Estado `Stopped`, rol IAM, grupo de seguridad y «IMDSv2: Required» | Criterio 3 |
| A2 | EC2 → Grupos de seguridad → `…web-sg` → *Reglas de entrada y salida* | 80/443 desde Internet, **sin puerto 22**; salida 5432 solo al SG de la base | Criterio 3 |
| A3 | EC2 → Grupos de seguridad → `…db-sg` → *Reglas de entrada* | 5432 solo desde el SG web | Criterio 3 |
| A4 | VPC → Subredes (filtrar `nexoeventos`) y Tablas de rutas de las subredes de datos | Subredes de datos sin ruta `0.0.0.0/0` | Criterio 3 |
| A5 | RDS → Bases de datos → `nexoeventos-academy-postgres` → *Configuración* y *Conectividad* | `Stopped`, Multi-AZ, cifrado habilitado, acceso público **No**, retención 7 días, protección contra borrado deshabilitada | Criterios 3 y 4 |
| A6 | RDS → *Snapshots* | Lista de manuales y automáticos | Criterio 5 |
| A7 | S3 → bucket `nexoeventos-academy-…` → *Permisos* y *Propiedades* | Bloqueo de acceso público activado, cifrado AES-256, versionado | Criterio 3 |
| A8 | CloudTrail → *Historial de eventos* y *Trails* | Historial con eventos; Trails vacío (evidencia honesta del control ausente) | Criterio 3 |
| A9 | CloudWatch → *Alarmas* → `…ec2-cpu-high` | Umbral 80 %, 0 acciones | Criterio 3 |
| A10 | CloudWatch → *Métricas → Todas* → buscar `GroupInServiceInstances`, rango 22-oct 14:00–18:00 UTC, resolución 1 min | Curva 0→2→3→2→0 **en la consola** (las métricas persisten aunque V2 esté destruida) | Criterio 4 |
| A11 | CloudWatch → Métricas → `ApplicationELB` → `HTTPCode_Target_5XX_Count` (Suma, 1 min, 22-oct 16:00–17:00 UTC) | Picos de 25 y 40 | Criterio 4 |
| A12 | CloudWatch → Métricas → `RDS` → `DatabaseConnections` (Máximo, 1 min, 22-oct) | Máximo 22 | Criterio 4 |
| A13 | IAM → Roles → `LabRole` → *Permisos* (si Academy deja verla) | Lista de políticas; si da «acceso denegado», captúralo: documenta el límite | Criterio 3 |

## B. Azure (portal, VM desasignada) — sin encender la VM
| # | Ruta | Qué debe verse |
|---|---|---|
| B1 | Grupo de recursos → Información general | Recursos del proyecto; VM *Deallocated* |
| B2 | NSG → Reglas de seguridad de entrada | 22/443 solo desde tu /32 (tapa la IP) |
| B3 | Monitor → Alertas → *Reglas de alerta* y *Todas las alertas* | `alerta-vm-cpu` **disparada y resuelta** el 28-oct, con hora |
| B4 | Monitor → Grupos de acción → `ag-nexoeventos-obs` | Receptor del correo (tapa la dirección) en estado habilitado |
| B5 | VM → Identidad y Control de acceso (IAM) → Asignaciones de roles | *Monitoring Reader* sobre el grupo de recursos |

## C. OCI (consola)
| # | Ruta | Qué debe verse |
|---|---|---|
| C1 | Almacenamiento → Buckets → `nexoeventos-recovery` → *Objetos* | Copias `.cms`, versionado activo |
| C2 | Identidad → Políticas (compartimento) | Política de solo lectura/subida de `nexoeventos-backup-uploaders` |

## D. Requieren **encender recursos** y tu autorización (no hacer ahora)
- **Grafana y Zabbix** (paneles, problemas, alertas): hace falta una segunda ventana de Azure con la VM encendida (≈ 0,11 USD/h; `azure-set-shutdown-window.sh` antes). Es el mismo trámite que la prueba de **entrega real del correo de la alerta**.
- **Consola de ALB/target group/ASG** de V2: la V2 está destruida; mostrarlos exige redeplegar (costo y autorización).
- **Consola de RDS con el estado `Available` o métricas en vivo**: exige iniciar la RDS.
