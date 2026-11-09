# Prueba real de V2 (6-nov-2026, hora de Perú, saneado)

Precondiciones (15:37): credenciales válidas, laboratorio con ≈ 133 min estimados, V1 `running` (`/healthz` 200), RDS `available`, V2 apagada (ASG 0/0/3).

15:38:18 `./v2-terraform.sh on` con la confirmación `APLICAR ON`: plan guardado válido (1 modificación del ASG: `desired_capacity` y `min_size` 0→2; máxima 3; 0 crear/destruir/reemplazar) → `Apply complete! Resources: 0 added, 1 changed, 0 destroyed.` Los 2 destinos del ALB quedaron `healthy` a los 57 s; el script terminó a las 15:40:05.

Estado verificado: ASG mínima=2, deseada=2, máxima=3; instancias `i-047939a71f0087190` (us-east-1b) e `i-068ef939e2355d2b6` (us-east-1a), ambas `InService`/`Healthy`; ALB `active`; 2 destinos `healthy`; 5 alarmas de V2 en `OK`; un nuevo `v2-terraform.sh on --plan-only` muestra que Terraform y AWS coinciden.

HTTPS por la IP del ALB (resuelta en el momento) con el nombre del dominio: `/livez` → 200 con `{"status":"ok","service":"nexoeventos-api"}`; `/healthz` → 200; `/api/events` → 200; certificado válido (verificación 0).

Pruebas funcionales (`verify-v2-flow.py`, datos ficticios): **15 de 15 OK**; reparto 49 %/51 % entre las dos instancias; 0 errores 5xx; limpieza con huella idéntica y sin cuentas ni eventos de ensayo (`docs/evidencias/validacion-v2-20261106/`).

## Qué NO está comprobado o quedó pendiente
- No se hicieron pruebas de autohealing ni de failover en esta ventana.
- **Prueba manual en el navegador** (archivo hosts, `/livez` en JSON, reserva con QR): se guió a la usuaria, pero **no se recibió confirmación del resultado ni capturas**; no se declara completada. Después la usuaria indicó que restauró su archivo hosts.
- **Capturas de consola de AWS** (instancias, ALB, grupo de destino, ASG, alarmas): las debía tomar la usuaria; **no se recibieron archivos**, por lo que no hay capturas de esta ventana. La evidencia de esta ventana es textual (JSON y registros de esta carpeta y de `validacion-v2-20261106/`).
- Si la usuaria hizo una reserva manual en el navegador, quedó en la base compartida (no se verificó ni se borró); las 15 pruebas automáticas sí limpian sus datos.
