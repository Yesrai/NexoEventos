# Despliegue de AWS V2 para la exposición (5-nov-2026, saneado)

Horas en hora de Perú (UTC−5). Crédito de Academy declarado por la usuaria antes de empezar: 11,2 de 50 USD usados.

## Secuencia
| Hora | Hecho |
|---|---|
| 14:21 | `start-db-instance` de `nexoeventos-academy-postgres` (autorizado); `available` a las 14:26 |
| 14:27 | `terraform plan` regenerado: **27 a crear, 0 a modificar, 0 a destruir**; `verificar-plan-v2.py` CORRECTO |
| 14:27:56–14:30:22 | `terraform apply` del plan guardado: **27 creados, 0 modificados, 0 destruidos** (`work/operacion/apply-v2-20261105.txt`, fuera de Git) |
| 14:30:53 | Los 2 destinos del ALB en `healthy` (≈ 30 s después del apply) |

## Estado verificado por la CLI (archivos en esta carpeta)
- ALB `nexoeventos-academy-v2-alb`: `active`, `internet-facing`, zonas us-east-1a y us-east-1b (`alb.json`).
- ASG `nexoeventos-academy-v2-asg`: mínimo 2, deseado 2, máximo 3; 2 instancias `InService`/`Healthy`, una en us-east-1a y otra en us-east-1b (`asg.json`, `ec2.json`).
- Grupo de destino: 2 destinos `healthy`; health check `/livez` (`target-health.json`).
- 5 alarmas de V2 en `OK` (`alarmas.txt`).
- HTTPS por la IP del ALB con el nombre autorizado (`--resolve`, sin tocar DNS): `/livez`, `/healthz` (`{"status":"ready"}`, requiere PostgreSQL), `/api/events` y `/` → 200; certificado válido (verificación TLS 0); HTTP 80 → 301 a HTTPS.

## Prueba funcional (`verify-v2-flow.py`, datos ficticios)
Carpeta `../validacion-v2-20261105/`: **15 de 15 comprobaciones OK** (registro y login, sesión válida entre instancias, reserva simulada idempotente, Mis entradas con QR, validación por operadora, 403 en casos no permitidos, fila virtual, disputa del mismo asiento con 1 ganador, limpieza con huella idéntica y sin eventos ni cuentas de ensayo). Reparto entre instancias: 38 y 38 solicitudes /api (50 % y 50 %), 0 errores 5xx.

## Pagos
La aplicación solo tiene **pago simulado** (`docs/persistencia-y-reservas.md`: «Pagos reales» fuera de alcance). No hay pasarela real ni sandbox; no se hizo ningún cobro.

## Límites
- No se ejecutaron pruebas de autohealing ni de failover.
- Las capturas de consola (ALB, ASG, EC2, grupos de destino) las debe tomar la usuaria en su navegador; la CLI no genera capturas. Los archivos JSON son evidencia textual, no capturas.
- Costos por tarifas públicas, sin facturación.
