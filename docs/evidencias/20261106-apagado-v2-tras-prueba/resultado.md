# Apagado de V2 tras la prueba real (6-nov-2026, hora de Perú, saneado)

Autorizado por la usuaria. Antes (16:54): V1 `running` (`/healthz` y `/api/events` → 200), RDS `available` (Multi-AZ, 20 GiB, máximo 40), V2 encendida (ASG 2/2/3, 2 destinos `healthy`).

16:54:29 `./v2-terraform.sh off` con la confirmación `APLICAR OFF`: plan guardado válido (1 modificación del ASG: `desired_capacity` y `min_size` 2→0; máxima 3; 0 crear/destruir/reemplazar) → `Apply complete! Resources: 0 added, 1 changed, 0 destroyed.` Las instancias llegaron a 0 a los 64 s; el script terminó a las 16:55:58 (91 s).

Verificación posterior: ASG mínima=0, deseada=0, máxima=3, sin instancias de V2 activas; un nuevo `v2-terraform.sh off --plan-only` → «Sin cambios: AWS ya coincide con V2 'off'»; V1 `running` con la misma hora de lanzamiento y respuestas 200; RDS `available`, Multi-AZ, 20 GiB asignados y máximo 40 (sin cambios); 5 alarmas de V2 en `OK`; ALB `active` sin destinos (`/livez` → 503, esperado). No se ejecutó destroy; no se modificaron RDS, ALB, DNS, certificados, Azure, OCI ni credenciales.

Costo que sigue (tarifas públicas, sin facturación): ALB ≈ 0,03–0,04 USD/h + RDS Multi-AZ ≈ 0,042 USD/h + EC2 de V1 ≈ 0,03 USD/h ≈ 0,11 USD/h (≈ 2,6 USD/día); si Academy detiene V1 al cerrar el laboratorio ≈ 0,08 USD/h. Más centavos por discos, instantáneas, AMI y secretos.

Nota: la prueba manual en el navegador y las capturas de consola de esa ventana no se confirmaron (ver `../20261106-prueba-real-v2/resultado.md`); V2 se apagó por decisión de la usuaria para ahorrar créditos, no porque esas pruebas estuvieran cerradas.
