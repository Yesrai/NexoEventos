# Propuesta: activar/desactivar V2, reducir costos y dominio estable (5-nov-2026; SOLO PROPUESTA, nada aplicado)

Estimaciones con tarifas públicas de us-east-1 (no verificadas con facturación). Estado auditado en solo lectura el 5-nov-2026 23:5x (hora de Perú).

## Recursos compartidos entre V1 y V2
| Recurso | Dueño | Cómo lo usa V2 | Riesgo |
|---|---|---|---|
| VPC, subred pública a, tabla de rutas pública | V1 (`infra/aws`) | `data` (solo lectura); V2 añade subred pública b y UNA asociación a la tabla de rutas de V1 | Bajo: el destroy de V2 solo quita lo que V2 creó |
| RDS `nexoeventos-academy-postgres` | V1 | Compartida, sin recurso Terraform en V2; V2 añade una regla 5432 desde su SG al SG de la base | Bajo: V1 declara sus reglas como recursos independientes (no inline), así que un `apply` de V1 no borra la regla de V2 |
| Secreto `nexoeventos/academy/backend-env` y credencial maestra | Fuera de Terraform / RDS | Lo lee el arranque de cada instancia | Medio: si se borra, las instancias nuevas no arrancan |
| Certificado ACM importado (Let's Encrypt, vence 1-ene-2027), AMI dorada, tema SNS | Fuera de Terraform (o V1) | Variables `certificate_arn`, `ami_id`, `alarm_topic_arn` | Medio: no se recrean con `terraform apply` |
| Estado de V2 | `work/terraform-state/academy-v2` (27 recursos) | Estado separado de V1 | Respaldar el archivo antes de cada cambio |

## Hallazgos
- El ASG tiene una *precondición* `asg_min >= 2`: **bajar la capacidad a 0 con Terraform exige un cambio de código** (p. ej. variable `asg_enabled`). Con la CLI (`update-auto-scaling-group`) se puede, pero Terraform lo vería como deriva (0→2) en el siguiente plan.
- Las 5 alarmas de V2 ya usan `treat_missing_data = notBreaching` y comparan contra la capacidad deseada: con el grupo en 0 no deberían disparar correos.
- Las 2 instancias usan `cpu_credits = unlimited`; el saldo de créditos excedentes (`CPUSurplusCreditBalance`) fue 0 en las últimas 3 horas: hasta ahora **no hubo cargos por créditos excedentes**.
- `t3.small` admite `standard` y `unlimited`. `standard` evita cargos por créditos excedentes pero **limita la CPU al valor base (20 %) al agotar créditos**, lo que puede distorsionar pruebas de carga y de escalado. Cambiarlo crea una nueva versión de la plantilla de lanzamiento; las instancias actuales no cambian hasta rotarse.
- Route 53: sin zonas alojadas; `route53domains:RegisterDomain` está **denegado explícitamente** (no se puede comprar un dominio en AWS Academy). `CreateHostedZone` y `acm:RequestCertificate` figuran como permitidos en la simulación de políticas (a confirmar al intentarlo).

## Costos por hora (con todo encendido ≈ 0,17 USD/h ≈ 4 USD/día)
| Componente | USD/h aprox. |
|---|---|
| 2 EC2 t3.small + 2 discos + 2 IPv4 públicas (V2) | 0,056 |
| ALB (mínimo 0,0225 + uso + 2 IPv4) | 0,04 |
| RDS Multi-AZ (cómputo 0,036 + almacenamiento 0,006) | 0,042 |
| EC2 de V1 (+ disco + IPv4) | 0,03 |

## Alternativas y ahorro
| Opción | Ahorro | Qué sigue cobrando | Tiempo de reactivación | Riesgo |
|---|---|---|---|---|
| A. ASG a 0 (CLI o variable `asg_enabled`) | ≈ 0,056 USD/h (≈ 41 USD/mes si estuviera apagado siempre) | ALB, RDS, V1 | 3–4 min (instancias nuevas + health check) | Bajo; no pierde datos; el nombre del ALB se conserva |
| B. A + destruir el ALB (destroy/apply de V2 completo) | ≈ 0,096 USD/h | RDS, V1 | 3–5 min por apply | Medio: cambia el nombre DNS del ALB (obliga a ajustar CNAME/hosts); requiere plan 27/0/0 y verificador cada vez |
| C. Detener la RDS | ≈ 0,036 USD/h | almacenamiento de la RDS, ALB | ≈ 5–8 min | Medio: la aplicación (V1 y V2) cae; Academy la reinicia sola a los 7 días |
| D. `cpu_credits = standard` | 0 en uso normal; evita hasta 0,05 USD por vCPU-hora de excedente bajo carga sostenida | — | requiere rotar instancias | Bajo; limita CPU en pruebas |

## Orden recomendado
1. **Scripts sin IP fija** (`v2-status`, `v2-up`, `v2-down`) que buscan por nombre/etiqueta (ASG, TG, ALB), activan con 2 y apagan con 0, comprueban salud y `/livez`. No tocan Terraform → ahorro inmediato (opción A).
2. **Variable `asg_enabled` en Terraform** para que el estado "apagado" también sea el estado declarado (sin deriva): un solo cambio en el ASG; plan esperado «0 a crear, 1 a modificar, 0 a destruir».
3. Dominio estable con CNAME al ALB y certificado propio de ACM (ver más abajo).
4. `cpu_credits = standard` solo si se prevén cargas largas; no es urgente.

## Plan de validación de cada cambio
Respaldo del estado de V2 → `terraform plan` guardado → verificador (`verificar-plan-v2.py`) → revisión de «sin destruir ni reemplazar la RDS» → apply del plan guardado → 2 destinos `healthy` → HTTPS, `/livez`, `/healthz`, `/api/events` → `verify-v2-flow.py` (15/15) → comprobar V1 y RDS intactas.

## Dominio estable
- DuckDNS: solo IP, sin CNAME; no sirve para validar certificados nuevos.
- Dominio propio barato (≈ 1–12 USD/año, fuera de AWS) + CNAME de un subdominio al nombre del ALB + certificado público de ACM con validación por DNS (gratuito, renovación automática). Con el estudiante de GitHub Student Pack puede haber un dominio gratis por un año (verificar elegibilidad).
- Route 53: zona alojada ≈ 0,50 USD/mes; permite un alias al ALB y automatizar con Terraform; no se puede registrar dominio desde Academy.
- FreeDNS (afraid.org): subdominios gratuitos con CNAME; comprobar antes que acepte los registros de validación de ACM.
