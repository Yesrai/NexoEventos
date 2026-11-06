# Operación de AWS V2: v2-status, v2-up, v2-down

Scripts locales para encender y apagar las EC2 de V2 (el Auto Scaling Group) sin tocar V1, la RDS ni el ALB. Usan el perfil `nexoeventos-lab` y la región `us-east-1` (fijos), identifican los recursos por etiqueta y nombre (nunca por IP ni ID de instancia) y necesitan `aws` y `jq`.

| Script | Qué hace | ¿Cambia algo? |
|---|---|---|
| `./v2-status.sh` | Muestra ASG (mín/deseada/máx), instancias, ALB, destinos healthy, RDS y EC2 de V1 | No (solo lectura) |
| `./v2-up.sh [--dry-run] [--timeout N]` | Pone mínima=2 y deseada=2 y espera 2 instancias InService/Healthy en 2 zonas y 2 destinos healthy; luego prueba `/livez` por HTTPS | Sí, tras escribir `ENCENDER V2` |
| `./v2-down.sh [--dry-run] [--timeout N]` | Pone mínima=0 y deseada=0 (no destruye el ASG) y espera a que no queden instancias | Sí, tras escribir `APAGAR V2` |

| `./v2-terraform.sh on\|off [--plan-only]` | Alterna V2 con Terraform (variable `asg_enabled`), con plan guardado y revisión estricta | Sí, solo tras escribir `APLICAR ON` o `APLICAR OFF` |

## Seguridad
- La única llamada que cambia recursos es `autoscaling update-auto-scaling-group` sobre el ASG de V2 (función `set_capacity` en `lib.sh`).
- El ASG se localiza con la etiqueta `Name=nexoeventos-academy-v2-app`; si hay 0 o más de 1 coincidencia, o el nombre no termina en `-v2-asg`, el script aborta sin cambios.
- El ALB y el grupo de destino se obtienen a partir del propio ASG; la IP del ALB se resuelve en el momento (`dig`) solo para la comprobación HTTPS.
- `v2-up` aborta si la RDS no está `available`. Tiempo máximo de espera: 600 s (cambiable con `--timeout`); al agotarse muestra las últimas actividades del ASG y sale con error.
- `--dry-run` muestra el plan y sale sin pedir confirmación ni cambiar nada.

## Cómo revertir
- Después de `v2-up`: `./v2-down.sh` (vuelve a mínima=0, deseada=0).
- Después de `v2-down`: `./v2-up.sh` (vuelve a mínima=2, deseada=2; ~3–4 min; las instancias nuevas se crean desde la plantilla de lanzamiento y la AMI actuales, sin pérdida de datos porque la base es la RDS).
- Si un script se interrumpe a mitad: `./v2-status.sh` muestra el estado real; ejecutar de nuevo el script deseado es seguro (es idempotente).

## Qué sigue cobrando con V2 en 0
El ALB (~0,03–0,04 USD/h con sus IP públicas), la RDS (~0,04 USD/h) y V1 si está encendida. Con V2 en 0 el ALB responde 503 y las alarmas de V2 no deben disparar (usan «sin datos no es alarma» y comparan con la capacidad deseada).

## v2-terraform.sh (modo recomendado con Terraform)
Archivos locales (fuera de Git, `work/terraform-envs/`): `academy-v2-common.tfvars` (cuenta, AMI, certificado, alarmas; no define `asg_enabled`), `academy-v2-on.tfvars` y `academy-v2-off.tfvars`. `asg_enabled` no tiene valor por defecto: sin el archivo on/off, Terraform falla en lugar de encender V2. El script comprueba perfil `nexoeventos-lab`, región y que la cuenta coincida con `expected_account_id` (sin imprimirla); genera un plan guardado y lo revisa; **acepta «No changes» o una sola modificación de `aws_autoscaling_group.web` que cambie únicamente `min_size` y `desired_capacity` (0/0 para `off`; 2 ≤ mín ≤ deseada ≤ máx para `on`)**; bloquea todo lo demás; para `on` exige la RDS `available`. Aplica solo el plan guardado y nunca ejecuta destroy. Pruebas: `./tests/test-terraform-mock.sh` (22 casos con terraform y aws simulados).

## Deriva con Terraform (solo si se usa v2-up/v2-down)
Mientras no exista la variable `asg_enabled`, un `terraform plan` de `infra/aws-v2` verá la capacidad apagada (0) como un cambio a 2 y la condición `asg_min >= 2` seguirá vigente. No ejecutes `terraform apply` en `infra/aws-v2` con V2 apagada sin revisar el plan.

## Pruebas locales (sin AWS)
`./tests/test-mock.sh` usa un `aws` simulado y comprueba 16 casos: solo lectura en status; cero cambios con confirmación incorrecta, `--dry-run`, RDS no disponible, 2 ASG o nombre inesperado; y exactamente una llamada de escritura (sobre el ASG de V2) cuando se confirma.
