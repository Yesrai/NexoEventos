# EV04 — security groups

Estado al 3 de octubre de 2026: Comprobado funcionalmente el 3 de octubre de 2026: HTTPS público operativo, SSH no habilitado (administración por Session Manager) y RDS accesible solo desde la aplicación. **Captura de consola sanitizada pendiente** (`scripts/cloud/capture-inventory.sh` y checklist en `docs/operacion/procedimientos-sesion-cloud.md` § 2). Capturar reglas efectivas sin identificadores de cuenta: 80/443 públicos, SSH ausente o `/32`, PostgreSQL 5432 referenciando únicamente el SG web.

Lectura API del 7 de octubre: web recibe solo 80/443 públicos, no existe regla 22; salida limitada a HTTPS, DNS de VPC y PostgreSQL hacia el SG de datos. El SG de datos recibe 5432 únicamente desde el SG web y no tiene salida propia.
