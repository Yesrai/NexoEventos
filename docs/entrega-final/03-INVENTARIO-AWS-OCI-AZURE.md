# 03 · Inventario AWS · OCI · Azure

**Fuente:** código Terraform (`infra/*`) y el «estado final» declarado en cada expediente T1–T5. **No se consultó ninguna nube para este documento**: el estado indicado es el último **verificado en el expediente citado**, no el de hoy. Sin IP, OCID, ID de cuenta ni URL de PAR.

## 1. AWS (us-east-1, AWS Academy Learner Lab)

| Recurso | Definición IaC | Configuración | Último estado verificado | Fuente del estado |
|---|---|---|---|---|
| VPC `10.20.0.0/16` + IGW | `infra/aws` | 2 subredes públicas, 2 de datos privadas | existe | `docs/entregable2/informe-entregable2.md` §10 |
| EC2 V1 (`t3.small`, AL2023) | `infra/aws` | Nginx + FastAPI, IMDSv2, EBS cifrado | `stopped` | `docs/evidencias/T5-20261123-resultado.md` |
| RDS PostgreSQL Multi-AZ (`db.t3.micro`, 20 GiB) | `infra/aws` (fuera del estado de `aws-v2`) | cifrada, backups 7 días, `verify-full` | `stopped` (se reinicia sola a los 7 días) | T5 resultado |
| S3 (2 buckets) | `infra/aws` | privado, versionado, SSE-S3, ciclo de vida | existe | `docs/evidencias/20261104-fase-a1-lifecycle-s3/` |
| CloudWatch (5 alarmas V1, logs 7 d), SNS, CloudTrail | `infra/aws` | — | existen | `infra/aws` |
| ALB + 2 listeners | `infra/aws-v2` | HTTPS TLS 1.3/1.2, 80→301 | **eliminado** (por API, en la limpieza) | T5 resultado |
| Target group | `infra/aws-v2` | health check 5 s / 3 s, 2/2, `weighted_random` + mitigación | existe (configuración HA aplicada) | T5 resultado |
| Launch template | `infra/aws-v2` | versión 2 (pool de BD 3+2) | existe | T5 resultado |
| ASG | `infra/aws-v2` | **0 / 0 / máx 6** | 0 EC2 | T5 resultado |
| Alarmas V2 (5) y panel | `infra/aws-v2` | dependen del ALB | se recrean con el ALB | T5 análisis §7 |
| `aws-recovery` (EC2 + RDS) | `infra/aws-recovery` | contingencia | no desplegado | — |

**Cambio pendiente de decisión:** volver al punto económico (mín 2 / máx 3, `least_outstanding_requests`, pool 5+5) requiere un plan revisado.

## 2. OCI (sa-saopaulo-1)

| Recurso | Módulo | Último estado verificado | Fuente |
|---|---|---|---|
| Compartimento, grupos, usuarios y políticas (carga de respaldos; lease) | `infra/oci/modules/iam`, `lease` | existen | `infra/oci` |
| VCN `10.30.0.0/16`, subred privada `10.30.1.0/24`, NSG, lista de seguridad, 2 tablas de rutas, Service Gateway | `network` | existen (VCN 1, subred 1, NSG 1, lista 1, 2 tablas) | `docs/evidencias/T3-20261122-intento3-resultado.md` |
| Bucket `nexoeventos-recovery` | `storage` | `NoPublicAccess`, versionado, **21 objetos / 471 979 B**, **0 PAR** | `docs/evidencias/T1-20261122-resultado.md` y T3 |
| Subred pública `10.30.2.0/24`, IGW, entrada 443 | `public_entry` | **destruidos** (0 IGW) | T3 intento 3 |
| VM de recuperación `E2.1.Micro` + Bastion | `recovery` | **destruidos** (0 instancias, 0 Bastion) | T3 intento 3 |
| PAR temporales del lease | — | 3 creados y revocados en T1; 0 activos | T1 |

## 3. Azure (centralus, Azure for Students)

| Recurso | Definición | Último estado verificado | Fuente |
|---|---|---|---|
| Grupo de recursos, VNet `10.40.0.0/16`, subred, NSG | `infra/azure` | existen; NSG de entrada idéntico antes/después de T4 | `docs/evidencias/T4-20261122-resultado.md` |
| VM de observabilidad `D2s_v4` (Ubuntu 24.04) + IP pública + NIC | `infra/azure` | **desasignada**; apagado automático 17:38 UTC restaurado exacto | T5 resultado |
| Software en la VM | instalador (no Terraform) | Zabbix, Grafana, Nginx, centro de operaciones, testigo (sin inicializar, sin dueño), recolector (timer), usuarios `opscenter`/`nexowitness`; 2 hosts de Zabbix deshabilitados | T4 resultado |
| Log Analytics, diagnósticos, Azure Monitor, grupo de acciones, alerta métrica, Application Insights web test, presupuesto | `infra/azure` | regla/rol de correo de prueba retirados tras T4 | T4 resultado |
| Snapshot y 2 discos del 4-nov | manual | intactos (snapshot de T4 borrado) | T4 resultado |

## 4. Otros servicios

| Servicio | Uso | Estado |
|---|---|---|
| DuckDNS | `nexoeventos-test` (pruebas) y `nexoeventos-demo` (no tocado) | `nexoeventos-test` en A (IP inicial) tras T2; **token de cuenta: regenerar** |
| GitHub Actions | CI (backend, frontend, Docker + Trivy) | ver `docs/entregable2/informe-entregable2.md` |
| NexoOps | portal T7 | **solo local** (puerto 8088); no desplegado |

## 5. Verificación final pendiente (T8)

Los criterios de `ops_center/criterios/T8.json` exigen comprobar en una sesión final: AWS sin recursos facturables (0 EC2/ALB/NAT/EIP, RDS detenida), OCI sin recursos temporales, VM de Azure desasignada, tokens y claves temporales revocados, paquete cifrado nuevo copiado y reverificado. **Estado: NOT_TESTED** (requiere acceso de lectura a las nubes, fuera del alcance de este paquete local).
