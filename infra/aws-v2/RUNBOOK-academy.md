# AWS V2 en Academy — despliegue de prueba limitada y reversión (PREPARADO, NO EJECUTADO)

Objetivo: probar ALB + 2 EC2 (zonas distintas) + RDS Multi-AZ real durante **≤ 2 h**, gasto estimado **≈ 0,3 USD** (techo duro de la sesión: **1,5 USD**). Nada de esto se ha ejecutado. `automatic=false`; el failover AWS→OCI no se toca.

## 0. Puertas de entrada (todas de SOLO LECTURA; si una falla, no se continúa)
```bash
aws sts get-caller-identity --query Account --output text            # = expected_account_id; región us-east-1
aws rds describe-db-instances --db-instance-identifier nexoeventos-academy-postgres --query 'DBInstances[0].[DBInstanceStatus,MultiAZ]'   # available / true
aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names nexoeventos-academy-v2-asg --query 'AutoScalingGroups[0].[MinSize,DesiredCapacity]'   # 0 0
aws elbv2 describe-load-balancers --query 'LoadBalancers[?contains(LoadBalancerName,`v2`)].LoadBalancerName'
aws ec2 describe-images --image-ids "$AMI" --query 'Images[0].State'; aws acm describe-certificate --certificate-arn "$CERT" --query Certificate.Status
aws secretsmanager describe-secret --secret-id nexoeventos/academy/backend-env --query Name
```
Crédito de Academy visible ≥ 10 USD. Local: `cd infra/aws-v2 && terraform fmt -check && terraform validate && python3 tests/check_security.py` y las pruebas de `backend/tests/test_v2_alb_asg_local.py`, `scripts/multicloud/tests/test_aws_v2_site.py`.

## 1. Plan (revisión humana antes de nada)
```bash
terraform plan -var-file=… -var asg_enabled=true -var asg_min=2 -var asg_desired=2 -out=work/v2.plan
terraform show work/v2.plan | grep -E "will be (created|destroyed|replaced)|must be replaced"
```
Se espera: ALB, listeners, target group y SG nuevos; ASG **in situ** (capacidad 0→2); **0 destrucciones**, ninguna del ASG ni de la RDS. Cualquier destrucción/reemplazo ⇒ PARAR.

## 2. Encender (con autorización explícita; reloj de 2 h desde aquí)
```bash
date -u +%FT%TZ > work/v2-start.txt
terraform apply work/v2.plan                                  # solo este plan guardado
until [ "$(aws elbv2 describe-target-health --target-group-arn "$TG" --query 'length(TargetHealthDescriptions[?TargetHealth.State==`healthy`])')" = 2 ]; do sleep 10; done   # máx. 10 min
aws ec2 describe-instances --filters Name=tag:Name,Values=nexoeventos-academy-v2-app Name=instance-state-name,Values=running --query 'Reservations[].Instances[].Placement.AvailabilityZone'   # 2 zonas distintas
```
Con AMI sin `/livez`: `ami_includes_livez=false` hasta validar `/livez` por Session Manager en cada instancia (ver plan-ejecucion-cloud.md, fase 4).

## 3. Pruebas reales (≈ 45 min; las mismas que el simulador local)
1. **Reparto:** 200 GET a `https://<alb>/api/events`; `RequestCountPerTarget` > 0 en las dos instancias.
2. **Sesión sin afinidad:** login + 20 GET autenticados.
3. **Reservas concurrentes:** `scripts/cloud/verify-v2-flow.py` / `run-scale-test-v2.py` con el evento de prueba de cupo 1 y una zona de 4: exactamente 1 y 4 reservas; `reserved_count` = entradas; sin claves de idempotencia repetidas.
4. **Caída de una instancia:** `aws ec2 stop-instances` (o `systemctl stop nexoeventos-api` por SSM) en UNA; medir 5xx durante la ventana de detección (≈ 20 s con interval 10 s × 2), sustitución por el ASG y `HealthyHostCount` = 2 de nuevo (`scripts/cloud/v2-failover-test.py --allow-replacement --max-seconds 600`).
5. **Failover de RDS Multi-AZ** (opcional, `scripts/cloud/v2-rds-failover-test.py`): con `/livez` los destinos siguen sanos y el ASG no actúa.
No se activa la elección de líder del sitio ni la compuerta de escritura en esta prueba (sin OCI no hay lease entre nubes que probar).

## 4. Reversión y cierre (siempre, al terminar o al primer criterio de parada)
```bash
terraform apply -var asg_enabled=false -var-file=… -auto-approve=false   # capacidad 0: las EC2 se terminan (reversión inmediata, < 3 min)
# opcional: destruir ALB y SG de V2 con plan guardado revisado (solo recursos de infra/aws-v2)
aws rds stop-db-instance …            # solo si la RDS se encendió para la prueba (Academy: reinicio automático a los 7 días)
aws ec2 describe-instances --filters Name=tag:Name,Values=nexoeventos-academy-v2-app Name=instance-state-name,Values=pending,running --query 'length(Reservations)'   # = 0
aws elbv2 describe-load-balancers …   # ALB: 0 si se destruyó
```
## 5. Límites y criterios de parada
- **Tiempo:** 2 h desde el `apply` (si se supera, ejecutar el §4 aunque falte una prueba). **Gasto:** estimado 0,3 USD; parar si el crédito baja > 1 USD o supera el techo de 1,5 USD.
- **Parar de inmediato:** identidad/región erróneas; plan con destrucciones; ALB sin destinos sanos > 90 s; credenciales caducadas (revisar estado real antes de reanudar); instancia o recurso no previsto.
- **Estimación (tarifas públicas us-east-1, SIN verificar con facturación):** ALB 0,0225 + LCU ≈ 0,008 USD/h; 2×t3.small 0,042 USD/h; IPv4 públicas (2 EC2 + 2 del ALB) ≈ 0,02 USD/h; EBS ≈ 0,003 USD/h; RDS Multi-AZ db.t3.micro ≈ 0,036 USD/h si estuviera apagada. ⇒ ≈ 0,13 USD/h; 2 h ≈ 0,26 USD (≈ 0,5 con margen).

