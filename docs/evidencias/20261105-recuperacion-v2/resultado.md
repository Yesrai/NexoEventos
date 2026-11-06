# Recuperación de V2 tras reabrir el laboratorio (5-nov-2026, 23:05 hora de Perú, saneado)

Solo lecturas y pruebas funcionales con datos ficticios; sin `terraform apply`/`destroy`, sin cambios de DNS ni de hosts.

- Al cerrarse el laboratorio, Academy terminó las 2 EC2 de V2; el ASG (deseado 2) falló al relanzar con `Client.InternalError on launch` (03:04–03:08 UTC) mientras el laboratorio estaba cerrado.
- Al reabrirse (22:40 hora de Perú), el **ASG creó solo las 2 EC2** (22:40:47): us-east-1a e us-east-1b, `InService`/`Healthy`; los 2 destinos del ALB `healthy`; `/livez`, `/healthz` y `/api/events` → 200.
- RDS `nexoeventos-academy-postgres`: `available`, Multi-AZ (primaria us-east-1b, standby us-east-1a); no se detuvo en el cierre.
- Certificado: Let's Encrypt para `nexoeventos-demo.duckdns.org`, válido hasta 1-ene-2027, verificación TLS correcta (TLS 1.3).
- Prueba funcional (`verify-v2-flow.py`): 15/15 OK; reparto 51 % / 49 %; 0 errores 5xx (`../validacion-v2-20261105-c/`).
- Hallazgo: las sondas de Zabbix usan la macro `{$NEXO.HOST}` = `nexoeventos-demo.duckdns.org`, resuelta por DNS público (hoy V1); no monitorean V2 mientras el DNS apunte a V1.
- Hallazgo: la EC2 de V1 tiene `nexoeventos-duckdns.timer` activo (cada 5 min) que reescribe DuckDNS a la IP de V1.
