# Auditoría AWS de solo lectura (28-oct-2026)

- **Procedencia:** `scripts/cloud/readonly-audit.py` (guarda en código: solo `describe/get/list`; sin Cost Explorer; sin lectura de secretos, objetos ni contraseñas) más una consulta puntual de VPC, subredes, tablas de rutas, grupos de seguridad y `cloudtrail lookup-events`. Sesión de AWS Academy activa, perfil de laboratorio, `us-east-1`, ~21:20Z. Ningún recurso fue modificado por esta auditoría.
- **Salida:** `resumen-solo-lectura.json` y `red-y-cloudtrail.json`. Enmascarados: cuenta, ARN, IDs (últimos 4 caracteres), IP, correos, endpoints y el identificador de laboratorio en los nombres de políticas. Las horas de `cloudtrail` están en la hora local de la estación (no UTC).
- **Corrección del script:** la guarda bloqueaba por error `iam list-attached-role-policies` (el nombre contiene «attach»); se añadió como excepción de lectura pura y el autotest sigue pasando.

## Hallazgos
| Tema | Resultado |
|---|---|
| RDS | `stopped`, db.t3.micro, PostgreSQL 18.3, **Multi-AZ**, cifrada, **no pública**, copias 7 días, **sin protección contra borrado**, gp2 20 GiB con autoescalado |
| Riesgo de reinicio | Última parada 2026-10-23T15:17:59Z → reinicio automático previsto ≈ 2026-10-30T15:17:59Z (≈ 41,9 h restantes a las 21:22Z del 28-oct); hora exacta variable. Los eventos solo cubren 14 días |
| EC2 V1 | `stopped`, t3.small, IMDSv2 obligatorio; EBS 20 GiB cifrado |
| Red | VPC `10.20.0.0/16`; pública con ruta a IGW; dos subredes de datos sin ruta a Internet ni IP pública; sin NAT, sin endpoints, sin ALB, sin ASG, sin IP elástica |
| Security groups | Web: 80/443 desde Internet, sin SSH; salida 443, 53 (VPC) y 5432 al SG de la base. Base: 5432 solo desde el SG web |
| S3 | Bloqueo público total, AES256, versionado, 1 regla de ciclo de vida |
| IAM | Perfil de instancia → `LabRole`; 7 políticas adjuntas (3 Academy, SSM, 3 EKS/ECR) |
| CloudTrail | **0 trails**; el historial de eventos responde |
| CloudWatch | 1 alarma de CPU (V1), 0 acciones, `INSUFFICIENT_DATA`; 0 paneles; logs API/Nginx con 7 días |
| Copias | 4 snapshots manuales + 9 automáticos de RDS (260 GiB asignados sumados), 1 snapshot EBS, 1 AMI |
| Secretos / ACM | 2 secretos (solo metadatos) / 0 certificados |

## No comprobado
Permisos efectivos de `LabRole` (no se leyeron los documentos de las políticas), clave KMS, contenido de S3, costo facturado real (no se usó Cost Explorer), tamaño facturable de los snapshots.

## Adenda 29-oct (02:19Z) — detalle de seguridad (P10)
- Procedencia: `scripts/cloud/readonly-audit-detalle.py` (solo `describe/get/list`), credenciales renovadas por la propietaria. Archivo: `detalle-seguridad.json` (enmascarado; la lista de ≈ 50 servicios de confianza se condensó a un recuento).
- Antes de la consulta, Academy había **encendido sola la EC2** (01:59Z). Se detuvo solo esa instancia (orden 02:19:28Z, `stopped` verificado). RDS: `stopped`, sin tocar.
- Hallazgos: 0 usuarios y 0 grupos IAM; `rds.force_ssl = 1` (por defecto); IMDSv2 obligatorio, hop limit 2; EBS cifrado por defecto **desactivado** a nivel de cuenta (el volumen sí está cifrado); S3 sin política de bucket y ciclo de vida solo sobre `database-backups/`; alarma sin acciones; `MaxAllocatedStorage = 20`.
- No legible: documentos de `VocLabPolicy1–3` (acceso denegado).
