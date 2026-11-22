# Entregable 3 · Verificaciones previas a eliminar el ALB y detener RDS — 10-nov-2026 (22:40 hora local)

**Solo lectura + un plan local de Terraform. No se eliminó el ALB, no se detuvo RDS, no se creó ni modificó nada en la nube, sin commits ni push; OCI, Azure y Docker intactos.** Complementa el informe 09. Los números de cuenta se muestran como `<cuenta>`.

## 1. Certificado HTTPS del listener 443 (solo lectura)
| Dato | Valor |
|---|---|
| ARN | `arn:aws:acm:us-east-1:<cuenta>:certificate/b8f2c28e-2df8-4100-a9f8-7a04a437abaa` |
| Origen | **IMPORTED** (importado a mano el 21-oct-2026; emisor Let's Encrypt) |
| Región | us-east-1 (la misma del ALB: válido para reutilizarlo) |
| Estado | **ISSUED**, en uso por 1 recurso (el listener) |
| Dominio | `nexoeventos-demo.duckdns.org` (sin SAN adicionales); clave EC prime256v1 |
| Vigencia | 3-oct-2026 → **1-ene-2027** |
| Renovación | **INELIGIBLE**: ACM no lo renueva solo; hay que reimportar uno nuevo antes del 1-ene |
- **R1 resuelto:** el listado anterior salía vacío porque ACM, por defecto, no lista claves EC. Con todos los tipos y estados aparecen **2 certificados importados** del mismo dominio, ambos ISSUED; el segundo (`cb25088b-…`) no es el del listener.
- **Reutilización:** eliminar el ALB **no borra** el certificado (vive en ACM, fuera de Terraform). El ALB nuevo puede usar el mismo ARN con `certificate_arn`. Debe cubrir el período de pruebas (vence el 1-ene).
- No se creó ni modificó ningún certificado.

## 2. Plan local de Terraform para retirar solo el ALB (NO aplicado)
- Comando ejecutado: `terraform -chdir=infra/aws-v2 plan -destroy -target=aws_lb.main` con `academy-v2-common.tfvars` + `academy-v2-off.tfvars`, guardado en `work/operacion/v2-plans/20261111T033846Z-destroy-alb-target.tfplan` (+ `.txt`). El plan lee AWS (refresco) pero no escribe; sin cambios fuera de Terraform detectados. Aviso esperado: «Resource targeting is in effect».
- **Resultado: 0 crear, 0 cambiar, 8 destruir** (verificado con `terraform show -json`, todas acciones `delete`):
| Se eliminaría (8) | Motivo |
|---|---|
| `aws_lb.main` | el ALB |
| `aws_lb_listener.https`, `aws_lb_listener.http_redirect` | listeners 443 y 80 |
| `aws_cloudwatch_metric_alarm.alb_target_5xx`, `alb_unhealthy_hosts`, `alb_healthy_below_desired`, `alb_latency_p95` | alarmas que usan el `arn_suffix` del ALB |
| `aws_cloudwatch_dashboard.v2` | panel que referencia el ALB |
| **Permanece (19 de la raíz V2)** | |
| ASG (a 0), notificación del ASG, política `cpu`, alarma `asg_in_service_below_desired`, plantilla de lanzamiento, **target group**, SG `alb` y `web` con sus 9 reglas (incluida `postgres_from_web_v2` en el SG de BD), subred `public_b` y su asociación | |
| **Fuera de la raíz V2, intactos** | **RDS** y su subred/SG, **EC2 V1**, VPC, subred A, tabla de rutas, IGW, AMI e instantáneas, certificados ACM, secretos, evidencias |
- No hay ningún recurso de RDS ni de V1 en el plan.
- **Para ejecutar (cuando lo autorices):** `terraform -chdir=infra/aws-v2 apply <ese .tfplan>` (aplica solo el plan guardado; si el estado cambió, Terraform lo rechaza). Efecto: V2 sigue sin destinos; liberan sus IP públicas las 2 interfaces del ALB.
- **Nota:** con el ALB eliminado no se debe encender V2 (`asg_enabled=true`): las instancias no tendrían balanceador. Reconstruir primero (§6).

## 3. Instantáneas de RDS (solo lectura)
- Instancia `available`, Multi-AZ; último punto restaurable: 11-nov 03:34 UTC.
- **Instantánea más reciente: automática del 10-nov 07:56 UTC, `available`, 100 %, cifrada.** Tiene ≈ 15 h.
- **Manuales existentes: 4, todas `available`** (4, 8, 19 y 23-oct, 20 GiB, cifradas). Cuota de manuales: 4 usadas de 100.
- La última manual es del 23-oct: **no refleja los datos de las últimas semanas**. Por eso conviene una manual nueva antes de parar (las automáticas caducan y no se renuevan mientras está detenida).

## 4. Comandos exactos (NO ejecutados) y estimación de costo
Siempre `--profile nexoeventos-lab --region us-east-1`.

**A. Instantánea manual (decisión 2.º tiempo, requiere tu autorización):**
```bash
aws rds create-db-snapshot --db-instance-identifier nexoeventos-academy-postgres --db-snapshot-identifier nexoeventos-pre-parada-20261111 --profile nexoeventos-lab --region us-east-1
aws rds wait db-snapshot-available --db-snapshot-identifier nexoeventos-pre-parada-20261111 --profile nexoeventos-lab --region us-east-1
aws rds describe-db-snapshots --db-snapshot-identifier nexoeventos-pre-parada-20261111 --query 'DBSnapshots[0].[Status,SnapshotType,Encrypted]' --output text --profile nexoeventos-lab --region us-east-1
```
Costo: es incremental sobre las anteriores; sobre 20 GiB cobra ≤ ≈ 1,9 USD/mes como cota alta (0,095 USD/GiB-mes), probablemente centavos; el almacenamiento de copias es gratis hasta el tamaño de la base (20 GiB). En Multi-AZ se toma desde el standby (sin pausar la escritura). Tarda unos minutos.

**B. Detener RDS (solo después de A en `available`, con tu autorización):**
```bash
aws rds stop-db-instance --db-instance-identifier nexoeventos-academy-postgres --profile nexoeventos-lab --region us-east-1
aws rds wait db-instance-stopped --db-instance-identifier nexoeventos-academy-postgres --profile nexoeventos-lab --region us-east-1
aws rds describe-db-instances --db-instance-identifier nexoeventos-academy-postgres --query 'DBInstances[0].DBInstanceStatus' --output text --profile nexoeventos-lab --region us-east-1
```
Ya se detuvo antes en esta cuenta (28-oct y 4-nov), por lo que Academy permite la operación. Tarda varios minutos en Multi-AZ.

**Estimación de costo (tarifas públicas; sin facturación en Academy):**
| Situación | USD/h | USD/día | Hasta 26-nov (≈ 15,9 días) |
|---|---|---|---|
| Hoy (ALB + RDS) | ≈ 0,09 | ≈ 2,2 | ≈ 34 (no alcanza 28,30) |
| ALB eliminado | ≈ 0,05 | ≈ 1,2 | ≈ 19 |
| ALB eliminado + RDS detenida | ≈ 0,015–0,025 | ≈ 0,4–0,6 | ≈ 6–10 |
Ahorro del ALB ≈ 0,04 USD/h (horas + 2 IPv4); ahorro de la parada de RDS ≈ 0,035 USD/h. Cada hora de demora cuesta ≈ 0,09 USD.

## 5. Vigilancia del reinicio automático (7 días)
- Fecha límite = **hora de la parada + 7 días** (parada el 11-nov UTC → arranque automático ≈ 18-nov). Se anota con el evento `DB instance stopped`.
- Cada sesión de laboratorio: `describe-db-instances` (estado) y `describe-events --source-type db-instance --duration 10080` (busca `DB instance started`). Consultar no reinicia el contador.
- Recordatorio humano 2 días antes (16-nov). Si no se va a usar antes de la fecha límite, se vuelve a detener a mano (el contador reinicia) o se acepta el costo de ≈ 0,04 USD/h (instancia) al volver a encender.
- Verificar el estado al empezar cada sesión: no está documentado qué hace Academy con RDS al terminar una.
- Límite honesto: no hay alarma nativa verificada que avise del arranque; el aviso depende de este procedimiento manual.

## 6. Cómo se reconstruye V2 (cuando se reanude)
1. Iniciar el laboratorio; si RDS está `stopped`, `start-db-instance` y esperar `available` (≈ 5–8 min); confirmar `rds` y la última instantánea.
2. Verificar que el certificado `b8f2c28e-…` sigue `ISSUED` y vigente (hasta 1-ene-2027).
3. `terraform plan` con `common` + `off`: debe mostrar **solo las 8 creaciones** del §2 (ALB, 2 listeners, 4 alarmas, panel); revisar y `apply` del plan guardado.
4. `v2-terraform.sh on` (o `v2-up.sh`) y esperar 2 destinos `healthy` en 2 zonas (≈ 10–15 min en total).
5. DNS: el ALB nuevo trae otro nombre y otras IP. `nexoeventos-demo.duckdns.org` solo admite un A con una IP: si apunta al ALB viejo, hay que reescribirlo y puede cambiar otra vez; con los scripts de `hosts` (`v2-hosts-on.sh`) no se toca el DNS. No verifiqué hacia dónde apunta hoy.
6. Apagar al terminar: `v2-terraform.sh off`, y repetir ALB/RDS según este procedimiento.

## 7. Autorizaciones que quedan por decidir (ninguna concedida)
1. **Aplicar el plan guardado** (eliminar el ALB y sus 7 dependencias).
2. **Crear la instantánea manual de RDS.**
3. **Detener RDS** (tras confirmar la instantánea `available`).
