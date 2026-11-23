# 2. Arquitectura técnica corregida e inventario

Principio: **AWS = producción**, **OCI = recuperación** (copia fuera de AWS, restauración verificable bajo demanda), **Azure = observabilidad** (monitoreo externo e independiente de AWS). Sin duplicar herramientas: CloudWatch sigue siendo la telemetría nativa de AWS; Azure añade la vista externa; OCI no ejecuta la aplicación salvo en simulacros.

```
Usuarios ─HTTPS─> [AWS] ALB(443, ACM) ─> ASG 2–3 EC2 (2 AZ) Nginx+FastAPI ─> RDS PostgreSQL (privada) ─> S3 privado
                         │  CloudWatch · Secrets Manager · AMI dorada
                         └─ respaldo lógico cifrado (CMS) + SHA-256 ──(HTTPS, estación del operador)──> [OCI] Object Storage privado
                                                                                  └─ VM temporal de recuperación (subred privada, Service Gateway) ─> restauración + huella
[Azure] VM Zabbix + Grafana  <── agentes activos (opcional) / comprobaciones HTTP(S) externas ── AWS (ALB, /healthz) · OCI
        Azure Monitor (VM + pruebas de disponibilidad externas) · presupuesto con alertas
```
Estados Terraform **separados**: `infra/aws` (V1), `infra/aws-v2`, `infra/aws-recovery`, `infra/oci` (nuevo), `infra/azure` (nuevo) — cada uno en `work/terraform-state/<nombre>/` con permisos 0600, nunca en Git.

## Inventario final
| Nube | Recurso | Detalle | Estado |
|---|---|---|---|
| AWS | VPC `10.20.0.0/16`, 3 subredes + pública-b de V2 | ver diagnóstico | PROBADO |
| AWS | EC2 V1, RDS Single-AZ, S3, CloudWatch, Secrets, AMI, ACM | detenidos/conservados | PROBADO |
| AWS | V2: ALB HTTPS, TG `/healthz`, ASG 2–3 en 2 AZ, política CPU 40 %, SG ALB/web | `infra/aws-v2` (21 recursos, reproducible) | PROBADO (destruida) |
| AWS | RDS Multi-AZ | `multi_az = true` aplicado el 23-oct; failover medido (≈ 14 s) | PROBADO |
| OCI | Compartment `nexoeventos` | aislamiento y políticas | PROBADO (23-oct) |
| OCI | VCN `10.30.0.0/16` (sin solape con AWS) y subred privada `10.30.1.0/24` | sin IP pública | PROBADO (23-oct) |
| OCI | NSG (entrada: solo SSH desde Bastion; salida: Object Storage/443) · Service Gateway (Object Storage) · NAT gateway solo si hace falta instalar PostgreSQL | | PROBADO (23-oct) |
| OCI | Bucket Object Storage privado (SSE con claves de Oracle, versionado, política de retención) | | PROBADO (23-oct) |
| OCI | VM temporal de recuperación (Always Free `VM.Standard.E2.1.Micro` si hay capacidad; PostgreSQL 18) + OCI Bastion | se crea y destruye en cada simulacro | PROBADO y destruida (23-oct) |
| Azure | Resource group, VNet `10.40.0.0/16` (**propuesta**) / subred `10.40.1.0/24`, NSG | región permitida (`centralus` o `southcentralus`) | PROBADO (28-oct) |
| Azure | VM Linux 2 vCPU/8 GiB `Standard_D2s_v4` (la B2s está restringida para Azure for Students; cuota verificada el 28-oct) + disco SSD estándar 64 GiB + IP pública estática | Zabbix server + PostgreSQL + Grafana | PROBADO (28-oct; VM desasignada) |
| Azure | Log Analytics (nivel gratuito de ingesta), Azure Monitor (métricas de la VM), pruebas de disponibilidad HTTPS externas, presupuesto con alertas | | PROBADO parcial (alertas de métricas sí; pruebas de disponibilidad externas desactivadas) |

IaC preparada y **validada localmente** (`terraform fmt/validate`, comprobaciones estáticas de seguridad y coherencia de CIDR): `infra/oci` y `infra/azure`, con estados independientes y `create_*=false` por defecto. **Actualización 28-oct-2026:** OCI y Azure están desplegados (OCI: red, IAM y bucket conservados, VM de recuperación destruida; Azure: base y VM desasignada). El estado real de cada recurso está en `docs/evidencias/multicloud/`.

## Conexiones y permisos
- **AWS → OCI (respaldo):** la estación del operador descarga el CMS cifrado y su SHA-256 de S3 (verifica), lo sube a OCI por HTTPS (política de OCI de solo escritura para el usuario API) y verifica el hash en destino. **No se guardan credenciales de OCI en AWS ni de AWS en OCI/CI.** Cifrado de extremo a extremo con la clave pública de recuperación ya usada; la clave privada se aporta solo durante el simulacro (por Bastion, en memoria) — *decisión del usuario pendiente* (alternativa: segundo par de claves solo para OCI).
- **Restauración OCI:** la VM (subred privada) lee el bucket por el Service Gateway; PostgreSQL local temporal; se compara la huella (conteos y hashes) con la línea base del respaldo del 19-oct (135 reservas, 135 entradas, 25 usuarios, Alembic 0008). Al terminar se destruye la VM.
- **Azure ← AWS (observabilidad):** *Fase A sin tocar AWS:* comprobaciones HTTP(S)/TLS (`/healthz`, `/api/events`, certificado, latencia) desde Zabbix y desde las pruebas de disponibilidad de Azure. *Fase B (requiere autorización):* agente Zabbix **activo** en las EC2 (salida TCP 10051 hacia la IP de Azure → regla de salida nueva en el SG web de V1/V2).
- **Grafana:** orígenes de datos Zabbix y Azure Monitor. CloudWatch **no** se integra con claves fijas (AWS Academy no permite IAM de largo plazo); sus métricas se exportan puntualmente como evidencia.
- **Acceso administrativo:** Azure: NSG con SSH/Grafana/Zabbix solo desde la IP del operador y TLS (Let's Encrypt sobre un nombre `sslip.io`/DuckDNS); OCI: solo Bastion; AWS: Session Manager (sin SSH).
- **Automatización:** Terraform (nubes) + Ansible (roles `nexoeventos_recovery_oci`, `monitoring_zabbix_grafana`, `zabbix_agent`) + GitHub Actions **solo estático** (fmt/validate/lint/Trivy; sin credenciales cloud ni apply automático).
