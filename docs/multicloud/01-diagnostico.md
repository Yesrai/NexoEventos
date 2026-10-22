# 1. Diagnóstico (22-oct-2026)

## AWS (producción) — datos reales del estado Terraform local `work/terraform-state/academy-current` y de las evidencias
| Elemento | Valor | Estado |
|---|---|---|
| Región / AZ | `us-east-1`, `a` y `b` | PROBADO |
| VPC | `10.20.0.0/16` (DNS y hostnames habilitados) | PROBADO |
| Subredes | pública-a `10.20.1.0/24` (1a); datos-privada-a `10.20.21.0/24` (1a); datos-privada-b `10.20.22.0/24` (1b). V2 añadió pública-b `10.20.2.0/24` (1b), **destruida** | PROBADO |
| Rutas | pública: `0.0.0.0/0` → IGW; datos: solo local (sin NAT) | PROBADO |
| SG web (V1) | entrada 80/443 desde Internet; salida 443 a Internet, DNS 53 a la VPC, 5432 al SG de la base | PROBADO |
| SG base | entrada 5432 solo desde el SG web | PROBADO |
| Cómputo V1 | EC2 `t3.small` AL2023, IMDSv2, Nginx + FastAPI (2 workers), release `311a830` desplegado (la AMI de V2 lleva `d3e52e8`); **detenida** | PROBADO |
| RDS | PostgreSQL 18.3 `db.t3.micro`, 20 GiB gp2, **Single-AZ**, privada, cifrada, respaldos 7 d; **detenida** | PROBADO |
| S3 | bucket privado, versionado, cifrado, sin acceso público, ciclo de vida; 3 respaldos lógicos cifrados (CMS) | PROBADO |
| Observabilidad | CloudWatch: 2 grupos de logs (api, nginx; 7 d) y alarma de CPU | PROBADO |
| Secretos | secreto maestro administrado por RDS + secreto compartido `backend-env` | PROBADO |
| AMI dorada V2 / certificado ACM importado | existen; **conservados** (vence 1-ene-2027) | PROBADO |
| V2 (ALB + ASG 2–3 en 2 AZ) | desplegada, medida y **destruida** (Terraform `infra/aws-v2`, estado separado); reproducible | PROBADO |
| Respaldos | 3 snapshots manuales RDS + 3 objetos S3; restauración PITR (RPO 3 min 32 s) y dump verificados | PROBADO |
| RDS Multi-AZ | no implementada | PENDIENTE |

Resultados medidos que se conservan: V1 vs V2 hasta 50 usuarios (p95 ≈ 140–290 ms, 0 errores), ráfagas de login con límite de Argon2, autohealing, Auto Scaling 2→3→2 (alarma a los 8 min 6 s; 3.ª instancia sana ≈ 9 min; regreso a 2 a los 16 min). Ver `docs/evidencias/` y `perf/results/`.

## OCI y Azure
- **OCI:** sin cuenta. Nada creado. **PENDIENTE** (`infra/` no tiene raíz OCI).
- **Azure:** suscripción *Azure for Students* activa, sin recursos; crédito USD 100 **informado, no verificado** (saldo/vigencia pendientes); política que **deniega** regiones salvo `southcentralus`, `mexicocentral`, `westus3`, `canadacentral`, `centralus`; proveedores `Microsoft.Compute/Network/Storage` **NotRegistered**; cuotas de vCPU **desconocidas** (`docs/diagnostico-entorno.md`). `infra/azure` es un esqueleto sin recursos.

## Bloqueos
1. **AWS:** hoy las credenciales del perfil `nexoeventos-lab` están bloqueadas por la política `voc-cancel-cred` (explicit deny en EC2, RDS, S3, Secrets…): el laboratorio fue cancelado/expiró; hace falta **Start Lab** y renovar credenciales. No se pudo releer la infraestructura viva; los CIDR/SG de arriba salen del estado local y de evidencias.
2. **OCI:** crear la cuenta (suele exigir tarjeta de verificación), elegir y fijar la región de origen (los recursos *Always Free* solo valen allí) y generar la clave API.
3. **Azure:** confirmar saldo/vigencia del crédito, registrar proveedores, comprobar cuota/tamaño de VM en una región permitida.
4. **Servicios no autorizados/inciertos:** IAM de usuarios y claves de larga duración en AWS Academy (no se pueden crear): descarta integrar CloudWatch con Grafana/Zabbix con claves fijas; Multi-AZ y NAT en el laboratorio sin probar.
