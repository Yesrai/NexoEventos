# Primer apagado de V2 con `v2-down.sh` (5-nov-2026 23:53, hora de Perú, saneado)

Autorizado por la usuaria. Comprobaciones previas: único ASG de la cuenta = `nexoeventos-academy-v2-asg`; 0 procesos locales de prueba; sin actividades del ASG en curso; V1 `/healthz` y `/api/events` → 200; RDS `available` (Multi-AZ, db.t3.micro, 9 conexiones); 0–1 solicitudes en 5 min al ALB.

Ejecución: `./v2-down.sh` con confirmación `APAGAR V2` → `autoscaling update-auto-scaling-group … --min-size 0 --desired-capacity 0` (04:53:42 UTC). Instancias a 0 a los 82 s (87 s en total).

Verificación posterior: ASG mínima 0, deseada 0, máxima 3, 0 instancias (las 2 de V2 `terminated`); V1 `running`, misma IP y misma hora de lanzamiento que antes; RDS `available`, Multi-AZ, misma clase y 20 GiB; 5 alarmas de V2 en `OK`; ALB activo, `/livez` → 503 (esperado); V1 `/healthz` → 200; sin cambios en el estado de Terraform de V2 (no se ejecutó) ni en Azure, OCI, DNS o credenciales.
