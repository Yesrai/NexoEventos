# EV04 — security groups

Estado al 3 de octubre de 2026: Comprobado funcionalmente el 3 de octubre de 2026: HTTPS público operativo, SSH no habilitado (administración por Session Manager) y RDS accesible solo desde la aplicación. **Captura de consola sanitizada pendiente** (`scripts/cloud/capture-inventory.sh` y checklist en `docs/operacion/procedimientos-sesion-cloud.md` § 2). Capturar reglas efectivas sin identificadores de cuenta: 80/443 públicos, SSH ausente o `/32`, PostgreSQL 5432 referenciando únicamente el SG web.