---
# B1–B3 EN UNA SOLA VENTANA DE 90 MIN (preparación final; NADA de esto se ha ejecutado)
Datos confirmados por la titular el 2026-11-20 ≈14:49Z: crédito USD 26,70; sesión restante 3,43 h ⇒ las credenciales caducan ≈ **18:10Z** (se toma 18:10Z por prudencia). Presupuesto operativo máximo propuesto: **USD 1,50** (estimado ≈ 0,26–0,5).

## Márgenes de seguridad
- **Todo lo facturable detenido antes de las 17:25Z** (= caducidad − 45 min). Ventana de 90 min ⇒ **B1 no puede empezar después de las 15:55Z** (RDS ≈ 15 min + 90 min + reversión ≈ 15 min); si se pasa esa hora, se aplaza a otra sesión.
- El watchdog se arma con `--minutes 90`; deja 80 min de margen frente a la caducidad. Si el crédito baja de USD 25,20 (−1,50) o aparece cualquier recurso no listado: reversión inmediata.
- Quien conduce la prueba ejecuta `scripts/v2-ops/rds-window.sh beat` al menos cada 10 min (el watchdog detiene la RDS si el latido supera 20 min).
- El plan guardado del 2026-11-20 14:39Z fue **DESCARTADO** (binario borrado): se regenera y se revisa justo antes del `apply`.

## Orden exacto (T0 = encendido de la RDS)
| Minuto | Paso | Autorización | Parada |
|---|---|---|---|
| T0−10 | `rds-window.sh check` (cuenta, RDS stopped, ASG 0/0, 0 EC2, 0 ALB) | lectura | cualquier fallo |
| **T0** | **B1** `NEXO_ALLOW_CLOUD_CHANGES=YES scripts/v2-ops/rds-window.sh start --minutes 90 --confirm "ENCENDER RDS"` (arma y verifica el watchdog, luego `start-db-instance`) | explícita (B1) | RDS no `available` en 25 min ⇒ revertir |
| T0+≈15 | **RDS `available` ⇒ DETENERSE y pedir la autorización del `apply`** | — | — |
| T0+20 | Regenerar el plan: `terraform plan -var-file=…common -var-file=…on -out=…` y revisar con `terraform show -json` | lectura | **0 destrucciones/sustituciones**; solo: 8 crear (ALB, 2 listeners, 4 alarmas, panel) + 1 modificar (ASG min/desired 0→2) |
| T0+22 | **B2** `terraform apply` del plan REGENERADO | explícita (B2) | cualquier error ⇒ revertir |
| T0+25…35 | Esperar 2 destinos `healthy` en 2 zonas (ALB ≈ 3 min + arranque ≈ 3 min; el 5-nov los destinos pasaron a `healthy` ≈ 30 s tras estar `InService`) | — | sin 2 sanos a T0+40 ⇒ revertir |
| T0+35…65 | **B3** pruebas (≈ 30 min): reparto, sesión, 1 y 4 reservas concurrentes, caída de UNA instancia y sustitución (`v2-failover-test.py --allow-replacement --max-seconds 600`). Sin DNS: `curl --resolve nexoeventos-demo.duckdns.org:443:<ip-ALB>`; el certificado es de ese dominio | explícita (B3) | ALB sin sanos > 90 s ⇒ revertir |
| T0+65 | **Reversión** (1) ASG a 0: `terraform apply` con `asg_enabled=false` (plan guardado revisado: solo el ASG); (2) destrucción dirigida de las 8 piezas (plan `-destroy -target=` guardado y revisado, como el del 11-nov: «0 to add, 0 to change, 8 to destroy») | explícita (reversión) | cualquier otro recurso en el plan ⇒ parar |
| T0+80 | Verificar 0 EC2, 0 ALB, ASG 0/0, RDS detenida por el watchdog (o `stop-now`) | lectura/explícita | RDS no `stopped` a T0+90 ⇒ `stop-now` |

## Requisitos que podrían impedir completarlo dentro de la ventana
1. **Hora de inicio** (≤ 15:55Z) y credenciales vigentes durante TODO Terraform: si caducan a mitad de un `apply` quedaría estado a medias.
2. **Arranque de la RDS Multi-AZ**: duración incierta (estimada 10–20 min; no medida en esta cuenta hoy). Si pasa de 25 min no se avanza.
3. **Arranque de las 2 EC2**: dependen de leer el secreto, descargar el paquete de CA de RDS por HTTPS (con IP pública) y de la RDS `available`; fallan sin arrancar la API si algo no cuadra (diseño seguro).
4. **Cuota de vCPU y de ALB**: ALB límite 50 (OK); la cuota de vCPU de EC2 no es legible con este rol (AccessDenied); 2×t3.small = 4 vCPU, normalmente holgado (sin verificar).
5. **AMI** `ami-0b9d9f97ca9623d3a` y su `/livez`: solo evidencia histórica del 5–6 nov; se valida de nuevo en B3 (`/livez` = 200 en ambas y API detenida ⇒ 502).
6. **El watchdog vive en este Mac**: Mac encendido con `caffeinate`, red y sesión de Academy vigentes.
7. **Academy puede volver a encender la EC2 de V1** si se reinicia el laboratorio: comprobar y avisar, no apagar sin autorización.
8. La variable `ami_includes_livez = true` ya está en las variables comunes: no hay segundo `apply` de cambio de ruta.
