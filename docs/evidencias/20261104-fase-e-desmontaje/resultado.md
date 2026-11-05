# Fase E — Desmontaje de V2 y parada de la RDS (4-nov-2026, saneado)

Horas en hora de Perú. **Estado: COMPLETADA.** V2 destruida por completo y RDS detenida (no eliminada).

## Contexto
La sesión anterior de Academy venció (≈ 15:20) con V2 y la RDS encendidas; la usuaria renovó credenciales a las 16:31. Entre las 12:04 y las 16:31 V2 y la RDS siguieron encendidas (y el perfil devolvía `AccessDenied` por `voc-cancel-cred`, sin eludirlo). Al volver, Academy había **reiniciado** la EC2 de V1 y el ASG de V2 había repuesto sus 2 instancias (destinos `healthy`); la RDS seguía `available`. Detalle de la incidencia: `../20261104-fase-c-d-v2/incidencia-sesion.md`.

## Prechequeos (16:33–16:34)
STS válido (cuenta `…1388`, `us-east-1`); `ec2`, `rds`, `cloudwatch`, `autoscaling`, `elbv2` y `ssm` ya sin denegación. Estado de Terraform V2: serie 81, 27 recursos gestionados. **Plan de destroy regenerado desde el estado actual** (con refresco): `0 to add, 0 to change, 27 to destroy`; los tipos coinciden exactamente con los de V2 (ASG, notificación y política del ASG, panel, 5 alarmas V2, plantilla de lanzamiento, ALB, 2 listeners, grupo de destino, asociación de ruta, 2 SG, subred B, 5 reglas de salida y 4 de entrada, entre ellas la regla aditiva **TCP 5432 sobre el SG existente de la RDS**). Sin recursos de RDS, S3, EC2 de V1, AMI/snapshots, ACM, SNS, IAM ni alarmas de V1 en el plan.

## Destroy (16:34:46–16:36:33)
`Apply complete! Resources: 0 added, 0 changed, 27 destroyed.` Solo el plan verificado; sin destroy general ni de V1.

## Verificación posterior (lecturas reales)
ALB 0 · grupos de destino 0 · ASG 0 · plantillas V2 0 · instancias V2 vivas 0 (las 2 antiguas `terminated`) · SG V2 0 · subred B 0 · panel V2 0 · alarmas: solo las 5 de V1 (`OK`; las de seguimiento del ASG desaparecieron con su política) · **regla 5432 de V2 retirada** (queda 1 regla 5432 de ingreso, la de V1) · estado Terraform V2: serie 116, **0 recursos gestionados**; un nuevo `plan -destroy` dice «No changes. No objects need to be destroyed».

## Detención de la RDS (16:37:19–16:47:44)
Identificador confirmado: `nexoeventos-academy-postgres` (PostgreSQL, db.t3.micro, Multi-AZ; la única RDS de la cuenta). `stop-db-instance` (sin `delete-db-instance`, sin modificar configuración): `stopping` ≈ 10,5 min → **`stopped`** (evento «DB instance stopped» 21:47:44 UTC). Protección contra borrado `false` (valor previo, sin cambios). La reactivación automática de Academy ocurriría a los 7 días: ≈ **11-nov-2026 16:47 (Perú)**.

## Conservado e intacto (verificado)
EC2 de V1 `running` (SSM `Online`, `/livez` por HTTPS → 200; la subred sigue con `MapPublicIpOnLaunch=false`) · bucket privado: lifecycle `backups/database/` 365 días y **4 respaldos** vigentes · **2 AMI** (22-oct y la nueva con `/livez`) y **2 snapshots** · **2 certificados ACM** idénticos (el duplicado no se borró) · 2 secretos de Secrets Manager · SNS con 1 suscripción confirmada · 5 alarmas de V1 en `OK` · 1 volumen (el de V1), 0 sin uso, 0 EIP sin asociar, 0 NAT. Azure y OCI no se tocaron.

## Costes (estimaciones con tarifas públicas, no verificadas con facturación)
- Incremental de Fases C–E: V2 encendida 11:32–16:36 (≈ 5,1 h × ≈ 0,1 USD/h) ≈ 0,5 USD + RDS encendida 11:22–16:47 (≈ 5,4 h × 0,036 USD/h) ≈ 0,2 USD ⇒ **≈ 0,7–0,8 USD**, por debajo del techo de 3 USD. Cerca de 3,8 h de ese tiempo (≈ 0,5 USD) fueron el hueco por el vencimiento de la sesión.
- **Recursos facturables que permanecen:** EC2 de V1 `running` (≈ 0,7 USD/día con IPv4 y disco), almacenamiento de la RDS detenida (Multi-AZ 20 GiB, ≈ 0,15 USD/día) y sus copias, 2 snapshots de AMI (≈ 0,2–0,4 USD/mes), 2 secretos (≈ 0,8 USD/mes), S3 y logs (centavos). 5 alarmas dentro de la capa gratuita; ACM gratis.
