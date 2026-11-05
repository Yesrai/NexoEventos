# Fase A2 — Subred pública de V1 sin IP pública automática (4-nov-2026, saneado)

**Estado: DESPLEGADA y verificada.** Cambio único: `aws_subnet.public_a.map_public_ip_on_launch` de `true` a `false` (AWS-0164).

## Condiciones comprobadas antes del apply
Sesión válida; estado Terraform serie 48 (sin cambios desde A1); crédito de Academy 40,20 USD (lectura de la usuaria: 9,80 de 50 usados); plan guardado vigente. Verificador `--solo-subred` sobre el plan JSON: **0 a crear, 1 a actualizar, 0 a destruir; único atributo distinto `map_public_ip_on_launch` true → false**.

Análisis de impacto (previo): la EC2 de V1, la plantilla de lanzamiento de V2 y `v2-prepare.sh` piden la IP pública explícitamente; no hay NAT ni endpoints VPC (0/0), de modo que SSM, Secrets Manager y ACM dependen de la IP pública que cada instancia pide por sí misma. El cambio solo afecta a instancias nuevas lanzadas en esa subred sin IP explícita.

## Resultado
`Apply complete! Resources: 0 added, 1 changed, 0 destroyed.` (11 s; estado serie 50; copia previa local `terraform.tfstate.pre-subred`, no restaurada). Plan guardado eliminado tras su uso.

## Verificación posterior (lecturas reales)
| Elemento | Resultado |
|---|---|
| Subred `public_a` (10.20.1.0/24) | `MapPublicIpOnLaunch = false` |
| Plan residual dirigido a la subred | «No changes» |
| EC2 V1 | `running`, **conserva su IP pública**, comprobaciones de instancia y de sistema `ok/ok` |
| SSM | `Online` (último contacto posterior al apply) |
| RDS | `stopped` (sin cambios) |
| Alarmas | 5 configuradas, acciones habilitadas (1 cada una): 2 `OK`, 3 `INSUFFICIENT_DATA` (RDS detenida) |
| S3 | lifecycle `backups/database/` 365/365; 4 respaldos vigentes con los mismos ETag |

## Límites
- Un cambio de este atributo no afecta a instancias ya lanzadas, por lo que **no se ha probado** el lanzamiento de una instancia nueva en la subred; eso lo demostrará la Fase B/C (el constructor de la AMI y el ASG de V2 piden IP pública explícita).
- Riesgo residual: una instancia lanzada a mano desde la consola en esa subred sin IP pública quedaría sin salida a internet/SSM (no hay NAT ni endpoints).
