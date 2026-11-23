# Cómo volver a encender AWS V2 (guía de operación; creada el 5-nov-2026)

Estado de partida tras el apagado del 5-nov-2026 23:53 (hora de Perú): ASG `nexoeventos-academy-v2-asg` con mínima=0, deseada=0, máxima=3; 0 instancias de V2; ALB `nexoeventos-academy-v2-alb` activo (responde 503); RDS `available`; EC2 de V1 `running`. Registro: `docs/evidencias/20261105-apagado-v2/resultado.md`.

## Pasos (todos desde el repositorio, sin Terraform)
1. **Abrir el laboratorio** de AWS Academy (Start Lab) y esperar el círculo verde. Si el laboratorio estuvo cerrado, Academy habrá terminado las instancias y puede haber detenido V1; la RDS podría seguir encendida (cobrando) o, si la detuvimos, reiniciarse sola a los 7 días.
2. **Ver el estado:** `cd scripts/v2-ops && ./v2-status.sh` (solo lectura). Debe decir «V2 APAGADA» y «RDS available».
3. **Si la RDS está `stopped`:** iniciarla antes (`aws rds start-db-instance --db-instance-identifier nexoeventos-academy-postgres --profile nexoeventos-lab --region us-east-1`) y esperar `available` (~5–8 min). `v2-up.sh` se niega a continuar si la RDS no está `available`.
4. **Encender V2:** `./v2-up.sh`; escribir `ENCENDER V2` cuando lo pida. Espera hasta 10 min; termina con «V2 ENCENDIDA» si las 2 instancias están InService/Healthy en 2 zonas, los 2 destinos están `healthy` y `/livez` responde 200 por el ALB.
5. **Prueba funcional (opcional):** `NEXO_ALLOW_CLOUD_CHANGES=YES backend/.venv/bin/python scripts/cloud/verify-v2-flow.py --out docs/evidencias/validacion-v2-AAAAMMDD` (15 comprobaciones con datos ficticios; limpia lo que crea).
6. **Verla en el navegador sin tocar DNS:** `work/operacion/hosts/v2-hosts-on.sh` (resuelve la IP actual del ALB) y, al terminar, `work/operacion/hosts/v2-hosts-off.sh`.
7. **Al terminar:** `./v2-down.sh` (escribir `APAGAR V2`).

## Si algo falla
- `v2-up.sh` agota el tiempo: muestra las últimas actividades del grupo. Un `Client.InternalError on launch` significa que el laboratorio estaba cerrado; ábrelo y repite. Para revertir: `./v2-down.sh`.
- El ASG no se encuentra o hay más de uno: los scripts no cambian nada; revisa la etiqueta `Name=nexoeventos-academy-v2-app`.
- Terraform (variable `asg_enabled`, **sin valor por defecto**; añadida el 6-nov-2026, aún no aplicada con `on`): alterna V2 con `scripts/v2-ops/v2-terraform.sh on|off [--plan-only]`. Usa `work/terraform-envs/academy-v2-common.tfvars` + `academy-v2-on.tfvars` o `academy-v2-off.tfvars` (locales, fuera de Git). Genera un plan guardado y solo acepta «No changes» o una única modificación del ASG que cambie min_size y desired_capacity; bloquea cualquier creación, destrucción, reemplazo u otro cambio; pide escribir `APLICAR ON` o `APLICAR OFF`; no ejecuta destroy. Los scripts `v2-up`/`v2-down` (CLI) quedan como vía de emergencia: después ejecuta `./v2-terraform.sh off|on --plan-only` para comprobar que Terraform y AWS coinciden.

## Costos aproximados (tarifas públicas; sin facturación)
- V2 apagada (esta situación): ALB ≈ 0,03–0,04 USD/h + RDS ≈ 0,042 USD/h + V1 encendida ≈ 0,03 USD/h ≈ **0,11 USD/h (≈ 2,6 USD/día)**; si el laboratorio se cierra y Academy detiene V1, ≈ 0,08 USD/h. Más centavos por discos, instantáneas, AMI y secretos.
- V2 encendida: ≈ 0,17 USD/h.
